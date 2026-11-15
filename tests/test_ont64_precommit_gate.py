"""ONT-64: aep-sync.sh --check runs the coverage gate only when staged files can affect the thread graph."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from engine import threads_extractors

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "aep-sync.sh"


def _needs(names: str) -> bool:
    # The gate protects exactly the claims the thread-graph extractor reads; bind to its regexes.
    assert threads_extractors._TOOL_COUNT_RE.search("17 tools") and threads_extractors._CAP_COUNT_RE
    src = SCRIPT.read_text(encoding="utf-8")
    start = src.index("needs_coverage_gate() {")
    end = src.index("\n}\n", start) + 3
    proc = subprocess.run(
        ["bash", "-c", src[start:end] + "\nneeds_coverage_gate"],
        input=names,
        text=True,
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0


@pytest.mark.parametrize(
    "names",
    [
        "README.md\n",
        "docs/STATE.md\n",
        "engine/threads_extractors.py\n",
        "engine/threads.py\nx.py\n",
        "tests/test_a.py\n",
    ],
)
def test_gate_runs_for_relevant_paths(names: str) -> None:
    assert _needs(names)


@pytest.mark.parametrize("names", ["", "engine/primitives_orient.py\n", "server.py\nscripts/aep-sync.sh\n"])
def test_gate_skipped_otherwise(names: str) -> None:
    assert not _needs(names)


def test_gate_is_wired_after_import_smoke() -> None:
    assert threads_extractors.HIST_MARKERS
    src = SCRIPT.read_text(encoding="utf-8")
    assert src.index("import server;") < src.index("| needs_coverage_gate; then")
    assert "test_ont41_coverage.py" in src


def test_readme_orientation_table_is_not_a_tool_count_claim() -> None:
    readme = SCRIPT.parent.parent.joinpath("README.md").read_text(encoding="utf-8")
    for line in readme.splitlines():
        if "toolchain-probe" in line:
            assert not threads_extractors._TOOL_COUNT_RE.search(line)
