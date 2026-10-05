"""The unit tier runs offline: sentence-transformers is blocked as if the extra
were missing, and a deterministic stand-in plays the model."""

from __future__ import annotations

import math
import struct
import sys
import zlib
from collections.abc import Callable, Sequence
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


def _record(text: str) -> bytes:
    return text.ljust(80).encode("ascii")


def _padded(data: bytes) -> bytes:
    return data + b" " * (-len(data) % 80)


def _transport(columns: list[str], rows: list[str]) -> bytes:
    """A transport file of 8-byte numeric columns; a row is its values' bytes
    in hex."""
    namestrs = b"".join(
        struct.pack(">hhhh8s68xl52x", 1, 0, 8, k + 1, name.ljust(8).encode(), 8 * k)
        for k, name in enumerate(columns)
    )
    return (
        _record(f"HEADER RECORD*******NAMESTR HEADER RECORD!!!!!!!{len(columns):010d}")
        + _padded(namestrs)
        + _record("HEADER RECORD*******OBS     HEADER RECORD!!!!!!!")
        + _padded(bytes.fromhex("".join(rows)))
    )


@pytest.fixture
def transport() -> Callable[[list[str], list[str]], bytes]:
    return _transport


@pytest.fixture
def pinned_config(monkeypatch: pytest.MonkeyPatch) -> Config:
    """The packaged config with its tuned values pinned: lexical by default and
    no threshold, so no test changes when a tuned value does; and the cycle, and
    count_as pinned to one line the fixture table fits. The CLI loads it too."""
    config = load_config()
    match = replace(
        config.match,
        default_method="lexical",
        no_match={"lexical": -math.inf, "embed": -math.inf},
    )
    popularity = replace(
        config.popularity,
        cycle="2021-2023",
        count_as={"sweet potato, flesh": "sweet potato"},
    )
    pinned = replace(config, match=match, popularity=popularity)
    monkeypatch.setattr("macroswap.cli.load_config", lambda path=None: pinned)
    return pinned
