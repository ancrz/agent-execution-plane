"""ONT-53 (G41): tabla unica de sinonimos de accion EN+ES (engine.privilege.ACTION_SYNONYMS)."""

from __future__ import annotations

import asyncio
import json

import pytest

import server
from engine import privilege


def _discover(use_case: str) -> dict:
    return json.loads(asyncio.run(server.discover(use_case=use_case, verbosity="summary")))


@pytest.mark.parametrize(
    ("use_case", "action"),
    [
        ("puertos abiertos escucha", "listeners"),
        ("hosts en mi red", "neighbors"),
        ("list open ports", "listeners"),
        ("find which hosts are on my LAN", "neighbors"),
        ("devices on my lan", "neighbors"),
    ],
)
def test_discover_routes_en_es_to_canonical_action(use_case, action):
    res = _discover(use_case)
    assert res["confidence"] == "HIGH"
    assert res["suggested_capability"][0]["capability"] == "system_inspect"
    assert f'action="{action}"' in res["recommended_next_call"]


def test_single_source_of_truth_for_synonyms():
    assert not hasattr(server, "_ACTION_SYNONYMS")
    assert server.ACTION_SYNONYMS is privilege.ACTION_SYNONYMS


def test_capability_keywords_consume_synonym_table_without_duplicates():
    toks = privilege._CAP_KEYWORDS["system_inspect"].split()
    for syns in privilege.ACTION_SYNONYMS.values():
        assert set(syns) <= set(toks)
    es = {"puertos", "escucha", "vecinos", "montajes"}
    assert es <= set(privilege.ACTION_SYNONYMS["listeners"]) | set(privilege.ACTION_SYNONYMS["neighbors"]) | set(
        privilege.ACTION_SYNONYMS["mounts"]
    )


def test_pick_canonical_call_uses_shared_table_for_spanish():
    calls = [
        'aep_ctl(action="schema")',
        'aep_ctl(domain="network", action="listeners")',
        'aep_ctl(domain="network", action="neighbors")',
        'aep_ctl(domain="storage", action="mounts")',
    ]
    assert "neighbors" in server._pick_canonical_call("vecinos dispositivos", calls)
    assert "mounts" in server._pick_canonical_call("montajes de disco", calls)
    assert "listeners" in server._pick_canonical_call("puertos abiertos", calls)
