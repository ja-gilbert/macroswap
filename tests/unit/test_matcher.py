from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest

from macroswap.config import Config, load_config
from macroswap.match.matcher import Encoder, Matcher, fuse, index_text
from macroswap.usda.keys import FieldRules
from macroswap.usda.table import Row

CONFIG = load_config()
RULES = FieldRules(CONFIG.usda)


@pytest.fixture
def matcher(usda_rows: list[Row]) -> Matcher:
    return Matcher(usda_rows, CONFIG.match, RULES)


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        pytest.param("Egg, white, raw, fresh", "egg white", id="state-fields-dropped"),
        pytest.param(
            "Cereals, oats, regular and quick, unenriched, cooked with water "
            "(includes boiling and microwaving), without salt",
            "cereals oats regular and quick cooked with water "
            "(includes boiling and microwaving)",
            id="cosmetic-dropped-cooking-and-parenthetical-kept",
        ),
    ],
)
def test_index_text(description: str, expected: str) -> None:
    assert index_text(description, RULES) == expected


def test_a_leanness_family_row_indexes_without_its_level() -> None:
    """The level is applied through the family, so the words of the level do
    not lengthen the text and cost the row its rank."""
    description = "Beef, ground, 93% lean meat / 7% fat, raw"
    assert index_text(description, RULES, leanness=True) == "beef ground"


@pytest.mark.parametrize(
    ("text", "row_id", "key"),
    [
        pytest.param(
            "cooked rice",
            "sr:169753",
            "rice, white, long-grain, regular / cooked",
            id="cooking-field-reaches-the-cooked-row",
        ),
        pytest.param(
            "grilled chicken breast",
            "sr:171477",
            "chicken, breast, meat only / cooked",
            id="no-grilled-row-takes-the-family-cooked-row",
        ),
        pytest.param(
            "kirkland - chicken breast",
            "sr:171077",
            "chicken, breast, meat only / raw",
            id="cosmetic-and-state-fields-dropped-from-the-index",
        ),
        pytest.param(
            "ground beef 93/7",
            "sr:173110",
            "beef, ground, 93/7 / raw",
            id="level-through-the-family",
        ),
        pytest.param(
            "96/4 ground beef",
            "derived:beef, ground:96/4",
            "beef, ground, 96/4 / raw",
            id="derived-level-row",
        ),
        pytest.param(
            "96% lean ground turkey",
            "sr:172847",
            "turkey, ground",
            id="level-the-family-lacks-keys-at-the-family",
        ),
        pytest.param(
            "nonfat milk",
            "sr:171269",
            "milk, nonfat, fluid / raw",
            id="candidate-beats-its-duplicate-on-a-tie",
        ),
        pytest.param(
            "apple",
            "sr:167793",
            "apples, fuji, with skin / raw",
            id="equal-scores-keep-index-order",
        ),
    ],
)
def test_top_hit(matcher: Matcher, text: str, row_id: str, key: str) -> None:
    top = matcher.lexical(text)[0]
    assert (top.row.id, top.key) == (row_id, key)


def test_an_excluded_sr_row_still_beats_its_duplicate(usda_rows: list[Row]) -> None:
    """Between two excluded rows the analytical duplicate comes last, so the
    SR identity is what a label or a swap records."""
    rows = [
        replace(r, exclusion_reason="excluded-category") if r.id == "sr:171269" else r
        for r in usda_rows
    ]
    top = Matcher(rows, CONFIG.match, RULES).lexical("nonfat milk")[0]
    assert top.row.id == "sr:171269"


def test_length_normalization_comes_from_the_config(usda_rows: list[Row]) -> None:
    """A short index text scores higher at b 0.75 than at 0, where length
    counts for nothing, so a typed bm25_b moves the ranking it tunes."""
    scores = {
        b: Matcher(usda_rows, replace(CONFIG.match, bm25_b=b), RULES)
        .lexical("egg whites")[0]
        .score
        for b in (0.0, 0.75)
    }
    assert scores[0.0] < scores[0.75]


def test_a_name_without_a_level_keys_at_the_family(matcher: Matcher) -> None:
    """Level resolution waits for the next milestone, so the family is the identity;
    the family's other rows cannot fill the top five."""
    hits = matcher.lexical("ground beef")
    assert (hits[0].row.id, hits[0].key) == ("sr:168652", "beef, ground")
    assert len({h.key for h in hits}) == len(hits) == CONFIG.match.top_k


@pytest.mark.parametrize(
    ("text", "threshold"),
    [
        pytest.param("zzzz", -math.inf, id="nothing-scores"),
        pytest.param("egg whites", 100.0, id="top-score-below-threshold"),
    ],
)
def test_no_match(usda_rows: list[Row], text: str, threshold: float) -> None:
    config = replace(CONFIG.match, no_match={"lexical": threshold})
    assert Matcher(usda_rows, config, RULES).run(text, "lexical") is None


def test_embed_compares_the_text_normalized_like_the_index(
    usda_rows: list[Row], fake_embedder: Encoder, pinned_config: Config
) -> None:
    """A typed plural meets its row's index text exactly, so the cosine is 1;
    for embed and hybrid alike the level and a cooking word apply through the
    family as for lexical, and a text with no words abstains."""
    matcher = Matcher(usda_rows, pinned_config.match, RULES, fake_embedder)
    assert matcher.methods == ("lexical", "embed", "hybrid")
    hits = matcher.run("Egg Whites", "embed")
    assert hits is not None
    assert hits[0].row.id == "sr:172183"
    assert hits[0].score == pytest.approx(1.0)
    for method in ("embed", "hybrid"):
        level = matcher.run("ground beef 93/7", method)
        assert level is not None
        assert level[0].key == "beef, ground, 93/7 / raw"
        assert matcher.rank("grilled chicken breast", method)[0].row.id == "sr:171477"
        assert matcher.run("93/7", method) is None


def test_fusion_adds_each_methods_reciprocal_rank(
    usda_rows: list[Row], fake_embedder: Encoder
) -> None:
    """Ranks count from 1 over the rows a method scores, an equal score going to
    the row with the smaller lag, then to the index order; an unscored row
    gains nothing from that method. Rows sharing a key can fill a method's
    top_k, as the ground beef rows do, so each ranking is fused whole."""
    lexical = np.array([2.0, 0.0, 2.0, 5.0])  # ranks 3, -, 2, 1
    embed = np.array([0.3, 0.9, 0.0, 0.1])  # ranks 2, 1, -, 3
    lags = np.array([1, 0, 0, 0])
    assert fuse([lexical, embed], lags, 60).tolist() == pytest.approx(
        [1 / 63 + 1 / 62, 1 / 61, 1 / 62, 1 / 61 + 1 / 63]
    )
    matcher = Matcher(usda_rows, CONFIG.match, RULES, fake_embedder)
    assert len(matcher.rank("ground beef", "hybrid")) == CONFIG.match.top_k


@pytest.mark.parametrize(
    ("text", "lexical", "embed", "abstains"),
    [
        pytest.param("oats", 6.0, 1.1, True, id="below-both"),
        pytest.param("oats", 6.0, -math.inf, False, id="embed-alone-keeps-it"),
        pytest.param("oats", -math.inf, 1.1, False, id="lexical-alone-keeps-it"),
        pytest.param("zzzz", -math.inf, 0.9, True, id="unscored-counts-as-below"),
        pytest.param("potato red", 6.5, 0.7, True, id="top-row-by-the-tie-order"),
    ],
)
def test_hybrid_abstains_only_below_both_thresholds(
    usda_rows: list[Row],
    fake_embedder: Encoder,
    text: str,
    lexical: float,
    embed: float,
    abstains: bool,
) -> None:
    """A fused score is a function of ranks alone, so its top row is judged on
    each method's threshold, a row a method does not score being below it. For
    oats the plain oats row leads both methods, at 5.78 and 1.0 (the stand-in
    scores a text 1 against itself), so hybrid abstains only at cuts above
    both. That the row judged is the first by fused score and tie order, not
    each method's own top, rests on "potato red": red potatoes and the sweet
    potato fuse equal and red potatoes lead, so hybrid abstains at cuts above
    both of its scores."""
    config = replace(CONFIG.match, no_match={"lexical": lexical, "embed": embed})
    matcher = Matcher(usda_rows, config, RULES, fake_embedder)
    assert (matcher.run(text, "hybrid") is None) is abstains
