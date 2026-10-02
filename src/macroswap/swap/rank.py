"""Which foods answer a target, one row per family, and in what order.

A candidate is fitted only when its family shares a macro pool with the target,
and the fit's deltas are scored in kcal space. The fit and the score are
separate weightings: the fit decides how many grams, the score which foods
come first, so a fatty food keeps its protein-matched serving and ranks below
a lean one.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import astuple, dataclass

from macroswap.config import SwapConfig
from macroswap.swap.fit import Fit, Macros, fit
from macroswap.usda.table import Row


@dataclass(frozen=True)
class Target:
    """Grams of protein, carbs and fat to match, and the food they came from:
    its family, its variant when one row was resolved, and its family's pools."""

    macros: Macros
    family: str
    variant: str | None
    pools: frozenset[str]


@dataclass(frozen=True)
class Candidate:
    """A row a swap may offer, with its family's participant count once the
    popularity table is built."""

    row: Row
    popularity: int | None = None


@dataclass(frozen=True)
class DefaultLevel:
    """The leanness level a family shows when none was asked for, and where it
    came from."""

    lean_pct: int
    source: str


@dataclass(frozen=True)
class Offer:
    """A candidate at its fitted serving; same_food marks a row of the target's
    own family."""

    candidate: Candidate
    fit: Fit
    score: float
    same_food: bool = False


@dataclass(frozen=True)
class FamilyRow:
    """A family at its lowest-score variant; its other variants when asked
    for; and a leanness family's default level when the best is another."""

    best: Offer
    others: tuple[Offer, ...] = ()
    default_level: Offer | None = None


@dataclass(frozen=True)
class Ranking:
    """The family rows by tier, and how many candidates were left out, by
    reason."""

    common: tuple[FamilyRow, ...]
    rest: tuple[FamilyRow, ...]
    filtered: dict[str, int]


def score(delta: Macros, weights: Macros) -> float:
    """The weighted miss of a serving: with the rank weights, kcal with protein
    counted three times."""
    return math.sqrt(
        sum(w * d**2 for w, d in zip(astuple(weights), astuple(delta), strict=True))
    )


def rank(
    target: Target,
    candidates: Sequence[Candidate],
    config: SwapConfig,
    *,
    default_levels: Mapping[str, DefaultLevel] | None = None,
    diary_families: frozenset[str] = frozenset(),
    variants: bool = False,
    new_only: bool = False,
    include_obscure: bool = False,
    top: int | None = None,
) -> Ranking:
    """The families that answer the target, the common tier and then the rest.

    A candidate is left out for the first reason that applies: its family is
    the target's (under variants only the target's own variant is), it shares
    no pool with the target, new_only and its family is in the diary, its count
    is below the floor (a diary family and include_obscure are exempt), or its
    serving falls outside the bounds. A family is common unless its count is
    below the common threshold and the diary lacks it; within a tier, near-ties
    in score go by count. top counts family rows in output order across both
    tiers; None is the configured number.
    """
    low, high = config.serving_bounds_g
    filtered: Counter[str] = Counter()
    families: dict[str, dict[str, Offer]] = {}
    for candidate in candidates:
        row, count = candidate.row, candidate.popularity
        own = row.family == target.family
        if own and not (variants and row.variant != target.variant):
            filtered["own-family"] += 1
        elif target.pools.isdisjoint(row.roles.split(",")):
            filtered["no-shared-pool"] += 1
        elif new_only and row.family in diary_families:
            filtered["diary-family"] += 1
        elif (
            count is not None
            and count < config.popularity_floor
            and row.family not in diary_families
            and not include_obscure
        ):
            filtered["below-floor"] += 1
        else:
            per_100g = Macros(row.protein or 0.0, row.carbs or 0.0, row.fat or 0.0)
            fitted = fit(target.macros, per_100g, config.fit_weights)
            if not low <= fitted.grams <= high:
                filtered["serving-bounds"] += 1
                continue
            offer = Offer(
                candidate, fitted, score(fitted.delta, config.rank_weights), own
            )
            # Rows sharing a variant are one offer, the closest of them.
            kept = families.setdefault(row.family, {})
            if row.variant not in kept or offer.score < kept[row.variant].score:
                kept[row.variant] = offer

    common: list[FamilyRow] = []
    rest: list[FamilyRow] = []
    for family, kept in families.items():
        best, *others = sorted(kept.values(), key=lambda o: o.score)
        level = default_levels.get(family) if default_levels else None
        at_default = None
        if level is not None and best.candidate.row.lean_pct != level.lean_pct:
            at_default = next(
                (o for o in others if o.candidate.row.lean_pct == level.lean_pct), None
            )
        count = best.candidate.popularity
        rare = count is not None and count < config.common_threshold
        tier = rest if rare and family not in diary_families else common
        tier.append(FamilyRow(best, tuple(others) if variants else (), at_default))

    limit = config.top if top is None else top
    common = _clustered(common, config.tie_epsilon)[:limit]
    rest = _clustered(rest, config.tie_epsilon)[: limit - len(common)]
    return Ranking(tuple(common), tuple(rest), dict(filtered))


def _clustered(rows: list[FamilyRow], epsilon: float) -> list[FamilyRow]:
    """Rows by score, regrouped so popularity breaks near-ties: a row joins the
    current cluster while its score is within epsilon of the cluster's best,
    since "within epsilon" of a neighbour would chain; a cluster's members go
    by count, higher first and an unknown count last, then score."""
    clusters: list[list[FamilyRow]] = []
    for row in sorted(rows, key=lambda r: r.best.score):
        if clusters and row.best.score - clusters[-1][0].best.score <= epsilon:
            clusters[-1].append(row)
        else:
            clusters.append([row])
    return [row for cluster in clusters for row in sorted(cluster, key=_by_count)]


def _by_count(row: FamilyRow) -> float:
    count = row.best.candidate.popularity
    return math.inf if count is None else -count
