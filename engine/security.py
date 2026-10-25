"""
Engine: security.py (SPEC-SEC-01 & ONT-11: Secret Masking & Cryptographic Audit Trail)

Intercepta y enmascara tokens, claves de API, hashes shadow, credenciales y encabezados
de autorización en cadenas de texto, estructuras de datos y volcados de Pueue/subprocesos.
Implementa registro de auditoría inmutable con encadenamiento de hash SHA-256 (security_audit_log).
"""

import hashlib
import json
import logging
import re
import sqlite3
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("aep.security")

# Expresiones regulares para detección de secretos y credenciales
_BEARER_RE = re.compile(r"Bearer\s+([A-Za-z0-9_\-\.]+)", re.IGNORECASE)
_PEM_PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z0-9 ]+PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]+PRIVATE KEY-----")
_SENSITIVE_KEY_RE = re.compile(r"(TOKEN|KEY|SECRET|PASS|AUTH|CRED|PASSWORD|APIKEY)", re.IGNORECASE)

# Nuevas expresiones regulares para hashes shadow y tokens cloud
_SHADOW_HASH_RE = re.compile(r"\$[1256y]\$[a-zA-Z0-9./=]+\$[a-zA-Z0-9./=]+(?:\$[a-zA-Z0-9./=]+)?")
_AWS_KEY_RE = re.compile(r"\b(AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}\b")
_GITHUB_TOKEN_RE = re.compile(r"\b(ghp_[a-zA-Z0-9]{36}|github_pat_[a-zA-Z0-9_]{82})\b")
_GCP_API_KEY_RE = re.compile(r"\bAIza[0-9A-Za-z-_]{35}\b")
_SLACK_TOKEN_RE = re.compile(r"\bxox[baprs]-[0-9a-zA-Z]{10,48}\b")
_JWT_RE = re.compile(r"\beyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\b")

GENESIS_HASH = "0" * 64


def mask_secrets(text: str) -> str:
    """
    Enmascara tokens, claves privadas, hashes shadow y secretos cloud en una cadena arbitraria.
    """
    if not text or not isinstance(text, str):
        return text

    # 1. Enmascarar claves privadas PEM
    text = _PEM_PRIVATE_KEY_RE.sub("[PRIVATE KEY MASKED]", text)

    # 2. Enmascarar tokens Bearer
    text = _BEARER_RE.sub("Bearer [MASKED]", text)

    # 3. Enmascarar hashes de contraseñas de Linux (/etc/shadow)
    text = _SHADOW_HASH_RE.sub("[SHADOW HASH MASKED]", text)

    # 4. Enmascarar tokens específicos de proveedores cloud y repositorios
    text = _AWS_KEY_RE.sub("[AWS KEY MASKED]", text)
    text = _GITHUB_TOKEN_RE.sub("[GITHUB TOKEN MASKED]", text)
    text = _GCP_API_KEY_RE.sub("[GCP API KEY MASKED]", text)
    text = _SLACK_TOKEN_RE.sub("[SLACK TOKEN MASKED]", text)
    text = _JWT_RE.sub("[JWT MASKED]", text)

    # 5. Enmascarar asignaciones clave=valor o "clave": "valor"
    kv_pattern = re.compile(
        r"([\x27\"]?(?:[A-Za-z0-9_]*(?:TOKEN|KEY|SECRET|PASS|AUTH|CRED|PASSWORD|APIKEY)[A-Za-z0-9_]*)[\x27\"]?\s*[:=]\s*[\x27\"]?)([^\s\x27\",;}{\[\]]+)([\x27\"]?)",
        re.IGNORECASE,
    )
    text = kv_pattern.sub(r"\1[MASKED]\3", text)

    return text


def sanitize_dict(data: Any, max_depth: int = 10) -> Any:
    """
    Recorre recursivamente diccionarios y listas, reemplazando valores de claves sensibles
    por '[MASKED]' y sanitizando cadenas de texto.
    """
    if max_depth <= 0:
        return data

    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            if _SENSITIVE_KEY_RE.search(str(k)):
                sanitized[k] = "[MASKED]"
            else:
                sanitized[k] = sanitize_dict(v, max_depth - 1)
        return sanitized
    elif isinstance(data, list):
        return [sanitize_dict(item, max_depth - 1) for item in data]
    elif isinstance(data, str):
        return mask_secrets(data)
    else:
        return data


def mask_pueue_output(raw_output: str) -> str:
    """
    Sanitiza la salida devuelta por Pueue (JSON o texto plano), enmascarando variables
    de entorno o salidas con credenciales sensibles.
    """
    if not raw_output or not isinstance(raw_output, str):
        return raw_output

    try:
        parsed = json.loads(raw_output)
        sanitized = sanitize_dict(parsed)
        return json.dumps(sanitized)
    except (json.JSONDecodeError, TypeError, ValueError):
        return mask_secrets(raw_output)


def _ensure_audit_table(conn: sqlite3.Connection) -> None:
    """Garantiza que la tabla de auditoría security_audit_log esté presente en la conexión."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS security_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            tool_name TEXT NOT NULL DEFAULT '',
            action TEXT NOT NULL,
            capability_tier TEXT NOT NULL DEFAULT '',
            target TEXT DEFAULT '',
            status TEXT NOT NULL,
            details_json TEXT NOT NULL,
            prev_hash TEXT NOT NULL,
            entry_hash TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_security_audit_agent ON security_audit_log(agent_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_security_audit_action ON security_audit_log(action)")


def record_audit_event(
    conn: sqlite3.Connection,
    agent_id: str,
    tool_name: str,
    action: str,
    capability_tier: str,
    status: str,
    details: Any = None,
    target: str | None = None,
) -> dict[str, Any]:
    """
    Registra un evento de auditoría criptográfica con encadenamiento de hash SHA-256.
    Aplica sanitize_dict/mask_secrets sobre el payload antes del cómputo criptográfico.
    """
    _ensure_audit_table(conn)

    # 1. Obtener hash previo del último registro insertado
    cur = conn.cursor()
    cur.execute("SELECT entry_hash FROM security_audit_log ORDER BY id DESC LIMIT 1")
    last_row = cur.fetchone()
    prev_hash = str(last_row[0]) if last_row and last_row[0] else GENESIS_HASH

    # 2. Sanitizar detalles y estructurar payload determinista
    sanitized_details = sanitize_dict(details) if details is not None else {}
    details_json = json.dumps(sanitized_details, sort_keys=True)
    iso_ts = datetime.now(UTC).isoformat()
    tgt = str(target) if target is not None else ""

    # 3. Cómputo del hash del bloque actual
    raw_payload = f"{prev_hash}|{iso_ts}|{agent_id}|{tool_name}|{action}|{capability_tier}|{tgt}|{status}|{details_json}"
    entry_hash = hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()

    # 4. Inserción atómica en la tabla
    cur.execute(
        """
        INSERT INTO security_audit_log (
            timestamp, agent_id, tool_name, action, capability_tier, target, status, details_json, prev_hash, entry_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (iso_ts, agent_id, tool_name, action, capability_tier, tgt, status, details_json, prev_hash, entry_hash),
    )

    return {
        "status": "RECORDED",
        "id": cur.lastrowid,
        "entry_hash": entry_hash,
        "prev_hash": prev_hash,
        "timestamp": iso_ts,
    }


def verify_audit_chain(conn: sqlite3.Connection) -> dict[str, Any]:
    """
    Verifica la integridad criptográfica de toda la cadena de auditoría SHA-256.
    Devuelve dict estructurado indicando validez y total de entradas verificadas.
    """
    _ensure_audit_table(conn)

    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, timestamp, agent_id, tool_name, action, capability_tier, target, status, details_json, prev_hash, entry_hash
        FROM security_audit_log ORDER BY id ASC
        """
    )
    rows = cur.fetchall()

    if not rows:
        return {
            "valid": True,
            "verified": True,
            "total_verified": 0,
            "count": 0,
            "latest_hash": GENESIS_HASH,
            "message": "Cadena de auditoría vacía (íntegra por definición).",
        }

    expected_prev = GENESIS_HASH
    for i, row in enumerate(rows):
        (
            row_id,
            r_ts,
            r_agent,
            r_tool,
            r_action,
            r_tier,
            r_target,
            r_status,
            r_details,
            r_prev,
            r_entry,
        ) = row

        # Validar enlace con el bloque anterior
        if r_prev != expected_prev:
            return {
                "valid": False,
                "verified": False,
                "error": f"Enlace roto en id {row_id}: se esperaba prev_hash '{expected_prev}', se encontró '{r_prev}'",
                "broken_row_id": row_id,
                "total_verified": i,
                "count": i,
            }

        # Recomputar hash del bloque
        tgt = str(r_target) if r_target is not None else ""
        raw_payload = f"{r_prev}|{r_ts}|{r_agent}|{r_tool}|{r_action}|{r_tier}|{tgt}|{r_status}|{r_details}"
        computed_hash = hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()

        if computed_hash != r_entry:
            return {
                "valid": False,
                "verified": False,
                "error": f"Manipulación detectada en id {row_id}: hash no coincide (esperado '{computed_hash}', guardado '{r_entry}')",
                "broken_row_id": row_id,
                "total_verified": i,
                "count": i,
            }

        expected_prev = r_entry

    return {
        "valid": True,
        "verified": True,
        "total_verified": len(rows),
        "count": len(rows),
        "latest_hash": expected_prev,
        "message": f"Cadena de auditoría verificada íntegra con {len(rows)} bloques encadenados.",
    }
