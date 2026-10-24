"""
Engine: security.py (SPEC-SEC-01: Secret Masking & Telemetry Redaction)

Intercepta y enmascara tokens, claves de API, credenciales y encabezados de autorización
en cadenas de texto, estructuras de datos (diccionarios/listas) y volcados de Pueue/subprocesos.
Garantiza que ningún secreto se filtre en los contextos de los LLMs.
"""

import json
import re
from typing import Any, Dict, List, Optional, Union

# Expresiones regulares para detección de secretos
_BEARER_RE = re.compile(r"Bearer\s+([A-Za-z0-9_\-\.]+)", re.IGNORECASE)
_PEM_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]+PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]+PRIVATE KEY-----"
)
_SENSITIVE_KEY_RE = re.compile(
    r"(TOKEN|KEY|SECRET|PASS|AUTH|CRED|PASSWORD|APIKEY)", re.IGNORECASE
)


def mask_secrets(text: str) -> str:
    """
    Enmascara tokens, claves privadas y secretos en una cadena de texto arbitraria.
    """
    if not text or not isinstance(text, str):
        return text

    # 1. Enmascarar claves privadas PEM
    text = _PEM_PRIVATE_KEY_RE.sub("[PRIVATE KEY MASKED]", text)

    # 2. Enmascarar tokens Bearer
    text = _BEARER_RE.sub("Bearer [MASKED]", text)

    # 3. Enmascarar asignaciones clave=valor o \"clave\": \"valor\"
    kv_pattern = re.compile(
        r"([\x27\"]?(?:[A-Za-z0-9_]*(?:TOKEN|KEY|SECRET|PASS|AUTH|CRED|PASSWORD|APIKEY)[A-Za-z0-9_]*)[\x27\"]?\s*[:=]\s*[\x27\"]?)([^\s\x27\",;}{]+)([\x27\"]?)",
        re.IGNORECASE,
    )
    text = kv_pattern.sub(r"\1[MASKED]\3", text)

    return text


def sanitize_dict(data: Any, max_depth: int = 10) -> Any:
    """
    Recorre recursivamente diccionarios y listas, reemplazando valores de claves sensibles
    por \x27[MASKED]\x27 y sanitizando cadenas de texto.
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
    except Exception:
        return mask_secrets(raw_output)
