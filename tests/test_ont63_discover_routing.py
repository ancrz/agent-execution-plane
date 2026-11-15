"""ONT-63 D2: deterministic lexical pre-routing of basic intents in discover (EN+ES, accent-folded)."""

from __future__ import annotations

import json

import pytest

import server
from engine.intent_router import route_basic_intent

_PROBE = 'aep_ctl(domain="network", action="probe", params={"host": "github.com", "port": 443}'
_CASES = [
    ("is go installed", 'name="toolchain-probe", params={"names": ["go"]}'),
    ("is docker installed", 'name="toolchain-probe", params={"names": ["docker"]}'),
    ("esta instalado docker", 'name="toolchain-probe", params={"names": ["docker"]}'),
    ("quién usa este archivo", 'name="path-users"'),
    ("who is using this file", 'name="path-users"'),
    ("cuánto ocupa la carpeta", 'name="dir-usage"'),
    ("how big is this folder", 'name="dir-usage"'),
    ("llego a github.com:443", _PROBE),
    ("can I reach github.com:443", _PROBE),
    ("qué es el proceso 1234", 'process_inspect(pid=1234, verbosity="detail")'),
    ("what is process 1234", 'process_inspect(pid=1234, verbosity="detail")'),
    ("qué es este repo", 'name="workspace-probe"'),
    ("what is this repo", 'name="workspace-probe"'),
    ("orientarme", 'name="orient"'),
    ("orient me", 'name="orient"'),
    ("get oriented", 'name="orient"'),
    ("dónde estoy", 'name="host-info"'),
    ("can I reach 10.0.0.5 port 22", '"host": "10.0.0.5", "port": 22'),
]


@pytest.mark.parametrize(("phrase", "expected"), _CASES)
def test_route_basic_intent_unit(phrase: str, expected: str) -> None:
    routed = route_basic_intent(phrase)
    assert routed is not None and expected in routed, (phrase, routed)


@pytest.mark.anyio
@pytest.mark.parametrize(("phrase", "expected"), _CASES)
async def test_discover_recommends_routed_call(phrase: str, expected: str) -> None:
    data = json.loads(await server.discover(use_case=phrase, action="discover", verbosity="detail"))
    assert data["match_status"] == "MATCHED" and expected in data["recommended_next_call"], data[
        "recommended_next_call"
    ]


@pytest.mark.parametrize(
    "phrase",
    ["how to start a service", "run the test suite", "restart nginx", "open ports listening", "host a.b.c:99999"],
)
def test_generic_phrases_are_not_hijacked(phrase: str) -> None:
    assert route_basic_intent(phrase) is None


def test_empty_and_invalid_inputs_return_none() -> None:
    assert route_basic_intent("") is None
    assert route_basic_intent("   ") is None
    assert route_basic_intent("process 0") is None
