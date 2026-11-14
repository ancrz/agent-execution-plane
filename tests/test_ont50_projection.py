"""ONT-50 T2 (G18): single projection in compact playbook_run; detail keeps `output` + projection."""

import asyncio
import json

import server
from engine.ipc_pool import project_fields

STEPS = [{"id": "s1", "tool": "process_inspect", "params": {"pid": 0, "limit": 2}}]


def _run(verbosity: str) -> dict:
    return json.loads(
        asyncio.run(
            server.playbook_run(
                action="batch",
                steps=STEPS,
                return_only="last",
                select_fields=["status", "pid"],
                verbosity=verbosity,
            )
        )
    )


def test_compact_modes_emit_projection_once():
    for verbosity in ("summary", "brief", "terse"):
        res = _run(verbosity)
        assert "output" not in res, verbosity
        assert isinstance(res["pid"], int) and res["pid"] > 0
        est = res["token_savings_estimate"]
        assert est["projected_bytes"] < est["full_bytes"]


def test_detail_keeps_output_and_projection():
    res = _run("detail")
    assert res["pid"] == res["output"]["pid"]


def test_project_fields_single_projection_flag():
    data = {"status": "OK", "output": {"pid": 7}}
    both = project_fields(data, ["pid"])
    once = project_fields(data, ["pid"], single_projection=True)
    assert both == {"pid": 7, "output": {"pid": 7}}
    assert once == {"pid": 7}
