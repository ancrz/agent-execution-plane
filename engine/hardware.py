"""
Engine: hardware.py (GAP-CP-05: Hardware Domain & Pre-Flight Accelerator Admission)

Linux sysfs and procfs hardware introspection module.
- CPU & RAM capacity/available metrics via /proc/cpuinfo and /proc/meminfo.
- DRM graphics/accelerator introspection via /sys/class/drm/card*.
- AMDGPU VRAM and GTT (Graphics Translation Table) memory telemetry.
- Mandatory 4096 MiB desktop safety margin on GTT to prevent compositor SIGABRT (Xorg/Wayland).
- Fail-soft handling on non-AMD GPUs, Intel, NVIDIA, and headless/container environments (R-3).
"""

import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger("aep.hardware")

DEFAULT_DESKTOP_SAFETY_MARGIN_MIB = 4096
AMDGPU_VENDOR_ID = "0x1002"
NVIDIA_VENDOR_ID = "0x10de"
INTEL_VENDOR_ID = "0x8086"


def _read_int_file(path: Path) -> int:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def _read_str_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return ""


def probe_accelerators(drm_dir: Path | str = "/sys/class/drm") -> list[dict[str, Any]]:
    """Enumerate DRM graphics accelerators and extract VRAM/GTT memory footprints.

    FAIL-SOFT: If /sys/class/drm does not exist, is unreadable, or contains no card nodes,
    returns [] without raising FileNotFoundError or crashing (R-3).
    """
    base = Path(drm_dir)
    if not base.exists() or not base.is_dir():
        return []

    accelerators: list[dict[str, Any]] = []
    try:
        cards = sorted(base.glob("card[0-9]*"))
    except OSError as e:
        logger.debug("Failed globbing %s: %s", drm_dir, e)
        return []

    for card in cards:
        # Ignore connector symlinks like card1-DP-1
        if "-" in card.name:
            continue

        device_dir = card / "device"
        if not device_dir.exists():
            continue

        vendor = _read_str_file(device_dir / "vendor").lower()
        device_id = _read_str_file(device_dir / "device").lower()
        if not vendor:
            continue

        if vendor == AMDGPU_VENDOR_ID:
            vendor_name = "AMD"
        elif vendor == NVIDIA_VENDOR_ID:
            vendor_name = "NVIDIA"
        elif vendor == INTEL_VENDOR_ID:
            vendor_name = "Intel"
        else:
            vendor_name = "Unknown"

        # Memory info from AMDGPU sysfs (in bytes)
        vram_total_b = _read_int_file(device_dir / "mem_info_vram_total")
        vram_used_b = _read_int_file(device_dir / "mem_info_vram_used")
        gtt_total_b = _read_int_file(device_dir / "mem_info_gtt_total")
        gtt_used_b = _read_int_file(device_dir / "mem_info_gtt_used")

        vram_total_mib = vram_total_b // (1024 * 1024)
        vram_used_mib = vram_used_b // (1024 * 1024)
        vram_free_mib = max(0, vram_total_mib - vram_used_mib)

        gtt_total_mib = gtt_total_b // (1024 * 1024)
        gtt_used_mib = gtt_used_b // (1024 * 1024)
        gtt_free_mib = max(0, gtt_total_mib - gtt_used_mib)

        # Distinguish integrated vs discrete AMD/Intel
        if gtt_total_mib > vram_total_mib and vram_total_mib <= 2048:
            accel_type = "integrated"
        elif vram_total_mib > 2048:
            accel_type = "discrete"
        else:
            accel_type = "gpu"

        accelerators.append(
            {
                "card": card.name,
                "vendor": vendor,
                "vendor_name": vendor_name,
                "device_id": device_id,
                "type": accel_type,
                "vram_total_mib": vram_total_mib,
                "vram_used_mib": vram_used_mib,
                "vram_free_mib": vram_free_mib,
                "gtt_total_mib": gtt_total_mib,
                "gtt_used_mib": gtt_used_mib,
                "gtt_free_mib": gtt_free_mib,
            }
        )

    return accelerators


def probe_hardware_inventory(
    cpuinfo_path: Path | str = "/proc/cpuinfo",
    meminfo_path: Path | str = "/proc/meminfo",
    drm_dir: Path | str = "/sys/class/drm",
) -> dict[str, Any]:
    """Introspect CPU, RAM, and graphics accelerators with fail-soft defaults."""
    # 1. CPU Introspection
    cpu_model = "unknown"
    cores = 0
    try:
        p_cpu = Path(cpuinfo_path)
        if p_cpu.exists():
            for line in p_cpu.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("model name") and cpu_model == "unknown":
                    cpu_model = line.split(":", 1)[1].strip()
                elif line.startswith("processor"):
                    cores += 1
    except OSError as e:
        logger.debug("Failed reading cpuinfo: %s", e)

    if cores == 0:
        cores = os.cpu_count() or 1

    # 2. Memory Introspection
    mem_total_mib = 0
    mem_available_mib = 0
    swap_total_mib = 0
    swap_free_mib = 0
    try:
        p_mem = Path(meminfo_path)
        if p_mem.exists():
            for line in p_mem.read_text(encoding="utf-8", errors="replace").splitlines():
                parts = line.split(":")
                if len(parts) == 2:
                    k = parts[0].strip()
                    val_m = re.search(r"(\d+)", parts[1])
                    val_kib = int(val_m.group(1)) if val_m else 0
                    if k == "MemTotal":
                        mem_total_mib = val_kib // 1024
                    elif k == "MemAvailable":
                        mem_available_mib = val_kib // 1024
                    elif k == "SwapTotal":
                        swap_total_mib = val_kib // 1024
                    elif k == "SwapFree":
                        swap_free_mib = val_kib // 1024
    except OSError as e:
        logger.debug("Failed reading meminfo: %s", e)

    # 3. Accelerators Introspection
    accels = probe_accelerators(drm_dir=drm_dir)

    status = "OK" if (cores > 0 and mem_total_mib > 0) else "DEGRADED"

    return {
        "status": status,
        "cpu": {
            "model": cpu_model,
            "logical_cores": cores,
        },
        "memory": {
            "total_mib": mem_total_mib,
            "available_mib": mem_available_mib,
            "swap_total_mib": swap_total_mib,
            "swap_free_mib": swap_free_mib,
        },
        "accelerators_count": len(accels),
        "accelerators": accels,
    }


def admit_accelerator(
    device: str | None = None,
    req_vram_mib: int = 0,
    req_gtt_mib: int = 0,
    margin_mib: int = DEFAULT_DESKTOP_SAFETY_MARGIN_MIB,
    drm_dir: Path | str = "/sys/class/drm",
) -> dict[str, Any]:
    """Pre-flight resource admission for graphics accelerators (GAP-CP-05).

    Enforces mandatory desktop safety margin (default 4096 MiB) on GTT allocations
    to prevent compositor memory exhaustion and GNOME Shell / Wayland SIGABRT.
    """
    accels = probe_accelerators(drm_dir=drm_dir)
    if not accels:
        return {
            "status": "REJECTED",
            "admit": False,
            "device": device,
            "reason": "no_accelerators_detected",
            "margin_mib": margin_mib,
            "req_vram_mib": req_vram_mib,
            "req_gtt_mib": req_gtt_mib,
            "vram_free_mib": 0,
            "gtt_free_mib": 0,
            "gtt_available_mib": 0,
        }

    # Find requested card or select first available accelerator
    target_card: dict[str, Any] | None = None
    if device:
        for a in accels:
            if a["card"] == device:
                target_card = a
                break
        if not target_card:
            return {
                "status": "REJECTED",
                "admit": False,
                "device": device,
                "reason": f"device_{device}_not_found",
                "available_devices": [a["card"] for a in accels],
                "margin_mib": margin_mib,
                "req_vram_mib": req_vram_mib,
                "req_gtt_mib": req_gtt_mib,
                "vram_free_mib": 0,
                "gtt_free_mib": 0,
                "gtt_available_mib": 0,
            }
    else:
        # Default to first AMD accelerator or first card
        amd_cards = [a for a in accels if a.get("vendor") == AMDGPU_VENDOR_ID]
        target_card = amd_cards[0] if amd_cards else accels[0]

    vram_free = target_card.get("vram_free_mib", 0)
    gtt_free = target_card.get("gtt_free_mib", 0)
    gtt_available = max(0, gtt_free - margin_mib)

    vram_ok = vram_free >= req_vram_mib
    gtt_ok = gtt_available >= req_gtt_mib
    admitted = vram_ok and gtt_ok

    if admitted:
        status = "OK"
        reason = "admitted"
    else:
        status = "REJECTED"
        reasons = []
        if not vram_ok:
            reasons.append(f"insufficient_vram: requested {req_vram_mib} MiB, free {vram_free} MiB")
        if not gtt_ok:
            reasons.append(
                f"insufficient_gtt_safety_margin: requested {req_gtt_mib} MiB, available {gtt_available} MiB "
                f"after {margin_mib} MiB desktop safety margin from {gtt_free} MiB free"
            )
        reason = "; ".join(reasons)

    return {
        "status": status,
        "admit": admitted,
        "device": target_card["card"],
        "vendor": target_card.get("vendor"),
        "vendor_name": target_card.get("vendor_name"),
        "req_vram_mib": req_vram_mib,
        "req_gtt_mib": req_gtt_mib,
        "margin_mib": margin_mib,
        "vram_total_mib": target_card.get("vram_total_mib", 0),
        "vram_free_mib": vram_free,
        "gtt_total_mib": target_card.get("gtt_total_mib", 0),
        "gtt_free_mib": gtt_free,
        "gtt_available_mib": gtt_available,
        "reason": reason,
    }
