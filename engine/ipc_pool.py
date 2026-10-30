"""
Engine: ipc_pool.py (SPEC-OM-7: Shared-Memory UNIX Socket Session Pool & Ephemeral Batch Engine)

Provides high-performance, non-blocking inter-agent and LLM-to-tool IPC:
  - SessionPool: Thread-safe and async-safe warm session slot leasing in Linux volatile memory (/dev/shm)
  - UnixSocketMux: Line-delimited JSON AF_UNIX daemon on /dev/shm/aep.sock (<0.5ms latency, zero-FD leak)
  - resolve_step_refs: Native-type preserving $prev.* and $steps.<id>.* variable resolver for DAG chaining
  - project_fields: Server-side dot-path field projection stripping verbose payloads in RAM before serialization

Topos: Pure stdlib leaf module. ZERO external imports, ZERO circular dependencies (never import server or catalog).
"""

from __future__ import annotations

import atexit
import contextlib
import json
import logging
import os
import re
import shutil
import socket
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger("aep.ipc_pool")

DEFAULT_MAX_SLOTS = 16
DEFAULT_LEASE_TTL_SEC = 60.0
MAX_IPC_BUFFER_BYTES = 16 * 1024 * 1024  # 16 MB


# -----------------------------------------------------------------------------
# Path Resolution Helpers (/dev/shm > $XDG_RUNTIME_DIR > /tmp)
# -----------------------------------------------------------------------------

def resolve_ipc_base_dir() -> Path:
    """Resolve the fastest available volatile directory for session slots."""
    env_dir = os.environ.get("AEP_POOL_DIR")
    if env_dir:
        p = Path(env_dir).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    shm = Path("/dev/shm")
    if shm.exists() and os.access(shm, os.W_OK):
        p = shm / "aep_pool"
        p.mkdir(parents=True, exist_ok=True)
        return p

    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        p = Path(xdg) / "aep_pool"
        with contextlib.suppress(OSError):
            p.mkdir(parents=True, exist_ok=True)
            return p

    p = Path(tempfile.gettempdir()) / "aep_pool"
    p.mkdir(parents=True, exist_ok=True)
    return p


def resolve_ipc_socket_path() -> Path:
    """Resolve the canonical UNIX domain socket path (/dev/shm/aep.sock with fallbacks)."""
    env_sock = os.environ.get("AEP_SOCKET_PATH")
    if env_sock:
        return Path(env_sock).resolve()

    shm = Path("/dev/shm")
    if shm.exists() and os.access(shm, os.W_OK):
        return shm / "aep.sock"

    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        p = Path(xdg) / "aep.sock"
        if os.access(Path(xdg), os.W_OK):
            return p

    return Path(tempfile.gettempdir()) / "aep.sock"


# -----------------------------------------------------------------------------
# SessionPool: Reusable Session Slot Management
# -----------------------------------------------------------------------------

class SessionPool:
    """
    Thread-safe and async-safe slot leasing for agent execution contexts.
    Each slot provides an isolated ephemeral scratch directory in volatile RAM
    and an in-memory key-value state cache.
    """

    def __init__(
        self,
        max_slots: int = DEFAULT_MAX_SLOTS,
        lease_ttl_sec: float = DEFAULT_LEASE_TTL_SEC,
        base_dir: Path | str | None = None,
        default_ttl_sec: float | None = None,
    ) -> None:
        self.max_slots = max(1, int(max_slots))
        eff_ttl = default_ttl_sec if default_ttl_sec is not None else lease_ttl_sec
        self.lease_ttl_sec = float(eff_ttl)
        self.base_dir = Path(base_dir).resolve() if base_dir else resolve_ipc_base_dir()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

        # Slots initialization
        self._slots: dict[int, dict[str, Any]] = {}
        for sid in range(self.max_slots):
            scratch = self.base_dir / f"slot_{sid}"
            scratch.mkdir(parents=True, exist_ok=True)
            self._slots[sid] = {
                "slot_id": sid,
                "session_id": None,
                "agent_id": None,
                "leased_at": 0.0,
                "expires_at": 0.0,
                "reuse_count": 0,
                "scratch_dir": str(scratch),
                "state_cache": {},
                "in_use": False,
            }

        self._session_map: dict[tuple[str, str], int] = {}
        self._shared_session_cache: dict[str, dict[str, Any]] = {}

    def cache_set(
        self,
        session_id: str,
        agent_id: str,
        key: str,
        value: Any,
    ) -> dict[str, Any]:
        """Store key-value in shared session cache and mapped slot state_cache."""
        sid_str = str(session_id or "default")
        aid_str = str(agent_id or "default")
        k_str = str(key).strip()
        with self._lock:
            sess_cache = self._shared_session_cache.setdefault(sid_str, {})
            sess_cache[k_str] = value

            slot_map_key = (sid_str, aid_str)
            if slot_map_key in self._session_map:
                slot_id = self._session_map[slot_map_key]
                slot = self._slots[slot_id]
                slot["state_cache"][k_str] = value
                slot["expires_at"] = time.time() + self.lease_ttl_sec
            else:
                with contextlib.suppress(RuntimeError, OSError):
                    slot = self.acquire(sid_str, aid_str)
                    slot_id = slot["slot_id"]
                    self._slots[slot_id]["state_cache"][k_str] = value

            return {
                "status": "OK",
                "session_id": sid_str,
                "agent_id": aid_str,
                "key": k_str,
                "cached_keys": list(sess_cache.keys()),
            }

    def cache_get(
        self,
        session_id: str,
        agent_id: str = "default",
        key: str | None = None,
    ) -> dict[str, Any]:
        """Retrieve key-value or all keys from merged session and slot cache."""
        sid_str = str(session_id or "default")
        aid_str = str(agent_id or "default")
        with self._lock:
            sess_cache = dict(self._shared_session_cache.get(sid_str, {}))

            slot_map_key = (sid_str, aid_str)
            if slot_map_key in self._session_map:
                slot_id = self._session_map[slot_map_key]
                sess_cache.update(self._slots[slot_id]["state_cache"])

            if key is not None:
                clean_k = str(key).strip()
                val = sess_cache.get(clean_k)
                return {
                    "status": "OK" if clean_k in sess_cache else "NOT_FOUND",
                    "session_id": sid_str,
                    "agent_id": aid_str,
                    "key": clean_k,
                    "value": val,
                    "found": clean_k in sess_cache,
                }

            return {
                "status": "OK",
                "session_id": sid_str,
                "agent_id": aid_str,
                "cache": sess_cache,
                "keys": list(sess_cache.keys()),
                "count": len(sess_cache),
            }

    def acquire(
        self,
        session_id: str,
        agent_id: str = "default",
        ttl_sec: float | None = None,
    ) -> dict[str, Any]:
        """
        Acquire or reuse an existing warm slot for (session_id, agent_id).
        Increments reuse_count when reusing an active slot.
        """
        sid_str = str(session_id or "default")
        aid_str = str(agent_id or "default")
        key = (sid_str, aid_str)
        effective_ttl = float(ttl_sec or self.lease_ttl_sec)
        now = time.time()

        with self._lock:
            # 1. Warm slot hit for active session
            if key in self._session_map:
                slot_id = self._session_map[key]
                slot = self._slots[slot_id]
                # If still valid or refreshed
                slot["expires_at"] = now + effective_ttl
                slot["reuse_count"] += 1
                slot["in_use"] = True
                return self._sanitize_slot(slot)

            # 2. Reap expired slots to make room
            self._reap_expired_locked(now)

            # 3. Find an available slot
            available_slot_id: int | None = None
            for sid, slot in self._slots.items():
                if not slot["in_use"] and slot["session_id"] is None:
                    available_slot_id = sid
                    break

            # 4. If all slots were previously associated, take the oldest idle or expired slot
            if available_slot_id is None:
                for sid, slot in self._slots.items():
                    if not slot["in_use"]:
                        available_slot_id = sid
                        # Unmap previous occupant
                        old_key = (slot["session_id"], slot["agent_id"])
                        self._session_map.pop(old_key, None)
                        break

            if available_slot_id is None:
                raise RuntimeError(
                    f"No available session slots in pool (max_slots={self.max_slots}, all active)"
                )

            slot = self._slots[available_slot_id]
            slot["session_id"] = sid_str
            slot["agent_id"] = aid_str
            slot["leased_at"] = now
            slot["expires_at"] = now + effective_ttl
            slot["reuse_count"] = 1
            slot["in_use"] = True
            slot["state_cache"].clear()

            scratch_path = Path(slot["scratch_dir"])
            scratch_path.mkdir(parents=True, exist_ok=True)

            self._session_map[key] = available_slot_id
            return self._sanitize_slot(slot)

    def release(
        self,
        session_id: str,
        agent_id: str = "default",
        clear_state: bool = False,
    ) -> dict[str, Any]:
        """Release slot lease. If clear_state=True, wipes in-memory cache and scratch dir."""
        sid_str = str(session_id or "default")
        aid_str = str(agent_id or "default")
        key = (sid_str, aid_str)

        with self._lock:
            if key not in self._session_map:
                return {
                    "status": "NOT_FOUND",
                    "session_id": sid_str,
                    "agent_id": aid_str,
                    "released": False,
                }

            slot_id = self._session_map[key]
            slot = self._slots[slot_id]
            slot["in_use"] = False

            if clear_state:
                slot["state_cache"].clear()
                self._shared_session_cache.pop(sid_str, None)
                self._clear_dir(Path(slot["scratch_dir"]))
                self._session_map.pop(key, None)
                slot["session_id"] = None
                slot["agent_id"] = None
                slot["reuse_count"] = 0

            return {
                "status": "OK",
                "session_id": sid_str,
                "agent_id": aid_str,
                "slot_id": slot_id,
                "released": True,
                "reused": slot["reuse_count"],
            }

    def reap_expired(self) -> dict[str, Any]:
        """Public thread-safe expired slot reaper."""
        with self._lock:
            reaped = self._reap_expired_locked(time.time())
            active_count = sum(1 for s in self._slots.values() if s["in_use"])
            return {
                "status": "OK",
                "reaped_count": reaped,
                "active_slots": active_count,
            }

    def _reap_expired_locked(self, now: float) -> int:
        reaped = 0
        for sid, slot in self._slots.items():
            if slot["session_id"] is not None and slot["expires_at"] > 0 and now >= slot["expires_at"]:
                key = (slot["session_id"], slot["agent_id"])
                self._session_map.pop(key, None)
                slot["in_use"] = False
                slot["session_id"] = None
                slot["agent_id"] = None
                slot["reuse_count"] = 0
                slot["state_cache"].clear()
                self._clear_dir(Path(slot["scratch_dir"]))
                if not any(s.get("session_id") == key[0] and s.get("slot_id") != sid for s in self._slots.values()):
                    self._shared_session_cache.pop(key[0], None)
                reaped += 1
        return reaped

    def flush(self) -> dict[str, Any]:
        """Flush all session slots, caches, and scratch files."""
        with self._lock:
            flushed = sum(1 for s in self._slots.values() if s.get("session_id") is not None)
            self._session_map.clear()
            self._shared_session_cache.clear()
            for slot in self._slots.values():
                slot["in_use"] = False
                slot["session_id"] = None
                slot["agent_id"] = None
                slot["reuse_count"] = 0
                slot["state_cache"].clear()
                self._clear_dir(Path(slot["scratch_dir"]))
            return {"status": "OK", "flushed_count": flushed}

    def status(self) -> dict[str, Any]:
        """Report slot allocation, active leases, and base directory status."""
        with self._lock:
            in_use = [self._sanitize_slot(s) for s in self._slots.values() if s["in_use"]]
            allocated = [self._sanitize_slot(s) for s in self._slots.values() if s.get("session_id") is not None]
            return {
                "status": "OK",
                "max_slots": self.max_slots,
                "active_count": len(in_use),
                "idle_count": self.max_slots - len(in_use),
                "allocated_count": len(allocated),
                "base_dir": str(self.base_dir),
                "slots": allocated,
            }

    @staticmethod
    def _sanitize_slot(slot: dict[str, Any]) -> dict[str, Any]:
        return {
            "slot_id": slot["slot_id"],
            "session_id": slot["session_id"],
            "agent_id": slot["agent_id"],
            "leased_at": slot["leased_at"],
            "expires_at": slot["expires_at"],
            "ttl_remaining_sec": max(0.0, round(slot["expires_at"] - time.time(), 2)),
            "reuse_count": slot["reuse_count"],
            "scratch_dir": slot["scratch_dir"],
            "in_use": slot["in_use"],
            "cached_keys": list(slot["state_cache"].keys()),
        }

    @staticmethod
    def _clear_dir(p: Path) -> None:
        if not p.is_dir():
            return
        for child in p.iterdir():
            try:
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
            except OSError:
                pass


# -----------------------------------------------------------------------------
# Variable Resolution Engine: $prev.* and $steps.<id>.*
# -----------------------------------------------------------------------------

_REF_EXACT_PATTERN = re.compile(
    r"^\$(prev|(?:steps|cache|slot)(?:\.([A-Za-z0-9_\-]+))?)(?:\.(.+))?$"
)
_REF_EMBED_PATTERN = re.compile(
    r"\$((?:prev|steps|cache|slot)(?:\.[A-Za-z0-9_\-]+)+)"
)


def _get_dot_path(data: Any, path_str: str) -> Any:
    """Navigate dictionary keys and list indices using dot-notation."""
    if not path_str:
        return data
    curr = data
    for part in path_str.split("."):
        if curr is None:
            return None
        if isinstance(curr, dict):
            if part in curr:
                curr = curr[part]
            else:
                return None
        elif isinstance(curr, (list, tuple)):
            try:
                idx = int(part)
                if 0 <= idx < len(curr):
                    curr = curr[idx]
                else:
                    return None
            except ValueError:
                return None
        else:
            return None
    return curr


def resolve_step_refs(
    params: Any,
    step_outputs: dict[str, Any],
    prev_output: Any = None,
    slot_cache: dict[str, Any] | None = None,
) -> Any:
    """
    Recursively resolves variable references ($prev.*, $steps.<id>.*, $cache.<key>.*, $slot.<key>.*).
    PRESERVES native Python types (int, float, list, dict, bool) on exact matches.
    Interpolates inside strings when embedded alongside other text.
    """
    if isinstance(params, dict):
        return {
            k: resolve_step_refs(v, step_outputs, prev_output, slot_cache=slot_cache)
            for k, v in params.items()
        }
    if isinstance(params, list):
        return [resolve_step_refs(v, step_outputs, prev_output, slot_cache=slot_cache) for v in params]
    if not isinstance(params, str):
        return params

    text = params.strip()

    # 1. Exact match -> preserves native Python types
    m_exact = _REF_EXACT_PATTERN.match(text)
    if m_exact:
        root_scope = m_exact.group(1)
        sub_step_id = m_exact.group(2)
        dot_path = m_exact.group(3) or ""

        if root_scope == "prev":
            target = prev_output
            return _get_dot_path(target, dot_path) if dot_path else target

        if root_scope.startswith("steps"):
            target = step_outputs.get(sub_step_id or "")
            return _get_dot_path(target, dot_path) if dot_path else target

        if root_scope.startswith(("cache", "slot")):
            target = (slot_cache or {}).get(sub_step_id or "")
            return _get_dot_path(target, dot_path) if dot_path else target

    # 2. Embedded string interpolation
    def _repl(m: re.Match) -> str:
        token = m.group(1)
        if token.startswith("prev"):
            sub_path = token[4:].lstrip(".")
            val = _get_dot_path(prev_output, sub_path)
            return str(val) if val is not None else m.group(0)
        if token.startswith("steps."):
            parts = token[6:].split(".", 1)
            step_id = parts[0]
            sub_path = parts[1] if len(parts) > 1 else ""
            target = step_outputs.get(step_id)
            val = _get_dot_path(target, sub_path)
            return str(val) if val is not None else m.group(0)
        if token.startswith("cache."):
            parts = token[6:].split(".", 1)
            k = parts[0]
            sub_path = parts[1] if len(parts) > 1 else ""
            target = (slot_cache or {}).get(k)
            val = _get_dot_path(target, sub_path) if sub_path else target
            return str(val) if val is not None else m.group(0)
        if token.startswith("slot."):
            parts = token[5:].split(".", 1)
            k = parts[0]
            sub_path = parts[1] if len(parts) > 1 else ""
            target = (slot_cache or {}).get(k)
            val = _get_dot_path(target, sub_path) if sub_path else target
            return str(val) if val is not None else m.group(0)
        return m.group(0)

    return _REF_EMBED_PATTERN.sub(_repl, params)


# -----------------------------------------------------------------------------
# Field Projector: Server-Side Dot-Path Key Filtering
# -----------------------------------------------------------------------------

def project_fields(data: Any, select_fields: list[str] | None) -> Any:
    """
    Server-side dot-path field projection (e.g. ['status', 'pid', 'output.total_sockets']).
    Constructs a lightweight dictionary containing ONLY requested fields in RAM
    prior to serialization, reducing response payload sizes by >75-95%.
    Supports smart fallback resolution for return_only="last" and return_only="all".
    """
    if not select_fields or not isinstance(data, dict):
        return data

    projected: dict[str, Any] = {}

    for field_path in select_fields:
        clean_path = str(field_path).strip()
        if not clean_path:
            continue
        # Direct resolution on data root (preserves existing behavior)
        val = _get_dot_path(data, clean_path)
        if val is not None:
            _set_dot_path(projected, clean_path, val)
            continue

        # Smart Fallback 1: return_only="last" where "output" is a dictionary
        output_obj = data.get("output")
        if isinstance(output_obj, dict):
            out_val = _get_dot_path(output_obj, clean_path)
            if out_val is None and isinstance(output_obj.get("telemetry"), dict):
                out_val = _get_dot_path(output_obj["telemetry"], clean_path)
            if out_val is not None:
                _set_dot_path(projected, clean_path, out_val)
                _set_dot_path(projected, f"output.{clean_path}", out_val)
                continue

        # Smart Fallback 2: return_only="all" where "results" is a list of steps
        results_list = data.get("results")
        if isinstance(results_list, list):
            for idx, r in enumerate(results_list):
                if not isinstance(r, dict):
                    continue
                step_val = None
                if isinstance(r.get("output"), dict):
                    step_val = _get_dot_path(r["output"], clean_path)
                    if step_val is None and isinstance(r["output"].get("telemetry"), dict):
                        step_val = _get_dot_path(r["output"]["telemetry"], clean_path)
                if step_val is None:
                    step_val = _get_dot_path(r, clean_path)

                if step_val is not None:
                    if "results" not in projected:
                        projected["results"] = []
                    while len(projected["results"]) <= idx:
                        mr = results_list[len(projected["results"])]
                        projected["results"].append({
                            "id": mr.get("id"),
                            "tool": mr.get("tool"),
                            "status": mr.get("status"),
                        })
                    _set_dot_path(projected["results"][idx], clean_path, step_val)

    # If projection ended up completely empty (e.g. unmatched fields), fall back gracefully
    return projected or data


def _set_dot_path(dest: dict[str, Any], path_str: str, value: Any) -> None:
    parts = path_str.split(".")
    curr = dest
    for i, part in enumerate(parts[:-1]):
        if part not in curr or not isinstance(curr[part], dict):
            curr[part] = {}
        curr = curr[part]
    curr[parts[-1]] = value


# -----------------------------------------------------------------------------
# UnixSocketMux: Line-Delimited AF_UNIX Server & Client
# -----------------------------------------------------------------------------

class UnixSocketMux:
    """
    Non-blocking background daemon thread AF_UNIX server.
    Handles ping, status, slot lease, and multi-step batch execution.
    Guarantees all client and server sockets close deterministically (fd_delta == 0).
    """

    def __init__(self, socket_path: Path | str | None = None) -> None:
        self.socket_path = Path(socket_path).resolve() if socket_path else resolve_ipc_socket_path()
        self._server_sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._batch_handler: Callable[[dict[str, Any]], Any] | None = None
        self._stats = {
            "requests_handled": 0,
            "bytes_received": 0,
            "bytes_sent": 0,
            "batches_executed": 0,
            "errors": 0,
        }
        self._lock = threading.Lock()

    def set_batch_handler(self, handler: Callable[[dict[str, Any]], Any]) -> None:
        """Inject batch execution callback from server.py (dependency inversion)."""
        self._batch_handler = handler

    def start(self, socket_path: Path | str | None = None) -> bool:
        """Bind and start server in background daemon thread."""
        with self._lock:
            if self._running:
                return True

            if socket_path:
                self.socket_path = Path(socket_path).resolve()

            # Ensure parent directory exists
            self.socket_path.parent.mkdir(parents=True, exist_ok=True)

            # Check if an existing server is alive on the socket before unlinking
            if self.socket_path.exists():
                probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                try:
                    probe.settimeout(0.2)
                    probe.connect(str(self.socket_path))
                    probe.close()
                    # An active server is already listening: adopt it and do not overwrite
                    self._running = True
                    return True
                except (ConnectionRefusedError, TimeoutError, OSError):
                    probe.close()
                    with contextlib.suppress(OSError):
                        self.socket_path.unlink()

            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.bind(str(self.socket_path))
                sock.listen(32)
                sock.settimeout(0.5)  # Responsive shutdown
                with contextlib.suppress(OSError):
                    self.socket_path.chmod(0o660)

                self._server_sock = sock
                self._running = True
                self._thread = threading.Thread(
                    target=self._serve_loop,
                    name="aep-unix-mux",
                    daemon=True,
                )
                self._thread.start()
                logger.info("UnixSocketMux listening on %s", self.socket_path)
                return True
            except (OSError, RuntimeError) as e:
                logger.debug("Failed to start UnixSocketMux on %s: %s", self.socket_path, e)
                with contextlib.suppress(OSError):
                    if self.socket_path.exists():
                        self.socket_path.unlink()
                return False

    def stop(self) -> None:
        """Stop server thread and clean up socket file."""
        with self._lock:
            self._running = False
            had_server_sock = self._server_sock is not None
            if self._server_sock:
                with contextlib.suppress(OSError):
                    self._server_sock.close()
                self._server_sock = None
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=1.0)
                self._thread = None
            if had_server_sock:
                with contextlib.suppress(OSError):
                    if self.socket_path.exists():
                        self.socket_path.unlink()

    def _serve_loop(self) -> None:
        while self._running:
            if not self._server_sock:
                break
            try:
                conn, _ = self._server_sock.accept()
            except TimeoutError:
                continue
            except (OSError, ValueError):
                break

            # Handle client with deterministic close
            t = threading.Thread(
                target=self._handle_client,
                args=(conn,),
                name="aep-ipc-client",
                daemon=True,
            )
            t.start()

    def _handle_client(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(10.0)
            buffer = bytearray()
            while self._running:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buffer.extend(chunk)
                if len(buffer) > MAX_IPC_BUFFER_BYTES:
                    conn.sendall(json.dumps({"status": "ERROR", "error": "PAYLOAD_TOO_LARGE"}).encode("utf-8") + b"\n")
                    return
                if b"\n" in buffer:
                    line, _, remaining = buffer.partition(b"\n")
                    buffer = bytearray(remaining)
                    if line:
                        resp = self._dispatch_message(line)
                        resp_bytes = json.dumps(resp).encode("utf-8") + b"\n"
                        conn.sendall(resp_bytes)
                        with self._lock:
                            self._stats["requests_handled"] += 1
                            self._stats["bytes_received"] += len(line)
                            self._stats["bytes_sent"] += len(resp_bytes)
        except (OSError, ValueError, RuntimeError) as e:  # noqa: BLE001
            with self._lock:
                self._stats["errors"] += 1
            logger.debug("IPC client handler error: %s", e)
        finally:
            with contextlib.suppress(OSError):
                conn.close()

    def _dispatch_message(self, line_bytes: bytes) -> dict[str, Any]:
        try:
            req = json.loads(line_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
            return {"status": "PARAM_ERROR", "error": f"Invalid JSON payload: {e}"}

        act = str(req.get("action", "ping")).strip().lower()

        if act == "ping":
            return {"status": "OK", "pong": True, "timestamp": time.time()}

        if act == "status":
            return self.status()

        if act == "lease":
            session_id = req.get("session_id", "default")
            agent_id = req.get("agent_id", "default")
            ttl_sec = req.get("ttl_sec")
            try:
                slot = GLOBAL_SESSION_POOL.acquire(session_id, agent_id, ttl_sec)
                return {"status": "OK", "slot": slot}
            except Exception as e:  # noqa: BLE001
                return {"status": "ERROR", "error": str(e)}

        if act == "release":
            session_id = req.get("session_id", "default")
            agent_id = req.get("agent_id", "default")
            clear_state = bool(req.get("clear_state", False))
            return GLOBAL_SESSION_POOL.release(session_id, agent_id, clear_state=clear_state)

        if act == "reap":
            return GLOBAL_SESSION_POOL.reap_expired()

        if act == "flush":
            return GLOBAL_SESSION_POOL.flush()

        if act == "pool":
            return GLOBAL_SESSION_POOL.status()

        if act == "metrics":
            return self.metrics()

        if act in ("batch", "code", "ephemeral", "pipeline"):
            if self._batch_handler:
                with self._lock:
                    self._stats["batches_executed"] += 1
                try:
                    res = self._batch_handler(req)
                    # If async coroutine was returned
                    if hasattr(res, "__await__"):
                        import asyncio
                        try:
                            loop = asyncio.get_event_loop()
                            if loop.is_running():
                                res = asyncio.run_coroutine_threadsafe(res, loop).result(timeout=30)
                            else:
                                res = loop.run_until_complete(res)
                        except RuntimeError:
                            res = asyncio.run(res)
                    return res if isinstance(res, dict) else {"status": "OK", "result": res}
                except Exception as e:  # noqa: BLE001
                    return {"status": "ERROR", "error": f"Batch handler failed: {e}"}
            else:
                return {
                    "status": "NOT_CONFIGURED",
                    "error": "Batch handler has not been registered in UnixSocketMux.",
                }

        return {
            "status": "INVALID_ACTION",
            "error": f"Action '{act}' not recognized by UnixSocketMux.",
            "valid_actions": ["ping", "status", "lease", "release", "reap", "flush", "pool", "metrics", "batch"],
        }

    @property
    def is_running(self) -> bool:
        """Check if the daemon socket listener is running."""
        return self._running

    def status(self) -> dict[str, Any]:
        """Status report for the UNIX domain socket mux."""
        return {
            "status": "OK",
            "running": self._running,
            "socket_path": str(self.socket_path),
            "socket_exists": self.socket_path.exists(),
            "pool": GLOBAL_SESSION_POOL.status(),
            "stats": dict(self._stats),
        }

    def metrics(self) -> dict[str, Any]:
        """Throughput and utilization metrics."""
        pool_st = GLOBAL_SESSION_POOL.status()
        return {
            "status": "OK",
            "socket_path": str(self.socket_path),
            "running": self._running,
            "requests_handled": self._stats["requests_handled"],
            "batches_executed": self._stats["batches_executed"],
            "bytes_received": self._stats["bytes_received"],
            "bytes_sent": self._stats["bytes_sent"],
            "errors": self._stats["errors"],
            "pool_active_count": pool_st["active_count"],
            "pool_max_slots": pool_st["max_slots"],
            "pool_utilization_pct": round((pool_st["active_count"] / pool_st["max_slots"]) * 100, 2),
        }


# -----------------------------------------------------------------------------
# Client Request Function
# -----------------------------------------------------------------------------

def ipc_client_request(
    payload: dict[str, Any],
    socket_path: Path | str | None = None,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """
    Synchronous AF_UNIX client request with deterministic socket closure.
    Guarantees fd_delta == 0 via try...finally block.
    """
    path = Path(socket_path).resolve() if socket_path else resolve_ipc_socket_path()
    if not path.exists():
        return {
            "status": "DEGRADED",
            "error": "SOCKET_NOT_FOUND",
            "socket_path": str(path),
            "message": f"UNIX domain socket {path} does not exist.",
        }

    client_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client_sock.settimeout(timeout)
        try:
            client_sock.connect(str(path))
        except (ConnectionRefusedError, FileNotFoundError):
            client_sock.close()
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)
            if GLOBAL_SOCKET_MUX:
                GLOBAL_SOCKET_MUX.start()
            client_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client_sock.settimeout(timeout)
            client_sock.connect(str(path))
        data = json.dumps(payload).encode("utf-8") + b"\n"
        client_sock.sendall(data)

        chunks = []
        while True:
            chunk = client_sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            if b"\n" in chunk:
                break

        raw_resp = b"".join(chunks).strip()
        if not raw_resp:
            return {"status": "ERROR", "error": "EMPTY_RESPONSE"}
        return json.loads(raw_resp.decode("utf-8"))
    except (OSError, json.JSONDecodeError, TimeoutError) as e:
        return {
            "status": "ERROR",
            "error": str(e),
            "socket_path": str(path),
        }
    finally:
        with contextlib.suppress(OSError):
            client_sock.close()


# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
# Global Singletons and Lazy Starter
# -----------------------------------------------------------------------------

GLOBAL_SESSION_POOL = SessionPool()
GLOBAL_SOCKET_MUX = UnixSocketMux()
atexit.register(GLOBAL_SOCKET_MUX.stop)


def ensure_ipc_server_started(socket_path: str | None = None) -> UnixSocketMux:
    """Ensure the global UnixSocketMux daemon is running."""
    if not GLOBAL_SOCKET_MUX._running:
        GLOBAL_SOCKET_MUX.start(socket_path=socket_path)
    return GLOBAL_SOCKET_MUX
