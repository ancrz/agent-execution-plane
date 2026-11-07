"""Soporte ONT-42c: repos temporales con remoto bare. NUNCA toca el repo real ni su origin."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engine import threads_evolve as te
from engine import threads_gitport as gp
from engine import threads_verify as tv

_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
    "GIT_TERMINAL_PROMPT": "0",
}


def sh(repo: Path, *args: str, check: bool = True) -> str:
    res = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=check, env={**os.environ, **_ENV}
    )
    return res.stdout.strip()


@dataclass
class Rig:
    root: Path
    bare: Path
    canon: Path
    work: Path
    fence: Path
    state: Path
    cycle: str
    live: dict[str, Any]

    def port(self) -> gp.GitCli:
        return gp.GitCli(self.work, self.canon, self.fence)

    def store(self) -> te.EvolveStore:
        return te.EvolveStore(base_dir=self.state)

    def run(self, *, octal: int = 7, label: str = "FULL", apply: bool = True, cycle: str | None = "") -> dict[str, Any]:
        return te.run_evolve(
            self.store(),
            self.port(),
            lambda: dict(self.live),
            cycle=self.cycle if cycle == "" else cycle,
            gap="D-88",
            apply=apply,
            octal=octal,
            label=label,
            cycle_dir=self.state,
        )

    def events(self) -> list[str]:
        from engine import threads_events as ev

        return [e["kind"] for e in ev.read_events(base_dir=self.state)]


def make_rig(tmp: Path, *, accepted: bool = True) -> Rig:
    bare = tmp / "remote.git"
    canon = tmp / "canon"
    work = tmp / "wt"
    state = tmp / "state"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "dev", str(bare)], check=True, env={**os.environ, **_ENV})
    canon.mkdir()
    sh(canon, "init", "-q", "-b", "dev")
    (canon / "a.txt").write_text("base\n", encoding="utf-8")
    (canon / "b.txt").write_text("other\n", encoding="utf-8")
    sh(canon, "add", "-A")
    sh(canon, "commit", "-q", "-m", "base")
    sh(canon, "remote", "add", "origin", str(bare))
    sh(canon, "push", "-q", "origin", "dev")
    sh(canon, "worktree", "add", "-q", "--detach", str(work), "dev")
    (work / "a.txt").write_text("patched\n", encoding="utf-8")  # el parche (tracked) + un archivo nuevo
    (work / "new.txt").write_text("new\n", encoding="utf-8")
    store = tv.CycleStore(base_dir=state)
    opened = store.open_cycle("drift:open:D-88:test:t", {"gaps": []})
    cycle = opened["cycle_id"]
    if accepted:
        judged = gp.GitCli(work, canon, tmp / "swap_fence")  # D-EV-1: ACCEPT atado al arbol juzgado
        store.record(
            cycle,
            {"verdict": tv.ACCEPT, "reasons": [], "judged": {"tree": judged.candidate_tree(), "root": os.path.realpath(work)}},
        )
    return Rig(tmp, bare, canon, work, tmp / "swap_fence", state, cycle, {"stale": False, "loaded": "f1", "disk": "f1"})
