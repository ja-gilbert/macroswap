"""The real USDA table and the pinned model, shared by the data tier."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from macroswap.config import load_config
from macroswap.match.embed import Embedder, EmbedUnavailable
from macroswap.usda.load import load_release, merge
from macroswap.usda.table import Row, build_table

CONFIG = load_config()


@pytest.fixture(scope="session")
def real_rows(releases: dict[str, Path]) -> list[Row]:
    loaded = merge(
        load_release(releases["sr_legacy"], "sr"),
        load_release(releases["foundation"], "foundation"),
        CONFIG.usda.dry_basis_marker,
    )
    return build_table(loaded.foods, CONFIG.usda)


def _pinned_embedder(cache: Path) -> Embedder:
    """The pinned model, caching into cache. Without the extra, or offline
    without the model, the tests that load it skip, and in CI fail."""
    try:
        return Embedder(CONFIG.match.model, CONFIG.match.revision, cache)
    except EmbedUnavailable as exc:
        if os.environ.get("MACROSWAP_REQUIRE_DATA") == "1":
            pytest.fail(str(exc))
        pytest.skip(str(exc))


@pytest.fixture
def embedder(tmp_path: Path) -> Embedder:
    """A fresh cache per test, for the tests that time the index or read the
    cache back."""
    return _pinned_embedder(tmp_path)


@pytest.fixture(scope="session")
def cached_embedder(tmp_path_factory: pytest.TempPathFactory) -> Embedder:
    """One cache for the session, for tests that only need the rankings."""
    return _pinned_embedder(tmp_path_factory.mktemp("embed"))
