"""ONT-46: precisión del extractor de hilos. El receptor se tipa antes de resolver `obj.metodo`.

Aristas precisas por tipo (constructor, anotación, atributo de clase, global de módulo, base del proyecto,
retorno anotado, fixture pytest); receptores externos/builtin sin arista; receptor desconocido con nombre único
no externo -> arista `weak` (cuenta para cobertura y alcance, jamás para SCC).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine import threads
from engine import threads_extractors as ex
from engine.threads_model import Edge, Node, ThreadGraph, copy_graph

REPO = Path(__file__).resolve().parent.parent

_SPOOL = """
class Spool:
    def append(self, item):
        return item
"""
_MGR = """
class Manager:
    def list_tools(self):
        return 1

    def refresh(self):
        return 2

    def refresh_all(self):
        return 3


class Base:
    def inherited_op(self):
        return 4


class Child(Base):
    pass


class Ledger:
    def claim(self, key):
        return key


class Store:
    def __init__(self):
        self.ledger = Ledger()


class Pool:
    def acquire(self):
        return 5


POOL = Pool()


def make_manager() -> "Manager":
    return Manager()
"""
_USE = """
from typing import Optional

from engine.mgr import POOL, Child, Manager, Store, make_manager
from engine.spool import Spool
from thirdparty import External


def f_builtin(items):
    items.append(1)


def f_ctor():
    mgr = Manager()
    mgr.list_tools()


def f_ann(m: Manager):
    m.list_tools()


def f_ann_str(m: "Manager"):
    m.list_tools()


def f_ann_union(m: Manager | None):
    m.list_tools()


def f_ann_optional(m: Optional[Manager]):
    m.list_tools()


def f_global():
    POOL.acquire()


def f_chain(store: Store):
    store.ledger.claim("k")


def f_inherited():
    c = Child()
    c.inherited_op()


def f_returns():
    m = make_manager()
    m.refresh()


def f_unknown(thing):
    thing.refresh_all()


class Holder:
    def __init__(self):
        self._tm = External()

    def go(self):
        self._tm.list_tools()


def f_keep_import():
    return Spool
"""


def _write(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root


def _build(root: Path, files: dict[str, str]) -> tuple[ThreadGraph, ex.ExtractionInfo]:
    _write(root, files)
    return ex.build_graph(ex.read_sources(root))


def _consumes(g: ThreadGraph, src: str) -> dict[str, bool]:
    return {e.dst: e.weak for e in g.out_edges(f"fn:{src}", "consumes")}


@pytest.fixture
def tree(tmp_path: Path) -> tuple[ThreadGraph, ex.ExtractionInfo]:
    return _build(
        tmp_path,
        {
            "engine/__init__.py": "",
            "engine/spool.py": _SPOOL,
            "engine/mgr.py": _MGR,
            "engine/use.py": _USE,
        },
    )


def test_a_builtin_method_name_does_not_link_to_project_method(tree) -> None:
    g, _ = tree
    assert "fn:engine.spool.Spool.append" not in _consumes(g, "engine.use.f_builtin")


def test_b_external_attribute_does_not_resolve_but_typed_constructor_does(tree) -> None:
    g, _ = tree
    assert "fn:engine.mgr.Manager.list_tools" not in _consumes(g, "engine.use.Holder.go")
    assert _consumes(g, "engine.use.f_ctor")["fn:engine.mgr.Manager.list_tools"] is False


@pytest.mark.parametrize("name", ["f_ann", "f_ann_str", "f_ann_union", "f_ann_optional"])
def test_c_annotated_parameters_type_the_receiver(tree, name: str) -> None:
    g, _ = tree
    assert _consumes(g, f"engine.use.{name}")["fn:engine.mgr.Manager.list_tools"] is False


def test_d_module_global_instance_types_the_receiver(tree) -> None:
    g, _ = tree
    assert _consumes(g, "engine.use.f_global")["fn:engine.mgr.Pool.acquire"] is False


def test_e_class_attribute_chain_resolves_through_constructor_assignment(tree) -> None:
    g, _ = tree
    assert _consumes(g, "engine.use.f_chain")["fn:engine.mgr.Ledger.claim"] is False


def test_f_method_inherited_from_project_base(tree) -> None:
    g, _ = tree
    assert _consumes(g, "engine.use.f_inherited")["fn:engine.mgr.Base.inherited_op"] is False


def test_g_function_with_return_annotation_types_the_local(tree) -> None:
    g, _ = tree
    assert _consumes(g, "engine.use.f_returns")["fn:engine.mgr.Manager.refresh"] is False


def test_i_unknown_receiver_with_unique_name_is_a_marked_weak_edge(tree) -> None:
    g, info = tree
    assert _consumes(g, "engine.use.f_unknown")["fn:engine.mgr.Manager.refresh_all"] is True
    assert info.weak_edges >= 1
    assert info.weak_edges == sum(1 for e in g.edges() if e.weak)
    assert info.external_skipped >= 1


def test_h_pytest_fixture_types_the_test_parameter_precisely(tmp_path: Path) -> None:
    g, _ = _build(
        tmp_path,
        {
            "engine/__init__.py": "",
            "engine/mgr.py": _MGR,
            "tests/conftest.py": (
                "import pytest\nfrom engine.mgr import Ledger\n\n"
                "@pytest.fixture\ndef ledger() -> Ledger:\n    return Ledger()\n"
            ),
            "tests/test_a.py": (
                "import pytest\nfrom engine.mgr import Manager\n\n"
                "@pytest.fixture\ndef mgr():\n    return Manager()\n\n"
                "def test_claim(ledger):\n    ledger.claim('k')\n\n"
                "def test_refresh(mgr):\n    mgr.refresh()\n\n"
                "def test_unknown(thing):\n    thing.refresh_all()\n"
            ),
        },
    )
    claim = {e.dst: e.weak for e in g.out_edges("test:tests/test_a.py::test_claim", "covers")}
    refresh = {e.dst: e.weak for e in g.out_edges("test:tests/test_a.py::test_refresh", "covers")}
    unknown = {e.dst: e.weak for e in g.out_edges("test:tests/test_a.py::test_unknown", "covers")}
    assert claim["fn:engine.mgr.Ledger.claim"] is False
    assert refresh["fn:engine.mgr.Manager.refresh"] is False
    assert unknown["fn:engine.mgr.Manager.refresh_all"] is True


def test_m_spawning_a_project_file_covers_its_module_weakly(tmp_path: Path) -> None:
    g, info = _build(
        tmp_path,
        {
            "aep_front.py": "def main():\n    return 1\n",
            "server.py": "def tool():\n    return 1\n",
            "tests/test_e2e.py": (
                "import subprocess, sys\n"
                "from mcp import StdioServerParameters\n\n"
                "def test_run():\n    subprocess.run([sys.executable, 'server.py'])\n\n"
                "def test_params():\n    StdioServerParameters(command='py', args=['aep_front.py'])\n"
            ),
        },
    )
    run = {e.dst: e.weak for e in g.out_edges("test:tests/test_e2e.py::test_run", "covers")}
    params = {e.dst: e.weak for e in g.out_edges("test:tests/test_e2e.py::test_params", "covers")}
    assert run == {"module:server": True}
    assert params == {"module:aep_front": True}
    assert info.weak_edges == 2


def test_n_reading_or_quoting_a_project_file_does_not_cover_it(tmp_path: Path) -> None:
    g, _ = _build(
        tmp_path,
        {
            "server.py": "def tool():\n    return 1\n",
            "tests/test_read.py": (
                "from pathlib import Path\n\n"
                "def test_read():\n    Path('server.py').read_text()\n    args = ['server.py', 'a note about server.py']\n"
            ),
        },
    )
    assert g.out_edges("test:tests/test_read.py::test_read", "covers") == []


def test_j_weak_edge_never_forms_a_codependency_but_counts_for_coverage_and_impact(tmp_path: Path) -> None:
    g, _ = _build(
        tmp_path,
        {
            "engine/__init__.py": "",
            "engine/a.py": "def alpha_entry(thing):\n    thing.beta_unique_op()\n",
            "engine/b.py": "from engine import a\n\nclass B:\n    def beta_unique_op(self):\n        return a.alpha_entry(None)\n",
            "tests/test_a.py": "from engine import a\n\ndef test_alpha():\n    a.alpha_entry(1)\n",
        },
    )
    weak = [e for e in g.edges() if e.weak and e.kind == "consumes"]
    assert [(e.src, e.dst) for e in weak] == [("fn:engine.a.alpha_entry", "fn:engine.b.B.beta_unique_op")]
    # el ciclo alpha_entry -> beta_unique_op -> alpha_entry solo existe por la arista débil
    assert not any(e.weak for e in g.out_edges("fn:engine.b.B.beta_unique_op", "consumes"))
    report = threads.classify_sccs(g)
    assert report.codependencies == [] and report.interdependencies == []
    # ...pero la cobertura y el alcance sí la ven (conservador)
    assert threads.coverage_map(g)["fn:engine.b.B.beta_unique_op"] == threads.COVERAGE_TRANSITIVE
    assert threads.impacted_tests(g, ["fn:engine.b.B.beta_unique_op"]) == ["test:tests/test_a.py::test_alpha"]


def test_k_copy_graph_and_edges_preserve_weak_and_precise_replaces_weak() -> None:
    g = ThreadGraph()
    for nid in ("fn:m.a", "fn:m.b"):
        g.add_node(Node("function", nid, "h"))
    assert g.add_edge("fn:m.a", "fn:m.b", "consumes", weak=True)
    assert g.add_edge("fn:m.a", "fn:m.b", "consumes", weak=True) is False
    clone = copy_graph(g)
    assert [e.weak for e in clone.edges()] == [True]
    assert Edge("fn:m.a", "fn:m.b", "consumes").weak is False
    # la precisa sustituye a la débil; una débil posterior no la desplaza
    assert g.add_edge("fn:m.a", "fn:m.b", "consumes")
    assert [e.weak for e in g.edges()] == [False] and g.edge_count() == 1
    assert len(g.out_edges("fn:m.a")) == 1 and len(g.in_edges("fn:m.b")) == 1
    assert g.add_edge("fn:m.a", "fn:m.b", "consumes", weak=True) is False
    assert [e.weak for e in g.edges()] == [False]


def test_l_two_analyses_have_the_same_merkle_root(tmp_path: Path) -> None:
    _write(
        tmp_path, {"engine/__init__.py": "", "engine/mgr.py": _MGR, "engine/use.py": _USE, "engine/spool.py": _SPOOL}
    )
    a = threads.analyze(tmp_path, use_cache=False)
    b = threads.analyze(tmp_path, use_cache=False)
    assert a.root_hash == b.root_hash
    assert a.info.weak_edges == b.info.weak_edges >= 1


def test_schema_version_bumped() -> None:
    assert threads.GRAPH_SCHEMA_VERSION == "threads/2"


# ---------------------------------------------------------------------------
# Repositorio real
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real() -> threads.Analysis:
    return threads.analyze(REPO, use_cache=False)


def _consumers(a: threads.Analysis, dst: str) -> list[str]:
    return sorted(e.src for e in a.graph.in_edges(dst, "consumes"))


def test_real_backend_handle_line_does_not_consume_front_list_tools(real: threads.Analysis) -> None:
    out = {e.dst for e in real.graph.out_edges("fn:aep_backend.BackendWorker.handle_line", "consumes")}
    assert "fn:aep_front.LivePlaneManager.list_tools" not in out


def test_real_spool_append_consumers_stay_in_front_module(real: threads.Analysis) -> None:
    consumers = _consumers(real, "fn:aep_front.PlaneEventSpool.append")
    assert consumers and all(c.startswith("fn:aep_front.") for c in consumers)


def test_real_sqlite_execute_does_not_leak_into_harness_reconnect(real: threads.Analysis) -> None:
    for c in _consumers(real, "fn:engine.harness_reconnect.execute"):
        assert c.startswith(("fn:engine.harness_reconnect.", "fn:server.")), c


def test_real_asyncio_create_task_does_not_leak_into_kanban(real: threads.Analysis) -> None:
    for c in _consumers(real, "fn:engine.kanban.KanbanBoard.create_task"):
        assert c.startswith(("fn:engine.kanban.", "fn:server.")), c


def test_real_weak_edges_are_a_small_marked_minority(real: threads.Analysis) -> None:
    weak = [e for e in real.graph.edges() if e.weak]
    assert real.info.weak_edges == len(weak) > 0
    assert len(weak) < real.graph.edge_count() * 0.05
    assert real.scc.codependencies == []


def test_payloads_terse_keys_unchanged_full_exposes_weak_edges_and_thread_marks_weak(real: threads.Analysis) -> None:
    terse = threads.graph_payload(real, terse=True)
    assert "weak_edges" not in terse
    assert set(terse) == {"root", "nodes", "edges", "gaps_open", "codep", "own_gaps"}
    full = threads.graph_payload(real, terse=False)
    assert full["weak_edges"] == real.info.weak_edges
    assert "weak" in full["limits"]
    edge = next(e for e in real.graph.edges() if e.weak)
    out = threads.thread_payload(real, edge.src, limit=500)["out"]
    marked = [r for r in out if r.get("weak")]
    assert any(r["kind"] == edge.kind and r["to"] == edge.dst for r in marked)
    assert all(r["weak"] is True for r in out if "weak" in r)  # la clave solo existe en aristas débiles
