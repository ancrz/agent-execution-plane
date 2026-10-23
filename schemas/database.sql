-- Evolutionary Artifact Engine Database Schema (SQLite)
-- Database Path: ~/.local/share/agent-os/artifacts.db

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,                       -- UUID v4
    name TEXT NOT NULL UNIQUE,                 -- Nombre identificativo (kebab-case)
    intent_hash TEXT NOT NULL,                 -- Hash SHA-256 de la intención funcional
    category TEXT NOT NULL,                    -- 'network', 'process', 'memory', 'filesystem', 'async'
    cue_contract TEXT NOT NULL,                -- Especificación CUE del contrato
    go_source TEXT NOT NULL,                   -- Código fuente completo en Go
    binary_blob BLOB,                          -- Binario ELF estático pre-compilado (opcional)
    binary_hash TEXT,                          -- Hash SHA-256 del binario
    version INTEGER NOT NULL DEFAULT 1,        -- Versión evolutiva del artefacto
    success_rate REAL NOT NULL DEFAULT 1.0,    -- Tasa histórica de éxito [0.0 - 1.0]
    execution_count INTEGER NOT NULL DEFAULT 0,-- Total de ejecuciones registradas
    avg_latency_ms REAL NOT NULL DEFAULT 0.0,  -- Latencia promedio de ejecución
    intent_description TEXT NOT NULL DEFAULT '', -- Texto en lenguaje natural (fuente del embedding semántico)
    reusable INTEGER NOT NULL DEFAULT 1,       -- Pico-Kanban: ¿promovido como plantilla reutilizable?
    promotion_score REAL NOT NULL DEFAULT 0.0, -- Ponderación [0-1] (linters + canary + éxito histórico)
    source_template TEXT NOT NULL DEFAULT '',  -- Plantilla origen (si fue sintetizado a partir de una)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_artifacts_intent ON artifacts(intent_hash);
CREATE INDEX IF NOT EXISTS idx_artifacts_category ON artifacts(category);

-- NOTA: la tabla virtual `vec_artifacts USING vec0(...)` NO se declara aquí: requiere que
-- la extensión sqlite-vec esté cargada en la conexión primero, por lo que la crea en código
-- `engine/catalog.py::_init_vec_table()`. El esquema relacional sigue siendo la fuente ACID.

-- Registro de Métricas y Telemetría de Ejecución
CREATE TABLE IF NOT EXISTS execution_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    artifact_id TEXT NOT NULL,
    exit_code INTEGER NOT NULL,
    latency_ms REAL NOT NULL,
    memory_peak_kb INTEGER,
    error_message TEXT,
    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(artifact_id) REFERENCES artifacts(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_metrics_artifact ON execution_metrics(artifact_id);

-- SPEC-OM-2: Active Crash Routing. Dueño autoritativo del DDL de crash_events.
-- engine/crash_router.py replica este CREATE IF NOT EXISTS como red de seguridad.
CREATE TABLE IF NOT EXISTS crash_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL UNIQUE,          -- de-duplicación (pid+timestamp+exe)
    pid INTEGER,
    signal TEXT,
    executable TEXT,
    event_timestamp TEXT,
    coredump_info TEXT,                         -- JSON crudo de coredumpctl
    resolved INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Pico-Kanban: tablero de estados abstracto para gestión agéntica y ponderación de artefactos.
-- engine/kanban.py replica este CREATE IF NOT EXISTS como red de seguridad.
CREATE TABLE IF NOT EXISTS kanban_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    intent TEXT,
    category TEXT,
    artifact_name TEXT,
    state TEXT NOT NULL DEFAULT 'BACKLOG',       -- BACKLOG|SYNTHESIZED|LINTED|CANARY|PROMOTED|REJECTED
    lint_passed INTEGER NOT NULL DEFAULT 0,
    canary_passed INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    promotion_score REAL NOT NULL DEFAULT 0.0,
    archived INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_kanban_state ON kanban_tasks(state);
CREATE INDEX IF NOT EXISTS idx_kanban_archived ON kanban_tasks(archived);

-- Pico-Playbooks: automatización por orquestación de tools/artefactos (DAG validado por Topos).
-- engine/playbook.py replica este CREATE IF NOT EXISTS como red de seguridad.
CREATE TABLE IF NOT EXISTS playbooks (
    name TEXT PRIMARY KEY,
    description TEXT,
    steps_json TEXT NOT NULL,                   -- JSON: [{id, tool, params, depends_on}] (puede tener ${var})
    params_contract TEXT NOT NULL DEFAULT '[]', -- JSON: [{name, type?, required?, default?}] (RE-as-SDD de Jinja)
    run_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    last_status TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
