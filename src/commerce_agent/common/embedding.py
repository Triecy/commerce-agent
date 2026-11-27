"""Local text embeddings with an on-disk cache (SPEC §4.4).

The default model is ``BAAI/bge-small-en-v1.5`` (MIT license, 384 dimensions), pinned
to a Hugging Face revision and run on CPU so that re-runs give the same vectors. The
heavy dependencies (``sentence-transformers``, ``torch``) live in the optional ``ml``
dependency group and are imported lazily; unit tests and CI use :class:`HashingEncoder`.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt

logger = logging.getLogger(__name__)

# Verified on 2026-11-25 via the Hugging Face API: license "mit", hidden_size 384,
# max_position_embeddings 512. Pinning the revision keeps vectors reproducible.
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
DEFAULT_DIM = 384

FloatMatrix = npt.NDArray[np.float32]


class TextEncoder(Protocol):
    """Maps texts to L2-normalized float32 vectors of shape ``(len(texts), dim)``."""

    @property
    def identity(self) -> str:
        """A string that changes whenever the vectors could change (model, revision...)."""
        ...

    @property
    def dim(self) -> int: ...

    def encode(self, texts: Sequence[str]) -> FloatMatrix: ...


def _normalize(vectors: npt.NDArray[Any]) -> FloatMatrix:
    vectors = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    out: FloatMatrix = (vectors / norms).astype(np.float32)
    return out


@dataclass(frozen=True, slots=True)
class SentenceTransformerEncoder:
    """``sentence-transformers`` model on CPU; needs ``uv sync --group ml``."""

    model_name: str = DEFAULT_MODEL
    revision: str = DEFAULT_REVISION
    max_seq_length: int = 256
    batch_size: int = 64
    device: str = "cpu"

    @property
    def identity(self) -> str:
        return f"{self.model_name}@{self.revision}:seq{self.max_seq_length}"

    @property
    def dim(self) -> int:
        return DEFAULT_DIM if self.model_name == DEFAULT_MODEL else -1

    def encode(self, texts: Sequence[str]) -> FloatMatrix:
        try:
            module = importlib.import_module("sentence_transformers")
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise RuntimeError(
                "sentence-transformers is not installed; run `uv sync --group ml`"
            ) from exc
        model = module.SentenceTransformer(
            self.model_name, revision=self.revision, device=self.device
        )
        model.max_seq_length = self.max_seq_length
        vectors = model.encode(
            list(texts),
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return _normalize(vectors)


@dataclass(frozen=True, slots=True)
class HashingEncoder:
    """Deterministic bag-of-words hashing encoder for tests; no model download."""

    dim_: int = 64

    @property
    def identity(self) -> str:
        return f"hashing:{self.dim_}"

    @property
    def dim(self) -> int:
        return self.dim_

    def encode(self, texts: Sequence[str]) -> FloatMatrix:
        out = np.zeros((len(texts), self.dim_), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in text.lower().split():
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                out[row, int.from_bytes(digest[:4], "little") % self.dim_] += 1.0
        return _normalize(out)


def texts_fingerprint(texts: Sequence[str]) -> str:
    """SHA-256 over the texts in order; part of the cache key."""
    digest = hashlib.sha256()
    for text in texts:
        digest.update(text.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def cached_encode(encoder: TextEncoder, texts: Sequence[str], cache_dir: Path) -> FloatMatrix:
    """Encode ``texts`` once and reuse the ``.npy`` file while model and texts are unchanged."""
    key = hashlib.sha256(f"{encoder.identity}|{texts_fingerprint(texts)}".encode()).hexdigest()
    path = cache_dir / f"{key[:24]}.npy"
    meta_path = path.with_suffix(".json")
    if path.exists():
        vectors: FloatMatrix = np.load(path)
        if vectors.shape[0] == len(texts):
            logger.info("embedding cache hit", extra={"path": str(path)})
            return vectors
    logger.info("encoding texts", extra={"n": len(texts), "encoder": encoder.identity})
    vectors = encoder.encode(texts)
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.npy")
    np.save(tmp, vectors)
    tmp.replace(path)
    meta_path.write_text(
        json.dumps({"encoder": encoder.identity, "n": len(texts), "dim": int(vectors.shape[1])})
    )
    return vectors
