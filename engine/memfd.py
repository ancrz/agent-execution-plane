"""
Engine: memfd.py (ONT-67 T2)
Description: sealed, close-on-exec, explicitly-executable memfd for in-RAM execution of catalog ELF binaries.

Kernel contract (docs.kernel.org/userspace-api/mfd_noexec.html, Linux >= 6.3):
  - `MFD_EXEC` (0x10) states the intent to execute the fd; without it (and without `MFD_NOEXEC_SEAL`) the kernel
    logs a warning, and under `vm.memfd_noexec=1` the memfd is created non-executable.
  - `vm.memfd_noexec=2` rejects every memfd that is not `MFD_NOEXEC_SEAL`: executing from RAM is impossible there.
  - Kernels < 6.3 do not know `MFD_EXEC` and answer EINVAL: retry without it.
Integrity (runc CVE-2019-5736 pattern): the content is sealed (WRITE|SHRINK|GROW|SEAL) before it is executed, so
nothing holding another reference to the file can alter the binary between verification and exec.

Leaf module of the Topos protocol: imports only the standard library.
"""

from __future__ import annotations

import errno
import fcntl
import os

MFD_EXEC = 0x10  # not exported by Python's `os` (3.14 has only MFD_CLOEXEC / MFD_ALLOW_SEALING)
# linux/fcntl.h values; Python's `fcntl` does not export the seal constants on every build.
F_ADD_SEALS = getattr(fcntl, "F_ADD_SEALS", 1033)
F_GET_SEALS = getattr(fcntl, "F_GET_SEALS", 1034)
F_SEAL_SEAL, F_SEAL_SHRINK, F_SEAL_GROW, F_SEAL_WRITE = 0x1, 0x2, 0x4, 0x8
SEALS = F_SEAL_WRITE | F_SEAL_SHRINK | F_SEAL_GROW | F_SEAL_SEAL
NOEXEC_SYSCTL = "/proc/sys/vm/memfd_noexec"


class MemfdNoexecEnforced(OSError):
    """The kernel forbids executing a memfd (vm.memfd_noexec=2, or EACCES/EPERM on create/exec)."""


def noexec_policy() -> int | None:
    """Value of `vm.memfd_noexec` (0 exec by default, 1 noexec by default, 2 enforced), None if the kernel lacks it."""
    try:
        with open(NOEXEC_SYSCTL, encoding="ascii") as fh:
            return int(fh.read().strip())
    except OSError, ValueError:
        return None


def _create(name: str, flags: int) -> int:
    """memfd_create with the EINVAL fallback for kernels that predate MFD_EXEC."""
    try:
        return os.memfd_create(name, flags)
    except OSError as exc:
        if exc.errno == errno.EINVAL and flags & MFD_EXEC:
            return os.memfd_create(name, flags & ~MFD_EXEC)
        if exc.errno in (errno.EACCES, errno.EPERM):
            raise MemfdNoexecEnforced(exc.errno, "memfd_create refused by vm.memfd_noexec policy") from exc
        raise


def create_sealed_exec_memfd(name: str, data: bytes) -> int:
    """Create a CLOEXEC memfd holding `data`, positioned at 0 and sealed against any further change.

    Raises MemfdNoexecEnforced when the host policy forbids executable memfds. The caller owns (must close) the fd.
    """
    if noexec_policy() == 2:
        raise MemfdNoexecEnforced(errno.EACCES, "vm.memfd_noexec=2: executable memfds are disabled on this host")
    fd = _create(name, os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING | MFD_EXEC)
    try:
        view = memoryview(data)
        written = 0
        while written < len(view):
            written += os.write(fd, view[written:])
        os.lseek(fd, 0, os.SEEK_SET)
        fcntl.fcntl(fd, F_ADD_SEALS, SEALS)
    except BaseException:
        os.close(fd)
        raise
    return fd


def seals(fd: int) -> int:
    """Seals currently applied to `fd` (F_GET_SEALS)."""
    return fcntl.fcntl(fd, F_GET_SEALS)
