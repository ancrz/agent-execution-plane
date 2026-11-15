"""ONT-65: un test que lee un archivo `.py` del proyecto por ruta literal lo cubre (arista `covers` débil)."""

from __future__ import annotations

from pathlib import Path

from engine import threads
from engine import threads_extractors as ex

REPO = Path(__file__).resolve().parent.parent
_MOD = "def f():\n    return 1\n"
_ROOT = "from pathlib import Path\n\nROOT = Path(__file__).resolve().parent.parent\n\n\n"


def _covers(tmp_path: Path, test_body: str) -> dict[str, bool]:
    files = {
        "engine/__init__.py": "",
        "engine/mod.py": _MOD,
        "scripts/x.sh": "echo hi\n",
        "tests/test_r.py": test_body,
    }
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    g, _ = ex.build_graph(ex.read_sources(tmp_path))
    return {e.dst: e.weak for e in g.out_edges("test:tests/test_r.py::test_a", "covers")}


def test_a_slash_path_to_project_py_is_a_weak_cover(tmp_path: Path) -> None:
    body = _ROOT + "def test_a():\n    (ROOT / 'engine' / 'mod.py').read_text()\n"
    assert _covers(tmp_path, body) == {"module:engine.mod": True}


def test_b_non_py_file_gives_no_edge(tmp_path: Path) -> None:
    body = _ROOT + "def test_a():\n    (ROOT / 'scripts' / 'x.sh').read_text()\n"
    assert _covers(tmp_path, body) == {}


def test_c_dynamic_segments_give_no_edge(tmp_path: Path) -> None:
    body = (
        _ROOT + "def test_a():\n    name = 'mod'\n"
        "    (ROOT / 'engine' / f'{name}.py').read_text()\n"
        "    (ROOT / 'engine' / name).read_text()\n"
    )
    assert _covers(tmp_path, body) == {}


def test_d_os_path_join_is_a_weak_cover(tmp_path: Path) -> None:
    body = (
        "import os\n\n\ndef test_a():\n    open(os.path.join(os.path.dirname(__file__), 'engine', 'mod.py')).read()\n"
    )
    assert _covers(tmp_path, body) == {"module:engine.mod": True}


def test_e_unknown_module_gives_no_edge(tmp_path: Path) -> None:
    body = _ROOT + "def test_a():\n    (ROOT / 'engine' / 'ghost.py').read_text()\n"
    assert _covers(tmp_path, body) == {}


def test_f_real_repo_gate8_is_covered_and_no_gaps() -> None:
    a = threads.analyze(REPO)
    tid = "test:tests/test_privilege_degradation.py::test_gate8_semantic_sanitization"
    out = {e.dst: e.weak for e in a.graph.out_edges(tid, "covers")}
    assert out.get("module:engine.privilege") is True
    assert out.get("module:server") is True
    assert a.gaps == []


def test_g_tmp_path_and_parameter_roots_are_not_project_reads(tmp_path: Path) -> None:
    body = (
        "def test_a(tmp_path, root):\n"
        "    (tmp_path / 'engine' / '__init__.py').write_text('')\n"
        "    (root / 'engine' / 'mod.py').write_text('')\n"
    )
    assert _covers(tmp_path, body) == {}


def test_h_file_anchored_root_is_a_project_read(tmp_path: Path) -> None:
    body = (
        "from pathlib import Path\n\n"
        "PROJECT_ROOT = Path(__file__).resolve().parent.parent\n\n\n"
        "def test_a():\n    (PROJECT_ROOT / 'engine' / 'mod.py').read_text()\n"
        "    (PROJECT_ROOT / 'engine' / '__init__.py').read_text()\n"
    )
    assert _covers(tmp_path, body) == {"module:engine.mod": True, "module:engine": True}


def test_i_local_rebinding_of_an_anchored_root_is_not_a_project_read(tmp_path: Path) -> None:
    body = (
        "from pathlib import Path\n\n"
        "ROOT = Path(__file__).parent.parent\n\n\n"
        "def test_a(tmp_path):\n    ROOT = tmp_path\n    (ROOT / 'engine' / 'mod.py').write_text('')\n"
    )
    assert _covers(tmp_path, body) == {}
