"""ONT-41 TB1: aep_lkg (Last-Known-Good store). Todos los tests usan AEP_DATA_HOME=tmp."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import aep_lkg

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "aep_lkg.py"


@pytest.fixture(autouse=True)
def data_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "data"
    monkeypatch.setenv("AEP_DATA_HOME", str(home))
    return home


def make_root(base: Path, body: str = "X = 1\n") -> Path:
    root = base / "code"
    for sub in ("engine", "templates", "schemas", "scripts"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    (root / "server.py").write_text(body)
    (root / "aep_backend.py").write_text("B = 1\n")
    (root / "engine" / "__init__.py").write_text("")
    (root / "engine" / "mod.py").write_text("def f():\n    return 1\n")
    (root / "templates" / "registry.json").write_text("{}")
    (root / "templates" / "tpl.go").write_text("package main\n")
    (root / "schemas" / "database.sql").write_text("-- sql\n")
    ctl = root / "scripts" / "aep-ctl"
    ctl.write_text("#!/bin/sh\n")
    ctl.chmod(0o755)
    (root / "pyproject.toml").write_text("[project]\nname='x'\n")
    (root / "aep_lkg.py").write_text(SOURCE.read_text())
    return root


def save(root: Path, gen: str = "g1") -> dict:
    return aep_lkg.save(root, gen, "fp-" + gen, "schema", "abc1234")


def test_lkg_home_env_and_mode(data_home: Path) -> None:
    home = aep_lkg.lkg_home()
    assert home == data_home / "lkg"
    assert home.stat().st_mode & 0o777 == 0o700


def test_lkg_home_default_uses_home_not_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("AEP_DATA_HOME")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "h"))
    assert aep_lkg.lkg_home() == tmp_path / "h" / ".local" / "share" / "agent-os" / "lkg"


def test_lkg_home_not_anchored_to_file() -> None:
    tree = ast.parse(SOURCE.read_text())
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    for name in ("lkg_home", "key_dir", "tree_path", "save", "list_keys", "latest", "verify"):
        names = {n.id for n in ast.walk(fns[name]) if isinstance(n, ast.Name)}
        assert "__file__" not in names, name


def test_stdlib_only() -> None:
    tree = ast.parse(SOURCE.read_text())
    mods: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods.update(a.name.split(".")[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom):
            assert n.level == 0
            mods.add((n.module or "").split(".")[0])
    assert mods <= set(sys.stdlib_module_names), mods - set(sys.stdlib_module_names)
    assert "engine" not in mods


def test_save_layout_and_manifest(tmp_path: Path) -> None:
    m = save(make_root(tmp_path))
    key = m["key"]
    home = aep_lkg.lkg_home()
    assert (home / key / "tree" / "server.py").is_file()
    assert (home / key / "tree" / "aep_lkg.py").is_file()
    assert os.access(home / key / "tree" / "scripts" / "aep-ctl", os.X_OK)
    man = json.loads((home / key / "manifest.json").read_text())
    for field in ("files", "code_fingerprint", "generation", "git_head", "ts", "schema_hash", "lkg_module_hash"):
        assert field in man
    assert man["lkg_module_hash"] == aep_lkg.LKG_MODULE_HASH
    assert man["manifest_sha"] == aep_lkg.manifest_digest(man)
    assert aep_lkg.verify(key)["ok"]
    assert aep_lkg.latest() == key


def test_idempotent(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    a, b = save(root, "g1"), save(root, "g2")
    assert a["key"] == b["key"] and a["created"] and not b["created"]
    assert b["generation"] == "g1"
    assert len(aep_lkg.list()) == 1


def test_retention_keeps_three_newest(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    keys = []
    for i in range(5):
        (root / "server.py").write_text(f"X = {i}\n")
        keys.append(save(root, f"g{i}")["key"])
    listed = [e["key"] for e in aep_lkg.list()]
    assert listed == keys[:1:-1]
    assert not (aep_lkg.lkg_home() / keys[0]).exists()


def test_crash_mid_save_leaves_no_partial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_root(tmp_path)
    real = aep_lkg._write_file
    calls = {"n": 0}

    def boom(dest: Path, data: bytes, executable: bool) -> None:
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError("disk full")
        real(dest, data, executable)

    monkeypatch.setattr(aep_lkg, "_write_file", boom)
    with pytest.raises(OSError):
        save(root)
    assert aep_lkg.list() == [] and aep_lkg.latest() is None
    assert [p.name for p in aep_lkg.lkg_home().iterdir()] == []
    monkeypatch.setattr(aep_lkg, "_write_file", real)
    assert aep_lkg.verify(save(root)["key"])["ok"]


def test_stale_tmp_ignored_and_swept(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    stale = aep_lkg.lkg_home() / ".tmp-deadbeef-xyz"
    (stale / "tree").mkdir(parents=True)
    assert aep_lkg.list() == [] and aep_lkg.latest() is None
    key = save(root)["key"]
    assert not stale.exists()
    assert aep_lkg.latest() == key


def test_tampered_file_detected(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    key = save(root)["key"]
    (aep_lkg.tree_path(key) / "server.py").write_text("X = 666\n")
    res = aep_lkg.verify(key)
    assert not res["ok"] and any("SHA_MISMATCH: server.py" in e for e in res["errors"])
    assert aep_lkg.latest() is None
    with pytest.raises(aep_lkg.LkgError) as ei:
        aep_lkg.restore_files(key, ["server.py"], root, dry_run=False)
    assert ei.value.code == "SHA_MISMATCH"


def test_tampered_manifest_detected(tmp_path: Path) -> None:
    key = save(make_root(tmp_path))["key"]
    mpath = aep_lkg.key_dir(key) / "manifest.json"
    man = json.loads(mpath.read_text())
    man["git_head"] = "evil"
    mpath.write_text(json.dumps(man))
    assert "MANIFEST_SHA_MISMATCH" in aep_lkg.verify(key)["errors"]
    with pytest.raises(aep_lkg.LkgError):
        aep_lkg.restore_files(key, ["server.py"], tmp_path / "code")


def test_extra_file_in_tree_detected(tmp_path: Path) -> None:
    key = save(make_root(tmp_path))["key"]
    (aep_lkg.tree_path(key) / "engine" / "evil.py").write_text("")
    assert any(e.startswith("EXTRA_FILE") for e in aep_lkg.verify(key)["errors"])


def test_symlink_in_tree_rejected(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    key = save(root)["key"]
    victim = tmp_path / "victim.py"
    victim.write_text("secret")
    link = aep_lkg.tree_path(key) / "engine" / "mod.py"
    link.unlink()
    link.symlink_to(victim)
    assert any("SYMLINK_IN_TREE" in e for e in aep_lkg.verify(key)["errors"])
    with pytest.raises(aep_lkg.LkgError) as ei:
        aep_lkg.restore_files(key, ["engine/mod.py"], root, dry_run=False)
    assert ei.value.code == "SYMLINK_IN_TREE"
    assert (root / "engine" / "mod.py").read_text() == "def f():\n    return 1\n"


def test_symlink_in_source_refused(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    (root / "engine" / "link.py").symlink_to(root / "server.py")
    with pytest.raises(aep_lkg.LkgError) as ei:
        save(root)
    assert ei.value.code == "SYMLINK_IN_SOURCE"


def test_symlink_manifest_rejected(tmp_path: Path) -> None:
    key = save(make_root(tmp_path))["key"]
    mpath = aep_lkg.key_dir(key) / "manifest.json"
    real = tmp_path / "real_manifest.json"
    real.write_text(mpath.read_text())
    mpath.unlink()
    mpath.symlink_to(real)
    assert not aep_lkg.verify(key)["ok"]
    with pytest.raises(aep_lkg.LkgError):
        aep_lkg.restore_files(key, ["server.py"], tmp_path / "code")


@pytest.mark.parametrize(
    "bad", ["/etc/passwd", "../x.py", "engine/../../x.py", "engine//mod.py", "a\\b", "", "README.md"]
)
def test_restore_rejects_bad_paths(tmp_path: Path, bad: str) -> None:
    root = make_root(tmp_path)
    key = save(root)["key"]
    with pytest.raises(aep_lkg.LkgError):
        aep_lkg.restore_files(key, [bad], root, dry_run=False)


def test_manifest_traversal_entries_rejected(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    key = save(root)["key"]
    mpath = aep_lkg.key_dir(key) / "manifest.json"
    man = json.loads(mpath.read_text())
    man["files"]["../../escape.py"] = "0" * 64
    man["manifest_sha"] = aep_lkg.manifest_digest(man)
    mpath.write_text(json.dumps(man))
    res = aep_lkg.verify(key)
    assert not res["ok"] and any("MANIFEST_PATH" in e for e in res["errors"])
    with pytest.raises(aep_lkg.LkgError):
        aep_lkg.restore_files(key, ["../../escape.py"], root, dry_run=False)


def test_restore_dest_symlink_and_escape_rejected(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    key = save(root)["key"]
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "engine" / "mod.py").unlink()
    (root / "engine" / "mod.py").symlink_to(outside / "t.py")
    with pytest.raises(aep_lkg.LkgError) as ei:
        aep_lkg.restore_files(key, ["engine/mod.py"], root, dry_run=False)
    assert ei.value.code == "SYMLINK_TARGET"
    (root / "engine" / "mod.py").unlink()
    (root / "engine" / "mod.py").write_text("x")
    (root / "templates").rename(tmp_path / "tpl_real")
    (root / "templates").symlink_to(outside)
    with pytest.raises(aep_lkg.LkgError) as ei2:
        aep_lkg.restore_files(key, ["templates/tpl.go"], root, dry_run=False)
    assert ei2.value.code == "ESCAPES_REPO"
    assert not (outside / "tpl.go").exists()


def test_restore_dry_run_then_apply_only_listed(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    key = save(root)["key"]
    (root / "server.py").write_text("BROKEN(\n")
    (root / "engine" / "mod.py").write_text("OTHER = 2\n")
    dry = aep_lkg.restore_files(key, ["server.py"], root)
    assert dry["dry_run"] and dry["restored"] == [] and dry["files"][0]["would_change"]
    assert (root / "server.py").read_text() == "BROKEN(\n"
    res = aep_lkg.restore_files(key, ["server.py"], root, dry_run=False)
    assert res["restored"] == ["server.py"]
    assert (root / "server.py").read_text() == "X = 1\n"
    assert (root / "engine" / "mod.py").read_text() == "OTHER = 2\n"
    assert not list(root.rglob(".*lkg-*"))


def test_restore_preserves_exec_bit(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    key = save(root)["key"]
    (root / "scripts" / "aep-ctl").write_text("junk")
    (root / "scripts" / "aep-ctl").chmod(0o644)
    aep_lkg.restore_files(key, ["scripts/aep-ctl"], root, dry_run=False)
    assert os.access(root / "scripts" / "aep-ctl", os.X_OK)


def test_diff_hunks(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    key = save(root)["key"]
    (root / "server.py").write_text("X = 2\nY = 3\n")
    d = aep_lkg.diff(key, "server.py", root)
    assert not d["identical"] and d["hunks"]
    joined = "\n".join(d["hunks"][0]["lines"])
    assert "-X = 2" in joined and "+X = 1" in joined
    assert aep_lkg.diff(key, "aep_backend.py", root)["identical"]


def test_parse_error_syntax_and_traceback() -> None:
    tail = (
        "Traceback (most recent call last):\n"
        '  File "/a/server.py", line 12, in <module>\n    import x\n'
        '  File "/a/engine/m.py", line 7\n    def f(:\n          ^\n'
        "SyntaxError: invalid syntax\n"
    )
    p = aep_lkg.parse_error(tail)
    assert p and p["type"] == "SyntaxError" and p["file"] == "/a/engine/m.py" and p["line"] == 7
    assert p["msg"] == "invalid syntax" and len(p["fingerprint"]) == 16
    q = aep_lkg.parse_error(tail.replace("/a/", "/b/"))
    assert q and q["fingerprint"] == p["fingerprint"]
    mnf = aep_lkg.parse_error("  File \"s.py\", line 3, in <module>\nModuleNotFoundError: No module named 'zz'")
    assert mnf and mnf["type"] == "ModuleNotFoundError" and "zz" in mnf["msg"]
    assert aep_lkg.parse_error("all good") is None


def test_c1_lkg_module_inside_tree_and_self_contained() -> None:
    m = aep_lkg.save(REPO, "c1", "fp", "schema", "head")
    key = m["key"]
    tree = aep_lkg.tree_path(key)
    assert "aep_lkg.py" in m["files"]
    assert (tree / "aep_lkg.py").read_bytes() == SOURCE.read_bytes()
    assert aep_lkg.verify(key)["ok"]
    assert not any(p.startswith("aep_front") for p in m["files"])
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONPATH"] = str(tree)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    code = (
        "import aep_lkg, server;"
        f"t={str(tree)!r};"
        "assert aep_lkg.__file__.startswith(t), aep_lkg.__file__;"
        "assert server.__file__.startswith(t), server.__file__;"
        "print('OK')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=tree, env=env, capture_output=True, text=True, timeout=120, check=False
    )
    assert proc.returncode == 0 and "OK" in proc.stdout, proc.stderr[-800:]
