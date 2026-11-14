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


_LITERAL_RE = re.compile(r"""["']([A-Z][A-Z0-9_]+)["']""")


def _expr_end(rhs: str) -> str:
    """Cut `rhs` at the first top-level `,` / `}` / `)` outside quotes (so sibling dict values are not scanned)."""
    quote = ""
    for i, ch in enumerate(rhs):
        if quote:
            quote = "" if ch == quote else quote
        elif ch in "\"'":
            quote = ch
        elif ch in ",})":
            return rhs[:i]
    return rhs


def scan_text(text: str) -> set[str]:
    """Every status literal on the right side of a matching line (ternaries: all branches, comments excluded)."""
    found: set[str] = set()
    for line in text.splitlines():
        for pat in _PATTERNS:
            m = pat.search(line)
            if m:
                rhs = line[m.start(1) - 1 :]
                rhs = _expr_end(re.split(r"\s#", rhs, maxsplit=1)[0])  # drop trailing comment, stop at sibling key
                found.update(_LITERAL_RE.findall(rhs))
    return found


def _emitted_statuses() -> set[str]:
    files = [
        ROOT / "server.py",
        ROOT / "scripts" / "aep-ctl",
        *map(pathlib.Path, glob.glob(str(ROOT / "engine" / "*.py"))),
    ]
    found: set[str] = set()
    for f in files:
        found |= scan_text(f.read_text(encoding="utf-8"))
    return found


def test_scanner_collects_every_ternary_literal():
    src = (
        'status = "AAA" if x else "BBB" if y else "CCC"  # "IGN"\n'
        '    return {"status": "DDD" if z else "EEE", "k": 1}\n'
    )
    assert scan_text(src) >= {"AAA", "BBB", "CCC", "DDD", "EEE"}
    assert "IGN" not in scan_text(src)
    assert "SIB" not in scan_text('x = {"status": "OK", "state": "SIB"}')
    assert is_classified_status("BROKEN") and infer_severity("BROKEN") == "WARN"


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
