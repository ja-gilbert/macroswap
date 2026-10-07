from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import pytest

from macroswap.config import load_config
from macroswap.match.diary import LabelError
from macroswap.match.evaluate import (
    Cell,
    compare,
    compare_methods,
    evaluate,
    read_expected,
    render_readme,
    score,
    tune_threshold,
    write_expected,
)
from macroswap.match.label import NO_MATCH, Label
from macroswap.match.matcher import Encoder, Matcher
from macroswap.usda.keys import FieldRules
from macroswap.usda.table import Row

CONFIG = load_config()
RULES = FieldRules(CONFIG.usda)
# Between the fixture's top scores, so some names abstain; lexical, whatever
# the packaged default.
TUNED = replace(
    CONFIG.match,
    default_method="lexical",
    no_match={"lexical": 5.0, "embed": -math.inf},
)

# Each name's lexical top score on the fixture table, and its top hit.
LABELS = [
    # 9.50, the raw egg white.
    Label("egg whites", 4, "head", "dev", "sr:172183", "suggestion"),
    # 6.14, Bananas, raw: the Foundation row labeled has its key, not its id.
    Label("banana", 3, "head", "dev", "foundation:790991", "search"),
    # 6.41, the 70/30 row, which keys at the family.
    Label("ground beef", 2, "head", "dev", "beef, ground", "suggestion"),
    # 6.37, the raw breast; the roasted one labeled is fourth.
    Label("chicken breast", 2, "head", "dev", "sr:171477", "search"),
    # 3.93, ground chicken.
    Label("chipotle - chicken bowl", 1, "head", "dev", NO_MATCH, "no_match"),
    # Nothing scores.
    Label("zzzz", 1, "head", "dev", NO_MATCH, "no_match"),
    # Not labeled yet, so in no cell.
    Label("cooked rice", 1, "head", "dev", "", ""),
    # 9.01, the raw sweet potato.
    Label("sweet potatoes", 1, "tail", "dev", "sr:168482", "suggestion"),
    # 4.00, raw rice; the cooked row labeled is second.
    Label("great value - jasmine rice", 1, "tail", "dev", "sr:169753", "search"),
    # Test, so in no dev cell.
    Label("nonfat milk", 2, "head", "test", "foundation:322559", "search"),
    # 6.41, the 93/7 row, which keys at that level.
    Label("ground beef 93/7", 1, "tail", "test", "sr:173110", "suggestion"),
    # 4.45, abstaining on the very row labeled.
    Label("salmon", 1, "tail", "test", "sr:175167", "search"),
    # 9.01, the raw sweet potato: the second id labeled, so not the exact one.
    Label(
        "sweet potato", 1, "tail", "test", "foundation:2346404 sr:168482", "suggestion"
    ),
]

# Lexical at 5.0 on the dev head by hand, (n, value, one_flip) per name and
# per row. Rows: egg whites 4, banana 3, ground beef 2, chicken breast 2,
# chipotle 1, zzzz 1. Chipotle and zzzz abstain.
DEV_HEAD = {
    # Ranking leaves out the two NO_MATCH labels; breast is wrong.
    ("top1_ranking", "names"): (4, 3 / 4, 1 / 4),
    ("top1_ranking", "rows"): (4, 9 / 11, 4 / 11),
    # Breast wrong; chipotle right, abstaining.
    ("top1_end_to_end", "names"): (6, 5 / 6, 1 / 6),
    ("top1_end_to_end", "rows"): (6, 11 / 13, 4 / 13),
    ("top5_ranking", "names"): (4, 4 / 4, 1 / 4),
    ("top5_ranking", "rows"): (4, 11 / 11, 4 / 11),
    ("top5_end_to_end", "names"): (6, 6 / 6, 1 / 6),
    ("top5_end_to_end", "rows"): (6, 13 / 13, 4 / 13),
    # Both abstaining names are labeled NO_MATCH.
    ("no_match_precision", "names"): (2, 2 / 2, 1 / 2),
    ("no_match_precision", "rows"): (2, 2 / 2, 1 / 2),
    ("no_match_recall", "names"): (2, 2 / 2, 1 / 2),
    ("no_match_recall", "rows"): (2, 2 / 2, 1 / 2),
    # Of the three row labels, egg whites alone has its top hit's id.
    ("exact_id", "names"): (3, 1 / 3, 1 / 3),
    ("exact_id", "rows"): (3, 4 / 9, 4 / 9),
}


@pytest.fixture
def matcher(usda_rows: list[Row]) -> Matcher:
    return Matcher(usda_rows, TUNED, RULES)


def test_each_cell_rule(matcher: Matcher, usda_rows: list[Row]) -> None:
    """The dev head by hand; on the test tail a row label keys at the name's
    level, exact_id reads the ranked list whatever the threshold, salmon
    abstaining on its labeled row is a wrong abstention, and the sweet potato is
    right at its label's second id while exact_id reads only the first."""
    cells = evaluate(matcher, usda_rows, LABELS, CONFIG.eval, ("lexical",))
    dev_head = {
        (c.metric, c.weighting): (c.n, c.value, c.one_flip)
        for c in cells
        if (c.split, c.bucket) == ("dev", "head")
    }
    assert dev_head == DEV_HEAD
    test_tail = {
        c.metric: c.value
        for c in cells
        if (c.split, c.bucket, c.weighting) == ("test", "tail", "names")
    }
    metrics = ("top1_ranking", "top1_end_to_end", "exact_id", "no_match_precision")
    assert [test_tail[metric] for metric in metrics] == [1.0, 2 / 3, 2 / 3, 0.0]


def test_intervals_resample_names_and_skip_draws_a_metric_cannot_score(
    matcher: Matcher, usda_rows: list[Row]
) -> None:
    cells = evaluate(matcher, usda_rows, LABELS, CONFIG.eval, ("lexical",))
    interval = {
        (c.bucket, c.weighting, c.metric): (c.low, c.high)
        for c in cells
        if c.split == "dev"
    }
    # Both NO_MATCH labels abstain; a draw holding neither scores nothing.
    assert interval["head", "names", "no_match_recall"] == (1.0, 1.0)
    # Three of four right: 1.5% of draws score under a quarter and 3.4% at most
    # a quarter, so the 2.5% quantile is a quarter.
    assert interval["head", "names", "top1_ranking"] == (0.25, 1.0)
    # By rows, 4, 3 and 2 right and 2 wrong: 2.1% of draws score under a third
    # and 3.9% at most a third, so the 2.5% quantile is a third.
    assert interval["head", "rows", "top1_ranking"] == (1 / 3, 1.0)


def test_every_method_is_scored_on_the_same_draws(
    usda_rows: list[Row], fake_embedder: Encoder
) -> None:
    """Draws are made once per split and bucket, so a method's interval does
    not depend on which methods ran before it."""
    matcher = Matcher(usda_rows, TUNED, RULES, fake_embedder)
    both = evaluate(matcher, usda_rows, LABELS, CONFIG.eval, ("lexical", "embed"))
    alone = evaluate(matcher, usda_rows, LABELS, CONFIG.eval, ("embed",))
    assert [c for c in both if c.method == "embed"] == alone


@pytest.mark.parametrize(
    "orphan",
    [
        pytest.param(
            Label("egg whites", 4, "head", "dev", "sr:1", "search"), id="an-unknown-id"
        ),
        pytest.param(
            Label("banana", 3, "head", "dev", "bananas", "search"),
            id="a-family-without-leanness",
        ),
        pytest.param(
            Label("sweet potato", 1, "tail", "test", "sr:168482 sr:1", "search"),
            id="a-second-id-naming-nothing",
        ),
    ],
)
def test_a_label_naming_no_row_and_no_leanness_family_is_refused(
    matcher: Matcher, usda_rows: list[Row], orphan: Label
) -> None:
    with pytest.raises(LabelError, match=f"{orphan.name} = {orphan.label}"):
        evaluate(matcher, usda_rows, [orphan], CONFIG.eval, ("lexical",))


def test_the_dev_objective_at_the_threshold_and_at_the_dev_optimal_cut(
    usda_rows: list[Row], fake_embedder: Encoder
) -> None:
    """Over the whole dev split, lexical and embed each on its own scores and
    threshold, hybrid at both. At 7.0 banana abstains too, which ranking alone
    would count right. The cut between chipotle and the jasmine rice ties with
    the one past the rice, whose top hit is wrong anyway, and the lower wins.
    Hybrid gets no dev-optimal line. When every top hit is right, as for egg
    whites and banana, never abstaining wins."""
    config = replace(TUNED, no_match={"lexical": 7.0, "embed": 0.74})
    matcher = Matcher(usda_rows, config, RULES, fake_embedder)
    lines = compare_methods(matcher, usda_rows, LABELS)
    assert lines.splitlines() == [
        "method lexical: 4 of 8 dev names right end to end at its threshold",
        "method embed: 6 of 8 dev names right end to end at its threshold",
        "method hybrid: 6 of 8 dev names right end to end at both thresholds",
        "lexical = 4.0734791321050805  # dev-optimal: 6 of 8 right; "
        "2 dev names labeled NO_MATCH",
        "embed = 0.7400474846363068  # dev-optimal: 6 of 8 right; "
        "2 dev names labeled NO_MATCH",
    ]
    right_at_the_top = score(matcher, usda_rows, LABELS[:2], "lexical")
    assert tune_threshold(right_at_the_top) == -math.inf


LEXICAL = Cell(
    "lexical",
    "test",
    "head",
    "names",
    "top1_ranking",
    220,
    137 / 220,
    0.56,
    0.69,
    1 / 220,
)
EMBED = replace(LEXICAL, method="embed")
# Seven right abstentions logged once each; then an eighth, wrong and logged
# twice, so n moves by one and the value by that name's share, 2 / 9.
PRECISION = replace(
    EMBED, weighting="rows", metric="no_match_precision", n=7, value=1.0, one_flip=1 / 7
)
MOVED = replace(PRECISION, n=8, value=7 / 9, one_flip=2 / 9)
# A cell of one wrong abstention, which one flip makes or drops.
LONE = replace(PRECISION, n=1, value=0.0, one_flip=1.0)


@pytest.mark.parametrize(
    ("expected", "actual", "says"),
    [
        pytest.param(
            LEXICAL,
            replace(LEXICAL, value=138 / 220),
            "expected",
            id="lexical-is-exact",
        ),
        pytest.param(
            EMBED, replace(EMBED, value=138 / 220), "", id="embed-allows-one-flip"
        ),
        pytest.param(
            EMBED, replace(EMBED, value=139 / 220), "expected", id="embed-not-two"
        ),
        pytest.param(EMBED, replace(EMBED, n=221), "expected", id="n-must-match"),
        pytest.param(PRECISION, MOVED, "", id="an-embed-abstention-may-flip"),
        pytest.param(
            replace(PRECISION, method="lexical"),
            replace(MOVED, method="lexical"),
            "expected",
            id="a-lexical-abstention-may-not",
        ),
        pytest.param(None, LONE, "", id="a-first-embed-abstention"),
        pytest.param(LONE, None, "", id="a-last-embed-abstention"),
        pytest.param(EMBED, None, "no longer made", id="a-cell-no-longer-made"),
        pytest.param(None, EMBED, "not in the table", id="a-cell-not-in-the-table"),
    ],
)
def test_compare_with_the_committed_table(
    tmp_path: Path, expected: Cell | None, actual: Cell | None, says: str
) -> None:
    path = tmp_path / "eval_expected.csv"
    write_expected(path, [expected] if expected else [])
    tolerated = CONFIG.eval.tolerated_flips
    found = compare([actual] if actual else [], read_expected(path), tolerated)
    assert (len(found) == 1 and says in found[0]) if says else found == []


def test_the_readme_block_is_rendered_in_place() -> None:
    """Methods as columns, a dash where a method has no cell; rendering twice
    changes nothing, so CI's diff check holds."""
    cells = [
        Cell(
            "lexical", "test", "head", "names", "top1_ranking", 4, 0.75, 0.25, 1.0, 0.25
        ),
        Cell("embed", "test", "head", "names", "top1_ranking", 4, 0.5, 0.0, 1.0, 0.25),
        Cell("embed", "test", "tail", "rows", "no_match_recall", 1, 1.0, 1.0, 1.0, 1.0),
    ]
    readme = "# macroswap\n\n<!-- eval:begin -->\nold\n<!-- eval:end -->\n\nMore.\n"
    rendered = render_readme(readme, cells)
    assert rendered == (
        "# macroswap\n\n<!-- eval:begin -->\n"
        "| split | bucket | weighting | metric | lexical | embed |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| test | head | names | top1_ranking "
        "| 0.750 [0.250, 1.000] n=4 | 0.500 [0.000, 1.000] n=4 |\n"
        "| test | tail | rows | no_match_recall | - | 1.000 [1.000, 1.000] n=1 |\n"
        "<!-- eval:end -->\n\nMore.\n"
    )
    assert render_readme(rendered, cells) == rendered
    with pytest.raises(ValueError, match="eval:begin"):
        render_readme("# macroswap\n", cells)
