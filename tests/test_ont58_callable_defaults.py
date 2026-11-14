"""ONT-58 T4: `ad.fn()` on a project class whose field is `fn: Callable = project_fn` links to that function."""

from __future__ import annotations

from pathlib import Path

from engine import threads_extractors as ex
from engine.threads_model import ThreadGraph

_ADAPT = """
from dataclasses import dataclass, field
from typing import Any, Callable


def read_sysctl() -> str:
    return "1"


def other() -> int:
    return 2


@dataclass
class Adapters:
    read_sysctl: Callable[[], str] = read_sysctl
    via_attr: Callable[[], int] = helpers.other
    no_default: Callable[[], int] | None = None
    made: Callable[[], int] = field(default=lambda: 3)
    lam: Callable[[], int] = lambda: 4


@dataclass
class Sub(Adapters):
    pass


import helpers  # noqa: E402
"""
_HELPERS = """
def other() -> int:
    return 9
"""
_USE = """
from engine.adapt import Adapters, Sub


def uses_default(ad: Adapters):
    ad.read_sysctl()


def uses_inherited(ad: Sub):
    ad.read_sysctl()


def uses_attr(ad: Adapters):
    ad.via_attr()


def uses_none(ad: Adapters):
    ad.no_default()


def uses_field_lambda(ad: Adapters):
    ad.made()
    ad.lam()


def unknown_receiver(thing):
    thing.read_sysctl()
"""


def _graph(root: Path) -> ThreadGraph:
    files = {
        "engine/__init__.py": "",
        "engine/adapt.py": _ADAPT.replace("helpers.other", "other"),
        "engine/use.py": _USE,
    }
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    g, _ = ex.build_graph(ex.read_sources(root))
    return g


def _dsts(g: ThreadGraph, fn: str) -> dict[str, bool]:
    return {e.dst: e.weak for e in g.out_edges(f"fn:engine.use.{fn}", "consumes")}


def test_default_function_resolves_precisely(tmp_path: Path) -> None:
    g = _graph(tmp_path)
    assert _dsts(g, "uses_default")["fn:engine.adapt.read_sysctl"] is False
    assert _dsts(g, "uses_inherited")["fn:engine.adapt.read_sysctl"] is False
    assert _dsts(g, "uses_attr")["fn:engine.adapt.other"] is False


def test_none_lambda_and_field_defaults_add_nothing(tmp_path: Path) -> None:
    g = _graph(tmp_path)
    for fn in ("uses_none", "uses_field_lambda"):
        assert not any(d.startswith("fn:engine.adapt.") for d in _dsts(g, fn)), fn


def test_unknown_receiver_does_not_use_defaults_precisely(tmp_path: Path) -> None:
    g = _graph(tmp_path)
    # unknown receiver keeps the legacy behaviour (unique-name weak edge or nothing), never a precise one
    assert _dsts(g, "unknown_receiver").get("fn:engine.adapt.read_sysctl", True) is True
