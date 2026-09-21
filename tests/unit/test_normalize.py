from __future__ import annotations

import pytest

from macroswap.diary.normalize import (
    NameParts,
    Quantity,
    parse_leanness,
    parse_quantity,
    plausible_grams,
    split_name,
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
    ],
)
def test_split_name(raw: str, expected: NameParts) -> None:
    assert split_name(raw) == expected


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
