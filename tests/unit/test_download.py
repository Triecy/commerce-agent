"""FR-D1: downloads are checksum-verified, idempotent and never leave partial files."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Any

import pytest

from commerce_agent.data import download
from commerce_agent.data.download import ChecksumMismatchError, Source, fetch

PAYLOAD = b"user_id,parent_asin,rating,timestamp\n"
SHA = hashlib.sha256(PAYLOAD).hexdigest()


class _FakeUrlopen:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, request: Any, timeout: float) -> io.BytesIO:
        self.calls.append(timeout)
        return io.BytesIO(PAYLOAD)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> _FakeUrlopen:
    f = _FakeUrlopen()
    monkeypatch.setattr(download.urllib.request, "urlopen", f)
    return f


def test_FR_D1_fetch_verifies_and_is_idempotent(fake: _FakeUrlopen, tmp_path: Path) -> None:
    src = Source("x", "https://example.invalid/x.csv.gz", SHA)
    first = fetch(src, tmp_path, timeout_s=5)
    second = fetch(src, tmp_path, timeout_s=5)
    assert first == second and first.read_bytes() == PAYLOAD
    assert fake.calls == [5]  # second call skipped the network; timeout always passed


def test_FR_D1_checksum_mismatch_leaves_no_file(fake: _FakeUrlopen, tmp_path: Path) -> None:
    src = Source("x", "https://example.invalid/x.csv.gz", "0" * 64)
    with pytest.raises(ChecksumMismatchError):
        fetch(src, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_FR_D1_rejects_non_https(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        fetch(Source("x", "http://example.invalid/x", None), tmp_path)
