"""
Engine: embedder.py
Description: Embedder semántico local en CPU para la memoria del catálogo (AEP).

Genera vectores de 384 dimensiones con `fastembed` (modelo BAAI/bge-small-en-v1.5,
espacio equivalente a all-MiniLM-L6-v2) ejecutándose 100% offline vía ONNX Runtime.

Diseño FAIL-SOFT: si `fastembed` no está instalado o el modelo no puede cargarse,
`is_available` queda en False y `embed()` devuelve None. Ningún consumidor debe
romperse por la ausencia del embedder — el catálogo degrada a su tier de hash exacto.

Módulo HOJA del Protocolo Topos: solo importa engine.memtrim (hoja, stdlib).
Relación con catalog.py y docs_vectorizer.py: dependencia unidireccional (A -> B).
"""

import gc
import logging
import os
import threading
import time

from engine import memtrim
from engine.go_toolchain import read_toolchain_env

log = logging.getLogger("aep.embedder")

# Nombre canónico del modelo (384-dim). fastembed lo descarga y cachea una sola vez.
MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384


class _EmbedderHolder:
    instance: LocalEmbedder | None = None


_instance_lock = threading.Lock()


def _disable_ort_telemetry() -> bool:
    """Desactiva la telemetría de onnxruntime (ONT-52 G37) con la API pública `disable_telemetry_events()`.

    Verificado en onnxruntime 1.31.1: `help(onnxruntime.disable_telemetry_events)` -> "Disables platform-specific
    telemetry collection". Fail-soft: si la API no existe o falla, el embedder sigue funcionando.
    """
    try:
        import onnxruntime

        onnxruntime.disable_telemetry_events()
        return True
    except ImportError, AttributeError, RuntimeError:
        return False


IDLE_ENV = "AEP_EMBED_IDLE_S"
IDLE_DEFAULT_S = 600.0  # ONT-67 T3: unload the ~235 MB model after 10 minutes without use; 0 = never


def idle_seconds() -> float:
    """Idle time before the model is unloaded (`AEP_EMBED_IDLE_S`, default 600; 0 or invalid-negative = never)."""
    raw = os.environ.get(IDLE_ENV, "").strip()
    if not raw:  # ONT-67 T8: a value the user set in toolchain.env (written by setup.sh) counts like the env var
        raw = read_toolchain_env().get(IDLE_ENV, "").strip()
    if not raw:
        return IDLE_DEFAULT_S
    try:
        return max(0.0, float(raw))
    except ValueError:
        return IDLE_DEFAULT_S


class LocalEmbedder:
    """Envoltura fail-soft y thread-safe sobre fastembed.TextEmbedding.

    ONT-67 T3: el modelo se descarga tras `AEP_EMBED_IDLE_S` sin uso y se recarga de forma perezosa y transparente
    en la siguiente llamada; `is_available` sigue siendo True mientras esta descargado.
    """

    def __init__(self) -> None:
        self._model = None
        self._available = False
        self._embed_lock = threading.Lock()
        self._last_used = time.monotonic()
        self._timer: threading.Timer | None = None
        self.loads = 0
        self.unloads = 0
        try:
            self._load_model()
            self._available = True
            log.info("LocalEmbedder listo (modelo=%s, dim=%d)", MODEL_NAME, EMBEDDING_DIM)
        except (ImportError, RuntimeError, ValueError, OSError) as exc:
            self._available = False
            log.warning("Embedder no disponible (%s): %s", type(exc).__name__, exc)
        else:
            with self._embed_lock:
                self._schedule_idle_check()

    def _load_model(self) -> None:
        # Import perezoso: fastembed es pesado y puede no estar instalado.
        # La variable debe existir ANTES de importar onnxruntime (ONT-53 G42): `disable_telemetry_events()`
        # por sí sola no impide abrir ~/.cache/Microsoft/DeveloperTools/.onnxruntime/onnxruntime.db.
        # setdefault respeta un valor explícito del operador.
        os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")
        from fastembed import TextEmbedding

        _disable_ort_telemetry()
        # ONT-67 T3: `enable_cpu_mem_arena=False` (exposed by fastembed 0.9.1) was measured and gave no RSS gain
        # (529 268 vs 529 536 kB idle): not applied.
        self._model = TextEmbedding(model_name=MODEL_NAME)
        self.loads += 1

    @property
    def is_available(self) -> bool:
        return self._available

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def _schedule_idle_check(self, delay: float | None = None) -> None:
        """Arm (at most) one daemon timer. Caller holds `_embed_lock`."""
        if self._timer is not None or self._model is None:
            return
        idle = idle_seconds()
        if idle <= 0:
            return
        timer = threading.Timer(idle if delay is None else delay, self._idle_check)
        timer.daemon = True
        self._timer = timer
        timer.start()

    def _idle_check(self) -> None:
        with self._embed_lock:
            self._timer = None
            idle = idle_seconds()
            if idle <= 0 or self._model is None:
                return
            remaining = idle - (time.monotonic() - self._last_used)
            if remaining > 0:
                self._schedule_idle_check(remaining)
                return
            self._unload_locked()

    def _unload_locked(self) -> None:
        self._model = None
        self.unloads += 1
        gc.collect()
        memtrim.trim()  # glibc keeps the freed ONNX buffers resident otherwise

    def unload(self) -> bool:
        """Frees the model now (it reloads lazily on next use). True if something was unloaded."""
        with self._embed_lock:
            if self._model is None:
                return False
            self._unload_locked()
            return True

    def _model_locked(self):
        """Loaded model (reloading it if idle-unloaded). Caller holds `_embed_lock`; None when the reload fails."""
        if self._model is None:
            try:
                self._load_model()
            except (ImportError, RuntimeError, ValueError, OSError) as exc:
                log.warning("Recarga del embedder falló (%s): %s", type(exc).__name__, exc)
                return None
        self._last_used = time.monotonic()
        self._schedule_idle_check()
        return self._model

    def embed(self, text: str) -> list[float] | None:
        """Devuelve el vector de 384 floats, o None si el embedder no está disponible."""
        if not self._available or not text:
            return None
        try:
            with self._embed_lock:  # ONNX Runtime no garantiza reentrancia
                model = self._model_locked()
                if model is None:
                    return None
                vec = next(iter(model.embed([text])))
                self._last_used = time.monotonic()
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
                model = self._model_locked()
                if model is None:
                    return [None] * len(texts)
                vecs = list(model.embed(texts))
                self._last_used = time.monotonic()
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
