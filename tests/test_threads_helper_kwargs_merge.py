"""D-E4-1 (00886c3): `_collect_test_refs` fusiona los kwargs constantes de CADA sitio de llamada a un helper local."""

from __future__ import annotations

from pathlib import Path

from engine import threads

_SERVER = """
mcp = object()

@mcp.tool()
async def multi(action: str = "main", verbosity: str = "summary"):
    act = action
    if act == "main":
        return 1
    elif act == "second":
        return 2
    elif act == "third":
        return 3
    elif act == "fourth":
        return 4
"""
_PRIV = """
_CAPABILITIES = {"c": (4, 4, "self", ["multi"], "d")}
CHMOD_DEGRADATION_MATRIX = {"tools": {"multi": {}}}
_CAP_TACTICAL = {}
CONTROL_PLANE_SCHEMA = {}
"""

_HEADER = "import server\n\n\ndef _call(action):\n    return server.multi(action=action, verbosity='terse')\n\n\n"
_BODY_A = "def test_two_sites():\n    _call(action='main')\n    _call(action='second')\n"
_BODY_B = "def test_other_site():\n    _call(action='third')\n"
_NESTED = "def _outer(action):\n    return _call(action=action)\n\n\ndef test_nested():\n    _outer(action='fourth')\n"


def _tree(tmp: Path, tests_src: str) -> Path:
    for d in ("engine", "tests", "schemas"):
        (tmp / d).mkdir()
    (tmp / "server.py").write_text(_SERVER)
    (tmp / "engine" / "__init__.py").write_text("")
    (tmp / "engine" / "privilege.py").write_text(_PRIV)
    (tmp / "tests" / "test_multi.py").write_text(tests_src)
    return tmp


def _covers(root: Path) -> dict[str, set[str]]:
    a = threads.analyze(root, use_cache=False)
    out: dict[str, set[str]] = {}
    for e in a.graph.edges({"covers"}):
        if e.src.startswith("test:") and (e.dst.startswith("action:multi:") or e.dst == "tool:multi"):
            out.setdefault(e.src, set()).add(e.dst)
    return out


def test_helper_from_multiple_sites_merges_each_site_kwargs(tmp_path: Path) -> None:
    covers = _covers(_tree(tmp_path, _HEADER + _BODY_A + "\n\n" + _BODY_B))
    two = covers["test:tests/test_multi.py::test_two_sites"]
    other = covers["test:tests/test_multi.py::test_other_site"]
    # ambos sitios del mismo test se acumulan: sin perdida ni fuga de un sitio al otro
    assert two == {"tool:multi", "action:multi:main", "action:multi:second"}
    assert other == {"tool:multi", "action:multi:third"}


def test_helper_kwargs_merge_is_order_independent_and_deterministic(tmp_path: Path) -> None:
    fwd = tmp_path / "fwd"
    rev = tmp_path / "rev"
    fwd.mkdir()
    rev.mkdir()
    swapped = "def test_two_sites():\n    _call(action='second')\n    _call(action='main')\n"
    first = _covers(_tree(fwd, _HEADER + _BODY_A))
    assert first == _covers(_tree(rev, _HEADER + swapped))
    # re-ejecutar sobre el mismo arbol da el mismo conjunto y el mismo Merkle R
    again = threads.analyze(fwd, use_cache=False)
    assert _covers(fwd) == first and again.root_hash == threads.analyze(fwd, use_cache=False).root_hash


def test_nested_helper_site_kwargs_propagate(tmp_path: Path) -> None:
    covers = _covers(_tree(tmp_path, _HEADER + _NESTED))
    assert covers["test:tests/test_multi.py::test_nested"] == {"tool:multi", "action:multi:fourth"}
