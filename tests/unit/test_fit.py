from __future__ import annotations

from dataclasses import astuple

import numpy as np
import pytest

from macroswap.swap.fit import Macros, fit

FIT_WEIGHTS = Macros(3, 1, 1)

# Per 100 g, from the USDA table's rows.
RICE = Macros(7.13, 79.95, 0.66)  # sr:168877, white, long-grain, regular, raw
POTATO = Macros(2.05, 17.49, 0.09)  # sr:170026, flesh and skin, raw
GREEK_YOGURT = Macros(10.19, 3.6, 0.39)  # sr:170894, plain, nonfat
CHICKEN = Macros(22.5, 0.0, 2.62)  # sr:171077, breast, meat only, raw
SALMON = Macros(20.42, 0.0, 13.42)  # sr:175167, Atlantic, farmed, raw
CUCUMBER = Macros(0.65, 3.63, 0.11)  # sr:168409, with peel, raw
OLIVE_OIL = Macros(0.0, 0.0, 100.0)  # sr:171413, salad or cooking
# Five large whites, 165 g of sr:172183 at 10.9, 0.73 and 0.17 per 100 g.
FIVE_EGG_WHITES = Macros(17.985, 1.2045, 0.2805)


@pytest.mark.parametrize(
    ("target", "per_100g", "weights"),
    [
        pytest.param(
            Macros(20, 50, 15),
            Macros(10, 30, 20),
            Macros(1, 2, 6),
            id="weight-per-macro",
        ),
        pytest.param(RICE, CUCUMBER, FIT_WEIGHTS, id="serving-above-a-kilogram"),
        pytest.param(
            Macros(0, 30, 0), OLIVE_OIL, Macros(3, 0, 1), id="no-shared-macro"
        ),
    ],
)
def test_serving_minimizes_the_weighted_squared_error(
    target: Macros, per_100g: Macros, weights: Macros
) -> None:
    """The best serving on a 0.01 g grid from 0 to 3 kg, to within a step; with no
    weighted macro in common that is 0 g, not an error, and a weight of zero
    is a weight like any other."""
    grams = np.arange(0, 3000, 0.01)
    error = sum(
        w * (grams * x / 100 - t) ** 2
        for t, x, w in zip(
            astuple(target), astuple(per_100g), astuple(weights), strict=True
        )
    )
    best = grams[np.argmin(error)]
    assert fit(target, per_100g, weights).grams == pytest.approx(best, abs=0.01)


@pytest.mark.parametrize(
    ("target", "per_100g", "grams", "delta"),
    [
        pytest.param(
            RICE, POTATO, 452.80, Macros(2.15, -0.76, -0.25), id="rice-potato-453g"
        ),
        pytest.param(
            FIVE_EGG_WHITES,
            GREEK_YOGURT,
            170.74,
            Macros(-0.59, 4.94, 0.39),
            id="egg-whites-yogurt-171g",
        ),
        pytest.param(
            CHICKEN, SALMON, 98.78, Macros(-2.33, 0.0, 10.64), id="chicken-salmon-99g"
        ),
    ],
)
def test_check_values(
    target: Macros, per_100g: Macros, grams: float, delta: Macros
) -> None:
    """100 g of rice and of chicken breast, so their rows are the targets; at the
    fit weights, to 0.01 g."""
    result = fit(target, per_100g, FIT_WEIGHTS)
    assert (result.grams, *astuple(result.delta)) == pytest.approx(
        (grams, *astuple(delta)), abs=0.01
    )


def test_deltas_are_serving_minus_target_priced_at_4_4_9() -> None:
    """(0.2, 0, 0.1) a gram against (40, 30, 7) at the fit weights: 190 g, deltas
    (-2, -30, +12) and 4(-2) + 4(-30) + 9(12) = -20 kcal. Relative tolerance 1e-6."""
    result = fit(Macros(40, 30, 7), Macros(20, 0, 10), FIT_WEIGHTS)
    assert (result.grams, *astuple(result.delta), result.kcal_delta) == pytest.approx(
        (190, -2, -30, 12, -20)
    )


@pytest.mark.parametrize(
    ("per_100g", "weights"),
    [
        pytest.param(Macros(0, 0, 0), FIT_WEIGHTS, id="all-zero-candidate"),
        pytest.param(OLIVE_OIL, Macros(1, 1, 0), id="only-macro-weighted-zero"),
    ],
)
def test_zero_weighted_denominator_raises(per_100g: Macros, weights: Macros) -> None:
    with pytest.raises(ValueError):
        fit(CHICKEN, per_100g, weights)
