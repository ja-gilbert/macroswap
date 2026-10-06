from __future__ import annotations

import pytest

from macroswap.swap.fit import Fit, Macros
from macroswap.swap.rank import (
    Candidate,
    DefaultLevel,
    FamilyRow,
    Offer,
    Ranking,
    Target,
)
from macroswap.swap.show import header, table
from macroswap.swap.target import Resolved
from macroswap.usda.table import Row

LEVEL = DefaultLevel(85, "config default")


def row(
    variant: str, family: str = "", as_bought: str = "raw", provenance: str = "sr"
) -> Row:
    return Row(
        id="sr:1",
        source="sr",
        ndb=None,
        description="Beef, ground, 85% lean meat / 15% fat, raw",
        category="test",
        family=family or variant,
        variant=variant,
        lean_pct=None,
        provenance=provenance,
        as_bought=as_bought,
        protein=0.0,
        carbs=0.0,
        fat=0.0,
        fiber=0.0,
        sugars=None,
        kcal=0.0,
        roles="",
        exclusion_reason=None,
    )


def offer(
    food: Row,
    grams: float,
    delta: Macros,
    kcal: float,
    popularity: int | None = None,
    same_food: bool = False,
) -> Offer:
    return Offer(Candidate(food, popularity), Fit(grams, delta, kcal), 0.0, same_food)


def test_a_table_lists_the_common_tier_then_the_rest() -> None:
    """A canned serving says so beside its grams, and a delta that rounds to
    zero prints without a minus. Under the best offer of the target's own
    family come its other variants; the one at the default level prints once,
    on the default line. A family the diary makes common says so beside the
    count on each of its lines."""
    tuna = row("fish, tuna, light, canned in water", "fish, tuna", "canned")
    lean = row("beef, ground, 96/4", "beef, ground", provenance="derived(95/5, 97/3)")
    fatty = row("beef, ground, 70/30", "beef, ground", provenance="sr-formula")
    usual = row("beef, ground, 85/15", "beef, ground", provenance="sr-formula")
    at_default = offer(usual, 103.2, Macros(-3.4, 0.0, 12.8), 101.6, 7, True)
    ranking = Ranking(
        common=(
            FamilyRow(offer(tuna, 119.6, Macros(-0.04, 0.0, 0.31), 2.6)),
            FamilyRow(
                offer(lean, 103.3, Macros(-0.1, 0.0, 1.5), 13.1, 7, True),
                others=(
                    at_default,
                    offer(fatty, 90.0, Macros(1.0, 0.0, 14.0), 130.0, 7, True),
                ),
                default_level=at_default,
                common_by="diary",
            ),
        ),
        rest=(FamilyRow(offer(row("tofu"), 250.4, Macros(2.0, 4.5, -1.0), 17.0, 12)),),
        filtered={},
    )
    assert table(ranking, {"beef, ground": LEVEL}) == [
        "120 g canned  fish, tuna, light, canned in water  protein +0.0  carbs +0.0"
        "  fat +0.3  kcal +3  count n/a  sr",
        "103 g  beef, ground, 96/4 (same food)  protein -0.1  carbs +0.0  fat +1.5"
        "  kcal +13  count 7 diary  derived(95/5, 97/3)",
        "    90 g  beef, ground, 70/30 (same food)  protein +1.0  carbs +0.0  fat +14.0"
        "  kcal +130  count 7 diary  sr-formula",
        "    default level (config default): 103 g  beef, ground, 85/15 (same food)"
        "  protein -3.4  carbs +0.0  fat +12.8  kcal +102  count 7 diary  sr-formula",
        "-- less common --",
        "250 g  tofu  protein +2.0  carbs +4.5  fat -1.0  kcal +17  count 12  sr",
    ]


def test_a_table_with_one_tier_has_no_divider() -> None:
    tofu = FamilyRow(offer(row("tofu"), 250.4, Macros(2.0, 4.5, -1.0), 17.0))
    assert len(table(Ranking((tofu,), (), {}), {})) == 1


def test_a_typed_header_names_the_row_the_method_and_the_level() -> None:
    """Ground beef typed at 91/9, a level it has no row at, names the default
    level it was read at and where that came from, then the note on the level
    asked for as it stands; the method line says why lexical ran. A typed food
    has its grams, so no line says the serving ratio is off."""
    beef = Target(Macros(27.885, 0.0, 22.5), "beef, ground", None, frozenset(), 150.0)
    usual = row("beef, ground, 85/15")
    notes = ("level asked for: 91/9, which beef, ground has no row at",)
    typed = Resolved(beef, usual, "beef, ground", "lexical", LEVEL, notes, None, ())
    assert header(typed, "150 g", "; embed extra not installed") == [
        "target: beef, ground (150 g)",
        "row: sr:1 Beef, ground, 85% lean meat / 15% fat, raw",
        "method: lexical; embed extra not installed",
        "macros: protein 27.9 g, carbs 0.0 g, fat 22.5 g",
        "level: 85/15, config default",
        "level asked for: 91/9, which beef, ground has no row at",
    ]


@pytest.mark.parametrize(
    ("family", "row_line"),
    [
        pytest.param("", "row: none", id="matched-to-nothing"),
        pytest.param(
            "beef, ground", "row: none; family beef, ground", id="matched-to-a-family"
        ),
    ],
)
def test_a_diary_header_names_the_days_and_the_rows_behind_the_medians(
    family: str, row_line: str
) -> None:
    """A diary food on no row has no weight, and the header says the serving
    ratio is not applied."""
    bar = Target(Macros(30, 40, 10), family, None, frozenset())
    names = (("bobs - trail bar", 3), ("trail bar", 1))
    window = ("2026-05-08", "2026-08-05")
    logged = Resolved(bar, None, "bobs - trail bar", "diary", None, (), window, names)
    assert header(logged, "as logged") == [
        "target: bobs - trail bar (as logged)",
        row_line,
        "method: diary",
        "macros: protein 30.0 g, carbs 40.0 g, fat 10.0 g",
        "serving ratio: not applied; no row with macros weighs the food",
        "logged: 2026-05-08 to 2026-08-05; rows per name: bobs - trail bar (3); "
        "trail bar (1)",
    ]
