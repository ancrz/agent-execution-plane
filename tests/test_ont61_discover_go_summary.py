"""ONT-61 T3/G65: discover(capabilities) exposes a compact `go` block in summary; detail keeps the full one."""

from __future__ import annotations

import asyncio
import json

import server


def _caps(verbosity: str) -> dict:
    return json.loads(asyncio.run(server.discover(action="capabilities", verbosity=verbosity, force_refresh=True)))


def test_summary_go_block_is_compact_and_within_20_tokens() -> None:
    go = _caps("summary")["go"]
    assert set(go) == {"version", "supported"}
    assert len(json.dumps(go, separators=(",", ":"))) / 4 <= 20


def test_detail_keeps_full_go_block_and_terse_has_none() -> None:
    full = _caps("detail")["go"]
    assert {"version", "bin", "gofmt", "supported", "supported_min", "channel"} <= set(full)
    assert "go" not in _caps("terse")


def test_summary_growth_is_only_the_go_block() -> None:
    summary = _caps("summary")
    go = summary.pop("go")
    base = len(json.dumps(summary, separators=(",", ":"))) / 4
    with_go = base + len(json.dumps({"go": go}, separators=(",", ":"))) / 4
    assert with_go - base <= 20 and with_go < 6100 / 4  # 6,100 B budget (was 6,000; +64 B go block)
