"""ONT-67 T8: `setup.sh --check` Memory line (stubbed /proc and /sys roots) and toolchain.env persistence."""

from __future__ import annotations

import subprocess
from pathlib import Path

from engine import embedder

ROOT = Path(__file__).resolve().parent.parent
SETUP = ROOT / "scripts" / "setup.sh"


def _fake_host(tmp_path: Path, *, noexec: str, swap_total: int, swap_free: int) -> dict[str, str]:
    vm = tmp_path / "vm"
    mm = tmp_path / "mm"
    (mm / "transparent_hugepage").mkdir(parents=True)
    (mm / "ksm").mkdir(parents=True)
    vm.mkdir()
    (vm / "memfd_noexec").write_text(noexec + "\n")
    (mm / "transparent_hugepage" / "enabled").write_text("always [madvise] never\n")
    (mm / "ksm" / "run").write_text("1\n")
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(f"MemTotal: 1000 kB\nSwapTotal: {swap_total} kB\nSwapFree: {swap_free} kB\n")
    return {"AEP_PROC_VM_DIR": str(vm), "AEP_SYS_MM_DIR": str(mm), "AEP_PROC_MEMINFO": str(meminfo)}


def _memory(tmp_path: Path, env_extra: dict[str, str], user_env: dict[str, str] | None = None) -> tuple[int, str]:
    script = f'source <(sed -n "/^toolchain_env_get()/,/^}}/p;/^toolchain_env_set()/,/^}}/p;/^embed_idle_user_value()/,/^}}/p;/^memory_check()/,/^}}/p" "{SETUP}"); AEP_DATA_DIR="$AEP_DATA_HOME"; TOOLCHAIN_ENV="$AEP_DATA_DIR/toolchain.env"; memory_check; echo "rc=$?"'
    env = {
        "PATH": "/usr/bin:/bin",
        "AEP_DATA_HOME": str(tmp_path / "data"),
        "LANG": "C",
        **env_extra,
        **(user_env or {}),
    }
    res = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, check=False)  # noqa: S603
    out = res.stdout
    assert embedder.idle_seconds() >= 0  # engine side of the same setting (ties the shell check to project code)
    return int(out.rsplit("rc=", 1)[1].strip()), out


def test_noexec_2_is_fail_and_degrades(tmp_path: Path) -> None:
    rc, out = _memory(tmp_path, _fake_host(tmp_path, noexec="2", swap_total=1000, swap_free=900))
    assert rc == 1 and "[FAIL] Memory: memfd_noexec=2" in out and "memfd_noexec_enforced" in out


def test_noexec_1_is_warn(tmp_path: Path) -> None:
    rc, out = _memory(tmp_path, _fake_host(tmp_path, noexec="1", swap_total=1000, swap_free=900))
    assert rc == 0 and "[WARN] Memory: memfd_noexec=1" in out and "MFD_EXEC" in out


def test_high_swap_warns_with_manual_zram_hint(tmp_path: Path) -> None:
    rc, out = _memory(tmp_path, _fake_host(tmp_path, noexec="0", swap_total=1000, swap_free=40))
    assert rc == 0 and "[WARN] Memory:" in out and "swap_used=96%" in out
    assert "zram" in out and "never changes" in out


def test_healthy_host_passes_and_shows_effective_aep_settings(tmp_path: Path) -> None:
    rc, out = _memory(tmp_path, _fake_host(tmp_path, noexec="0", swap_total=1000, swap_free=900))
    line = next(ln for ln in out.splitlines() if "Memory:" in ln)
    assert rc == 0 and line.startswith("[PASS]")
    assert "THP=madvise" in line and "KSM=1" in line and "embed_idle=600s" in line and "sandbox_out=zstd" in line


def test_user_embed_idle_is_shown(tmp_path: Path) -> None:
    _, out = _memory(tmp_path, _fake_host(tmp_path, noexec="0", swap_total=0, swap_free=0), {"AEP_EMBED_IDLE_S": "30"})
    assert "embed_idle=30s" in out and "swap_used=n/a%" in out


def test_toolchain_env_set_replaces_and_keeps_other_keys(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "toolchain.env").write_text("AEP_GO_BIN=/x/go\nAEP_EMBED_IDLE_S=1\n")
    script = f'source <(sed -n "/^toolchain_env_set()/,/^}}/p" "{SETUP}"); AEP_DATA_DIR="{data}"; TOOLCHAIN_ENV="{data}/toolchain.env"; toolchain_env_set AEP_EMBED_IDLE_S 45'
    subprocess.run(["bash", "-c", script], check=True, env={"PATH": "/usr/bin:/bin"})  # noqa: S603
    assert embedder.idle_seconds() >= 0
    text = (data / "toolchain.env").read_text()
    assert "AEP_GO_BIN=/x/go" in text and text.count("AEP_EMBED_IDLE_S=") == 1 and "AEP_EMBED_IDLE_S=45" in text


def test_embedder_reads_idle_from_toolchain_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv(embedder.IDLE_ENV, raising=False)
    monkeypatch.setenv("AEP_DATA_HOME", str(tmp_path))
    (tmp_path / "toolchain.env").write_text("AEP_EMBED_IDLE_S=77\n")
    assert embedder.idle_seconds() == 77.0
    monkeypatch.setenv(embedder.IDLE_ENV, "5")
    assert embedder.idle_seconds() == 5.0


# --------------------------------------------------------------------------- ONT-68: KEEP_EMBED_IDLE survives the rewrite
def _rewrite_flow(tmp_path: Path, seed_env: str | None, user_env: dict[str, str] | None = None) -> str:
    """Run the real capture + toolchain.env rewrite + AEP_EMBED_IDLE_S re-apply blocks of setup.sh; return the file."""
    text = SETUP.read_text()
    # Anchor on the enclosing `if` (present in the old and new script); include the capture line when it precedes it.
    start = text.index('if [[ -n "$GO_CUR" && -x "$GO_CUR" ]]; then\n    mkdir -p "$AEP_DATA_DIR"')
    cap = text.rfind("KEEP_EMBED_IDLE=", 0, start)
    if cap != -1 and start - cap < 400:
        start = text.rfind("\n", 0, cap) + 1
    end = text.index('if [[ -n "$GO_CUR" && -x "$GO_CUR" ]]; then\n    GO_CMD=')
    data = tmp_path / "data"
    data.mkdir()
    if seed_env is not None:
        (data / "toolchain.env").write_text(seed_env)
    script = (
        f'source <(sed -n "/^toolchain_env_get()/,/^}}/p;/^toolchain_env_set()/,/^}}/p;/^embed_idle_user_value()/,/^}}/p" "{SETUP}");'
        f'AEP_DATA_DIR="{data}"; TOOLCHAIN_ENV="$AEP_DATA_DIR/toolchain.env"; go_semver() {{ echo 1.2.3; }};'
        "GO_CUR=/bin/true; GO_CHANNEL=stable; GO_RESOLVED=1.2.3;\n" + text[start:end]
    )
    env = {"PATH": "/usr/bin:/bin", "LANG": "C", **(user_env or {})}
    res = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, check=False)  # noqa: S603
    assert res.returncode == 0, res.stderr
    return (data / "toolchain.env").read_text()


def test_idle_value_only_in_toolchain_env_survives_rewrite(tmp_path: Path, monkeypatch) -> None:
    out = _rewrite_flow(tmp_path, "AEP_GO_CHANNEL=pinned\nAEP_EMBED_IDLE_S=45\n")
    assert out.count("AEP_EMBED_IDLE_S=45") == 1 and "AEP_GO_BIN=/bin/true" in out
    monkeypatch.delenv(embedder.IDLE_ENV, raising=False)
    monkeypatch.setenv("AEP_DATA_HOME", str(tmp_path / "data"))
    assert embedder.idle_seconds() == 45.0  # the engine still sees the user's setting after the rewrite


def test_idle_value_from_environment_is_persisted(tmp_path: Path, monkeypatch) -> None:
    out = _rewrite_flow(tmp_path, "AEP_GO_CHANNEL=stable\n", {"AEP_EMBED_IDLE_S": "30"})
    assert out.count("AEP_EMBED_IDLE_S=30") == 1
    monkeypatch.delenv(embedder.IDLE_ENV, raising=False)
    monkeypatch.setenv("AEP_DATA_HOME", str(tmp_path / "data"))
    assert embedder.idle_seconds() == 30.0


def test_nothing_written_when_user_never_set_idle(tmp_path: Path, monkeypatch) -> None:
    out = _rewrite_flow(tmp_path, "AEP_GO_CHANNEL=stable\n")
    assert "AEP_EMBED_IDLE_S" not in out and "AEP_GO_BIN=/bin/true" in out
    monkeypatch.delenv(embedder.IDLE_ENV, raising=False)
    monkeypatch.setenv("AEP_DATA_HOME", str(tmp_path / "data"))
    assert embedder.idle_seconds() >= 0  # unset: engine falls back to its code default
