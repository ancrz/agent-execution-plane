"""ONT-59 T5: canal `stable` de Go en el montaje (scripts/setup.sh) con curl/JSON simulados; nunca descargas reales.

Se ejecuta la sección real de Go de setup.sh (helpers + resolve/instalación + toolchain.env) en un HOME aislado.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
from pathlib import Path

import pytest

from engine import go_toolchain

ROOT = Path(__file__).resolve().parent.parent
SETUP = (ROOT / "scripts" / "setup.sh").read_text()

CURL_STUB = r"""#!/bin/bash
url="" out=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
echo "$url" >> "$STUB_LOG"
[[ "${STUB_NET:-1}" == "1" ]] || exit 6
case "$url" in
  *'go.dev/dl/?mode=json') [[ -f "$STUB_JSON" ]] || exit 22; cp "$STUB_JSON" "$out" ;;
  *go*.linux-amd64.tar.gz) f="$STUB_TARBALLS/$(basename "$url")"; [[ -f "$f" ]] || exit 22; cp "$f" "$out" ;;
  *) exit 22 ;;
esac
"""


def _script(mode: str = "setup") -> str:
    pins = "\n".join(re.findall(r"^GO_(?:VERSION|SHA256_\w+)=.*$", SETUP, re.MULTILINE))
    pins = "\n".join("GO_" + ln.removeprefix("GO_") for ln in pins.splitlines())
    helpers = SETUP[SETUP.index('GO_SUPPORTED_MIN="') : SETUP.index("# Cuenta los clientes MCP")]
    dl = re.search(r"^download\(\) \{.*?^\}\n", SETUP, re.DOTALL | re.MULTILINE).group(0)
    dlv = re.search(r"^DL_FAIL_REASON=\"\"\ndownload_verified\(\) \{.*?^\}\n", SETUP, re.DOTALL | re.MULTILINE).group(0)
    a = SETUP.index('log_step "Verificando compilador Golang..."')
    b = SETUP.index('if [[ -n "$GO_CUR" && -x "$GO_CUR" ]]; then\n    GO_CMD=')
    return (
        "set -euo pipefail\n"
        'log_step() { echo "STEP:$*"; }\nlog_success() { echo "OK:$*"; }\nlog_warn() { echo "WARN:$*"; }\nlog_err() { echo "ERR:$*"; }\n'
        + pins
        + "\n"
        + "SHA_OVERRIDE\n"
        + f'MODE="{mode}"\nARCH_OK=1\nGO_ARCH="amd64"\nTMP_DIR="$(mktemp -d)"\n'
        + helpers
        + dl
        + dlv
        + SETUP[a:b]
        + 'echo "RESULT:CUR=$GO_CUR RESOLVED=$GO_RESOLVED"\n'
    )


def _fake_go_dir(root: Path, version: str, marker: str = "") -> Path:
    """Directorio estilo GOROOT con bin/go falso que responde a `env GOVERSION`."""
    (root / "bin").mkdir(parents=True, exist_ok=True)
    go = root / "bin" / "go"
    go.write_text(f'#!/bin/sh\n# {marker}\nif [ "$1 $2" = "env GOVERSION" ]; then echo go{version}; exit 0; fi\n')
    go.chmod(go.stat().st_mode | stat.S_IXUSR)
    return go


def _tarball(dest_dir: Path, version: str) -> str:
    buf = io.BytesIO()
    body = f'#!/bin/sh\nif [ "$1 $2" = "env GOVERSION" ]; then echo go{version}; exit 0; fi\n'.encode()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo("go/bin/go")
        info.size, info.mode = len(body), 0o755
        tf.addfile(info, io.BytesIO(body))
    data = buf.getvalue()
    (dest_dir / f"go{version}.linux-amd64.tar.gz").write_bytes(data)
    return hashlib.sha256(data).hexdigest()


class Env:
    def __init__(self, tmp: Path) -> None:
        self.home = tmp / "home"
        self.home.mkdir()
        self.stubs = tmp / "stubbin"
        self.stubs.mkdir()
        self.tarballs = tmp / "tarballs"
        self.tarballs.mkdir()
        self.log = tmp / "curl.log"
        self.log.write_text("")
        self.json = tmp / "godl.json"
        curl = self.stubs / "curl"
        curl.write_text(CURL_STUB)
        curl.chmod(curl.stat().st_mode | stat.S_IXUSR)
        self.tmp = tmp

    def stable_json(self, versions: list[tuple[str, bool]]) -> None:
        rels = []
        for ver, stable in versions:
            sha = _tarball(self.tarballs, ver) if stable else "0" * 64
            rels.append(
                {
                    "version": f"go{ver}",
                    "stable": stable,
                    "files": [
                        {"os": "linux", "arch": "arm64", "kind": "archive", "sha256": "1" * 64},
                        {"os": "linux", "arch": "amd64", "kind": "archive", "sha256": sha},
                    ],
                }
            )
        self.json.write_text(json.dumps(rels))

    def run(
        self,
        *,
        mode: str = "setup",
        net: bool = True,
        extra_path: str = "",
        channel: str | None = None,
        sha_override: str | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        script = _script(mode).replace("SHA_OVERRIDE", f'GO_SHA256_amd64="{sha_override}"' if sha_override else ":")
        env = {
            "HOME": str(self.home),
            "PATH": f"{self.stubs}{os.pathsep}{extra_path}{os.pathsep}/usr/bin:/bin",
            "STUB_LOG": str(self.log),
            "STUB_JSON": str(self.json),
            "STUB_TARBALLS": str(self.tarballs),
            "STUB_NET": "1" if net else "0",
            "LANG": "C",
        }
        if channel:
            env["AEP_GO_CHANNEL"] = channel
        env.update(extra_env or {})
        res = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60, env=env, check=False)
        return res

    @property
    def toolchain_env(self) -> dict[str, str]:
        p = self.home / ".local" / "share" / "agent-os" / "toolchain.env"
        return dict(ln.split("=", 1) for ln in p.read_text().splitlines() if ln and not ln.startswith("#"))

    @property
    def urls(self) -> list[str]:
        return [ln for ln in self.log.read_text().splitlines() if ln]


def _run(env: Env, **kw: object) -> subprocess.CompletedProcess[str]:
    """Corre la sección Go de setup.sh; el mínimo soportado del script y el del motor deben coincidir."""
    assert go_toolchain.supported(f"go{go_toolchain.GO_SUPPORTED_MIN}")
    return env.run(**kw)  # type: ignore[arg-type]


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


def test_stable_resolves_first_stable_release_and_its_sha_from_json(env: Env) -> None:
    env.stable_json([("1.28rc1", False), ("1.27.9", True), ("1.26.14", True)])
    res = _run(env)
    out = res.stdout + res.stderr
    assert res.returncode == 0, out
    assert "RESOLVED=stable" in out
    managed = env.home / ".local" / "share" / "go" / "bin" / "go"
    assert managed.exists()
    te = env.toolchain_env
    assert te["AEP_GO_CHANNEL"] == "stable" and te["AEP_GO_CHANNEL_RESOLVED"] == "stable"
    assert te["AEP_GO_VERSION"] == "1.27.9" and te["AEP_GO_BIN"] == str(managed) and te["AEP_GO_RESOLVED_AT"]
    assert any(u.endswith("go1.27.9.linux-amd64.tar.gz") for u in env.urls)
    assert (env.home / ".local" / "bin" / "go").is_symlink()  # no había Go: enlace de conveniencia como antes


def test_engine_reads_what_setup_wrote(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    env.stable_json([("1.27.9", True)])
    assert _run(env).returncode == 0
    monkeypatch.delenv("AEP_GO_BIN", raising=False)
    monkeypatch.setenv("AEP_DATA_HOME", str(env.home / ".local" / "share" / "agent-os"))
    assert go_toolchain.read_toolchain_env()["AEP_GO_BIN"] == str(env.home / ".local" / "share" / "go" / "bin" / "go")
    assert go_toolchain.go_bin() == str(env.home / ".local" / "share" / "go" / "bin" / "go")


def test_no_network_falls_back_to_the_pinned_version(env: Env) -> None:
    pinned = re.search(r'^GO_VERSION="([^"]+)"', SETUP, re.MULTILINE).group(1)
    sha = _tarball(env.tarballs, pinned)
    # go.dev/dl/?mode=json inalcanzable (sin JSON), pero el espejo del tarball fijado responde
    res = _run(env, sha_override=sha)
    out = res.stdout + res.stderr
    assert res.returncode == 0, out
    assert "RESOLVED=pinned-fallback" in out and "pinned-fallback" in out.split("WARN:")[1]
    assert env.toolchain_env["AEP_GO_CHANNEL_RESOLVED"] == "pinned-fallback"
    assert env.toolchain_env["AEP_GO_VERSION"] == pinned


def test_total_network_failure_installs_nothing(env: Env) -> None:
    res = _run(env, net=False)
    out = res.stdout + res.stderr
    assert res.returncode == 0, out
    assert "pinned-fallback" in out and "Descarga/validación de Go falló" in out
    assert not (env.home / ".local" / "share" / "go").exists()
    assert not (env.home / ".local" / "share" / "agent-os" / "toolchain.env").exists()


def test_old_foreign_go_is_not_touched_and_managed_one_is_installed(env: Env) -> None:
    foreign = _fake_go_dir(env.tmp / "foreign", "1.22.5", marker="foreign")
    before = foreign.read_bytes()
    env.stable_json([("1.27.9", True)])
    res = _run(env, extra_path=str(foreign.parent))
    out = res.stdout + res.stderr
    assert res.returncode == 0, out
    assert "fuera de soporte" in out
    assert foreign.read_bytes() == before and "1.22.5" in foreign.read_text()
    managed = env.home / ".local" / "share" / "go" / "bin" / "go"
    assert env.toolchain_env["AEP_GO_BIN"] == str(managed) and env.toolchain_env["AEP_GO_VERSION"] == "1.27.9"
    assert not (env.home / ".local" / "bin" / "go").exists()  # no sombrea al Go ajeno


def test_supported_foreign_go_is_kept_without_network(env: Env) -> None:
    foreign = _fake_go_dir(env.tmp / "foreign", "1.26.3")
    res = _run(env, extra_path=str(foreign.parent))
    assert res.returncode == 0, res.stdout + res.stderr
    assert env.urls == []  # sin red cuando no hace falta instalar
    te = env.toolchain_env
    assert te["AEP_GO_BIN"] == str(foreign) and te["AEP_GO_VERSION"] == "1.26.3"
    assert not (env.home / ".local" / "share" / "go").exists()


def test_update_re_resolves_stable_and_replaces_managed_go(env: Env) -> None:
    managed = _fake_go_dir(env.home / ".local" / "share" / "go", "1.26.11", marker="old-managed")
    env.stable_json([("1.27.9", True)])
    res = _run(env, mode="update", extra_path=str(managed.parent))
    out = res.stdout + res.stderr
    assert res.returncode == 0, out
    assert env.toolchain_env["AEP_GO_VERSION"] == "1.27.9"
    assert "old-managed" not in managed.read_text()
    assert not list((env.home / ".local" / "share").glob("go.prev.*"))


def test_update_is_a_noop_when_already_on_latest_stable(env: Env) -> None:
    managed = _fake_go_dir(env.home / ".local" / "share" / "go", "1.27.9", marker="current")
    env.stable_json([("1.27.9", True)])
    res = _run(env, mode="update", extra_path=str(managed.parent))
    assert res.returncode == 0, res.stdout + res.stderr
    assert "current" in managed.read_text()
    assert not any(u.endswith(".tar.gz") for u in env.urls)


def test_update_failure_keeps_previous_install(env: Env) -> None:
    managed = _fake_go_dir(env.home / ".local" / "share" / "go", "1.26.11", marker="keep-me")
    env.stable_json([("1.27.9", True)])
    (env.tarballs / "go1.27.9.linux-amd64.tar.gz").write_bytes(b"corrupted")  # sha del JSON ya no coincide
    res = _run(env, mode="update", extra_path=str(managed.parent))
    out = res.stdout + res.stderr
    assert res.returncode == 0, out
    assert "no coincide" in out and "keep-me" in managed.read_text()
    assert env.toolchain_env["AEP_GO_VERSION"] == "1.26.11"


def test_pinned_channel_never_asks_go_dev_for_the_stable_json(env: Env) -> None:
    pinned = re.search(r'^GO_VERSION="([^"]+)"', SETUP, re.MULTILINE).group(1)
    sha = _tarball(env.tarballs, pinned)
    env.stable_json([("1.99.9", True)])
    res = _run(env, channel="pinned", sha_override=sha)
    assert res.returncode == 0, res.stdout + res.stderr
    assert not any("mode=json" in u for u in env.urls)
    te = env.toolchain_env
    assert te["AEP_GO_CHANNEL"] == "pinned" and te["AEP_GO_VERSION"] == pinned


def test_channel_persisted_in_toolchain_env_is_honoured(env: Env) -> None:
    data = env.home / ".local" / "share" / "agent-os"
    data.mkdir(parents=True)
    (data / "toolchain.env").write_text("AEP_GO_CHANNEL=pinned\n")
    pinned = re.search(r'^GO_VERSION="([^"]+)"', SETUP, re.MULTILINE).group(1)
    sha = _tarball(env.tarballs, pinned)
    assert _run(env, sha_override=sha).returncode == 0
    assert env.toolchain_env["AEP_GO_CHANNEL"] == "pinned"
    assert not any("mode=json" in u for u in env.urls)


def test_apt_is_no_longer_used_for_go_and_pin_is_current() -> None:
    assert (
        "golang-go" not in SETUP and "apt-get install" not in SETUP.split("# 4. Golang Toolchain")[1].split("# 4.1")[0]
    )
    assert re.search(r'^GO_VERSION="1\.2[67]\.\d+"', SETUP, re.MULTILINE)
    assert re.search(r'^GO_SHA256_amd64="[0-9a-f]{64}"$', SETUP, re.MULTILINE)
    assert re.search(r'^GO_SHA256_arm64="[0-9a-f]{64}"$', SETUP, re.MULTILINE)
    assert f'GO_SUPPORTED_MIN="{go_toolchain.GO_SUPPORTED_MIN}"' in SETUP  # script y motor comparten el mínimo


def test_setup_syntax_and_shellcheck() -> None:
    assert go_toolchain.supported(go_toolchain.GO_SUPPORTED_MIN)
    assert subprocess.run(["bash", "-n", str(ROOT / "scripts" / "setup.sh")], check=False).returncode == 0
    sc = shutil.which("shellcheck")
    if sc:
        res = subprocess.run([sc, str(ROOT / "scripts" / "setup.sh")], capture_output=True, text=True, check=False)
        assert res.returncode == 0, res.stdout
