"""ONT-67 T7: sandbox outputs persisted in tmpfs are zstd-compressed, paged transparently, TTL/cap intact."""

from __future__ import annotations

import time
from pathlib import Path

import server


def _ref(req: str) -> Path:
    return server._sandbox_out_dir() / f"sandbox_{req}.out"


def test_large_output_is_stored_as_zstd_and_smaller() -> None:
    text = "\n".join(f"line {i} of the build log" for i in range(20000))
    ref = server._sandbox_out_persist("req_00000000a1", text, "")
    assert ref is not None
    raw = Path(ref).read_bytes()
    assert raw[:4] == server._ZSTD_MAGIC
    assert len(raw) < len(text.encode()) / 4
    assert server._sandbox_out_read(Path(ref)) == text


def test_paging_over_compressed_file_is_transparent() -> None:
    text = "\n".join(f"row-{i}" for i in range(5000))
    ref = server._sandbox_out_persist("req_00000000a2", text, "")
    page = server._sandbox_out_page(ref, 0, 10)
    assert page["status"] == "OK" and page["total_lines"] == 5000
    assert page["output"].splitlines() == [f"row-{i}" for i in range(10)]
    assert page["truncated"] is True and page["cursor"] == "10"
    last = server._sandbox_out_page(ref, 4995, 50)
    assert last["truncated"] is False and last["cursor"] is None
    assert last["output"].splitlines()[-1] == "row-4999"


def test_small_output_and_legacy_plain_files_stay_readable() -> None:
    ref = server._sandbox_out_persist("req_00000000a3", "tiny\n", "")
    assert Path(ref).read_bytes().startswith(b"tiny")
    legacy = _ref("req_00000000a4")
    legacy.write_text("old\nplain\nfile\n" * 1000, encoding="utf-8")
    page = server._sandbox_out_page(str(legacy), 0, 3)
    assert page["status"] == "OK" and page["output"].splitlines() == ["old", "plain", "file"]


def test_stderr_is_kept_after_separator_when_compressed() -> None:
    ref = server._sandbox_out_persist("req_00000000a5", "o\n" * 4000, "boom")
    text = server._sandbox_out_read(Path(ref))
    assert text.endswith("--- stderr ---\nboom")


def test_corrupt_zstd_file_is_a_param_error() -> None:
    bad = _ref("req_00000000a6")
    bad.write_bytes(server._ZSTD_MAGIC + b"not-a-frame")
    page = server._sandbox_out_page(str(bad), 0, 5)
    assert page["status"] == "PARAM_ERROR" and "ilegible" in page["error"]


def test_ttl_and_cap_still_apply_to_compressed_files() -> None:
    d = server._sandbox_out_dir()
    ref = Path(server._sandbox_out_persist("req_00000000a7", "z\n" * 4000, ""))
    server._sandbox_out_reap(d, now=time.time() + server._SANDBOX_OUT_TTL_SEC + 5)
    assert not ref.exists()
