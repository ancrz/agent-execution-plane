"""ONT-57 T1: every status emitted by server.py / engine/*.py / scripts/aep-ctl has an explicit severity."""

import glob
import pathlib
import re

import pytest

from engine.telemetry import infer_severity, is_classified_status

ROOT = pathlib.Path(__file__).resolve().parent.parent
_PATTERNS = [
    re.compile(r"""["']status["']\s*:\s*["']([A-Z][A-Z0-9_]+)["']"""),
    re.compile(r"""["']verdict["']\s*:\s*["']([A-Z][A-Z0-9_]+)["']"""),
    re.compile(r"""\bstatus\s*=\s*["']([A-Z][A-Z0-9_]+)["']"""),
    re.compile(r"""\bst\s*=\s*["']([A-Z][A-Z0-9_]+)["']"""),
    re.compile(r"""\bstatus_val\s*=\s*["']([A-Z][A-Z0-9_]+)["']"""),
]


def _emitted_statuses() -> set[str]:
    files = [
        ROOT / "server.py",
        ROOT / "scripts" / "aep-ctl",
        *map(pathlib.Path, glob.glob(str(ROOT / "engine" / "*.py"))),
    ]
    found: set[str] = set()
    for f in files:
        text = f.read_text(encoding="utf-8")
        for pat in _PATTERNS:
            found.update(pat.findall(text))
    return found


def test_scan_finds_statuses():
    found = _emitted_statuses()
    assert len(found) > 60  # guards against a silently broken scanner
    assert is_classified_status("OK")


def test_every_emitted_status_is_explicitly_classified():
    missing = sorted(s for s in _emitted_statuses() if not is_classified_status(s))
    assert not missing, f"unclassified statuses (add to engine/telemetry.py sets): {missing}"


@pytest.mark.parametrize(
    ("status", "sev"),
    [
        ("RECLASSIFIED", "INFO"),
        ("APPLIED", "INFO"),
        ("HEALTHY", "INFO"),
        ("NOT_FOUND", "WARN"),
        ("BLOCKED", "WARN"),
        ("CONFIRM_REQUIRED", "WARN"),
        ("PARAM_ERROR", "ERROR"),
        ("BACKUP_NOT_FOUND", "ERROR"),
        ("PERMISSION_DENIED", "ERROR"),
        ("CORRUPTED_BACKUP", "ERROR"),
        ("SNAPSHOT_FAILED", "ERROR"),
        ("INVALID_ACTION", "ERROR"),
        ("SOMETHING_NEW", "ERROR"),
    ],
)
def test_severity(status, sev):
    assert infer_severity(status) == sev
