from __future__ import annotations

import pytest

from macroswap.config import load_config
from macroswap.diary.normalize import (
    NameParts,
    Quantity,
    name_key,
    parse_leanness,
    parse_quantity,
    parse_state,
    plausible_grams,
    split_name,
    strip_leanness,
    tokens,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param(
            "Kirkland - Chicken Breast, 6 oz (112g)",
            NameParts("Kirkland", "Chicken Breast", "6 oz (112g)"),
            id="brand-and-quantity",
        ),
        pytest.param(
            "Egg Whites, 5 large",
            NameParts(None, "Egg Whites", "5 large"),
            id="no-brand",
        ),
        pytest.param(
            "Yogurt, Greek, plain",
            NameParts(None, "Yogurt, Greek, plain", None),
            id="commas-are-not-a-quantity",
        ),
        pytest.param(
            "Trader Joe's - Chicken - Grilled Strips, 85 g",
            NameParts("Trader Joe's", "Chicken - Grilled Strips", "85 g"),
            id="only-the-first-dash-is-the-brand",
        ),
        pytest.param(
            "Milk, 2%", NameParts(None, "Milk, 2%", None), id="bare-percent-stays"
        ),
        pytest.param(
            "Milk, 2% reduced fat",
            NameParts(None, "Milk, 2% reduced fat", None),
            id="percent-is-never-a-unit",
        ),
        pytest.param(
            "Egg Whites, 3",
            NameParts(None, "Egg Whites, 3", None),
            id="a-number-without-a-unit-stays",
        ),
        pytest.param(
            "Ground Beef, 93% lean",
            NameParts(None, "Ground Beef, 93% lean", None),
            id="leanness-after-the-comma-stays",
        ),
        pytest.param(
            "Ground Beef, 93 lean",
            NameParts(None, "Ground Beef, 93 lean", None),
            id="leanness-without-a-percent-after-the-comma-stays",
        ),
    ],
)
def test_split_name(raw: str, expected: NameParts) -> None:
    assert split_name(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param(
            "Kirkland - Chicken Breast, 6 oz (112g)",
            "kirkland - chicken breast",
            id="brand-kept-quantity-dropped",
        ),
        pytest.param("Egg Whites, 5 large", "egg whites", id="no-brand"),
    ],
)
def test_name_key_is_the_counted_name(raw: str, expected: str) -> None:
    assert name_key(raw) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("4 oz", Quantity(4.0, "oz", 113.398), id="mass-unit"),
        pytest.param("1.25 oz(s)", Quantity(1.25, "oz", 35.437), id="oz-plural-suffix"),
        pytest.param(
            "6 oz (112g)",
            Quantity(6.0, "oz", 170.097),
            id="mass-unit-beats-parenthetical",
        ),
        pytest.param(
            "0.38 container (7 oz)",
            Quantity(0.38, "container", 75.410),
            id="count-times-parenthetical-mass",
        ),
        pytest.param(
            "0.06 medium", Quantity(0.06, "medium", None), id="count-unit-alone"
        ),
        pytest.param("1/2 cup", Quantity(0.5, "cup", None), id="fraction"),
        pytest.param(
            "12 fl oz", Quantity(12.0, "fl oz", None), id="fluid-ounces-not-mass"
        ),
    ],
)
def test_parse_quantity(text: str, expected: Quantity) -> None:
    result = parse_quantity(text)
    assert result is not None
    assert (result.amount, result.unit) == (expected.amount, expected.unit)
    if expected.grams is None:
        assert result.grams is None
    else:
        assert result.grams == pytest.approx(expected.grams, abs=0.01)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("Ground Beef 93/7", 93, id="slash"),
        pytest.param("96% Lean Ground Turkey", 96, id="percent-lean"),
        pytest.param("ground beef 90 lean", 90, id="bare-lean"),
        pytest.param("Whole Wheat Bread 12/24", None, id="slash-not-summing-to-100"),
        pytest.param("100% Whole Wheat", None, id="percent-without-lean"),
    ],
)
def test_parse_leanness(text: str, expected: int | None) -> None:
    assert parse_leanness(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param(
            "Laura's Lean 93/7 - Ground Beef",
            "Laura's Lean - Ground Beef",
            id="slash-level-in-the-brand",
        ),
        pytest.param("96% Lean Ground Turkey", "Ground Turkey", id="percent-lean"),
        pytest.param(
            "Whole Wheat Bread 12/24",
            "Whole Wheat Bread 12/24",
            id="slash-that-is-not-a-level-stays",
        ),
    ],
)
def test_strip_leanness_removes_what_parses(text: str, expected: str) -> None:
    assert strip_leanness(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param(
            "mac and cheese, not prepared", set(), id="state-phrase-is-not-cooking"
        ),
        pytest.param(
            "Pan-Broiled Ground Turkey",
            {"pan", "broiled"},
            id="cooking-words-as-the-index-reads-them",
        ),
    ],
)
def test_parse_state(text: str, expected: set[str]) -> None:
    """The table's raw-state phrases hold cooking words, and "not prepared" ends
    many a packaged food's name: the food as bought, not cooked. A cooking word
    comes back in the words a row's index text holds."""
    usda = load_config().usda
    assert parse_state(text, usda.cooking_words, usda.state_fields) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param(
            "Chicken w/ Rice & Beans w/o Salt",
            ["chicken", "with", "rice", "and", "bean", "without", "salt"],
            id="abbreviations-are-whole-words",
        ),
        pytest.param(
            "Chicken, Bnls, (w/ Rice)",
            ["chicken", "boneless", "with", "rice"],
            id="abbreviations-next-to-punctuation",
        ),
        pytest.param(
            "Strawberries, Tomatoes, Peaches, Pies, Brownie, Egg Whites, Swiss",
            ["strawberry", "tomato", "peach", "pie", "browny", "egg", "white", "swiss"],
            id="plurals-fold",
        ),
        pytest.param("Jalapeño", ["jalapeno"], id="accents-drop"),
        pytest.param(
            "Hellmann's - Mayonnaise, Kellogg\u2019s",
            ["hellmann", "mayonnaise", "kellogg"],
            id="apostrophes-deleted-not-split",
        ),
        pytest.param(
            "rice 1 cup cooked, 2% milk",
            ["rice", "cooked", "2", "milk"],
            id="quantity-anywhere-dropped-bare-percent-kept",
        ),
    ],
)
def test_tokens(text: str, expected: list[str]) -> None:
    assert tokens(text, load_config().match.abbreviations) == expected


@pytest.mark.parametrize(
    ("grams", "calories", "expected"),
    [
        pytest.param(2.25, 90.0, None, id="cheddar-wrong-unit"),
        pytest.param(50.0, None, 50.0, id="no-calories-keeps-grams"),
        pytest.param(0.0, 0.0, None, id="zero-grams"),
    ],
)
def test_plausible_grams(
    grams: float | None, calories: float | None, expected: float | None
) -> None:
    assert plausible_grams(grams, calories, max_kcal_per_gram=9.5) == expected
