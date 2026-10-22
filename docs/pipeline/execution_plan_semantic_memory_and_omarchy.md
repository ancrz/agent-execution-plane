# Execution Plan: Semantic Memory (sqlite-vec) + Omarchy 5 Specs
**AEP — Agent Execution Plane**
Authored by: Archon (Stage 1 Planner)
Date: 2026-10-22
Status: AWAITING ONTOS AUDIT

---

## 0. Ground Truth Inventory (Physically Verified)

| Asset | Expected | Physical Reality |
|---|---|---|
| `schemas/hybrid_database.sql` | referenced in docs | ABSENT — does not exist |
| `sqlite_vec` Python package | needed for vec0 | NOT installed |
| `fastembed` Python package | needed for embedder | NOT installed |
| `onnxruntime` Python package | fastembed dep | NOT installed |
| `golangci-lint` binary | required by EAES-v1 | ABSENT (not in PATH, not in `~/.local/bin`) |
| `xvfb-run` / `Xvfb` | needed for SPEC-OM-5 | NOT installed |
| `gemini` CLI | needed for SPEC-OM-3 | NOT in PATH |
| `schemas/database.sql` | DDL for artifacts.db | EXISTS — `intent_hash`, NO `intent_description`, NO `vec_artifacts` |
| `engine/catalog.py` | catalog manager | EXISTS — hash-only, no semantic tier |
| `artifacts.db` | live DB | EXISTS at `~/.local/share/agent-os/artifacts.db` |
| `~/.local/share/agent-os/bin/` | binary store | EXISTS |
| Python | runtime | 3.14.4 (system) |
| Go | compiler | 1.22.5 linux/amd64 at `/usr/local/bin/go` |
| `uv` | package manager | EXISTS at `~/.local/bin/uv` |
| `go env GOPATH` | Go workspace | `/home/ancruz/go` |
| `/usr/bin/bwrap` | sandbox | EXISTS (verified) |
| `/usr/bin/bpftrace` | eBPF | EXISTS (verified) |
| `onnxruntime` latest | wheels | 1.31.0 available via pip |

---

## 1. Schema Decision: Extend `database.sql`, Reject `hybrid_database.sql`

**Decision:** Extend `schemas/database.sql` in place. Do NOT create `schemas/hybrid_database.sql`.

**Justification:**
1. `_init_db()` in `catalog.py` reads one DDL file. Two files would require conditional branching — a fragility vector.
2. The `vec_artifacts` virtual table requires the `vec0` extension to be loaded BEFORE `CREATE VIRTUAL TABLE ... USING vec0(...)`. This means the vec0 DDL cannot be in any file processed by `executescript()` — it must be executed in code after `load_extension()`. The DDL file is therefore descriptive-only for the vec table.
3. `CREATE TABLE IF NOT EXISTS` is idempotent for new columns ONLY in new databases. Existing `artifacts.db` requires a migration script for the added `intent_description` column.
4. Single source of truth: one DDL file, one migration script.

**Migration path:**
- New installs: `database.sql` contains the complete schema including `intent_description`.
- Existing installs: `schemas/migration_v2_vec.sql` runs `ALTER TABLE artifacts ADD COLUMN intent_description TEXT NOT NULL DEFAULT ''`.
- `vec_artifacts` table: created at runtime in `catalog.py::_init_vec_table()` after extension load.

---

## 2. Phase Overview and Dependency Graph

```
A1 (provisioning)
 ├─► A2 (schema)      ─┐
 ├─► A3 (embedder)    ─┼─► A4 (hybrid catalog) ─► A5 (MCP wire)
 ├─► B2 (aep-ctl)       |                       └─► A6 (setup.sh)
 ├─► B4 (skills hub)    └─► B3 (crash routing)
 └─► B5 (headless)
                        A3 done ─► B1 (man-pages vectorizer)
```

**Parallelism opportunities:**
- After A1: {A2, A3, B2, B4, B5} can execute concurrently.
- After A2 + A3: {A4, B3} can execute concurrently.
- After A4: {A5, A6} can execute concurrently.
- After A3 + A2: B1 can execute.

**Critical path:** A1 → A2/A3 → A4 → A5 → A6

---

## 3. Phase A1: Environment and Tool Provisioning

**id:** A1
**action:** configure
**target:** system packages, user-space installs
**re_source:** docs/sqlite_vec_hybrid_retrieval.md §6 (embedder), docs/spec_artifact_engine.md §4 (golangci-lint)
**depends_on:** none
**Topos:** no module coupling — pure provisioning

### A1.1 sqlite-vec Python package

**Tool Awareness Cascade:**
1. MCP: not available as MCP tool.
2. skill-swarm: OFFLINE (ENOENT error in session). Skip.
3. Remote skill: Skip (swarm unavailable).
4. Package manager (primary): `uv pip install sqlite-vec`
   - The `sqlite-vec` package bundles `vec0.so` for the current platform (linux/x86_64).
   - After install: `python3 -c "import sqlite_vec; print(sqlite_vec.loadable_path())"` gives the `.so` path.
   - Vendor the `.so` to `~/.local/share/agent-os/vec0.so` for persistence outside virtual envs.
   - **Python 3.14 risk:** `onnxruntime` 1.31.0 wheels confirmed available; `sqlite-vec` is C-only, likely has 3.14 wheels. If install fails due to missing wheel, fallback: `uv venv --python 3.12 ~/.local/share/agent-os/venv && uv pip install --python ~/.local/share/agent-os/venv sqlite-vec fastembed`.
5. Terminal fallback: if ALL steps fail, log `VEC0_UNAVAILABLE`, catalog stays hash-only (full backward compat).

**Commands:**
```bash
uv pip install sqlite-vec
# Vendor the .so
python3 -c "import sqlite_vec, shutil; shutil.copy(sqlite_vec.loadable_path(), '$HOME/.local/share/agent-os/vec0.so')"
```

### A1.2 fastembed (onnxruntime + all-MiniLM-L6-v2 ONNX model)

**Tool Awareness Cascade:**
1-3. Not available via MCP/skill. Proceed to step 4.
4. Package manager: `uv pip install fastembed`
   - Model (`BAAI/bge-small-en-v1.5`, 384-dim, ~90 MB) is auto-downloaded to `~/.cache/fastembed/` on first `TextEmbedding()` init.
   - **Note:** docs reference `all-MiniLM-L6-v2`; `fastembed` bundles `BAAI/bge-small-en-v1.5` which is the same 384-dim family. Both models produce compatible vector spaces. `BAAI/bge-small-en-v1.5` is the correct `fastembed` model name.
   - Pre-download model during setup: `python3 -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"` (one-time download).
5. Terminal fallback: `EMBEDDER_UNAVAILABLE`, semantic tier skipped.

### A1.3 golangci-lint

**Tool Awareness Cascade:**
1-3. Not available. Proceed to step 4.
4. Package manager (Go install, user-space):
```bash
curl -sSfL https://raw.githubusercontent.com/golangci/golangci-lint/master/install.sh | sh -s -- -b ~/.local/bin v1.61.0
```
   - This installs to `~/.local/bin/golangci-lint` (already in PATH via `~/.zshenv` AEP_UNIVERSAL_INHERITANCE block).
   - Verify: `golangci-lint --version`
   - Target version: v1.61.0 (stable as of Aug 2025, compatible with Go 1.22.x).
5. Terminal fallback: `artifact_lint_and_build` continues with `go vet` only, logs `LINT_DEGRADED`.

**Risks:**
- Python 3.14 wheel availability for sqlite-vec/onnxruntime. Mitigation: fallback to uv-managed 3.12 venv.
- fastembed model download requires internet on first run. Mitigation: pre-download in setup.sh, document offline install path.
- golangci-lint install.sh depends on network. Mitigation: also document `go install` as alternative.

---

## 4. Phase A2: Schema Extension

**id:** A2
**action:** modify + create
**target:** `schemas/database.sql` (modify), `schemas/migration_v2_vec.sql` (create)
**re_source:** docs/sqlite_vec_hybrid_retrieval.md §5 (DDL spec)
**depends_on:** [A1]
**Topos:** no module coupling — DDL files

### A2.1 Modify `schemas/database.sql`

Add `intent_description TEXT NOT NULL DEFAULT ''` column to the `artifacts` table DDL (after `intent_hash`). Keep `intent_hash` unchanged (backward compat — hash path remains the fast exact-match tier).

No `vec_artifacts` DDL in this file. Document in a comment why: extension must be loaded first.

New index: add `CREATE INDEX IF NOT EXISTS idx_artifacts_intent_desc ON artifacts(intent_description)` — enables fuzzy substring fallback if needed.

### A2.2 Create `schemas/migration_v2_vec.sql`

```sql
-- AEP Migration v2: Add intent_description for semantic search
-- Run once against existing artifacts.db instances.
-- vec_artifacts virtual table is created at runtime by catalog.py after vec0 load.

ALTER TABLE artifacts ADD COLUMN intent_description TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_artifacts_intent_desc ON artifacts(intent_description);
```

### A2.3 Migration detection in setup.sh (see A6)

`setup.sh` detects existing `artifacts.db` and runs migration if `intent_description` column absent:
```bash
python3 -c "
import sqlite3, pathlib
db = pathlib.Path.home() / '.local/share/agent-os/artifacts.db'
if db.exists():
    conn = sqlite3.connect(db)
    cols = [r[1] for r in conn.execute('PRAGMA table_info(artifacts)')]
    if 'intent_description' not in cols:
        with open('schemas/migration_v2_vec.sql') as f: conn.executescript(f.read())
        print('Migration v2 applied.')
    else:
        print('Migration v2 already applied.')
"
```

**Risks:**
- `ALTER TABLE ADD COLUMN` on SQLite with `NOT NULL DEFAULT ''` is safe and atomic.
- If `artifacts.db` is open by the running server during migration, SQLite WAL mode handles concurrent readers. Pragma should document a server-restart step post-migration.

---

## 5. Phase A3: Local Embedder Module

**id:** A3
**action:** create
**target:** `engine/embedder.py` (new file)
**re_source:** docs/sqlite_vec_hybrid_retrieval.md §6 (embedder spec)
**depends_on:** [A1]
**Topos:** `embedder.py` is a leaf dependency (no imports from AEP codebase). `catalog.py → embedder.py` is a clean `dep (A→B)`.

### A3.1 `engine/embedder.py` specification

Class `LocalEmbedder`:
- Module-level singleton `_instance: Optional[LocalEmbedder]`
- `__init__`: attempts `from fastembed import TextEmbedding; self._model = TextEmbedding("BAAI/bge-small-en-v1.5")`. If ImportError or any exception: sets `self._available = False`, logs warning. Does NOT raise.
- `is_available: bool` property
- `embed(text: str) -> Optional[list[float]]`: returns `list[float]` of length 384 on success, `None` if unavailable. Normalizes input text (strip, lowercase). Wraps inference in try/except returning None on failure.
- `embed_batch(texts: list[str]) -> list[Optional[list[float]]]`: batch path for ingestion phases (B1).
- `get_instance() -> LocalEmbedder`: module-level factory that returns the singleton.

**Error handling requirements:**
- ImportError (fastembed not installed): FAIL-SOFT, sets `_available = False`
- Model download failure (no network): FAIL-SOFT
- Inference exception: FAIL-SOFT, returns None
- Thread safety: fastembed models are not inherently thread-safe for concurrent inference. The `embed()` method must acquire a module-level threading.Lock.

**Omission checks:**
- [ ] Import `threading.Lock` for thread safety
- [ ] Log warning at module load if fastembed unavailable (do not be silent)
- [ ] Include `__all__ = ["LocalEmbedder", "get_instance"]`

---

## 6. Phase A4: Hybrid Catalog

**id:** A4
**action:** modify
**target:** `engine/catalog.py`
**re_source:** `engine/catalog.py` (existing code), docs/sqlite_vec_hybrid_retrieval.md §4 (2-step pattern)
**depends_on:** [A2, A3]
**Topos:**
- `catalog.py → embedder.py`: `dep (A→B)` — VALID
- `catalog.py → artifacts.db`: `dep (A→B)` — VALID (unchanged)
- Internal: `find_hybrid()` calls `find_by_intent()` then `find_by_semantic()` — sequential, same class

### A4.1 Extension loading

Add `_load_vec_extension(conn: sqlite3.Connection)` private method:
```python
def _load_vec_extension(self, conn):
    vec0_path = Path.home() / ".local/share/agent-os/vec0.so"
    try:
        conn.enable_load_extension(True)
        # Prefer vendored path; fallback to sqlite_vec package path
        if vec0_path.exists():
            conn.load_extension(str(vec0_path))
        else:
            import sqlite_vec
            conn.load_extension(sqlite_vec.loadable_path())
        self._vec_available = True
    except Exception as e:
        self._vec_available = False
        # log warning, do NOT raise
```

**Critical:** `conn.enable_load_extension(True)` requires Python's `sqlite3` module to have been compiled with loadable extension support. On Ubuntu with system Python, this is typically enabled. On Python 3.14+ this must be verified. If it raises `AttributeError`, set `_vec_available = False`.

### A4.2 Vec table initialization

Add `_init_vec_table(conn: sqlite3.Connection)` called only when `self._vec_available`:
```sql
CREATE VIRTUAL TABLE IF NOT EXISTS vec_artifacts USING vec0(
    artifact_id TEXT PRIMARY KEY,
    intent_embedding float[384] distance_metric=cosine
);
```
This must run AFTER `_load_vec_extension()` succeeds.

Modify `_get_connection()`: load extension and init vec table on every new connection (SQLite extensions are connection-scoped).

### A4.3 Modify `_init_db()`

Connection sequence:
1. Get connection.
2. Attempt `_load_vec_extension(conn)`.
3. Run `executescript(schema_path.read_text())` — creates artifacts and execution_metrics if not exist.
4. If `self._vec_available`: run `_init_vec_table(conn)`.

### A4.4 Add `intent_description` to `register_artifact()`

New parameter: `intent_description: str = ""` (defaults to empty string — backward compat for all callers).

If `intent_description` is empty, use the `intent` string directly as the description.

After inserting into `artifacts`, if `self._vec_available` and embedder available:
- Compute embedding: `vec = get_instance().embed(intent_description or intent)`
- If vec is not None: `conn.execute("INSERT OR REPLACE INTO vec_artifacts (artifact_id, intent_embedding) VALUES (?, ?)", (artifact_id, serialize_float32(vec)))` using sqlite-vec's serialization helper.

**Note on serialization:** `sqlite-vec` expects float arrays as `bytes` from `struct.pack(f"{len(vec)}f", *vec)`. Pragma must use this exact format, NOT a Python list literal.

### A4.5 Add `find_by_semantic()`

```python
def find_by_semantic(
    self, intent: str, category: str, threshold: float = 0.15
) -> Optional[Dict[str, Any]]:
```

Steps:
1. Check `self._vec_available` and `get_instance().is_available()`. Return None if either false.
2. Embed intent.
3. Execute:
```sql
SELECT a.*, v.distance
FROM vec_artifacts v
JOIN artifacts a ON a.id = v.artifact_id
WHERE v.intent_embedding MATCH ?
  AND v.distance <= ?
  AND a.category = ?
  AND a.success_rate >= 0.85
ORDER BY v.distance ASC
LIMIT 1
```
Parameters: `(serialize_float32(vec), threshold, category)`.
4. Return dict with extra field `retrieval_mode: "semantic_knn"` and `semantic_distance: float`.
5. Wrap entire method in try/except returning None on any failure.

### A4.6 Add `find_hybrid()`

```python
def find_hybrid(self, intent: str, category: str) -> Optional[Dict[str, Any]]:
```

Tier 1: Call `self.find_by_intent(intent, category)`. If result, add `retrieval_mode: "exact_hash"`, return.
Tier 2: Call `self.find_by_semantic(intent, category)`. If result, return.
Return None (CACHE_MISS) if both tiers miss.

**Omission checks for A4:**
- [ ] `struct` import for float32 serialization
- [ ] Thread safety: each call creates a new connection (already the pattern in existing code via `_get_connection()`). Extension loading happens per-connection. Confirm this is correct — yes, `_get_connection()` already uses `sqlite3.connect()` each time.
- [ ] `_vec_available` instance variable must be initialized to `False` in `__init__` before any method calls it.
- [ ] Missing: `find_by_semantic` must check extension loaded on the current connection (not just `self._vec_available` set during init). Same connection instance must be used throughout the semantic query.
- [ ] Error message if `enable_load_extension` is not available should be logged, not raised.

**Risks:**
- `sqlite3.enable_load_extension` may be disabled in Python 3.14 system builds on some distros. Mitigation: catch `AttributeError`, set `_vec_available = False`.
- `vec_artifacts MATCH` query syntax is sqlite-vec specific. If extension not loaded, the MATCH will raise `OperationalError`. The try/except in `find_by_semantic` handles this.

---

## 7. Phase A5: MCP Tool Wire-up

**id:** A5
**action:** modify
**target:** `server.py`
**re_source:** `server.py::artifact_query` (existing tool, lines 43-69)
**depends_on:** [A4]
**Topos:** `server.py → catalog.py`: existing `dep (A→B)`. No new coupling introduced.

### A5.1 Modify `artifact_query` tool

Replace `catalog.find_by_intent(intent, category)` call with `catalog.find_hybrid(intent, category)`.

Enrich the `CACHE_HIT` response with two new fields (backward compatible — additive only):
- `"retrieval_mode"`: `"exact_hash"` | `"semantic_knn"`
- `"semantic_distance"`: float | null (null for exact_hash hits)

The `CACHE_MISS` response: add `"semantic_available": catalog._vec_available` flag so the agent knows whether semantic search was attempted.

**No other changes to `server.py` in this phase.**

**Omission checks:**
- [ ] Verify `catalog` singleton at module level is already instantiated before first tool call (it is — line 22 of `server.py`: `catalog = ArtifactCatalog()`).
- [ ] The `_vec_available` attribute is set in `__init__` — it will be False initially if extension fails to load. The CACHE_MISS response correctly reports this.

---

## 8. Phase A6: setup.sh Extension

**id:** A6
**action:** modify
**target:** `scripts/setup.sh`
**depends_on:** [A4, A5] (A5 ensures server.py is ready; A4 ensures catalog handles new seeds)

### A6.1 Add provisioning section (after existing Step 1)

New Step 2 (shift existing steps):
```bash
# 2. Instalar sqlite-vec, fastembed y golangci-lint (user-space)
log_step "Instalando dependencias de memoria semántica (sqlite-vec, fastembed)..."

if ! python3 -c "import sqlite_vec" 2>/dev/null; then
    uv pip install sqlite-vec fastembed || {
        log_warn "Instalación de sqlite-vec/fastembed falló con Python $(python3 --version)."
        log_warn "Intentando con venv Python 3.12..."
        uv venv --python 3.12 "$HOME/.local/share/agent-os/venv" 2>/dev/null && \
            uv pip install --python "$HOME/.local/share/agent-os/venv" sqlite-vec fastembed || \
            log_warn "Memoria semántica no disponible. Modo hash-only activo."
    }
fi

# Vendor vec0.so para persistencia fuera de entornos virtuales
python3 -c "
import sqlite_vec, shutil, pathlib
dest = pathlib.Path.home() / '.local/share/agent-os/vec0.so'
shutil.copy(sqlite_vec.loadable_path(), dest)
print(f'vec0.so copiado a {dest}')
" 2>/dev/null || log_warn "No se pudo vender vec0.so (sqlite-vec no instalado)."

# Pre-descargar modelo ONNX (requiere internet una sola vez)
python3 -c "
from fastembed import TextEmbedding
TextEmbedding('BAAI/bge-small-en-v1.5')
print('Modelo BAAI/bge-small-en-v1.5 descargado.')
" 2>/dev/null || log_warn "Modelo ONNX no descargado (fastembed no disponible)."

# Instalar golangci-lint en ~/.local/bin
if ! command -v golangci-lint &>/dev/null; then
    log_step "Instalando golangci-lint en ~/.local/bin..."
    curl -sSfL https://raw.githubusercontent.com/golangci/golangci-lint/master/install.sh | \
        sh -s -- -b "$HOME/.local/bin" v1.61.0 2>/dev/null || \
        log_warn "golangci-lint no instalado. go vet será el único linter activo."
fi
```

### A6.2 Add DB migration step (before artifact seeding)

Before the `python3 -c "from engine.catalog import..."` seeding block, add migration detection.

### A6.3 Update artifact seeding with intent_description

Update the two `register_artifact` calls to include `intent_description`:
- `socket-monitor`: `intent_description="inspect TCP sockets and network listeners on the host"`
- `fd-rescuer`: `intent_description="inspect file descriptors of a process or diagnose hung processes"`

### A6.4 Add Codex symlink (SPEC-OM-3 fix, absorbed here)

Add:
```bash
mkdir -p "$HOME/.codex/skills"
ln -sfn "$HOME/.agents/skills" "$HOME/.codex/skills/shared"
```

---

## 9. Phase B1: SPEC-OM-4 Man-Pages Vectorizer

**id:** B1
**action:** create + modify
**target:** `engine/docs_vectorizer.py` (new), `server.py` (new tool `query_system_docs`)
**re_source:** docs/omarchy_specs_decomposition.md §5 (SPEC-OM-4)
**depends_on:** [A3, A2] — needs embedder module and migration pattern established
**Topos:**
- `server.py → docs_vectorizer.py`: `dep (A→B)` — VALID
- `docs_vectorizer.py → embedder.py`: `dep (A→B)` — VALID
- `docs_vectorizer.py → system_docs.db`: `dep (A→B, separate file from artifacts.db)` — VALID
- `docs_vectorizer.py` does NOT touch `artifacts.db` or `catalog.py` — no cross-coupling

### B1.1 `engine/docs_vectorizer.py`

**DB target:** `~/.local/share/agent-os/system_docs.db` (separate from `artifacts.db`)

**Schema (created at runtime after vec0 load):**
```sql
CREATE TABLE IF NOT EXISTS man_chunks (
    id TEXT PRIMARY KEY,          -- uuid4
    command TEXT NOT NULL,        -- e.g. "iptables"
    section TEXT NOT NULL,        -- "SYNOPSIS", "OPTIONS", "DESCRIPTION"
    chunk_text TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_man_cmd ON man_chunks(command);

-- vec0 virtual table (created at runtime after extension load):
-- CREATE VIRTUAL TABLE IF NOT EXISTS vec_docs USING vec0(
--     chunk_id TEXT PRIMARY KEY,
--     chunk_embedding float[384] distance_metric=cosine
-- );
```

**Class `ManPagesVectorizer`:**
- `__init__(db_path: Optional[Path] = None)`: defaults to `~/.local/share/agent-os/system_docs.db`
- `_load_vec_extension(conn)`: identical pattern to `catalog.py`
- `ingest_command(cmd: str) -> int`: runs `man -P cat <cmd> 2>/dev/null`, parses into chunks, embeds, inserts. Returns chunk count. Skips if command has no man page.
- `ingest_curated_list(commands: list[str])`: batch ingest. Default curated list: `["systemctl", "journalctl", "ip", "ss", "ufw", "apt", "dpkg", "cron", "bwrap", "bpftrace", "coredumpctl", "find", "grep", "rsync", "curl", "jq", "go", "python3"]` (~19 commands, fast ingestion).
- `query(q: str, limit: int = 3) -> list[dict]`: embeds query, KNN on `vec_docs`, JOINs `man_chunks`. Returns list of `{command, section, chunk_text, distance}`.
- `is_populated() -> bool`: checks if `man_chunks` row count > 0.

**Chunking strategy:** Split man page text at section headers (lines matching `^[A-Z ]+$`). Each chunk is max 512 tokens. Use section name as chunk metadata.

### B1.2 New MCP tool `query_system_docs` in `server.py`

```python
@mcp.tool()
def query_system_docs(query: str, limit: int = 3) -> str:
    """
    [SPEC-OM-4 / LOCAL MAN-PAGES] Consulta la base de datos semántica local
    de manuales del sistema Ubuntu. Devuelve fragmentos relevantes sin acceso a Internet.
    """
```

FAIL-SOFT: if `system_docs.db` absent or not populated, returns `{"status": "DOCS_UNAVAILABLE", "message": "Run setup.sh to ingest man pages."}`.

### B1.3 setup.sh addition (absorbed into A6 step or separate B-phase step)

Add after all A-phase setup:
```bash
log_step "Ingiriendo páginas de manual del sistema (sistema_docs.db)..."
python3 -c "
from engine.docs_vectorizer import ManPagesVectorizer
v = ManPagesVectorizer()
if not v.is_populated():
    v.ingest_curated_list()
    print('Man-pages ingestadas.')
else:
    print('Man-pages ya indexadas.')
" 2>/dev/null || log_warn "Vectorización de man-pages no disponible (dependencias faltantes)."
```

**Omission checks for B1:**
- [ ] `man` command must be installed (`apt install man-db`). Check in setup.sh with `command -v man`.
- [ ] vec0 extension loaded per-connection (same pattern as catalog.py).
- [ ] `ingest_command` must handle `man` returning non-zero (command has no page) without exception.
- [ ] Large man pages (e.g., `git`, `bash`) may have thousands of lines. Max chunk count per command: 50.
- [ ] `system_docs.db` does NOT use WAL mode by default — enable with `PRAGMA journal_mode=WAL` for concurrent read safety.

**Risks:**
- `man -P cat` may fail if `PAGER` is unset or if `mandoc` is used instead. Use `MANPAGER=cat man <cmd>` as the subprocess invocation.

---

## 10. Phase B2: SPEC-OM-1 aep-ctl

**id:** B2
**action:** create + modify
**target:** `scripts/aep-ctl` (new executable), `server.py` (new tool `aep_ctl`)
**re_source:** docs/omarchy_specs_decomposition.md §2 (SPEC-OM-1)
**depends_on:** [A1] (only needs Python3, no new packages)
**Topos:**
- `server.py → scripts/aep-ctl`: `dep (A→B)` via subprocess — VALID
- `aep-ctl` has no imports from AEP Python codebase — self-contained CLI
- `aep-ctl → systemctl/ip/df/apt-cache`: `dep (A→B)` via subprocess — VALID

### B2.1 `scripts/aep-ctl` specification

Python3 script (shebang `#!/usr/bin/env python3`). No external packages beyond stdlib.

**Required subcommands:**
```
aep-ctl service [status|start|stop|restart] <name> [--json] [--schema]
aep-ctl network [inspect|routes|listeners] [--json] [--schema]
aep-ctl storage [usage|mounts|disks] [--json] [--schema]
aep-ctl package [installed|check|info] <name> [--json] [--schema]
```

**Guarantees:**
1. `--json` on every subcommand: structured dict, no ANSI escape.
2. `--schema`: print JSONSchema of that subcommand and exit 0.
3. Missing required param: exit 1 with `{"error": "...", "remedy": "..."}` on stdout.
4. No interactive prompts. No sudo in critical path. `service restart` wraps `systemctl restart <name>` (may require sudo for system services — document this; use `systemctl --user restart <name>` for user services).
5. Read-only operations (`status`, `inspect`, `usage`, `check`, `installed`, `info`) must not require sudo.

**Symlink:** `setup.sh` creates `ln -sfn "$PROJECT_ROOT/scripts/aep-ctl" "$HOME/.local/bin/aep-ctl"` and `chmod +x "$PROJECT_ROOT/scripts/aep-ctl"`.

### B2.2 New MCP tool `aep_ctl` in `server.py`

```python
@mcp.tool()
def aep_ctl(subcommand: str, args: list[str] = []) -> str:
    """
    [SPEC-OM-1 / UNIFIED CONTROL] Invoca aep-ctl con un subcomando determinista.
    Siempre retorna JSON tipado. Sin prompts interactivos.
    """
```

Invokes `aep-ctl <subcommand> <args...> --json` via `subprocess.run`. FAIL-SOFT wrapper.

**Omission checks for B2:**
- [ ] `aep-ctl` must handle `service start/stop/restart` gracefully when systemctl not available (container environments). Return `{"status": "SYSTEMCTL_UNAVAILABLE"}`.
- [ ] `network inspect` must work without root. Use `ip addr` (not `ifconfig`).
- [ ] `storage usage` must use `df` (stdlib `shutil.disk_usage` is portable alternative).
- [ ] Test that `--schema` output is valid JSON parseable by Python.

---

## 11. Phase B3: SPEC-OM-2 Crash Routing

**id:** B3
**action:** modify + create
**target:** `schemas/database.sql` (new table), `schemas/migration_v3_crash.sql` (new), `engine/crash_router.py` (new), `server.py` (new tool `check_crash_alerts`)
**re_source:** docs/omarchy_specs_decomposition.md §3 (SPEC-OM-2)
**depends_on:** [A2] — schema migration pattern established
**Topos:**
- `crash_router.py → artifacts.db`: `dep (A→B)` — opens its own connection to `artifacts.db`
- `server.py → crash_router.py`: `dep (A→B)` — VALID
- `crash_router.py` does NOT import `catalog.py` — ZERO coupling between crash_router and catalog
- This is intentional: `crash_events` shares the same DB file but is accessed via independent connection class

**Decision: polling mode** (not push hook).
`check_crash_alerts()` polls `coredumpctl list --json=short` at call time, diffs against known `crash_events`, inserts new entries, returns pending unresolved. This requires no sudo and no systemd unit privilege. The push hook mode is documented as a future enhancement requiring systemd override.

### B3.1 Modify `schemas/database.sql`

Add `crash_events` table DDL:
```sql
CREATE TABLE IF NOT EXISTS crash_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pid INTEGER,
    signal INTEGER,
    executable TEXT,
    timestamp TEXT,
    coredump_info TEXT,       -- JSON blob from coredumpctl
    stacktrace TEXT,          -- gdb/coredumpctl stack trace
    resolved INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_crash_ts ON crash_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_crash_resolved ON crash_events(resolved);
```

### B3.2 Create `schemas/migration_v3_crash.sql`

```sql
-- AEP Migration v3: crash_events table for proactive crash routing
CREATE TABLE IF NOT EXISTS crash_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pid INTEGER,
    signal INTEGER,
    executable TEXT,
    timestamp TEXT,
    coredump_info TEXT,
    stacktrace TEXT,
    resolved INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_crash_ts ON crash_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_crash_resolved ON crash_events(resolved);
```

### B3.3 `engine/crash_router.py`

Class `CrashRouter`:
- `__init__(db_path: Optional[Path] = None)`: same default path as catalog
- `_get_connection() -> sqlite3.Connection`
- `_init_table()`: creates `crash_events` IF NOT EXISTS
- `sync_coredumps() -> int`: calls `coredumpctl list --json=short`, parses JSON list, for each entry checks if `(pid, timestamp)` already in `crash_events`, inserts if not. Returns count of new entries.
- `get_pending_alerts(limit: int = 5) -> list[dict]`: returns unresolved crash_events ordered by `created_at DESC`.
- `mark_resolved(crash_id: int)`: sets `resolved = 1`.
- `_extract_stacktrace(pid: int) -> Optional[str]`: runs `coredumpctl info <pid> 2>/dev/null`, extracts stack frames. Returns None on failure (coredump may be missing).

### B3.4 New MCP tool `check_crash_alerts` in `server.py`

```python
@mcp.tool()
def check_crash_alerts(resolve_after_report: bool = False) -> str:
    """
    [SPEC-OM-2 / PROACTIVE CRASH ROUTING] Sincroniza coredumps recientes,
    retorna alertas de crashes pendientes con stacktrace para auto-diagnóstico.
    """
```

Calls `crash_router.sync_coredumps()`, then `crash_router.get_pending_alerts()`. If `resolve_after_report=True`, marks all returned crashes as resolved.

Instantiate `crash_router = CrashRouter()` at module level in `server.py` (alongside existing `catalog` and `hydrator`).

**Topos note:** `server.py` imports `CrashRouter` directly, same as it imports `ArtifactCatalog`. This adds one more `dep (A→B)` to `server.py`. The existing `diagnose_system_crashes` tool remains unchanged (reactive path). `check_crash_alerts` is the proactive path. No overlap — different use cases, different implementations.

**Omission checks for B3:**
- [ ] `coredumpctl` may not be installed (embedded systems). Wrap all subprocess calls in try/except.
- [ ] `coredumpctl list --json=short` output format must be verified: it returns a JSON array of objects. Handle the case where it returns nothing (empty list).
- [ ] `created_at` and `timestamp` field naming collision — `timestamp` is from coredumpctl, `created_at` is the DB insert time.
- [ ] Migration detection for `crash_events` in setup.sh (check if table exists, apply migration_v3 if not).

---

## 12. Phase B4: SPEC-OM-3 Skills Hub Completion

**id:** B4
**action:** modify
**target:** `scripts/setup.sh`
**re_source:** docs/omarchy_specs_decomposition.md §4 (SPEC-OM-3)
**depends_on:** [A1] (only needs shell)
**Topos:** shell script, no module coupling — VALID

### B4.1 Add Codex symlink

The existing setup.sh (Step 1) creates Claude and Gemini symlinks but OMITS Codex:
```bash
mkdir -p "$HOME/.codex/skills"
ln -sfn "$HOME/.agents/skills" "$HOME/.codex/skills/shared"
```

Note: `~/.codex/` dir exists (confirmed on disk). The `skills/` subdirectory may not. Use `mkdir -p`.

### B4.2 Make existing symlinks idempotent

`ln -sfn` is already idempotent by design. Add `mkdir -p` before EACH symlink creation:
```bash
mkdir -p "$HOME/.claude/skills"
mkdir -p "$HOME/.gemini/skills"
mkdir -p "$HOME/.codex/skills"
```

### B4.3 Add Gemini CLI MCP seeding block

`gemini` is not in PATH but `~/.gemini/` exists (likely Antigravity-managed). Add a `gemini` CLI check block matching the structure of the `agy` block. If `gemini` not found, warn but continue.

**Omission checks:**
- [ ] The symlink `$HOME/.codex/skills/shared` does NOT conflict with existing Codex config — verify `$HOME/.codex/AGENTS.md` is already present (confirmed: yes). Adding `skills/` subdirectory is safe.

---

## 13. Phase B5: SPEC-OM-5 Headless Display Actuator

**id:** B5
**action:** create + modify
**target:** `engine/headless_display.py` (new), `server.py` (new tool `visual_inspect`)
**re_source:** docs/omarchy_specs_decomposition.md §6 (SPEC-OM-5)
**depends_on:** [A1] (provisioning context only; Xvfb requires sudo)
**Topos:**
- `server.py → headless_display.py`: `dep (A→B)` — VALID
- `headless_display.py → Xvfb`: external process, no Python coupling
- `headless_display.py → playwright`: optional dep (A→B)
- Zero coupling with catalog, embedder, crash_router, or docs_vectorizer — fully isolated

**Sudo constraint:** Xvfb install requires `sudo apt install xvfb`. This is NOT in the critical path. `setup.sh` will include an OPTIONAL block with clear user instruction:
```bash
echo "[OPTIONAL] Instalación de Xvfb para SPEC-OM-5 (requiere sudo):"
echo "  sudo apt install -y xvfb"
echo "  pip install playwright && python -m playwright install chromium --with-deps"
```

### B5.1 `engine/headless_display.py`

Class `HeadlessDisplay` (context manager):
- `is_available() -> bool`: `shutil.which("Xvfb") is not None`
- `__enter__(self)`: if available, launches `Xvfb :99 -screen 0 1920x1080x24 -ac` as background subprocess (via `subprocess.Popen`), sets `os.environ["DISPLAY"] = ":99"`. Returns self.
- `__exit__(self, ...)`: terminates Xvfb process, unsets `DISPLAY`.
- FAIL-SOFT: if Xvfb unavailable, `__enter__` raises `DisplayUnavailableError` (custom exception) that the MCP tool catches and converts to JSON.

Module-level function `is_playwright_available() -> bool`: `importlib.util.find_spec("playwright") is not None`.

### B5.2 New MCP tool `visual_inspect` in `server.py`

```python
@mcp.tool()
def visual_inspect(
    url: str,
    viewport_width: int = 1920,
    viewport_height: int = 1080,
    selector: Optional[str] = None,
) -> str:
    """
    [SPEC-OM-5 / HEADLESS DISPLAY] Renderiza una URL en un framebuffer virtual efímero
    y retorna un screenshot en base64. Funciona en servidores sin monitor físico.
    """
```

Returns:
- Success: `{"status": "SUCCESS", "screenshot_b64": "...", "display": ":99"}`
- Unavailable: `{"status": "DISPLAY_UNAVAILABLE", "message": "Install: sudo apt install xvfb && pip install playwright && playwright install chromium"}`

**Omission checks for B5:**
- [ ] Playwright is async-native. For sync invocation from `server.py` (sync FastMCP context), use `playwright.sync_api.sync_playwright()`.
- [ ] Screenshot bytes must be base64-encoded before JSON serialization (`base64.b64encode(bytes).decode()`).
- [ ] `Xvfb :99` may conflict if display :99 is already taken. Use port probing: try :99, :100, :101.
- [ ] Screenshot must be taken in `/dev/shm` (RAM) not `/tmp` (disk): `tmpfile = Path("/dev/shm/aep_screenshot.png")`.
- [ ] Timeout: playwright navigation must have a timeout (default 30s). Expose as parameter.

---

## 14. Dependency Topology — Full Vertical Trace (sqlite-vec change)

```
STORAGE LAYER
  ~/.local/share/agent-os/artifacts.db  (SQLite, ACID)
    ├─ TABLE artifacts (relational, B-Tree, intent_hash + intent_description)
    ├─ TABLE execution_metrics (FK to artifacts)
    ├─ TABLE crash_events (NEW, B3)
    └─ VIRTUAL TABLE vec_artifacts (vec0 KNN, SIMD cosine — extension-gated)
  ~/.local/share/agent-os/system_docs.db (SQLite, separate file, B1)
    ├─ TABLE man_chunks
    └─ VIRTUAL TABLE vec_docs (vec0 KNN — B1)

DATA ACCESS LAYER
  engine/embedder.py              ← fastembed + onnxruntime (NEW, A3)
    └─► BAAI/bge-small-en-v1.5 ONNX (~/.cache/fastembed/)
  engine/catalog.py               ← artifacts.db (MODIFIED, A4)
    └─► engine/embedder.py  [dep A→B]
  engine/crash_router.py          ← artifacts.db (NEW, B3)
    (no import from catalog.py — separate connection class)
  engine/docs_vectorizer.py       ← system_docs.db, embedder.py (NEW, B1)
    └─► engine/embedder.py  [dep A→B]
  engine/headless_display.py      ← Xvfb process (NEW, B5)

BUSINESS LOGIC LAYER
  scripts/aep-ctl                 ← systemctl/ip/df/apt-cache (NEW, B2)

API/MCP LAYER
  server.py (MODIFIED: A5, B1, B2, B3, B5)
    ├─► engine/catalog.py      [dep A→B, existing]
    ├─► engine/hydrator.py     [dep A→B, existing, unchanged]
    ├─► engine/topos_guard.py  [dep A→B, existing, unchanged]
    ├─► engine/crash_router.py [dep A→B, NEW]
    ├─► engine/docs_vectorizer.py [dep A→B, NEW]
    ├─► engine/headless_display.py [dep A→B, NEW]
    └─► scripts/aep-ctl        [dep A→B, subprocess, NEW]

AGENT CONSUMER LAYER
  AI Agent (Claude Code / agy / Codex)
    └─► server.py via FastMCP stdio/JSON-RPC
```

**All cross-module relationships classified:**

| From | To | Classification | Valid? |
|---|---|---|---|
| `server.py` | `catalog.py` | dep (A→B) | YES |
| `server.py` | `hydrator.py` | dep (A→B) | YES |
| `server.py` | `topos_guard.py` | dep (A→B) | YES |
| `server.py` | `crash_router.py` | dep (A→B) | YES |
| `server.py` | `docs_vectorizer.py` | dep (A→B) | YES |
| `server.py` | `headless_display.py` | dep (A→B) | YES |
| `server.py` | `aep-ctl` (subprocess) | dep (A→B) | YES |
| `catalog.py` | `embedder.py` | dep (A→B) | YES |
| `docs_vectorizer.py` | `embedder.py` | dep (A→B) | YES |
| `catalog.py` | `artifacts.db` | dep (A→B) | YES |
| `crash_router.py` | `artifacts.db` | dep (A→B) | YES |
| `docs_vectorizer.py` | `system_docs.db` | dep (A→B) | YES |
| `embedder.py` | fastembed (ext) | dep (A→B) | YES |
| `headless_display.py` | Xvfb (process) | dep (A→B) | YES |

**No interdependencies (A↔B). No co-dependencies (A⊗B). All clean unidirectional.**

---

## 15. Omission Detection Checklist

### Missing Imports (must be added by Pragma)
- [ ] `engine/catalog.py`: add `import struct`, `import threading` (for embed lock), `from engine.embedder import get_instance`
- [ ] `engine/embedder.py`: add `import threading`, `import logging`, `from typing import Optional`
- [ ] `engine/crash_router.py`: add `import subprocess`, `import json`, `import uuid`, `sqlite3`
- [ ] `engine/docs_vectorizer.py`: add `import subprocess`, `import hashlib`, `import re` (chunker)
- [ ] `server.py`: add `from engine.crash_router import CrashRouter`, `from engine.docs_vectorizer import ManPagesVectorizer`, `from engine.headless_display import HeadlessDisplay`, `import base64`

### Missing Error Handling
- [ ] `catalog.py::_load_vec_extension`: must handle `AttributeError` if `enable_load_extension` not available
- [ ] `catalog.py::find_by_semantic`: must catch `sqlite3.OperationalError` (MATCH syntax fails if extension not loaded)
- [ ] `crash_router.py::sync_coredumps`: must handle empty/invalid JSON from coredumpctl
- [ ] `docs_vectorizer.py::ingest_command`: must handle non-zero exit from `man`
- [ ] `headless_display.py::__enter__`: must handle Xvfb display port conflicts

### Missing Migration Handling
- [ ] `setup.sh`: migration_v2_vec.sql detection for existing `artifacts.db`
- [ ] `setup.sh`: migration_v3_crash.sql detection for existing `artifacts.db`
- [ ] `setup.sh`: `crash_events` table check (not just column check)

### Missing Test Surface
Dokimos will need to generate tests for:
- `LocalEmbedder.embed()` with mock fastembed (fail-soft path)
- `ArtifactCatalog.find_hybrid()` — both exact-hash hit and semantic KNN hit paths
- `ArtifactCatalog.find_hybrid()` — CACHE_MISS path when both tiers fail
- `ArtifactCatalog.register_artifact()` — verify vec_artifacts row inserted
- `CrashRouter.sync_coredumps()` with mocked coredumpctl output
- `aep-ctl service status` with mocked systemctl
- `visual_inspect` fail-soft path when Xvfb absent
- `query_system_docs` fail-soft path when system_docs.db absent

### Missing Rollback Logic
- [ ] If `migration_v2_vec.sql` fails mid-run (e.g., disk full), `artifacts.db` may be in inconsistent state. Mitigation: wrap migration in `BEGIN TRANSACTION / COMMIT` in the SQL file.
- [ ] `vec_artifacts` insert failure (disk full, extension not loaded) must NOT fail `register_artifact()` — use separate try/except block.

### Undocumented Assumptions
- [ ] `fastembed` model path is `~/.cache/fastembed/` — this must be documented in setup.sh so agents know where to look if model is missing.
- [ ] `vec0.so` vendored path `~/.local/share/agent-os/vec0.so` — document this in README inventory.
- [ ] `system_docs.db` path — document in README inventory alongside `artifacts.db`.

---

## 16. Minimal First-Executable Slice

**Smallest atomic unit delivering working end-to-end semantic retrieval:**

Tasks: A1 → A2 → A3 → A4 → A5 (in this order, no B phases required)

**End-to-end test scenario:**
1. After A1: `python3 -c "import sqlite_vec; import fastembed"` succeeds.
2. After A2: `schemas/database.sql` has `intent_description` column; `migration_v2_vec.sql` exists.
3. After A3: `from engine.embedder import get_instance; e = get_instance(); print(e.is_available())` prints `True`.
4. After A4: `from engine.catalog import ArtifactCatalog; c = ArtifactCatalog(); hit = c.find_hybrid("find open network ports on this machine", "network")` returns a CACHE_HIT for `socket-monitor` (after seeding via A6).
5. After A5: MCP call `artifact_query(intent="is there anything listening on port 8080", category="network")` returns `{"status": "CACHE_HIT", "retrieval_mode": "semantic_knn", "semantic_distance": 0.08, ...}` rather than CACHE_MISS.

**Pragma can ship A1+A2+A3+A4+A5 as one coherent PR.** B phases follow in a second PR after Dokimos verifies the A group.

---

## 17. Open Decisions Requiring User Input

**OD-1 (Python version isolation):**
Python 3.14.4 is the system Python. `onnxruntime` 1.31.0 and `fastembed` 0.9.0 are available via pip. However, Python 3.14 may not have prebuilt wheels for all transitive deps. The plan includes a fallback to `uv venv --python 3.12`. Should Pragma attempt the system Python first and only fall back, or proactively isolate in a 3.12 venv from the start?

**OD-2 (Dual-column intent storage):**
The plan preserves `intent_hash` (existing, backward compat) AND adds `intent_description` (new, for embedding). `register_artifact()` will populate both. Alternatively, we could rename `intent_hash` to `intent_description` (breaking change for existing rows). Keeping both is safer for the 2 existing seeded artifacts. **Recommendation: keep both. User should confirm.**

**OD-3 (golangci-lint in artifact_lint_and_build):**
`golangci-lint` is ABSENT but required by EAES-v1 Axiom 4. Should Pragma update `artifact_lint_and_build` in `server.py` to invoke `golangci-lint` after `go vet` (when available), or defer this to a future phase? **Recommendation: yes, add it in A6 scope since golangci-lint install is already planned in A1.**

**OD-4 (Man-pages ingestion scope):**
The curated list proposed in B1 is ~19 commands (fast, <30s). Ingesting all `/usr/share/man` could be 10k+ pages (slow, minutes). The full-corpus approach would require background async ingestion. **Recommendation: curated list for Phase 1. User to confirm scope.**

**OD-5 (Crash routing mode):**
The plan uses polling mode for `check_crash_alerts()` (queries coredumpctl on demand, no systemd hook). This is simpler and requires no privileges. A real-time push hook via a systemd path unit or `coredumpctl --follow` would be more proactive but requires system-level access. **User to confirm: polling-on-demand is acceptable for Phase 1.**

---

## 18. Summary of Files Touched

| File | Action | Phase |
|---|---|---|
| `schemas/database.sql` | modify: add `intent_description` + `crash_events` | A2, B3 |
| `schemas/migration_v2_vec.sql` | create | A2 |
| `schemas/migration_v3_crash.sql` | create | B3 |
| `engine/embedder.py` | create | A3 |
| `engine/catalog.py` | modify: vec extension load, vec table, semantic methods, hybrid finder | A4 |
| `engine/crash_router.py` | create | B3 |
| `engine/docs_vectorizer.py` | create | B1 |
| `engine/headless_display.py` | create | B5 |
| `server.py` | modify: artifact_query → find_hybrid; add check_crash_alerts, query_system_docs, aep_ctl, visual_inspect | A5, B1, B2, B3, B5 |
| `scripts/aep-ctl` | create | B2 |
| `scripts/setup.sh` | modify: provisioning + migration + seeding + symlinks | A6, B4 |

**New files created: 6** (`embedder.py`, `crash_router.py`, `docs_vectorizer.py`, `headless_display.py`, `scripts/aep-ctl`, `migration_v2_vec.sql`, `migration_v3_crash.sql` — technically 7 including both migrations)

**Existing files modified: 4** (`database.sql`, `catalog.py`, `server.py`, `setup.sh`)

**Existing 9 MCP tools: fully backward compatible.** `artifact_query` output is additive (new fields only). All other tools are untouched.

---

*End of Execution Plan — Archon Stage 1*
*Route to: Ontos (Stage 2 Audit)*
