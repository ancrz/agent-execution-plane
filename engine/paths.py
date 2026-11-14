"""Single source of truth for AEP's per-user data directory (ONT-61/G67).

`AEP_DATA_HOME` overrides the default `~/.local/share/agent-os`. Every default DB path derives from here, so a test
session (or a demo) can pin the whole data tree to a temp dir before `import server` runs the module-level
`ArtifactCatalog()` / `KanbanBoard()` constructors, whose `_migrate` would otherwise touch the user's real DB.
"""

from __future__ import annotations

import os
from pathlib import Path

DATA_HOME_ENV = "AEP_DATA_HOME"


def data_home() -> Path:
    """`$AEP_DATA_HOME` if set and non-blank, else `~/.local/share/agent-os` (production default, unchanged)."""
    env = os.environ.get(DATA_HOME_ENV, "").strip()
    return Path(env) if env else Path.home() / ".local" / "share" / "agent-os"
