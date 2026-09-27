"""The unit tier runs offline: sentence-transformers is blocked as if the extra
were missing, and a deterministic stand-in plays the model."""

from __future__ import annotations

import math
import sys
import zlib
from collections.abc import Sequence
from dataclasses import replace

import numpy as np
import pytest
from numpy.typing import NDArray

from macroswap.config import Config, load_config


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)


class FakeEmbedder:
    """Each text's character trigrams hashed into 64 dimensions and scaled to
    unit length, so a text scores 1 against itself."""

    def encode(self, texts: Sequence[str]) -> NDArray[np.float32]:
        vectors = np.zeros((len(texts), 64), dtype=np.float32)
        for vector, text in zip(vectors, texts, strict=True):
            padded = f"  {text} "
            for i in range(len(padded) - 2):
                vector[zlib.crc32(padded[i : i + 3].encode()) % 64] += 1
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors

    def index_vectors(self, texts: Sequence[str]) -> NDArray[np.float32]:
        """Uncached: the stand-in costs nothing to run."""
        return self.encode(texts)


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def pinned_config(monkeypatch: pytest.MonkeyPatch) -> Config:
    """The packaged config with its tuned values pinned: lexical by default and
    no threshold, so no test changes when a tuned value does. The CLI loads it
    too."""
    config = load_config()
    match = replace(
        config.match,
        default_method="lexical",
        no_match={"lexical": -math.inf, "embed": -math.inf},
    )
    pinned = replace(config, match=match)
    monkeypatch.setattr("macroswap.cli.load_config", lambda path=None: pinned)
    return pinned
