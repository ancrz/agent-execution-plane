# Software Design Document (SDD): Linux Primitives, Landlock LSM Sandboxing, eBPF Security Tracing, and Anti-Poisoning Backups

- **Document ID**: `sdd_linux_primitives_and_anti_poisoning.md`
- **Milestone**: ONT-13 (Task 114: `feat:re_as_sdd_landlock_ebpf_and_anti_poisoning_backups`)
- **System**: Agent Execution Plane (AEP)
- **Status**: APPROVED & IMPLEMENTED
- **Pipeline Mode**: Full Mode (Topos Integrity Protocol)

---

## 1. Architectural Overview & Motivation

The Agent Execution Plane (AEP) provides autonomous execution primitives to multi-agent coding engines. While previous milestones (ONT-01 through ONT-12) established bubblewrap sandboxing, process inspection, Pueue job dispatch, and hot 5-slot FIFO backups, Milestone ONT-13 hardens the execution fabric directly at the Linux kernel boundary using Reverse-Engineering as Software Design Document (RE as SDD).

This document specifies four foundational system components:
1. **Linux Landlock LSM In-Process Sandboxing**: Kernel-level unprivileged filesystem access control via native syscall ABI (`sys_landlock_create_ruleset`, `sys_landlock_add_rule`, `sys_landlock_restrict_self`).
2. **eBPF Security Tracing**: Non-invasive kernel observability using `bpftrace` bounded tracepoints for security audits (denied file opens, Landlock restriction events, child process executions).
3. **Volatile In-RAM Micro-Snapshots**: Sub-millisecond copy-on-write in-memory transactional snapshots using SQLite Backup API streaming (`src_conn.backup(mem_conn)`) for speculative agent exploration.
4. **Anti-Poisoning Zero-Trust Quarantine Backup Engine**: Cryptographic schema hashing, integrity checking, canary record verification, and quarantine isolation preventing poisoned database states from polluting the backup pool.

---

## 2. Linux Landlock LSM Architecture

### 2.1 Syscall ABI Specification
Linux Landlock (merged in kernel 5.13) is a stacked Linux Security Module (LSM) that allows unprivileged processes to restrict their own ambient file system access rights without requiring `CAP_SYS_ADMIN` or container runtimes.

The syscall ABI utilizes three x86_64 syscalls:
- **`SYS_landlock_create_ruleset` (`444`)**: Creates a new ruleset file descriptor from a `landlock_ruleset_attr` structure.
- **`SYS_landlock_add_rule` (`445`)**: Adds a rule (e.g. `LANDLOCK_RULE_PATH_BENEATH`) referencing an open file descriptor (`parent_fd`) and an access rights bitmask.
- **`SYS_landlock_restrict_self` (`446`)**: Irrevocably restricts the calling thread and all future children to the ruleset.

```
+-------------------------------------------------------------+
|                      Agent Process Space                    |
|                                                             |
|  1. prctl(PR_SET_NO_NEW_PRIVS, 1)                           |
|         |                                                   |
|  2. syscall(444, &ruleset_attr, size, 0) -> ruleset_fd      |
|         |                                                   |
|  3. open(path, O_PATH|O_CLOEXEC) -> parent_fd               |
|     syscall(445, ruleset_fd, RULE_PATH_BENEATH, &attr, 0)   |
|         |                                                   |
|  4. syscall(446, ruleset_fd, 0)                             |
|         v                                                   |
|  Process ambient rights restricted to allowed beneath paths |
+-------------------------------------------------------------+
```

### 2.2 Access Bitmasks & ABI Versions
- Filesystem Rights (ABI v1):
  - `LANDLOCK_ACCESS_FS_EXECUTE` (`1 << 0`)
  - `LANDLOCK_ACCESS_FS_WRITE_FILE` (`1 << 1`)
  - `LANDLOCK_ACCESS_FS_READ_FILE` (`1 << 2`)
  - `LANDLOCK_ACCESS_FS_READ_DIR` (`1 << 3`)
  - `LANDLOCK_ACCESS_FS_REMOVE_DIR` (`1 << 4`)
  - `LANDLOCK_ACCESS_FS_REMOVE_FILE` (`1 << 5`)
  - `LANDLOCK_ACCESS_FS_MAKE_CHAR` (`1 << 6`)
  - `LANDLOCK_ACCESS_FS_MAKE_DIR` (`1 << 7`)
  - `LANDLOCK_ACCESS_FS_MAKE_REG` (`1 << 8`)
  - `LANDLOCK_ACCESS_FS_MAKE_SOCK` (`1 << 9`)
  - `LANDLOCK_ACCESS_FS_MAKE_FIFO` (`1 << 10`)
  - `LANDLOCK_ACCESS_FS_MAKE_BLOCK` (`1 << 11`)
  - `LANDLOCK_ACCESS_FS_MAKE_SYM` (`1 << 12`)
- Extended Rights:
  - `LANDLOCK_ACCESS_FS_REFER` (`1 << 13`, ABI v2)
  - `LANDLOCK_ACCESS_FS_TRUNCATE` (`1 << 14`, ABI v3)
  - `LANDLOCK_ACCESS_FS_IOCTL_DEV` (`1 << 15`, ABI v5)

### 2.3 Ontos Audit Directives Compliance (DIR-ONT-01 & DIR-ONT-03)
- **`PR_SET_NO_NEW_PRIVS` Prerequisite**: In accordance with DIR-ONT-01, `prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)` (`38`) is unconditionally invoked prior to calling `SYS_landlock_restrict_self`. Without this, `SYS_landlock_restrict_self` returns `-EPERM`.
- **Pure Go Static Probe**: In accordance with DIR-ONT-03, `diagnostic/go/landlock-guard/main.go` uses standard library `syscall.Syscall6` with numeric constants (444, 445, 446, 38, 157) with zero external dependencies (`golang.org/x/sys/unix` is strictly avoided).

---

## 3. eBPF Security Tracing

### 3.1 Bounded Probe Execution & Threat Model
eBPF tracepoints provide read-only observability of kernel syscall dispatch. To guarantee that tracing scripts cannot cause kernel overhead or hang the execution plane, all scripts enforce:
1. Strict duration limits via bpftrace timer interval: `interval:s:{d} { exit(); }` where `1 <= d <= 30`.
2. Map aggregation: All metrics are collected in aggregated maps (e.g., `@[comm, args->ret] = count()`) rather than emitting unbounded stream events.
3. Privilege gating: bpftrace requires `CAP_BPF` / root (`sudo -n`). If running under `DIMINISHED` privilege, the tool fails soft returning `{"status": "DEGRADED", "capability_tier": "DIMINISHED"}` without raising exceptions.

### 3.2 Security Tracepoint Modes
- `security_open_denials`: Traces failed `sys_exit_openat` calls (`args->ret < 0`, e.g. `-EACCES`, `-EPERM`) grouped by executable name and error code.
- `security_landlock_audit`: Monitors invocations of `sys_enter_landlock_restrict_self` across the host.
- `security_exec_monitor`: Audits child binary executions (`sys_enter_execve`) by command name.

---

## 4. Volatile In-RAM Micro-Snapshots

### 4.1 Copy-on-Write Memory Architecture
Traditional database snapshots require file copying to disk, incurring 10-50ms latency depending on storage I/O and fsync barriers. For speculative subagent operations, speculative refactorings, or rapid unit testing, AEP provides volatile in-RAM micro-snapshots.

- Implementation: Uses SQLite Online Backup API (`src_conn.backup(mem_conn)`).
- Latency: < 2.0ms for typical databases (< 100MB).
- Persistence: Held in memory buffers (`:memory:` connection); non-polluting to disk.
- Restoration: `mem_conn.backup(dst_conn)` streams pages from RAM back into the active database without unlinking files.

---

## 5. Anti-Poisoning Zero-Trust Quarantine Engine

### 5.1 The Database Poisoning Threat Model
In an autonomous agent environment, a corrupted tool, hallucinated migration, or malicious payload could corrupt `artifacts.db`. If corrupted or poisoned databases are backed up automatically, corrupted files will rotate through the 5-slot FIFO pool, eventually overwriting all healthy historical snapshots (poisoning the pool).

### 5.2 Verification Pipeline
Before any backup is inserted into the 5-slot rotation pool or restored:
1. **Integrity Check**: Executes `PRAGMA quick_check` and `PRAGMA integrity_check`. Must return single row `"ok"`.
2. **Foreign Key Integrity**: Executes `PRAGMA foreign_key_check`. Must return 0 violations.
3. **Canary Verification**: Inspects table `_aep_canary`.
   - On fresh uninitialized databases, auto-seeds the canary record `aep_canary_v1_active` (DIR-ONT-05).
   - On existing databases, validates canary presence and token integrity.
4. **Schema Fingerprint**: Queries `sqlite_master` excluding temporary and canary objects, generating a deterministic SHA-256 hash. Any unauthorized schema tampering is flagged.

### 5.3 Quarantine Protocol
If any integrity check fails:
1. The 5-slot FIFO backup pool is **frozen** and left unmodified.
2. The problematic database is isolated into `~/.local/share/agent-os/backups/quarantine/artifacts.db.corrupt.<timestamp>`.
3. A forensic report is generated: `artifacts.db.corrupt.<timestamp>.forensic.json` containing:
   - Failure category (`INTEGRITY_CHECK_FAILED`, `FK_VIOLATION`, `CANARY_CORRUPTED`, `SCHEMA_MISMATCH`).
   - Diagnostic trace and SHA-256 hash.
   - Timestamp and isolation path.
4. A `DatabasePoisonError` is raised or returned in the typed JSON response.

---

## 6. FastMCP RPC & CLI Surface (DIR-ONT-02)

To maintain invariant FastMCP parity across all milestones:
- FastMCP tool count remains **strictly invariant at 15 tools**.
- New capabilities are exposed through existing unified dispatchers:
  - `aep_ctl(domain="security", action="landlock_status")`
  - `aep_ctl(domain="backup", action="verify_integrity")`
  - `aep_ctl(domain="backup", action="micro_snapshot")`
  - `aep_ctl(domain="backup", action="golden")`
  - `aep_ctl(domain="backup", action="restore_golden")`
  - `aep_ctl(domain="backup", action="quarantine_status")`
  - `kernel_trace(mode="security_open_denials"|"security_landlock_audit"|"security_exec_monitor")`

---

## 7. Zero Co-Dependency Invariant (DIR-ONT-07)

```
        server.py / aep-ctl
           /            \
          v              v
   engine/landlock.py   engine/backup.py
        (leaf)                 |
                               v
                         engine/db.py
                            (leaf)
```

- `engine/landlock.py` is a strict leaf module (depends only on ctypes/stdlib).
- `engine/db.py` is a strict leaf module (never imports `engine/backup.py`).
- `engine/backup.py` depends directionally on `engine/db.py` (A -> B).
- Total mutual co-dependencies: **0**.
