"""ONT-42b B1: D-01b, toda tool con parámetro `action` anuncia `actions` en discover(schema, summary).

`aep_ctl` queda fuera: sus acciones se anuncian por dominio (`aep_ctl(action="schema")`).
El xfail estricto es el dogfood de B9 (la constante `_TOOL_ACTIONS` lo cierra); no se implementa aquí.
"""

from __future__ import annotations

import asyncio
import json

import server

_PER_DOMAIN = frozenset({"aep_ctl"})


def test_every_action_tool_advertises_actions_in_schema_summary() -> None:
    payload = json.loads(asyncio.run(server.discover(action="schema", verbosity="summary", force_refresh=True)))
    tools = payload["tools"]
    with_action = sorted(
        name
        for name, meta in tools.items()
        if name not in _PER_DOMAIN and any(p.split(":", 1)[0] == "action" for p in meta["params"])
    )
    assert with_action, "ninguna tool con parámetro 'action' en el schema"
    missing = [name for name in with_action if not tools[name]["actions"]]
    assert not missing, f"tools con 'action' sin 'actions': {missing}"
