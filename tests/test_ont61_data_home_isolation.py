"""ONT-61/G67: `import server` must never open the user's real DB when AEP_DATA_HOME is set."""

from __future__ import annotations

import os
import pwd
import subprocess
import sys
from pathlib import Path

from engine import paths

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PROBE = (
    "import server, engine.catalog as c, engine.kanban as k, engine.backup as b, engine.playbook as p;"
    "print(c.DB_DEFAULT_PATH); print(k.DB_DEFAULT_PATH); print(b.DB_DEFAULT_PATH); print(p.DB_DEFAULT_PATH)"
)


def _run(env_extra: dict[str, str], drop_data_home: bool = False) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not (drop_data_home and k == paths.DATA_HOME_ENV)}
    env |= env_extra | {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(PROJECT_ROOT)}
    return subprocess.run(
        [sys.executable, "-c", _PROBE], cwd=PROJECT_ROOT, env=env, capture_output=True, text=True, check=False
    )


def test_import_server_creates_db_only_under_aep_data_home(tmp_path: Path) -> None:
    home, data = tmp_path / "home", tmp_path / "data"
    home.mkdir()
    res = _run({"HOME": str(home), paths.DATA_HOME_ENV: str(data)})
    assert res.returncode == 0, res.stderr
    assert (data / "artifacts.db").is_file()
    assert not (home / ".local" / "share" / "agent-os").exists(), "import server leaked into the HOME-derived dir"
    assert set(res.stdout.split()) == {str(data / "artifacts.db")}


def test_default_without_env_is_unchanged_production_path(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    res = _run({"HOME": str(home)}, drop_data_home=True)
    assert res.returncode == 0, res.stderr
    assert paths.data_home().name  # in-process default resolves too (session-pinned by conftest)
    expected = home / ".local" / "share" / "agent-os" / "artifacts.db"
    assert set(res.stdout.split()) == {str(expected)}
    assert expected.is_file()


def test_pytest_session_is_pinned_away_from_the_real_db() -> None:
    """Sentinel: after collection every default DB path lives under the session AEP_DATA_HOME, never the real one."""
    import engine.backup
    import engine.catalog
    import engine.kanban

    real = Path(pwd.getpwuid(os.getuid()).pw_dir) / ".local" / "share" / "agent-os"
    for mod in (engine.catalog, engine.kanban, engine.backup):
        p = mod.DB_DEFAULT_PATH
        assert real not in p.parents, f"{mod.__name__}.DB_DEFAULT_PATH points at the real data dir: {p}"
    assert Path(os.environ["AEP_DATA_HOME"]).name != "agent-os"
