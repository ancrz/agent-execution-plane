"""
Engine: embedder.py
Description: Embedder semántico local en CPU para la memoria del catálogo (AEP).

Genera vectores de 384 dimensiones con `fastembed` (modelo BAAI/bge-small-en-v1.5,
espacio equivalente a all-MiniLM-L6-v2) ejecutándose 100% offline vía ONNX Runtime.

Diseño FAIL-SOFT: si `fastembed` no está instalado o el modelo no puede cargarse,
`is_available` queda en False y `embed()` devuelve None. Ningún consumidor debe
romperse por la ausencia del embedder — el catálogo degrada a su tier de hash exacto.

Módulo HOJA del Protocolo Topos: no importa nada del resto del código de AEP.
Relación con catalog.py y docs_vectorizer.py: dependencia unidireccional (A -> B).
"""

import logging
import threading
from typing import List, Optional

log = logging.getLogger("aep.embedder")

# Nombre canónico del modelo (384-dim). fastembed lo descarga y cachea una sola vez.
MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384

_instance: "Optional[LocalEmbedder]" = None
_instance_lock = threading.Lock()


class LocalEmbedder:
    """Envoltura fail-soft y thread-safe sobre fastembed.TextEmbedding."""

    def __init__(self) -> None:
        self._model = None
        self._available = False
        self._embed_lock = threading.Lock()
        try:
            # Import perezoso: fastembed es pesado y puede no estar instalado.
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=MODEL_NAME)
            self._available = True
            log.info("LocalEmbedder listo (modelo=%s, dim=%d)", MODEL_NAME, EMBEDDING_DIM)
        except Exception as exc:  # ImportError o fallo de carga del modelo
            self._available = False
            log.warning("Embedder no disponible (%s): %s", type(exc).__name__, exc)

    @property
    def is_available(self) -> bool:
        return self._available

    def embed(self, text: str) -> Optional[List[float]]:
        """Devuelve el vector de 384 floats, o None si el embedder no está disponible."""
        if not self._available or not text:
            return None
        try:
            with self._embed_lock:  # ONNX Runtime no garantiza reentrancia
                vec = next(iter(self._model.embed([text])))
            return [float(x) for x in vec]
        except Exception as exc:
            log.warning("embed() falló (%s): %s", type(exc).__name__, exc)
            return None

    def embed_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """Embebe una lista de textos (usado por el vectorizador de man-pages)."""
        if not self._available or not texts:
            return [None] * len(texts)
        try:
            with self._embed_lock:
                vecs = list(self._model.embed(texts))
            return [[float(x) for x in v] for v in vecs]
        except Exception as exc:
            log.warning("embed_batch() falló (%s): %s", type(exc).__name__, exc)
            return [None] * len(texts)


def get_instance() -> LocalEmbedder:
    """Factory singleton thread-safe (double-checked locking)."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = LocalEmbedder()
    return _instance
