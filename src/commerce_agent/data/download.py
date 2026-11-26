"""Checksum-verified, idempotent dataset downloads (FR-D1, SPEC §5.4).

Every network call has an enforced timeout (CLAUDE.md §7.3). A file that already
exists with the expected checksum is not downloaded again, so ``make data`` is
idempotent. Downloads go to a temporary file first and are renamed only after the
checksum matches, so an interrupted run never leaves a half-written file behind.
"""

from __future__ import annotations

import hashlib
import logging
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_CHUNK = 1 << 20


class ChecksumMismatchError(RuntimeError):
    """The downloaded bytes do not match the pinned SHA-256."""


@dataclass(frozen=True, slots=True)
class Source:
    """A pinned remote file. ``sha256=None`` means "not pinned yet" (profiling only)."""

    name: str
    url: str
    sha256: str | None
    size_bytes: int | None = None


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(source: Source, dest_dir: Path, *, timeout_s: float = 60.0) -> Path:
    """Download ``source`` into ``dest_dir`` unless a verified copy already exists.

    ``timeout_s`` bounds every socket operation (connect and each read).
    Raises :class:`ChecksumMismatchError` if a pinned checksum does not match.
    """
    if not source.url.startswith("https://"):
        raise ValueError(f"only https sources are allowed: {source.url}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / source.url.rsplit("/", 1)[-1]

    if dest.exists() and source.sha256 is not None and sha256_of(dest) == source.sha256:
        logger.info("download skipped (verified copy exists)", extra={"file": str(dest)})
        return dest

    tmp = dest.with_suffix(dest.suffix + ".part")
    digest = hashlib.sha256()
    logger.info("downloading", extra={"url": source.url})
    request = urllib.request.Request(source.url, headers={"User-Agent": "commerce-agent-data"})  # noqa: S310 (https enforced above)
    with urllib.request.urlopen(request, timeout=timeout_s) as response, tmp.open("wb") as out:  # noqa: S310
        for chunk in iter(lambda: response.read(_CHUNK), b""):
            digest.update(chunk)
            out.write(chunk)

    actual = digest.hexdigest()
    if source.sha256 is not None and actual != source.sha256:
        tmp.unlink(missing_ok=True)
        raise ChecksumMismatchError(f"{source.name}: expected {source.sha256}, got {actual}")
    os.replace(tmp, dest)
    return dest
