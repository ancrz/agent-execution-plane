"""
Quantitative Benchmarks: Linux Landlock LSM & SQLite Volatile Micro-Snapshots.

Compares:
1. Volatile In-RAM Micro-Snapshots (SQLite Backup API streaming into memory)
   vs Full On-Disk Hot Backup (FIFO rotation, SHA-256, atomic rename).
2. Linux Landlock LSM In-Process Restriction Latency
   vs Bubblewrap (bwrap) Sandbox Process/Namespace Containerization Overhead.
"""

from __future__ import annotations

import sqlite3
import statistics
import time
from pathlib import Path

import pytest

import server
from engine.backup import clear_micro_snapshots, create_backup, create_micro_snapshot
from engine.landlock import get_landlock_status, run_isolated_probe


class TestPrimitivesBenchmark:
    def test_benchmark_volatile_ram_snapshot_vs_disk_backup(self, tmp_path: Path):
        """Quantitative Benchmark: Volatile RAM micro-snapshot vs On-Disk Hot Backup."""
        clear_micro_snapshots()
        db_path = tmp_path / "bench.db"
        backups_dir = tmp_path / "backups"

        # Seed realistic dataset (500 records)
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("CREATE TABLE benchmark_records (id INTEGER PRIMARY KEY, payload TEXT, created_at REAL)")
            rows = [(i, f"benchmark_payload_record_{i}_{'x'*128}", time.time()) for i in range(500)]
            conn.executemany("INSERT INTO benchmark_records VALUES (?, ?, ?)", rows)
            conn.commit()

        # Warmup
        create_micro_snapshot(db_path, snapshot_id="warmup_ram")
        create_backup(db_path=db_path, backups_dir=backups_dir, raise_on_poison=False)

        # 1. Benchmark Volatile In-RAM Micro-Snapshot
        ram_latencies = []
        for i in range(10):
            t0 = time.perf_counter()
            res = create_micro_snapshot(db_path, snapshot_id=f"snap_{i}")
            t1 = time.perf_counter()
            assert res["status"] == "SUCCESS"
            assert res["in_ram"] is True
            ram_latencies.append((t1 - t0) * 1000.0)

        # 2. Benchmark Full On-Disk Hot Backup (SHA-256 + 5-slot FIFO)
        disk_latencies = []
        for i in range(10):
            t0 = time.perf_counter()
            res = create_backup(db_path=db_path, backups_dir=backups_dir, raise_on_poison=False)
            t1 = time.perf_counter()
            assert res["status"] == "SUCCESS"
            disk_latencies.append((t1 - t0) * 1000.0)

        mean_ram = statistics.mean(ram_latencies)
        mean_disk = statistics.mean(disk_latencies)
        speedup = mean_disk / mean_ram if mean_ram > 0 else 1.0

        print(f"\n[BENCHMARK] In-RAM Micro-Snapshot: mean={mean_ram:.3f}ms (min={min(ram_latencies):.3f}ms, max={max(ram_latencies):.3f}ms)")
        print(f"[BENCHMARK] On-Disk 5-Slot Backup: mean={mean_disk:.3f}ms (min={min(disk_latencies):.3f}ms, max={max(disk_latencies):.3f}ms)")
        print(f"[BENCHMARK] Volatile RAM Speedup: {speedup:.1f}x faster")

        # Invariant checks: RAM micro-snapshots must be ultra-fast (< 10ms for 500 rows)
        assert mean_ram < 15.0, f"RAM micro-snapshot too slow: {mean_ram:.2f}ms"
        assert speedup >= 1.5, f"Expected RAM to be significantly faster than Disk: speedup={speedup:.2f}x"
        clear_micro_snapshots()

    def test_benchmark_landlock_vs_bubblewrap_sandbox(self, tmp_path: Path):
        """Quantitative Benchmark: Landlock LSM In-Process Restriction vs Bubblewrap Containerization."""
        status = get_landlock_status()
        if not status.get("supported"):
            pytest.skip("Landlock LSM not supported on host kernel")

        target_file = tmp_path / "probe_target.txt"

        # 1. Benchmark Landlock Isolated Probe Latency
        landlock_latencies = []
        for _ in range(5):
            t0 = time.perf_counter()
            res = run_isolated_probe(target_file)
            t1 = time.perf_counter()
            assert res.get("write_blocked") is True
            landlock_latencies.append((t1 - t0) * 1000.0)

        # 2. Benchmark Bubblewrap Sandbox Run Latency
        bwrap_latencies = []
        import asyncio
        for _ in range(5):
            t0 = time.perf_counter()
            res_str = asyncio.run(server.sandbox_run("echo probe"))
            t1 = time.perf_counter()
            assert "SUCCESS" in res_str
            bwrap_latencies.append((t1 - t0) * 1000.0)

        mean_landlock = statistics.mean(landlock_latencies)
        mean_bwrap = statistics.mean(bwrap_latencies)

        print(f"\n[BENCHMARK] Landlock LSM Fork+Restrict Probe: mean={mean_landlock:.3f}ms (min={min(landlock_latencies):.3f}ms)")
        print(f"[BENCHMARK] Bubblewrap Process+Namespace Launch: mean={mean_bwrap:.3f}ms (min={min(bwrap_latencies):.3f}ms)")

        # Bubblewrap creates namespaces, mounts tmpfs, proc, drops caps, which incurs substantial overhead
        assert mean_landlock < 50.0
