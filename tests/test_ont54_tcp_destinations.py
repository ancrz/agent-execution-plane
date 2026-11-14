"""ONT-54 T3 (G46): kernel_trace(tcp_connect) reports destinations when BTF exists (bpftrace is always simulated)."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

import server

JSON_OUT = "\n".join(
    json.dumps(o)
    for o in (
        {"type": "attached_probes", "data": {"probes": 2}},
        {"type": "map", "data": {"@c": {"curl": 3, "ssh": 1}}},
        {
            "type": "map",
            "data": {
                "@d": {
                    "curl, 172.66.147.243, 443": 2,
                    "curl, 127.0.0.1, 1": 1,
                    "ssh, ::1, 22": 1,
                }
            },
        },
    )
)
TEXT_OUT = "@c[curl]: 3\n@d[curl, 172.66.147.243, 443]: 2\n@d[ssh, 10.0.0.1, 22]: 1\n@[legacy]: 4\ngarbage line\n"


def _arm(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stdout: str, btf: bool) -> list[str]:
    seen: list[str] = []
    btf_path = tmp_path / "vmlinux"
    if btf:
        btf_path.write_bytes(b"")
    monkeypatch.setattr(server, "_BTF_VMLINUX_PATH", btf_path)
    monkeypatch.setattr(server, "privilege_prefix", lambda: [])
    monkeypatch.setattr(server, "privilege_mode", lambda: "test")

    def fake_run(cmd: list[str], **_k: Any) -> subprocess.CompletedProcess:
        seen.append(cmd[cmd.index("-e") + 1])
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(server.subprocess, "run", fake_run)
    return seen


def _trace(**kw: Any) -> dict[str, Any]:
    return json.loads(asyncio.run(server.kernel_trace(mode="tcp_connect", **kw)))


def test_parser_json_and_text_forms() -> None:
    counts, dests = server._parse_bpftrace_output(JSON_OUT)
    assert counts == {"curl": 3, "ssh": 1}
    assert dests[0] == {"comm": "curl", "daddr": "172.66.147.243", "dport": 443, "count": 2}
    assert {d["daddr"] for d in dests} == {"172.66.147.243", "127.0.0.1", "::1"}
    counts_t, dests_t = server._parse_bpftrace_output(TEXT_OUT)
    assert counts_t == {"curl": 3, "legacy": 4} and [d["comm"] for d in dests_t] == ["curl", "ssh"]


def test_parser_nested_and_comma_comm_and_bad_port() -> None:
    nested = json.dumps({"type": "map", "data": {"@d": {"curl": {"1.2.3.4": {"80": 2}}}}})
    assert server._parse_bpftrace_output(nested)[1] == [{"comm": "curl", "daddr": "1.2.3.4", "dport": 80, "count": 2}]
    odd = json.dumps({"type": "map", "data": {"@d": {"a,b, 1.1.1.1, 9": 1, "x, 1.1.1.1, nope": 5}}})
    assert server._parse_bpftrace_output(odd)[1] == [{"comm": "a,b", "daddr": "1.1.1.1", "dport": 9, "count": 1}]


def test_btf_present_uses_destination_script_and_keeps_counts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen = _arm(monkeypatch, tmp_path, JSON_OUT, btf=True)
    res = _trace(verbosity="detail")
    assert "@d[comm, ntop(2" in seen[0] and "skc_v6_daddr" in seen[0] and "{" in seen[0] and "{{" not in seen[0]
    assert res["counts"] == {"curl": 3, "ssh": 1}
    assert res["destinations_total"] == 3
    assert res["destinations"][0] == {"comm": "curl", "daddr": "172.66.147.243", "dport": 443, "count": 2}
    assert "limits" not in res


def test_btf_destinations_paginate_with_cursor(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _arm(monkeypatch, tmp_path, JSON_OUT, btf=True)
    p1 = _trace(limit=2)
    assert len(p1["destinations"]) == 2 and p1["truncated"] is True and p1["cursor"] == "2"
    p2 = _trace(limit=2, cursor=int(p1["cursor"]))
    assert len(p2["destinations"]) == 1 and p2["truncated"] is False and p2["cursor"] is None


def test_no_btf_keeps_legacy_script_and_flags_limit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen = _arm(monkeypatch, tmp_path, '{"type": "map", "data": {"@": {"curl": 2}}}', btf=False)
    res = _trace()
    assert seen[0].startswith("kprobe:tcp_connect { @[comm] = count(); }")
    assert res["counts"] == {"curl": 2} and "destinations" not in res
    assert res["limits"] == ["no BTF: destinations unavailable"]
