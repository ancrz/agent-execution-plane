"""download_verified must tell a failed download apart from a checksum mismatch."""

import hashlib
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETUP = (ROOT / "scripts" / "setup.sh").read_text()


def _functions() -> str:
    """Extract download() + download_verified() (with their globals) from setup.sh."""
    m = re.search(r"^download\(\) \{.*?^\}\n", SETUP, re.DOTALL | re.MULTILINE)
    n = re.search(r"^DL_FAIL_REASON=\"\"\ndownload_verified\(\) \{.*?^\}\n", SETUP, re.DOTALL | re.MULTILINE)
    assert m and n
    return m.group(0) + n.group(0)


def _run(url: str, sha: str, dest: Path) -> subprocess.CompletedProcess:
    script = (
        "log_warn() { echo \"WARN:$*\"; }\nlog_err() { echo \"ERR:$*\"; }\n"
        + _functions()
        + f'download_verified "{url}" "{dest}" "{sha}"; rc=$?\necho "RC=$rc REASON=$DL_FAIL_REASON"\n'
    )
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60, check=False)


def test_checksum_mismatch_reports_checksum(tmp_path) -> None:
    src = tmp_path / "asset.bin"
    src.write_bytes(b"payload")
    dest = tmp_path / "out.bin"
    res = _run(f"file://{src}", "0" * 64, dest)
    assert "RC=2 REASON=checksum" in res.stdout
    assert "no coincide" in res.stdout
    assert "red o release" not in res.stdout
    assert not dest.exists()


def test_download_failure_reports_download(tmp_path) -> None:
    dest = tmp_path / "out.bin"
    res = _run(f"file://{tmp_path}/missing.bin", "0" * 64, dest)
    assert "RC=1 REASON=download" in res.stdout
    assert "red o release" in res.stdout
    assert "no coincide" not in res.stdout


def test_valid_download_returns_zero(tmp_path) -> None:
    src = tmp_path / "asset.bin"
    src.write_bytes(b"payload")
    dest = tmp_path / "out.bin"
    res = _run(f"file://{src}", hashlib.sha256(b"payload").hexdigest(), dest)
    assert "RC=0 REASON=" in res.stdout
    assert dest.read_bytes() == b"payload"


def test_pinned_golangci_lint_is_go126_compatible_v2() -> None:
    assert re.search(r'^GL_VERSION="2\.\d+\.\d+"$', SETUP, re.MULTILINE)
