"""The serving of a candidate food that comes closest to a target's macros.

The serving is the weighted least-squares scale of the candidate against the
target's protein, carbs and fat. Calories are not fitted: they are 4P + 4C +
9F, so a kcal term would count every macro twice, fat most; the kcal delta is
priced from the three macro deltas instead.
"""

from __future__ import annotations

from dataclasses import astuple, dataclass


@dataclass(frozen=True)
class Macros:
    """Protein, carbs and fat: grams, grams per 100 g, or a weight on each."""

    protein: float
    carbs: float
    fat: float


@dataclass(frozen=True)
class Fit:
    """A serving in grams as bought, its macros minus the target's, and those
    deltas in kcal."""

    grams: float
    delta: Macros
    kcal_delta: float


def fit(target: Macros, per_100g: Macros, weights: Macros) -> Fit:
    """The serving minimizing the weighted squared error against the target. It
    is not bounded here; a candidate with no weighted macro raises ValueError."""
    t, w = astuple(target), astuple(weights)
    x = [m / 100 for m in astuple(per_100g)]
    denominator = sum(wi * xi**2 for wi, xi in zip(w, x, strict=True))
    if denominator == 0:
        raise ValueError(f"no weighted macro to fit in {per_100g}")
    grams = sum(wi * xi * ti for wi, xi, ti in zip(w, x, t, strict=True)) / denominator
    delta = Macros(*(grams * xi - ti for xi, ti in zip(x, t, strict=True)))
    return Fit(grams, delta, 4 * delta.protein + 4 * delta.carbs + 9 * delta.fat)
