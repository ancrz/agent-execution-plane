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

log = logging.getLogger("aep.embedder")

# Nombre canónico del modelo (384-dim). fastembed lo descarga y cachea una sola vez.
MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384


class _EmbedderHolder:
    instance: LocalEmbedder | None = None


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
        except (ImportError, RuntimeError, ValueError, OSError) as exc:
            self._available = False
            log.warning("Embedder no disponible (%s): %s", type(exc).__name__, exc)

    @property
    def is_available(self) -> bool:
        return self._available

    def embed(self, text: str) -> list[float] | None:
        """Devuelve el vector de 384 floats, o None si el embedder no está disponible."""
        if not self._available or not text:
            return None
        try:
            with self._embed_lock:  # ONNX Runtime no garantiza reentrancia
                vec = next(iter(self._model.embed([text])))
            return [float(x) for x in vec]
        except (RuntimeError, ValueError, OSError) as exc:
            log.warning("embed() falló (%s): %s", type(exc).__name__, exc)
            return None

    def embed_batch(self, texts: list[str]) -> list[list[float] | None]:
        """Embebe una lista de textos (usado por el vectorizador de man-pages)."""
        if not self._available or not texts:
            return [None] * len(texts)
        try:
            with self._embed_lock:
                vecs = list(self._model.embed(texts))
            return [[float(x) for x in v] for v in vecs]
        except (RuntimeError, ValueError, OSError) as exc:
            log.warning("embed_batch() falló (%s): %s", type(exc).__name__, exc)
            return [None] * len(texts)


def get_instance() -> LocalEmbedder:
    """Factory singleton thread-safe (double-checked locking)."""
    if _EmbedderHolder.instance is None:
        with _instance_lock:
            if _EmbedderHolder.instance is None:
                _EmbedderHolder.instance = LocalEmbedder()
    return _EmbedderHolder.instance
