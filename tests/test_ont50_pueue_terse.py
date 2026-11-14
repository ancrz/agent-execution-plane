"""ONT-50 T4 (G32): pueue status in terse mode folds rows like summary and drops the all-Running groups map."""

import json

import server


def _raw(group_status: str = "Running", n: int = 8) -> str:
    tasks = {
        str(i): {
            "id": i,
            "label": f"job-{i}",
            "command": "x" * 200,
            "group": "default",
            "envs": {"BIG": "y" * 500},
            "path": "/tmp/work",
            "status": {"Done": {"result": "Success", "start": "t0", "end": "t1"}},
        }
        for i in range(n)
    }
    groups = {"default": {"status": group_status, "parallel_tasks": 1}}
    return json.dumps({"tasks": tasks, "groups": groups})


def test_terse_row_shape_and_no_groups_when_all_running():
    payload, _ = server._compact_pueue_payload(_raw(), limit=3, is_compact=True, terse=True)
    assert "groups" not in payload
    row = payload["tasks"]["7"]
    assert set(row) == {"id", "label", "command", "group", "status"}
    assert len(row["command"]) == 80 and row["status"] == "Done (Success)"


def test_terse_keeps_groups_when_one_is_not_running():
    payload, _ = server._compact_pueue_payload(_raw("Paused"), limit=3, is_compact=True, terse=True)
    assert payload["groups"]["default"]["status"] == "Paused"


def test_summary_unchanged_and_terse_is_smaller():
    summary, _ = server._compact_pueue_payload(_raw(), limit=3, is_compact=True)
    terse, _ = server._compact_pueue_payload(_raw(), limit=3, is_compact=True, terse=True)
    assert "groups" in summary and len(summary["tasks"]["7"]["command"]) == 100
    assert len(json.dumps(terse)) < len(json.dumps(summary))
    assert len(json.dumps(terse)) <= 700  # budget: 3 folded rows + counters
