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
from collections.abc import Collection, Mapping, Sequence
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
    """A row a swap may offer, and how many participants reported its family
    and its variant. A candidate without a family count passes the floor and
    is common."""

    row: Row
    popularity: int | None = None
    variant_popularity: int = 0


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
    """A family at the variant it shows; its other variants when asked for; a
    leanness family's default level when the best is another; and the word,
    diary or allowlist, that puts it in the common tier when its count would
    not."""

    best: Offer
    others: tuple[Offer, ...] = ()
    default_level: Offer | None = None
    common_by: str = ""


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
    allowlist: Collection[str] = (),
    variants: bool = False,
    new_only: bool = False,
    include_obscure: bool = False,
    top: int | None = None,
) -> Ranking:
    """The families that answer the target, the common tier and then the rest.

    A candidate is left out for the first reason that applies: its family is
    the target's (under variants only the target's own variant is), it shares
    no pool with the target, new_only and its family is in the diary, its count
    is below the floor (a diary family, an allowlisted one and include_obscure
    are exempt), or its serving falls outside the bounds. A family shows the
    variant most participants reported among those within the tie epsilon of
    its closest, the closer of two reported alike, when at least the floor
    reported it; otherwise, and for a leanness family always, it shows its
    closest. A family is common unless its count is below the common threshold
    and neither the diary nor the allowlist holds it; within a tier a family
    is placed by its closest variant, whichever it shows, and near-ties go by
    the family's count. top counts family rows in output order across both
    tiers; None is the configured number.
    """

    def common_by(family: str) -> str:
        if family in diary_families:
            return "diary"
        return "allowlist" if family in allowlist else ""

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
            and not common_by(row.family)
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

    common: list[tuple[float, FamilyRow]] = []
    rest: list[tuple[float, FamilyRow]] = []
    for family, kept in families.items():
        offers = sorted(kept.values(), key=lambda o: o.score)
        closest = best = offers[0]
        level = default_levels.get(family) if default_levels else None
        at_default = None
        if level is None:
            # max keeps the first of equals, and the offers run closest first.
            near = [o for o in offers if o.score - closest.score <= config.tie_epsilon]
            most = max(near, key=lambda o: o.candidate.variant_popularity)
            if most.candidate.variant_popularity >= config.popularity_floor:
                best = most
        elif closest.candidate.row.lean_pct != level.lean_pct:
            at_default = next(
                (o for o in offers if o.candidate.row.lean_pct == level.lean_pct), None
            )
        others = tuple(o for o in offers if o is not best) if variants else ()
        count = best.candidate.popularity
        rare = count is not None and count < config.common_threshold
        word = common_by(family) if rare else ""
        tier = rest if rare and not word else common
        tier.append((closest.score, FamilyRow(best, others, at_default, word)))

    limit = config.top if top is None else top
    first = _clustered(common, config.tie_epsilon)[:limit]
    second = _clustered(rest, config.tie_epsilon)[: limit - len(first)]
    return Ranking(tuple(first), tuple(second), dict(filtered))


def _clustered(rows: list[tuple[float, FamilyRow]], epsilon: float) -> list[FamilyRow]:
    """Rows by the score each is placed at, regrouped so popularity breaks
    near-ties: a row joins the current cluster while its score is within
    epsilon of the cluster's first, since "within epsilon" of a neighbour
    would chain; a cluster's members go by count, higher first and an unknown
    count last, then score."""
    clusters: list[tuple[float, list[FamilyRow]]] = []
    for place, row in sorted(rows, key=lambda placed: placed[0]):
        if clusters and place - clusters[-1][0] <= epsilon:
            clusters[-1][1].append(row)
        else:
            clusters.append((place, [row]))
    return [row for _, cluster in clusters for row in sorted(cluster, key=_by_count)]


def _by_count(row: FamilyRow) -> float:
    count = row.best.candidate.popularity
    return math.inf if count is None else -count
