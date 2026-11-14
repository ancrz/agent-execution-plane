"""ONT-50 T3 (G31): NOOP / DRY_RUN / SKIPPED are not errors (INFO + neutral next_action)."""

import json

import pytest

from engine.telemetry import RequestTelemetry, attach_envelope, infer_severity, is_field_error_status


@pytest.mark.parametrize("status", ["NOOP", "DRY_RUN", "SKIPPED"])
def test_non_error_statuses_are_info_with_neutral_next_action(status):
    assert infer_severity(status) == "INFO"
    assert not is_field_error_status(status)
    out = json.loads(
        attach_envelope({"status": status}, RequestTelemetry("kanban_board", "archive"), verbosity="detail")
    )
    assert out["severity"] == "INFO"
    assert out["next_action"] == "Nothing to do; adjust filters or apply=true."


def test_real_errors_keep_error_severity():
    assert infer_severity("EXEC_FAILED") == "ERROR"
