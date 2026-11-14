"""ONT-54 T2 (G44): error_class folds accents instead of dropping the accented letter."""

from __future__ import annotations

import pytest

from engine.telemetry import normalize_error_class


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"error": "parámetro requerido"}, "parametro"),
        ({"error_class": "ValueErrör"}, "valueerror"),
        ({"error": "Acción inválida"}, "accion"),
        ({"error": "ValueError: boom"}, "valueerror"),
        ({"error": "日本語"}, "unknown"),
    ],
)
def test_error_class_is_ascii_folded(payload: dict, expected: str) -> None:
    assert normalize_error_class(payload) == expected
