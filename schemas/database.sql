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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_artifacts_intent ON artifacts(intent_hash);
CREATE INDEX IF NOT EXISTS idx_artifacts_category ON artifacts(category);

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
