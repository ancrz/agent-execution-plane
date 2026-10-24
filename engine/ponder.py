"""
Engine: ponder.py — Motor de ponderación multidimensional CONSCIENTE DE CONFIANZA (compartido).

Fuente única de la vara con que se mide toda entidad reutilizable (artefactos, playbooks, ...).
Adaptado del trust engine de skill-swarm-mcp: dimensiones ponderadas + factor de confianza +
bandas de veredicto. `effective = Σ(dim·peso) × confidence`; las dimensiones sin señal se OMITEN
(no suman y bajan la confianza -> una entidad sin historial no se confía a ciegas).

Cada entidad construye su propio dict de dimensiones y llama a finalize(); así la vara es común
pero el significado de cada dimensión lo aporta el dominio (artefacto vs playbook).
"""

import logging
import math
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("aep.ponder")

DIMENSION_WEIGHTS = {
    "quality": 0.35,  # señales de compuerta (lint/canary para artefactos; validación DAG para playbooks)
    "reliability": 0.30,  # tasa de éxito histórica
    "experience": 0.15,  # cuán battle-tested (log de ejecuciones/corridas)
    "recency": 0.20,  # frescura: decae con el tiempo sin validarse/usarse
}
TRUST_BAND = 0.75
CAUTION_BAND = 0.50
WARNING_BAND = 0.25
RECENCY_HALF_LIFE_DAYS = 45


def log_norm(value: int, midpoint: int) -> float:
    if value <= 0:
        return 0.0
    return min(math.log10(1 + value) / math.log10(1 + midpoint), 1.0)


def recency_decay(days: float) -> float:
    return math.exp(-math.log(2) / RECENCY_HALF_LIFE_DAYS * max(0.0, days))


def days_since(ts: Any) -> float:
    if not ts:
        return 0.0
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(str(ts).split(".")[0], fmt).replace(tzinfo=UTC)
            return max(0.0, (datetime.now(UTC) - dt).total_seconds() / 86400.0)
        except (ValueError, TypeError) as e:
            logger.debug("days_since parse failed for %s (%s): %s", ts, fmt, e)
            continue
    return 0.0


def finalize(dims: dict[str, float], reliability_veto: bool = False) -> dict[str, Any]:
    """Combina dimensiones conocidas en el veredicto. `reliability_veto`: fallo demostrado
    (éxito<0.70 con historial) impide TRUST por mucha calidad/frescura que haya."""
    total = sum(dims[k] * DIMENSION_WEIGHTS[k] for k in dims)
    confidence = len(dims) / len(DIMENSION_WEIGHTS)
    effective = round(total * confidence, 4)
    if effective >= TRUST_BAND:
        verdict = "TRUST"
    elif effective >= CAUTION_BAND:
        verdict = "CAUTION"
    elif effective >= WARNING_BAND:
        verdict = "WARNING"
    else:
        verdict = "REJECT"
    if reliability_veto and verdict == "TRUST":
        verdict = "CAUTION"
    return {
        "effective": effective,
        "raw": round(total, 4),
        "confidence": round(confidence, 2),
        "verdict": verdict,
        "dimensions": {k: round(v, 3) for k, v in dims.items()},
    }
