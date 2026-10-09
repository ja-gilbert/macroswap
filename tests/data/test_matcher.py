from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path
from typing import BinaryIO

import numpy as np
import pytest
from numpy.typing import NDArray

from macroswap.config import load_config
from macroswap.match.embed import Embedder, EmbedUnavailable
from macroswap.match.evaluate import compare, evaluate, read_expected
from macroswap.match.label import Label, read_labels
from macroswap.match.matcher import Matcher
from macroswap.usda.keys import FieldRules
from macroswap.usda.table import Row

ROOT = Path(__file__).resolve().parents[2]
CONFIG = load_config()
RULES = FieldRules(CONFIG.usda)


@pytest.fixture(scope="module")
def made_labels() -> list[Label]:
    """The committed labels made so far. Until the first is made there is
    nothing to compare, so the comparison skips, in CI too."""
    path = ROOT / CONFIG.paths.labels
    labels = read_labels(path) if path.exists() else []
    made = [label for label in labels if label.label]
    if not made:
        pytest.skip(f"no labels made in {path}")
    return made


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
    # Measured 2026-09-27: a cooking word steers to the family's row in that
    # state, a level implies ground meat, "generic" is dropped, and an exact tie
    # goes to the row with the fewest first-field words missing from the text,
    # then to SR, then to the lower number; SR first is implied by the id ranges
    # today, every SR id below every Foundation id.
    "cooking-word-steers-to-the-cooked-row": (
        "cooked chicken breast",
        "sr:171078",
        "chicken, breast, meat only / cooked",
    ),
    "cooking-word-at-the-level": (
        "ground beef 93/7 cooked",
        "sr:174752",
        "beef, ground, 93/7, patty / cooked",
    ),
    "cooked-row-at-the-level-is-its-plain-row": (
        "ground turkey 93/7 cooked",
        "sr:172851",
        "turkey, ground, 93/7 / cooked",
    ),
    "level-implies-ground": (
        "beef - 88/12",
        "derived:beef, ground:88/12",
        "beef, ground, 88/12 / raw",
    ),
    "generic-is-dropped": ("generic - banana", "sr:173944", "bananas / raw"),
    "tie-to-the-first-field-the-text-holds": (
        "potatoes",
        "sr:170032",
        "potatoes, skin / raw",
    ),
    "tie-to-fewer-first-field-words-missing": (
        "salmon",
        "sr:173688",
        "fish, salmon, chinook / raw",
    ),
    "cooked-row-of-the-tie-winner": (
        "salmon cooked",
        "sr:171999",
        "fish, salmon, chinook, dry heat / cooked",
    ),
    "almonds-over-almond-flour-on-a-tie": (
        "almonds",
        "sr:170567",
        "nuts, almonds / raw",
    ),
    "tie-to-the-lower-number-not-the-string": (
        "olive oil",
        "foundation:748608",
        "oil, olive, extra virgin / raw",
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


# The embed top on the real table: the raw row over the dried one, the SR row
# over the analytical duplicate that shares its index text, and a raw chicken
# breast standing for its family's cooked row that holds the cooking word, not
# the fried row ahead of it. Lexical scores the grilled row first itself, and a
# chicken-breast roll over the family for "roasted".
EMBED_PROBES = {
    "egg whites": "sr:172183",
    "lowfat milk 1%": "sr:170872",
    "grilled chicken breast": "sr:171534",
    "roasted chicken breast": "sr:171477",
}


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
    notice; the vectors are read back until a text changes, and a changed
    text's file goes beside the old one, which stays readable."""
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
    assert list(tmp_path.glob("embeddings-*.npy")) == [cached]
    embedder.index_vectors(["egg white", "bananas"])
    assert len(list(tmp_path.glob("embeddings-*.npy"))) == 2
    assert cached.stat().st_mtime_ns == written


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


def test_the_test_split_scores_as_the_committed_table_says(
    made_labels: list[Label], real_rows: list[Row], embedder: Embedder
) -> None:
    """Lexical exactly; embed and hybrid within tolerated_flips names per cell,
    the float noise between CPU and GPU. The dev split is never gated."""
    matcher = Matcher(real_rows, CONFIG.match, RULES, embedder)
    test = [label for label in made_labels if label.split == "test"]
    cells = evaluate(matcher, real_rows, test, CONFIG.eval, matcher.methods)
    expected = read_expected(ROOT / CONFIG.paths.eval_expected)
    assert compare(cells, expected, CONFIG.eval.tolerated_flips) == []
