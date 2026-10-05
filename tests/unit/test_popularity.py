from __future__ import annotations

from dataclasses import replace

import pytest

from macroswap.config import load_config
from macroswap.nhanes.popularity import (
    Attribution,
    Popularity,
    attribute,
    count,
    file_left_out,
)
from macroswap.usda.table import BuildError, Row

WATER = ("beverages, water",)
COUNT_AS = {"potatoes, flesh": "potatoes"}
# Each food code with its ingredients: an NDB number of ROWS, another food's
# code, or a code nothing knows.
RECIPES = {
    "rice bowl": [("2", 60.0), ("1", 40.0)],
    "soup": [("3", 80.0), ("1", 20.0)],
    "tap water": [("3", 100.0)],
    "plate": [("rice bowl", 50.0), ("1", 15.0), ("999", 35.0)],
    "baked potato": [("4", 100.0)],
    "loop": [("back", 100.0)],
    "back": [("loop", 50.0), ("1", 50.0)],
    "colby jack": [("7", 50.0), ("8", 50.0)],
    "stew": [("1", 75.0), ("2", 75.0), ("5", 37.5), ("6", 37.5)],
    "close call": [("2", 50.001), ("1", 49.999)],
    "tenths": [("5", 1.0), ("6", 2.0), ("2", 3.0), ("3", 4.0)],
    "home fries": [("4", 50.0), ("5", 50.0), ("2", 50.0)],
    "mash": [("5", 40.0), ("6", 30.0), ("9", 30.0)],
    "nothing": [],
}


def row(
    ndb: str,
    family: str,
    variant: str = "",
    reason: str | None = None,
    category: str = "test",
) -> Row:
    return Row(
        id=f"sr:{ndb}",
        source="sr",
        ndb=ndb,
        description=family,
        category=category,
        family=family,
        variant=variant or family,
        lean_pct=None,
        provenance="sr",
        as_bought="raw",
        protein=0.0,
        carbs=0.0,
        fat=0.0,
        fiber=0.0,
        kcal=0.0,
        roles="",
        exclusion_reason=reason,
    )


ROWS = [
    row("1", "chicken, breast"),
    row("2", "rice, white"),
    row("3", "beverages, water", reason="excluded-category"),
    row("4", "potatoes, flesh", reason="cooked-with-raw-sibling"),
    row("5", "potatoes", "potatoes, russet"),
    row("6", "potatoes", "potatoes, red"),
    row("7", "cheese, colby"),
    row("8", "cheese, monterey"),
    row("9", "potatoes", "potatoes, red"),
]
CHICKEN, RICE = "chicken, breast", "rice, white"


@pytest.mark.parametrize(
    ("code", "families", "variants", "unattributed"),
    [
        pytest.param("soup", {CHICKEN}, {CHICKEN}, 0.0, id="water-set-aside"),
        pytest.param(
            "tap water", {"beverages, water"}, {"beverages, water"}, 0.0, id="all-water"
        ),
        pytest.param(
            "plate", {CHICKEN}, {CHICKEN}, 0.35, id="nested-with-an-unknown-ingredient"
        ),
        pytest.param(
            "baked potato", {"potatoes"}, {"potatoes, flesh"}, 0.0, id="counted-as-raw"
        ),
        pytest.param("loop", {CHICKEN}, {CHICKEN}, 0.5, id="a-recipe-inside-itself"),
        pytest.param(
            "colby jack",
            {"cheese, colby", "cheese, monterey"},
            {"cheese, colby", "cheese, monterey"},
            0.0,
            id="a-two-way-tie",
        ),
        pytest.param(
            "stew",
            {CHICKEN, RICE, "potatoes"},
            {CHICKEN, RICE, "potatoes, russet", "potatoes, red"},
            0.0,
            id="a-three-way-tie",
        ),
        pytest.param("close call", {RICE}, {RICE}, 0.0, id="close-is-not-a-tie"),
        pytest.param(
            "tenths",
            {"potatoes", RICE},
            {"potatoes, red", RICE},
            0.0,
            id="a-tie-but-for-float-rounding",
        ),
        pytest.param(
            "home fries",
            {"potatoes", RICE},
            {"potatoes, flesh", "potatoes, russet", RICE},
            0.0,
            id="counted-as-after-the-tie",
        ),
        pytest.param(
            "mash", {"potatoes"}, {"potatoes, red"}, 0.0, id="a-variant-in-two-rows"
        ),
        pytest.param("nothing", set(), set(), 1.0, id="no-weight"),
    ],
)
def test_a_food_counts_toward_its_largest_ingredients_families(
    code: str, families: set[str], variants: set[str], unattributed: float
) -> None:
    """The plate is half a rice bowl, so the bowl's rice carries 0.3 of it and
    its chicken 0.2, which with the 0.15 added whole beats the rice; the
    unknown 0.35 reaches no row. The loop holds a recipe that holds the loop:
    that half reaches no row and the other half is chicken. The stew ties
    three families at 75 g, potatoes through two rows that tie as well. In
    tenths the potatoes' 0.1 and 0.2 sum to 0.30000000000000004 beside rice's
    0.3, a tie; the close call's 50.001 beside 49.999 is not. Home fries tie a
    cooked key, the raw family it counts as, and rice: counted as after the
    tie, potatoes appears once beside rice. The mash is 40 g of russets beside
    60 g of reds in two rows, so red carried the most."""
    got = attribute(RECIPES, ROWS, WATER, COUNT_AS)[code]
    assert (set(got.families), set(got.variants)) == (families, variants)
    assert got.unattributed == pytest.approx(unattributed)


@pytest.mark.parametrize(
    ("count_as", "line"),
    [
        pytest.param(
            {"potatoes, flesh": "potatoes", "potatoes": "rice, white"},
            "potatoes, flesh -> potatoes",
            id="a-chain",
        ),
        pytest.param(
            {"potatoes": "potatoes, flesh"},
            "potatoes -> potatoes, flesh",
            id="a-target-no-swap-offers",
        ),
        pytest.param(
            {"potatos, flesh": "potatoes"},
            "potatos, flesh -> potatoes",
            id="a-source-the-table-lacks",
        ),
    ],
)
def test_a_count_as_line_that_does_not_fit_the_table_is_refused(
    count_as: dict[str, str], line: str
) -> None:
    with pytest.raises(BuildError, match=line):
        attribute(RECIPES, ROWS, WATER, count_as)


def test_a_participant_counts_once_per_family_and_per_variant() -> None:
    """Participant 1 reports the rice bowl twice and chicken once; participant 2
    a food that ties chicken with rice, then chicken alone; participant 3 only
    a food that counts nowhere, and is still a participant."""
    attributions = {
        "rice bowl": Attribution(frozenset({RICE}), frozenset({RICE}), 0.0),
        "breast": Attribution(frozenset({CHICKEN}), frozenset({CHICKEN}), 0.0),
        "half and half": Attribution(
            frozenset({CHICKEN, RICE}), frozenset({CHICKEN, RICE}), 0.0
        ),
        "nothing": Attribution(frozenset(), frozenset(), 1.0),
    }
    reports = [
        (1, "rice bowl"),
        (1, "rice bowl"),
        (1, "breast"),
        (2, "half and half"),
        (2, "breast"),
        (3, "nothing"),
    ]
    counts = {CHICKEN: 2, RICE: 2}
    assert count(reports, attributions) == Popularity(3, counts, counts)


# Two categories left out on purpose and no word rules, whatever the packaged
# lists hold.
USDA = replace(
    load_config().usda,
    excluded_categories=("Snacks", "Sweets"),
    allow_words={},
    deny_words={},
)
LEFT_OUT = "excluded-category"


@pytest.mark.parametrize(
    ("reported", "by_design", "not_reachable"),
    [
        pytest.param(
            [
                row("1", "ham", reason=LEFT_OUT, category="Sweets"),
                row("2", "ham", reason="cooked-with-raw-sibling", category="Pork"),
            ],
            {},
            {"ham"},
            id="one-row-left-out-for-its-key-alone",
        ),
        pytest.param(
            [
                row("1", "leather", reason=LEFT_OUT, category="Sweets"),
                row("2", "leather", reason=LEFT_OUT, category="Sweets"),
                row("3", "leather", reason=LEFT_OUT, category="Snacks"),
            ],
            {"leather": "Sweets"},
            set(),
            id="the-category-with-the-most-rows",
        ),
        pytest.param(
            [
                row("1", "leather", reason=LEFT_OUT, category="Sweets"),
                row("2", "leather", reason=LEFT_OUT, category="Snacks"),
            ],
            {"leather": "Snacks"},
            set(),
            id="the-first-by-name-on-a-tie",
        ),
        pytest.param(
            [row("1", "twin", reason="analytical-duplicate", category="Pork")],
            {},
            {"twin"},
            id="a-duplicate-is-a-key-reason",
        ),
    ],
)
def test_a_family_no_swap_offers_is_filed_by_the_rows_given(
    reported: list[Row], by_design: dict[str, str], not_reachable: set[str]
) -> None:
    """Left out by design takes every row: the ham's one cooked row in a
    category that leaves nothing out makes it not reachable. The category shown
    is the one with the most rows, Sweets over Snacks at two to one, and the
    first by name when they tie."""
    assert file_left_out(reported, USDA) == (by_design, not_reachable)
