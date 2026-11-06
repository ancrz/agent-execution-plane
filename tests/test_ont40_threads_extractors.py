"""ONT-40 T4-T8: extractores, claims, gaps por omisión, SyntaxError y determinismo (F11)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from engine import threads
from engine import threads_extractors as ex

REPO = Path(__file__).resolve().parent.parent

_SERVER = '''
from engine.helper import util
mcp = object()
_PLANNED_ACTIONS = ("spec",)

@mcp.tool()
async def autoevol(action: str = "list", verbosity: str = "summary"):
    act = action
    if act == "list":
        return util()
    if act in ("info", "spec"):
        return 1
'''
_PRIV = '''
_CAPABILITIES = {"orientation": (4, 4, "self", ["autoevol"], "d")}
CHMOD_DEGRADATION_MATRIX = {"tools": {"autoevol": {}}}
_CAP_TACTICAL = {"orientation": {"canonical_calls": ['autoevol(action="info")']}}
CONTROL_PLANE_SCHEMA = {}
'''
_HELPER = 'def util():\n    return "INSERT INTO t (a) VALUES (1)"\n\ndef orphan():\n    return 2\n'
_TEST = '''
import server
def test_autoevol():
    server.autoevol(action="list")
'''


def _tree(tmp: Path, *, readme: str = "autoevol(action=\"list\") 20 tools\n") -> Path:
    (tmp / "engine").mkdir()
    (tmp / "tests").mkdir()
    (tmp / "schemas").mkdir()
    (tmp / "server.py").write_text(_SERVER)
    (tmp / "engine" / "__init__.py").write_text("")
    (tmp / "engine" / "helper.py").write_text(_HELPER)
    (tmp / "engine" / "privilege.py").write_text(_PRIV)
    (tmp / "tests" / "test_autoevol.py").write_text(_TEST)
    (tmp / "schemas" / "database.sql").write_text("CREATE TABLE IF NOT EXISTS t (\n a INTEGER\n);\n")
    (tmp / "README.md").write_text(readme)
    (tmp / "pyproject.toml").write_text('[project]\nversion = "1.0.0"\n')
    return tmp


def test_tools_actions_planned_excluded_and_edges(tmp_path: Path) -> None:
    a = threads.analyze(_tree(tmp_path), use_cache=False)
    g = a.graph
    assert "tool:autoevol" in g.nodes
    assert {"action:autoevol:list", "action:autoevol:info"} <= set(g.nodes)
    assert "action:autoevol:spec" not in g.nodes  # _PLANNED_ACTIONS sin nodos
    assert g.in_edges("tool:autoevol", "routes")
    assert g.out_edges("tool:autoevol", "privileged_by")
    assert g.in_edges("action:autoevol:list", "covers")
    assert g.in_edges("state:t", "writes")
    assert g.in_edges("fn:engine.helper.util", "consumes")
    gap_ids = {x.id for x in a.gaps}
    assert "omission:fn:engine.helper.orphan:in:covers" in gap_ids


def test_claims_drift_and_historical_marker(tmp_path: Path) -> None:
    readme = "We have 15 tools.\nOld: 15 tools (histórico)\n"
    a = threads.analyze(_tree(tmp_path, readme=readme), use_cache=False)
    drift = [x for x in a.gaps if x.kind == "claim_drift"]
    assert len(drift) == 1 and "declared 15, observed 1" in drift[0].detail and drift[0].ref == "D-14"


def test_syntax_error_becomes_gap_with_reach(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    (root / "engine" / "helper.py").write_text("def broken(:\n")
    a = threads.analyze(root, use_cache=False)
    gap = next(x for x in a.gaps if x.kind == "syntax_error")
    assert gap.node == "module:engine.helper" and gap.reach >= 2  # server lo importa


def test_forbidden_threads_to_server_edge(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    (root / "engine" / "threads_x.py").write_text("import server\n")
    a = threads.analyze(root, use_cache=False)
    assert any(x.kind == "forbidden_edge" for x in a.gaps)


def test_r_deterministic_across_hashseed_and_path(tmp_path: Path) -> None:
    """F11: PYTHONHASHSEED y ruta distintos dan la misma R."""
    assert ex.module_name("engine/threads.py") == "engine.threads"
    copy = tmp_path / "copy_elsewhere"
    shutil.copytree(REPO, copy, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", ".claude"))
    code = "import sys; sys.path.insert(0, sys.argv[1]); from engine import threads; print(threads.analyze(sys.argv[1], use_cache=False).root_hash)"
    outs = []
    for seed, path in (("1", REPO), ("2", copy)):
        r = subprocess.run(
            [sys.executable, "-c", code, str(path)],
            capture_output=True, text=True, timeout=120, check=True,
            env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
        )
        outs.append(r.stdout.strip())
    assert outs[0] == outs[1] and len(outs[0]) == 64


def test_extract_inputs_hash_changes(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    h1 = ex.read_sources(root).inputs_hash()
    (root / "README.md").write_text("changed")
    assert ex.read_sources(root).inputs_hash() != h1


# --- D-23: alias de acciones -------------------------------------------------------------------------

_ALIAS_SERVER = '''
mcp = object()
_MODE_ALIASES = {"short": "long", "other": "nowhere"}

@mcp.tool()
async def multi(action: str = "main", mode: str = "long"):
    act = action
    if act == "main":
        return 1
    elif act in ("show", "view", "peek"):
        if act == "peek":
            return 2
        return 3
    elif act in ("wipe", "reset") and mode == "x":
        return 4
    elif act == "wipe":
        return 5
    if mode == "long":
        return _MODE_ALIASES
    if mode == "short":
        return 6
'''
_ALIAS_PRIV = '''
_CAPABILITIES = {"c": (4, 4, "self", ["multi"], "d")}
CHMOD_DEGRADATION_MATRIX = {"tools": {"multi": {}}}
_CAP_TACTICAL = {}
CONTROL_PLANE_SCHEMA = {}
'''


def _alias_tree(tmp: Path, test_body: str) -> Path:
    for d in ("engine", "tests", "schemas"):
        (tmp / d).mkdir()
    (tmp / "server.py").write_text(_ALIAS_SERVER)
    (tmp / "engine" / "__init__.py").write_text("")
    (tmp / "engine" / "privilege.py").write_text(_ALIAS_PRIV)
    (tmp / "tests" / "test_multi.py").write_text("import server\n" + test_body)
    return tmp


def test_d23_aliases_detected_deterministically(tmp_path: Path) -> None:
    root = _alias_tree(tmp_path, "def test_a():\n    server.multi(action='view')\n")
    a = threads.analyze(root, use_cache=False)
    alias_edges = {(e.src, e.dst) for e in a.graph.edges({"alias_of"})}
    p = "action:multi:"
    # `view` -> `show` (first literal of the branch); `peek` is re-distinguished inside the branch (own behaviour)
    assert (p + "view", p + "show") in alias_edges
    assert not any(src == p + "peek" for src, _ in alias_edges)
    # `act in (...) and cond` is a guard, not a pure dispatch branch: no alias
    assert not any(src in (p + "reset", p + "wipe") for src, _ in alias_edges)
    # module alias table: both ends are actions of the tool
    assert (p + "short", p + "long") in alias_edges
    assert not any(src == p + "other" for src, _ in alias_edges)
    assert a.graph.out_edges(p + "view", "alias_of")


def test_d23_alias_has_no_own_req_and_canonical_inherits_coverage(tmp_path: Path) -> None:
    root = _alias_tree(tmp_path, "def test_a():\n    server.multi(action='view')\n")
    a = threads.analyze(root, use_cache=False)
    omitted = {g.node for g in a.gaps if g.kind == "omission"}
    assert "action:multi:view" not in omitted  # alias: no node with its own Req
    assert "action:multi:short" not in omitted
    # canonical `show` is covered through its alias `view` (same body): inherits the covers edge
    assert not any(g.id == "omission:action:multi:show:in:covers" for g in a.gaps)
    # a real canonical action nobody tests stays a gap
    assert any(g.id == "omission:action:multi:main:in:covers" for g in a.gaps)
    assert any(g.id == "omission:action:multi:peek:in:covers" for g in a.gaps)


def test_d23_alias_edge_is_outside_merkle_root(tmp_path: Path) -> None:
    from engine.threads_model import HASH_EDGE_KINDS

    assert "alias_of" not in HASH_EDGE_KINDS
    root = _alias_tree(tmp_path, "def test_a():\n    server.multi(action='view')\n")
    a = threads.analyze(root, use_cache=False)
    assert a.root_hash and a.scc is not None


def test_d23_repo_aliases_resolve_to_canonical() -> None:
    a = threads.analyze(REPO, use_cache=False)
    edges = {(e.src, e.dst) for e in a.graph.edges({"alias_of"})}
    for alias, canon in [
        ("discover:route", "discover:discover"),
        ("discover:tactical_guide", "discover:playbook"),
        ("discover:tools_schema", "discover:schema"),
        ("diagnose_system_crashes:check", "diagnose_system_crashes:alerts"),
    ]:
        assert (f"action:{alias}", f"action:{canon}") in edges
    ids = {g.id for g in a.gaps}
    assert "omission:action:discover:route:in:covers" not in ids
