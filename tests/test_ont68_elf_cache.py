"""ONT-68 T1: artifact_execute_in_ram honours the on-disk ELF cache only when it is a real ELF whose sha256
matches the catalog; otherwise it falls back to the catalog blob and rewrites the cache."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

import server
from engine.catalog import ArtifactCatalog

ELF = b"\x7fELF" + b"\x02\x01\x01" + b"\x00" * 64  # not runnable; exec is stubbed
OTHER_ELF = b"\x7fELF" + b"\x02\x01\x01" + b"\xff" * 64


class _Catalog:
    """Minimal catalog double: records get_binary_blob calls."""

    def __init__(self, blobs: dict[str, bytes], hashes: dict[str, str] | None = None) -> None:
        self.blobs = blobs
        self.hashes = hashes if hashes is not None else {n: hashlib.sha256(b).hexdigest() for n, b in blobs.items()}
        self.blob_calls: list[str] = []

    def get_binary_blob(self, name: str) -> bytes | None:
        self.blob_calls.append(name)
        return self.blobs.get(name)

    def get_binary_hash(self, name: str) -> str | None:
        return self.hashes.get(name)

    def __getattr__(self, item: str):  # any other catalog call used by the tool is a harmless no-op
        return lambda *a, **k: None


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setattr(server, "TEMP_BIN_DIR", bin_dir)
    monkeypatch.setenv("AEP_FORCE_TIER", "6rw-")
    seen: list[bytes] = []

    def fake_memfd(label: str, data: bytes) -> int:
        seen.append(data)
        raise OSError("stop before exec")  # abort after resolution; resolved bytes are captured

    monkeypatch.setattr(server._memfd, "create_sealed_exec_memfd", fake_memfd)
    return bin_dir, seen


def _run(name: str) -> dict:
    return json.loads(asyncio.run(server.artifact_execute_in_ram(name=name, verbosity="detail")))


def test_elf_helper_uses_real_magic() -> None:
    assert server._is_elf(ELF) and not server._is_elf(b"ELF" + b"\x00" * 8) and not server._is_elf(b"")


def test_valid_disk_elf_used_without_blob_lookup(env, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir, seen = env
    cat = _Catalog({"probe": ELF})
    monkeypatch.setattr(server, "catalog", cat)
    (bin_dir / "probe").write_bytes(ELF)
    _run("probe")
    assert seen == [ELF] and cat.blob_calls == []


def test_disk_elf_without_catalog_entry_is_used(env, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir, seen = env
    monkeypatch.setattr(server, "catalog", _Catalog({}))
    (bin_dir / "orphan").write_bytes(ELF)
    _run("orphan")
    assert seen == [ELF]


def test_non_elf_disk_file_falls_back_to_blob_and_rewrites(env, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir, seen = env
    cat = _Catalog({"probe": ELF})
    monkeypatch.setattr(server, "catalog", cat)
    (bin_dir / "probe").write_bytes(b"#!/bin/sh\necho pwned\n")
    _run("probe")
    assert seen == [ELF] and cat.blob_calls == ["probe"]
    assert (bin_dir / "probe").read_bytes() == ELF


def test_hash_mismatched_elf_falls_back_to_blob_and_cache_rewritten(env, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir, seen = env
    cat = _Catalog({"probe": ELF})
    monkeypatch.setattr(server, "catalog", cat)
    (bin_dir / "probe").write_bytes(OTHER_ELF)  # real ELF magic, but not what the catalog registered
    _run("probe")
    assert seen == [ELF] and cat.blob_calls == ["probe"]
    assert (bin_dir / "probe").read_bytes() == ELF


def test_alt_name_valid_disk_elf_used(env, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir, seen = env
    cat = _Catalog({"mem_stat": ELF})
    monkeypatch.setattr(server, "catalog", cat)
    (bin_dir / "mem_stat").write_bytes(ELF)
    _run("mem-stat")
    assert seen == [ELF] and cat.blob_calls == ["mem-stat"]  # primary blob lookup misses; alt hits the disk cache


def test_alt_name_hash_mismatch_falls_back_to_alt_blob(env, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir, seen = env
    cat = _Catalog({"mem_stat": ELF})
    monkeypatch.setattr(server, "catalog", cat)
    (bin_dir / "mem_stat").write_bytes(OTHER_ELF)
    _run("mem-stat")
    assert seen == [ELF] and cat.blob_calls == ["mem-stat", "mem_stat"]
    assert (bin_dir / "mem_stat").read_bytes() == ELF


def test_real_catalog_hash_accessor(tmp_path: Path) -> None:
    cat = ArtifactCatalog(db_path=tmp_path / "c.db")
    assert cat.get_binary_hash("nope") is None
