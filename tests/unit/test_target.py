from __future__ import annotations

import math
from dataclasses import astuple, replace

import pytest

from macroswap.config import Config, load_config
from macroswap.match.matcher import Encoder, Matcher
from macroswap.swap.fit import Macros
from macroswap.swap.rank import DefaultLevel
from macroswap.swap.target import NoTarget, TargetError, typed
from macroswap.usda.keys import FieldRules
from macroswap.usda.table import Row

PACKAGED = load_config()
COOKED_RICE = "rice, white, long-grain, regular / cooked"
LEVELS = {"beef, ground": DefaultLevel(85, "test")}


@pytest.fixture
def config() -> Config:
    """The packaged config with what tuning changes pinned: a lexical threshold
    above what the fixture table scores for "jasmine rice" and below "white
    rice", and a table of everyday names for a row, two families, a row without
    macros and nothing."""
    staples = {
        "white rice": COOKED_RICE,
        "almonds": "nuts, almonds",
        "mince": "beef, ground",
        "olive oil": "oil, olive, extra virgin / raw",
        "ghost": "no such food / raw",
    }
    return replace(
        PACKAGED,
        match=replace(PACKAGED.match, no_match={"lexical": 5.0, "embed": -math.inf}),
        swap=replace(PACKAGED.swap, staples=staples),
    )


@pytest.fixture
def matcher(usda_rows: list[Row], config: Config) -> Matcher:
    return Matcher(usda_rows, config.match, FieldRules(config.usda))


@pytest.mark.parametrize(
    ("text", "row_id", "key", "source", "variant", "level"),
    [
        pytest.param(
            "Egg Whites",
            "sr:172183",
            "egg, white / raw",
            "lexical",
            "egg, white",
            None,
            id="by-the-matcher",
        ),
        pytest.param(
            "White Rices, 1 bowl",
            "sr:169753",
            COOKED_RICE,
            "everyday name",
            "rice, white, long-grain, regular",
            None,
            id="everyday-name-before-the-matcher",
        ),
        pytest.param(
            "ground beef",
            "sr:171796",
            "beef, ground",
            "lexical",
            None,
            LEVELS["beef, ground"],
            id="family-at-its-default-level",
        ),
        pytest.param(
            "almonds",
            "sr:170567",
            "nuts, almonds",
            "everyday name",
            None,
            None,
            id="everyday-name-for-a-family",
        ),
        pytest.param(
            "mince",
            "sr:171796",
            "beef, ground",
            "everyday name",
            None,
            LEVELS["beef, ground"],
            id="everyday-name-for-a-family-with-a-default-level",
        ),
        pytest.param(
            "ground beef ham lunchmeat",
            "sr:171796",
            "beef, ground",
            "lexical",
            None,
            LEVELS["beef, ground"],
            id="a-family-standing-in-for-a-top-hit-without-macros",
        ),
    ],
)
def test_typed_text_resolves_to_a_row_and_its_key(
    usda_rows: list[Row],
    matcher: Matcher,
    config: Config,
    text: str,
    row_id: str,
    key: str,
    source: str,
    variant: str | None,
    level: DefaultLevel | None,
) -> None:
    """The matcher alone takes "white rice" to the raw row; the table's cooked
    row is one a swap may not offer, and a plural or a quantity in the text
    still finds the table, since both sides are read as the matcher reads them.
    Ground beef without a level stands on its 85/15 row and keeps no variant;
    almonds, a family without a default level, stand on their raw row, not the
    roasted row before it that a swap may not offer."""
    got = typed(text, 100, usda_rows, matcher, "lexical", config, LEVELS)
    assert got.row is not None
    assert (got.row.id, got.key, got.source, got.target.variant, got.level) == (
        row_id,
        key,
        source,
        variant,
        level,
    )


@pytest.mark.parametrize("text", ["cooked ground beef", "cooked ground beef 91/9"])
def test_a_cooking_word_survives_a_default_level(
    usda_rows: list[Row], config: Config, text: str
) -> None:
    """Ground beef typed cooked, without a level or at one it has no row at,
    stands on the cooked row at the default level, as it would with that level
    typed: not on the raw row, and not on the cooked row the matcher ranks
    first, at 70/30. The fixture has no cooked ground beef, so two patties are
    added."""
    raw = next(r for r in usda_rows if r.id == "sr:171796")
    patties = [
        replace(
            raw,
            id=row_id,
            description=f"Beef, ground, {lean}% lean meat / {100 - lean}% fat, "
            "patty, cooked, broiled",
            variant=f"beef, ground, {lean}/{100 - lean}, patty",
            lean_pct=lean,
            as_bought="cooked",
            exclusion_reason="cooked-with-raw-sibling",
        )
        for row_id, lean in (("sr:168650", 70), ("sr:174032", 85))
    ]
    rows = [*usda_rows, *patties]
    matcher = Matcher(rows, config.match, FieldRules(config.usda))
    got = typed(text, 100, rows, matcher, "lexical", config, LEVELS)
    beef = "beef, ground"
    assert (got.row, got.key, got.level) == (patties[1], beef, LEVELS[beef])


@pytest.mark.parametrize(
    ("text", "notes"),
    [
        pytest.param(
            "ground chicken 93/7",
            ("level asked for: 93/7, which chicken, ground has no row at",),
            id="a-food-without-levels",
        ),
        pytest.param(
            "ground turkey 90/10",
            ("level asked for: 90/10, which turkey, ground has no row at",),
            id="a-level-the-family-lacks",
        ),
        pytest.param("ground beef 93/7", (), id="a-level-the-family-has"),
    ],
)
def test_a_level_asked_for_that_no_row_is_at_is_noted(
    usda_rows: list[Row],
    matcher: Matcher,
    config: Config,
    text: str,
    notes: tuple[str, ...],
) -> None:
    """Ground chicken has one row and no levels; ground turkey has rows at
    99/1, 93/7 and 85/15."""
    got = typed(text, 100, usda_rows, matcher, "lexical", config, LEVELS)
    assert got.notes == notes


def test_a_top_hit_without_macros_gives_way_to_the_next_that_has_them(
    usda_rows: list[Row], matcher: Matcher, config: Config
) -> None:
    """Pie pumpkin's top hit, a Foundation row at 8.5, lacks carbs and fat; the
    next, plain pumpkin at 6.7, is above the threshold of 5 and has all three."""
    got = typed("pie pumpkin", 100, usda_rows, matcher, "lexical", config, {})
    assert (got.row and got.row.id, got.key, got.notes) == (
        "sr:168448",
        "pumpkin / raw",
        (
            "matched foundation:2727578 Squash, pie pumpkin, peeled, seeded, raw; "
            "using sr:168448 Pumpkin, raw, foundation:2727578 has no carbs, fat value",
        ),
    )


@pytest.mark.parametrize(
    ("text", "method", "no_match", "message"),
    [
        pytest.param(
            "pie pumpkin",
            "lexical",
            {"lexical": 7.0, "embed": -math.inf},
            "foundation:2727578 lacks carbs, fat",
            id="below-the-threshold",
        ),
        pytest.param(
            "virgin olive oil",
            "hybrid",
            {"lexical": 7.0, "embed": 0.7},
            "foundation:748608 lacks protein, carbs, fat",
            id="hybrid-below-both-thresholds",
        ),
    ],
)
def test_no_hit_below_the_threshold_stands_in(
    usda_rows: list[Row],
    config: Config,
    fake_embedder: Encoder,
    text: str,
    method: str,
    no_match: dict[str, float],
    message: str,
) -> None:
    """Plain pumpkin scores 6.7 for pie pumpkin; anchovies in olive oil, next
    after the extra virgin row for virgin olive oil, score 6.3 lexical and 0.69
    embed. The refusal is the top hit's."""
    strict = replace(config.match, no_match=no_match)
    matcher = Matcher(usda_rows, strict, FieldRules(config.usda), fake_embedder)
    with pytest.raises(TargetError, match=message):
        typed(text, 100, usda_rows, matcher, method, replace(config, match=strict), {})


@pytest.mark.parametrize(
    ("text", "grams", "macros", "family", "pools"),
    [
        pytest.param(
            "chicken breast",
            200,
            Macros(45.0, 0.0, 5.24),
            "chicken, breast",
            {"protein", "fat"},
            id="pools-of-its-family",
        ),
        pytest.param(
            "chocolate chip cookies",
            50,
            Macros(2.985, 33.745, 8.955),
            "cookies, chocolate chip",
            {"carbs", "fat"},
            id="pools-of-its-macros-when-no-swap-offers-its-family",
        ),
    ],
)
def test_a_typed_target_is_the_row_at_its_grams(
    usda_rows: list[Row],
    matcher: Matcher,
    config: Config,
    text: str,
    grams: float,
    macros: Macros,
    family: str,
    pools: set[str],
) -> None:
    """Chicken breast, meat only, is 22.5, 0 and 2.62 per 100 g: on its own
    macros it would reach protein alone, and its family reaches fat too.
    Cookies are an excluded category, so their family has no roles; protein
    gives 5% of their calories."""
    target = typed(text, grams, usda_rows, matcher, "lexical", config, {}).target
    assert (*astuple(target.macros), target.family, target.pools) == pytest.approx(
        (*astuple(macros), family, pools)
    )


@pytest.mark.parametrize(
    ("text", "grams", "message"),
    [
        pytest.param("egg whites", 0, "no protein, carbs or fat", id="no-grams"),
        pytest.param(
            "olive oil",
            100,
            "foundation:748608 lacks protein, carbs, fat in the table",
            id="no-macros",
        ),
        pytest.param("ghost", 100, "names no row", id="everyday-name-for-nothing"),
    ],
)
def test_a_typed_target_is_refused(
    usda_rows: list[Row],
    matcher: Matcher,
    config: Config,
    text: str,
    grams: float,
    message: str,
) -> None:
    with pytest.raises(TargetError, match=message):
        typed(text, grams, usda_rows, matcher, "lexical", config, {})


def test_text_the_method_abstains_on_carries_each_methods_nearest_rows(
    usda_rows: list[Row], config: Config, fake_embedder: Encoder
) -> None:
    """Jasmine rice scores below the lexical threshold; the refusal names what
    each method came nearest to, lexical's long-grain white rice first."""
    matcher = Matcher(usda_rows, config.match, FieldRules(config.usda), fake_embedder)
    with pytest.raises(NoTarget) as refused:
        typed("jasmine rice", 100, usda_rows, matcher, "lexical", config, {})
    nearest = refused.value.nearest
    assert (set(nearest), nearest["lexical"][0].row.id) == (
        {"lexical", "embed", "hybrid"},
        "sr:168877",
    )
