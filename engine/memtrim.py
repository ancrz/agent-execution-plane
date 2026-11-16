"""
Engine: memtrim.py (ONT-67 T6)
Description: fail-soft `malloc_trim(0)` (glibc) so freed heap goes back to the OS after heavy transient work.

glibc keeps freed arena pages resident; `malloc_trim(0)` returns the free ones with `madvise`/`MADV_DONTNEED`.
It is a no-op on musl/macOS (symbol missing) and never raises. Leaf module: standard library only.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import threading

_LIB_LOCK = threading.Lock()
_STATE: dict[str, object] = {"fn": None, "resolved": False}


def _resolve() -> object:
    with _LIB_LOCK:
        if not _STATE["resolved"]:
            _STATE["resolved"] = True
            try:
                libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6")
                fn = libc.malloc_trim
                fn.argtypes = [ctypes.c_size_t]
                fn.restype = ctypes.c_int
                _STATE["fn"] = fn
            except OSError, AttributeError:
                _STATE["fn"] = None
        return _STATE["fn"]


def trim() -> bool:
    """Run malloc_trim(0). True if glibc released memory, False if nothing released or unsupported."""
    fn = _resolve()
    if fn is None:
        return False
    try:
        return bool(fn(0))  # type: ignore[operator]
    except OSError, ctypes.ArgumentError:
        return False
