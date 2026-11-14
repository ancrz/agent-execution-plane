"""ONT-53 (G42): el embedder fija ORT_DISABLE_TELEMETRY antes de importar onnxruntime. Sin red ni DB real."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from engine import embedder

ROOT = Path(__file__).resolve().parent.parent

_PROBE = textwrap.dedent(
    """
    import os, sys
    sys.path.insert(0, os.getcwd())
    from engine.embedder import LocalEmbedder
    e = LocalEmbedder()
    if not e.is_available:
        print("UNAVAILABLE")
        raise SystemExit(0)
    e.embed("hello")
    fds = []
    for x in os.listdir("/proc/self/fd"):
        try:
            fds.append(os.readlink("/proc/self/fd/" + x))
        except OSError:
            pass
    print("DB_OPEN" if any("onnxruntime.db" in f for f in fds) else "DB_CLOSED")
    """
)

needs_fastembed = pytest.mark.skipif(importlib.util.find_spec("fastembed") is None, reason="fastembed no instalado")


@needs_fastembed
def test_setdefault_does_not_override_operator_value(monkeypatch):
    monkeypatch.setenv("ORT_DISABLE_TELEMETRY", "0")
    embedder.LocalEmbedder()
    assert os.environ["ORT_DISABLE_TELEMETRY"] == "0"


@needs_fastembed
def test_embedder_sets_variable_when_absent(monkeypatch):
    monkeypatch.delenv("ORT_DISABLE_TELEMETRY", raising=False)
    embedder.LocalEmbedder()
    assert os.environ["ORT_DISABLE_TELEMETRY"] == "1"


@needs_fastembed
def test_embedder_leaves_no_onnxruntime_db_fd():
    env = {k: v for k, v in os.environ.items() if k != "ORT_DISABLE_TELEMETRY"}
    env["HF_HUB_OFFLINE"] = "1"
    res = subprocess.run(
        [sys.executable, "-I", "-c", _PROBE],
        check=False,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = res.stdout.strip().splitlines()[-1:] or [""]
    if out[0] == "UNAVAILABLE":
        pytest.skip("modelo no disponible offline")
    assert out[0] == "DB_CLOSED", res.stdout + res.stderr
