"""
Engine: intent_router.py — deterministic lexical pre-routing of basic orientation intents (ONT-63 D2).

`discover(use_case=...)` ranks capabilities by token overlap and falls back to the playbook below a 0.12 gate,
which natural short phrases ("is go installed", "llego a github.com:443") never reach.  This module resolves the
unambiguous basic intents BEFORE that gate, with no model and no randomness:

  1. host:port (or reach-word + host + port)         -> aep_ctl network probe        (L1 sub-tool, not a primitive)
  2. process/proceso/pid + number                    -> process_inspect(pid=N, detail)
  3. installed/instalado/version + a tool name       -> toolchain-probe(names=[name])
  4. best unique score against PRIMITIVE_SYNONYMS    -> the matching layer-0 primitive

Accents are folded (NFKD) so "quién" == "quien".  Returns the canonical call string or None.
"""

from __future__ import annotations

import json
import re
import unicodedata

from engine.privilege import PRIMITIVE_SYNONYMS


def fold(text: str) -> str:
    """Lowercase and strip combining accents (NFKD)."""
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def tokens(text: str) -> set[str]:
    """Folded word tokens (>= 3 chars) with a trailing plural 's' stripped."""
    return {
        t[:-1] if t.endswith("s") and len(t) > 3 else t for t in re.findall(r"[a-z0-9]+", fold(text)) if len(t) >= 3
    }


_HOST = r"(?:localhost|\d{1,3}(?:\.\d{1,3}){3}|[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9-]+)+)"
_HOST_PORT = re.compile(rf"\b({_HOST})\s*:\s*(\d{{1,5}})\b")
_REACH_WORDS = re.compile(r"\b(reach|llego|alcanzo|alcanzar|ping|connect|conecto|conectar|conectarme|acceder)\b")
_HOST_THEN_PORT = re.compile(rf"\b({_HOST})\b\W+(?:port|puerto)\s*(\d{{1,5}})\b")
_PROCESS = re.compile(r"\b(?:proceso|process|pid)\b\D{0,15}?(\d+)\b")
_INSTALL_WORDS = re.compile(r"\b(installed|instalado|instalada|version)\b")
_STOP = frozenset(
    "is the a an of de del la el esta este que what which version installed instalado instalada here aqui this "
    "machine host check tengo hay have do does on en my mi es cual and for in it".split()
)
_TOOL_NAME = re.compile(r"^[a-z0-9][a-z0-9._+-]*$")

# Tokens that identify a primitive on their own; any other synonym needs a second corroborating token.
_STRONG = frozenset(
    "orient orientar orientarme orientame oriented overview hostname distro kernel uptime toolchain hash checksum "
    "sha256 fingerprint huella folder directory carpeta directorio repo repository repositorio workspace lsof fuser".split()
)

_CALLS = {
    "orient": 'default_primitives(action="run", name="orient", verbosity="summary")',
    "host-info": 'default_primitives(action="run", name="host-info", verbosity="summary")',
    "cpu-load": 'default_primitives(action="run", name="cpu-load", verbosity="summary")',
    "toolchain-probe": 'default_primitives(action="run", name="toolchain-probe", verbosity="summary")',
    "workspace-probe": 'default_primitives(action="run", name="workspace-probe", params={"path": "."}, verbosity="summary")',
    "file-fingerprint": 'default_primitives(action="run", name="file-fingerprint", params={"paths": ["<file>"]}, verbosity="summary")',
    "dir-usage": 'default_primitives(action="run", name="dir-usage", params={"path": "<dir>"}, verbosity="summary")',
    "path-users": 'default_primitives(action="run", name="path-users", params={"path": "<path>"}, verbosity="summary")',
}


def _port_ok(raw: str) -> int | None:
    port = int(raw)
    return port if 1 <= port <= 65535 else None


def _network_call(host: str, port: int) -> str:
    return (
        f'aep_ctl(domain="network", action="probe", params={{"host": "{host}", "port": {port}}}, verbosity="summary")'
    )


def _tool_name(folded: str) -> str | None:
    for word in re.findall(r"[a-z0-9][a-z0-9._+-]*", folded):
        if word not in _STOP and _TOOL_NAME.fullmatch(word):
            return word
    return None


def route_basic_intent(use_case: str) -> str | None:
    """Canonical call for an unambiguous basic intent, else None (caller keeps its ranking-based routing)."""
    if not use_case or not use_case.strip():
        return None
    text = fold(use_case)

    m = _HOST_PORT.search(text)
    if m and (port := _port_ok(m.group(2))):
        return _network_call(m.group(1), port)
    if _REACH_WORDS.search(text) and (m := _HOST_THEN_PORT.search(text)) and (port := _port_ok(m.group(2))):
        return _network_call(m.group(1), port)

    m = _PROCESS.search(text)
    if m and int(m.group(1)) > 0:
        return f'process_inspect(pid={int(m.group(1))}, verbosity="detail")'

    if _INSTALL_WORDS.search(text) and (name := _tool_name(text)):
        names = json.dumps([name])
        return f'default_primitives(action="run", name="toolchain-probe", params={{"names": {names}}}, verbosity="summary")'

    want = tokens(use_case)
    scored: list[tuple[int, str]] = []
    for prim, syns in PRIMITIVE_SYNONYMS.items():
        hits = want & {t for s in syns for t in tokens(s)}
        if not hits:
            continue
        score = len(hits) + sum(1 for t in hits if t in _STRONG)  # a strong token alone reaches the threshold
        if score >= 2:
            scored.append((score, prim))
    scored.sort(reverse=True)
    if scored and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        return _CALLS[scored[0][1]]
    return None
