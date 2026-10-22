"""
Engine: privilege.py — Modelo de niveles de capacidad (least-privilege por defecto).

Fuente de verdad única sobre el privilegio disponible. Las tools privilegiadas del stack
lo consultan para operar en dos niveles:

  - FULL       : el proceso es root, o puede escalar sin password (sudo -n). Alcance
                 de sistema (observabilidad kernel-wide, control de servicios, coredumps
                 de otros usuarios).
  - DIMINISHED : usuario sin vía de escalada. Alcance acotado al propio usuario/proceso;
                 la capacidad existe pero con apertura reducida (fail-soft, nunca excepción).

Diseño de seguridad: la escalada es por-tool y acotada; nunca se asume root. Un nivel más
alto AMPLÍA la apertura (self-scope -> system-scope), no es un requisito para operar.
"""

import os
import shutil
import subprocess
from typing import List, Optional

_SUDO_N_CACHE: Optional[bool] = None


def sudo_n_available() -> bool:
    """¿Hay sudo sin contraseña (escalada no-interactiva)? Resultado cacheado por proceso."""
    global _SUDO_N_CACHE
    if _SUDO_N_CACHE is None:
        try:
            _SUDO_N_CACHE = bool(shutil.which("sudo")) and subprocess.run(
                ["sudo", "-n", "true"], capture_output=True, timeout=5
            ).returncode == 0
        except Exception:
            _SUDO_N_CACHE = False
    return _SUDO_N_CACHE


def privilege_prefix() -> Optional[List[str]]:
    """[] si ya es root; ['sudo','-n'] si se puede escalar; None si no hay vía (DIMINISHED)."""
    if os.geteuid() == 0:
        return []
    return ["sudo", "-n"] if sudo_n_available() else None


def privilege_mode() -> str:
    """Etiqueta del modo efectivo: direct-root | sudo-n | unprivileged."""
    if os.geteuid() == 0:
        return "direct-root"
    return "sudo-n" if sudo_n_available() else "unprivileged"


def capability_tier() -> str:
    """FULL si hay root o escalada disponible; DIMINISHED en caso contrario."""
    return "FULL" if privilege_prefix() is not None else "DIMINISHED"
