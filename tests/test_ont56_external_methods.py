"""ONT-56: `_EXTERNAL_METHODS` congelado como literal versionado (independiente de la versión de Python)."""

from __future__ import annotations

import sys

import pytest

from engine import threads
from engine import threads_extractors as ex
from engine.threads_external_methods import EXTERNAL_METHODS, SNAPSHOT_PY_VERSION


def test_extractor_uses_frozen_literal() -> None:
    assert ex._EXTERNAL_METHODS is EXTERNAL_METHODS
    assert isinstance(EXTERNAL_METHODS, frozenset) and EXTERNAL_METHODS
    assert all(isinstance(n, str) and not n.startswith("_") for n in EXTERNAL_METHODS)
    assert ex.EXTERNAL_METHODS_SNAPSHOT == SNAPSHOT_PY_VERSION


def test_generator_matches_literal_on_snapshot_interpreter() -> None:
    generated = ex._build_external_methods()
    if not sys.version.startswith(SNAPSHOT_PY_VERSION):
        added = sorted(generated - EXTERNAL_METHODS)
        removed = sorted(EXTERNAL_METHODS - generated)
        pytest.skip(
            f"Python {sys.version.split()[0]} != snapshot {SNAPSHOT_PY_VERSION}: +{added} -{removed}; "
            "regenerar engine/threads_external_methods.py"
        )
    assert generated == EXTERNAL_METHODS


def test_graph_payload_reports_snapshot_only_in_detail() -> None:
    analysis = threads.analyze(".", use_cache=False)
    detail = threads.graph_payload(analysis)
    assert detail["external_methods_snapshot"] == SNAPSHOT_PY_VERSION
    assert "py_version" in detail
    assert "external_methods_snapshot" not in threads.graph_payload(analysis, terse=True)
