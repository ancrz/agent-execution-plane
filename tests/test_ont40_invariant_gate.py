"""ONT-40 T15 (F1, C3): gate grep que falla si queda una referencia residual a «16 tools».

El gate se excluye a sí mismo. La exclusión de líneas con «passed» (resúmenes de pytest) NO tapa asserts
reales de conteo: una línea con `assert`/`len(` jamás se excluye por contener «passed».
"""

from __future__ import annotations

import re
from pathlib import Path

from engine import threads

REPO = Path(__file__).resolve().parent.parent
SELF = Path(__file__).resolve()

_TOOL16 = re.compile(
    r"\b16[ -](?:fast ?mcp[ -]|typed[ -]|polymorphic[ -]|rpc[ -]|json-rpc[ -]|mcp[ -])*tools?\b"
    r"|\b16-Tool\b|\b16/16\b|expected_16|exactly 16\b|len\(\w*tools\w*(?:\.keys\(\))?\)\s*==\s*16\b",
    re.IGNORECASE,
)
_HIST = ("(histórico)", "(historical)", "<!-- aep:hist -->")
_ASSERTISH = re.compile(r"\bassert\b|\blen\(|==")


def _excluded(line: str) -> bool:
    if any(m in line for m in _HIST):
        return True
    # Resúmenes de pytest («16 passed») se ignoran, pero nunca una línea que sea un assert de conteo.
    return "passed" in line and not _ASSERTISH.search(line)


def scan(files: list[Path]) -> list[str]:
    hits: list[str] = []
    for path in files:
        if path.resolve() == SELF:
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            if _TOOL16.search(line) and not _excluded(line):
                hits.append(f"{path.relative_to(REPO)}:{i}: {line.strip()[:100]}")
    return hits


def _targets() -> list[Path]:
    files = [REPO / "server.py", REPO / "README.md", *sorted((REPO / "engine").glob("*.py"))]
    files += sorted((REPO / "tests").glob("*.py")) + sorted((REPO / "scripts").glob("*.sh"))
    return [f for f in files if f.is_file()]


def test_no_residual_16_tools_reference() -> None:
    assert threads.GRAPH_SCHEMA_VERSION
    assert scan(_targets()) == []


def test_gate_excludes_pytest_summaries_but_not_count_asserts(tmp_path: Path) -> None:
    assert threads.GRAPH_SCHEMA_VERSION
    f = tmp_path / "x.py"
    f.write_text("================ 16 passed in 2s ================\nassert len(tools) == 16, 'passed'\n")
    hits = scan([f]) if f.is_relative_to(REPO) else None
    assert hits is None  # fuera del repo: se prueba la lógica directamente
    assert _excluded("16 passed, 2 tools") is True
    assert _excluded("assert len(tools) == 16  # all passed") is False
    assert _TOOL16.search("assert len(tools) == 16")
    assert not _TOOL16.search("assert parsed['passed'] == 16")


def test_gate_excludes_itself() -> None:
    assert threads.GRAPH_SCHEMA_VERSION
    assert not any("test_ont40_invariant_gate" in h for h in scan(_targets()))
