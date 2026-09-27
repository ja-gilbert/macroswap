from __future__ import annotations

import os
import time
from dataclasses import replace
from pathlib import Path
from typing import BinaryIO

import numpy as np
import pytest
from numpy.typing import NDArray

from macroswap.config import load_config
from macroswap.match.embed import Embedder, EmbedUnavailable
from macroswap.match.matcher import Matcher
from macroswap.usda.keys import FieldRules
from macroswap.usda.load import load_release, merge
from macroswap.usda.table import Row, build_table

CONFIG = load_config()
RULES = FieldRules(CONFIG.usda)


@pytest.fixture(scope="module")
def real_rows(releases: dict[str, Path]) -> list[Row]:
    loaded = merge(
        load_release(releases["sr_legacy"], "sr"),
        load_release(releases["foundation"], "foundation"),
        CONFIG.usda.dry_basis_marker,
    )
    return build_table(loaded.foods, CONFIG.usda)


@pytest.fixture
def embedder(tmp_path: Path) -> Embedder:
    """The pinned model, caching into tmp_path. Without the extra, or offline
    without the model, the tests that load it skip, and in CI fail."""
    try:
        return Embedder(CONFIG.match.model, CONFIG.match.revision, tmp_path)
    except EmbedUnavailable as exc:
        if os.environ.get("MACROSWAP_REQUIRE_DATA") == "1":
            pytest.fail(str(exc))
        pytest.skip(str(exc))


@pytest.mark.parametrize(
    ("text", "before", "after"),
    [
        pytest.param("egg whites", "sr:172204", "sr:172183", id="raw-over-dried"),
        pytest.param("banana", "sr:173945", "sr:173944", id="raw-over-dehydrated"),
        pytest.param(
            "kirkland - chicken breast",
            "foundation:2759004",
            "foundation:2646170",
            id="raw-over-lunchmeat",
        ),
    ],
)
def test_dropping_state_and_cosmetic_fields_puts_the_raw_row_first(
    real_rows: list[Row], text: str, before: str, after: str
) -> None:
    """Measured 2026-09-26: with those fields in the index text, the dried,
    dehydrated or sliced row led."""
    kept = FieldRules(replace(CONFIG.usda, state_fields=(), cosmetic_patterns=()))
    assert Matcher(real_rows, CONFIG.match, kept).lexical(text)[0].row.id == before
    assert Matcher(real_rows, CONFIG.match, RULES).lexical(text)[0].row.id == after


# The index-text rule, measured 2026-09-26: the level is applied through the
# family, a level-less name keys at the family, and the grass-fed row no longer
# outranks every level row.
PROBES = {
    "ground-beef-anchor": (
        "ground beef 80/20",
        "sr:174036",
        "beef, ground, 80/20 / raw",
    ),
    "ground-beef-derived-level": (
        "ground beef 88/12",
        "derived:beef, ground:88/12",
        "beef, ground, 88/12 / raw",
    ),
    "leanness-after-the-comma": (
        "ground beef, 93 lean",
        "sr:173110",
        "beef, ground, 93/7 / raw",
    ),
    "leanness-in-the-brand": (
        "laura's lean 93/7 - ground beef",
        "sr:173110",
        "beef, ground, 93/7 / raw",
    ),
    "level-less-beef-keys-at-the-family": ("ground beef", "sr:168652", "beef, ground"),
    "level-less-turkey-keys-at-the-family": (
        "ground turkey",
        "sr:171505",
        "turkey, ground",
    ),
    "fat-free-turkey-is-99-1": (
        "kroger 99/1 ground turkey - 99%",
        "sr:172847",
        "turkey, ground, 99/1 / raw",
    ),
    "grass-fed-stays-its-own-family": (
        "grass-fed ground beef 85/15",
        "sr:168608",
        "beef, grass-fed, ground / raw",
    ),
    "pork-level": ("ground pork 96/4", "sr:169190", "pork, ground, 96/4 / raw"),
    "bison-has-no-levels": (
        "bison ground 90/10",
        "foundation:2727571",
        "bison, ground / raw",
    ),
}


@pytest.mark.parametrize(("text", "row_id", "key"), PROBES.values(), ids=PROBES.keys())
def test_probe_set_on_the_real_table(
    real_rows: list[Row], text: str, row_id: str, key: str
) -> None:
    top = Matcher(real_rows, CONFIG.match, RULES).lexical(text)[0]
    assert (top.row.id, top.key) == (row_id, key)


def test_a_cooking_word_reaches_a_cooked_row(real_rows: list[Row]) -> None:
    """Which cooked rice leads is a score tie the eval measures; the rule is
    that a cooked row in a rice family comes first."""
    top = Matcher(real_rows, CONFIG.match, RULES).lexical("cooked rice")[0]
    assert top.row.as_bought == "cooked"
    assert "rice" in top.row.family.replace(",", " ").split()


# The embed top on the real table: the raw row over the dried one, and the SR
# row over the analytical duplicate that shares its index text.
EMBED_PROBES = {"egg whites": "sr:172183", "lowfat milk 1%": "sr:170872"}


def test_the_pinned_model_embeds_the_real_index_within_its_budget(
    real_rows: list[Row], embedder: Embedder
) -> None:
    """The model loads in the fixture, so only the index is timed."""
    start = time.perf_counter()
    matcher = Matcher(real_rows, CONFIG.match, RULES, embedder)
    seconds = time.perf_counter() - start
    print(f"index embedded in {seconds:.1f} s")
    assert seconds < CONFIG.match.index_seconds
    tops = {text: matcher.embed(text)[0].row.id for text in EMBED_PROBES}
    assert tops == EMBED_PROBES


def test_index_vectors_are_reused_until_a_text_changes(
    embedder: Embedder,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The model, cached by the fixture, loads again without the first-use
    notice; the vectors are read back until a text changes."""
    Embedder(CONFIG.match.model, CONFIG.match.revision, tmp_path)
    assert "downloading" not in capsys.readouterr().err
    first = embedder.index_vectors(["egg white", "banana"])
    [cached] = tmp_path.glob("embeddings-*.npy")
    written = cached.stat().st_mtime_ns
    np.testing.assert_array_equal(
        embedder.index_vectors(["egg white", "banana"]), first
    )
    assert cached.stat().st_mtime_ns == written
    save = np.save

    def cut_short(file: BinaryIO, vectors: NDArray[np.float32]) -> None:
        save(file, vectors[:1])
        raise OSError("disk full")

    with monkeypatch.context() as patch, pytest.raises(OSError):
        patch.setattr(np, "save", cut_short)
        embedder.index_vectors(["egg white", "plantain"])
    assert not list(tmp_path.glob("embeddings-*.npy"))  # only the cut-short .part
    embedder.index_vectors(["egg white", "bananas"])
    [replaced] = tmp_path.glob("embeddings-*")
    assert replaced != cached


def test_first_use_offline_says_so_and_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No cached model and no network: the notice, then the error the CLI turns
    into exit 2, or into lexical alone by default."""
    constants = pytest.importorskip("huggingface_hub.constants")
    monkeypatch.setattr(constants, "HF_HUB_CACHE", str(tmp_path))
    monkeypatch.setattr(constants, "HF_HUB_OFFLINE", True)
    with pytest.raises(EmbedUnavailable, match="is not cached and did not download"):
        Embedder(CONFIG.match.model, CONFIG.match.revision, tmp_path)
    notice = f"downloading {CONFIG.match.model}@{CONFIG.match.revision[:7]} (first use)"
    assert notice in capsys.readouterr().err
