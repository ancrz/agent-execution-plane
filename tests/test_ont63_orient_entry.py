"""ONT-63 group (d): orient entry point, L0/L1/L2 ladder, WF-0 playbook and discover routing."""

from __future__ import annotations

import json
import time
from unittest.mock import patch

import pytest

import engine.primitives_orient as po
import server
from engine.privilege import tactical_playbook


async def _orient(verbosity: str = "summary", params: dict | None = None) -> tuple[str, dict]:
    raw = await server.default_primitives(action="run", name="orient", params=params or {}, verbosity=verbosity)
    return raw, json.loads(raw)


@pytest.mark.anyio
async def test_orient_summary_is_terse_and_fast() -> None:
    t0 = time.perf_counter()
    raw, data = await _orient()
    assert time.perf_counter() - t0 < 4.0
    assert data["status"] in ("OK", "PARTIAL")
    res = data["result"]
    assert len(json.dumps(res, separators=(",", ":")).encode()) <= 1500
    for key in ("host", "resources", "tools_present", "tools_missing", "workspace", "aep_ready", "next_actions"):
        assert key in res
    assert len(res["next_actions"]) <= 5
    assert "L2" in res["escalate"] and "artifact_execute_in_ram" in res["escalate"]


@pytest.mark.anyio
async def test_orient_detail_has_full_sub_results() -> None:
    _, data = await _orient("detail")
    res = data["result"]
    for key in ("host", "cpu", "mem", "disk_root", "disk_path", "tools", "workspace"):
        assert key in res
    assert res["tools"]["tools"] and "partial" not in res


@pytest.mark.anyio
async def test_orient_partial_failure_does_not_sink_the_rest() -> None:
    def boom(_p: dict) -> dict:
        raise RuntimeError("probe exploded")

    with patch.object(po, "_run_cpu_load", boom):
        raw, data = await _orient()
    assert data["status"] == "PARTIAL" and data["severity"] == "WARN"
    assert data["result"]["partial"] is True and data["result"]["errors"]["cpu"] == "RuntimeError"
    assert data["result"]["host"] and data["result"]["tools_present"]


@pytest.mark.anyio
async def test_orient_vetoed_path_is_param_error() -> None:
    _, data = await _orient(params={"path": "/etc/shadow"})
    assert data["status"] == "PARAM_ERROR"


@pytest.mark.anyio
async def test_each_primitive_within_its_latency_cap(tmp_path) -> None:
    caps = {
        "host-info": (1.0, {}),
        "cpu-load": (1.5, {"sample_ms": 100}),
        "toolchain-probe": (3.5, {}),
        "workspace-probe": (2.5, {"path": str(tmp_path)}),
        "file-fingerprint": (1.0, {"paths": [str(tmp_path)]}),
        "dir-usage": (5.5, {"path": str(tmp_path)}),
        "path-users": (5.5, {"path": str(tmp_path)}),
        "orient": (4.0, {"path": str(tmp_path)}),
    }
    for name, (cap_s, params) in caps.items():
        t0 = time.perf_counter()
        data = json.loads(await server.default_primitives(action="run", name=name, params=params, verbosity="summary"))
        assert data["status"] in ("OK", "PARTIAL"), name
        assert time.perf_counter() - t0 < cap_s, name


def test_playbook_wf0_and_quick_reference() -> None:
    pb = tactical_playbook()
    assert pb["workflow_recipes"][0]["id"] == "WF-0"
    assert "orient" in pb["workflow_recipes"][0]["steps"][0]
    assert "artifact_execute_in_ram" in pb["workflow_recipes"][0]["steps"][2]
    assert "orient" in pb["quick_reference"]["orient_first"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("use_case", "expected"),
    [
        ("orientarme y empezar en este host overview", 'name="orient"'),
        ("hash sha256 checksum del archivo", 'name="file-fingerprint"'),
        ("cuanto ocupa la carpeta directory size", 'name="dir-usage"'),
        ("que es este repositorio proyecto repo workspace", 'name="workspace-probe"'),
    ],
)
async def test_discover_routes_basic_intents_to_primitives(use_case: str, expected: str) -> None:
    data = json.loads(await server.discover(use_case=use_case, action="discover", verbosity="detail"))
    assert expected in data["recommended_next_call"], data["recommended_next_call"]


@pytest.mark.anyio
async def test_discover_network_and_process_intents_not_hijacked() -> None:
    net = json.loads(
        await server.discover(use_case="open listening ports sockets", action="discover", verbosity="detail")
    )
    assert "default_primitives" not in net["recommended_next_call"]
    proc = json.loads(
        await server.discover(
            use_case="inspect process pid open file descriptors", action="discover", verbosity="detail"
        )
    )
    assert "default_primitives" not in proc["recommended_next_call"]
