"""How many NHANES participants reported each food family.

An FNDDS survey food counts toward the family of its largest ingredient by
weight, nested recipes expanded and water set aside, and toward each family
when several tie for the largest; a participant counts once per family,
however often and on whichever day they reported it.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from macroswap.nhanes.xpt import read_xpt
from macroswap.usda.table import BuildError, Row

# Shares this close are a tie. FNDDS builds its unspecified foods as equal
# blends, and equal weights summed in different orders differ in the last bits.
_TIE = 1e-9


@dataclass(frozen=True)
class Attribution:
    """Where an FNDDS food counts: its families, more than one when they tie
    for the largest weight; the variants that carried the most of each; and
    the share of the food's weight that reached no row of the table."""

    families: frozenset[str]
    variants: frozenset[str]
    unattributed: float


@dataclass(frozen=True)
class Popularity:
    """The participants with a reliable recall, and how many of them reported
    each family and each variant."""

    participants: int
    families: dict[str, int]
    variants: dict[str, int]


def load_recipes(folder: Path) -> dict[str, list[tuple[str, float]]]:
    """Each FNDDS food code with its ingredients as (code, grams); an
    ingredient's code is an NDB number or another FNDDS food's code."""
    with (folder / "survey_fndds_food.csv").open(newline="", encoding="utf-8") as f:
        codes = {r["fdc_id"]: r["food_code"] for r in csv.DictReader(f)}
    recipes: dict[str, list[tuple[str, float]]] = {c: [] for c in codes.values()}
    with (folder / "input_food.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ingredient = (r["sr_code"], float(r["gram_weight"]))
            recipes[codes[r["fdc_id"]]].append(ingredient)
    return recipes


def reliable_reports(path: Path, day: int) -> Iterator[tuple[int, str]]:
    """(participant, food code) for every food row of a reliable recall."""
    columns = ("SEQN", f"DR{day}DRSTZ", f"DR{day}IFDCD")
    for participant, status, code in read_xpt(path, columns):
        if status == 1 and participant is not None and code is not None:
            yield int(participant), str(int(code))


def attribute(
    recipes: Mapping[str, Sequence[tuple[str, float]]],
    rows: Sequence[Row],
    water: Collection[str],
    count_as: Mapping[str, str],
) -> dict[str, Attribution]:
    """Each FNDDS food's families: the heaviest among its ingredients' families
    outside water, every one of them when several tie, or water when the food
    is all water. A family in count_as then counts as its target. A food none
    of whose weight reaches a row counts nowhere, all of it unattributed."""
    known = {r.family for r in rows}
    candidates = {r.family for r in rows if r.exclusion_reason is None}
    stale = [
        f"{source} -> {target}"
        for source, target in count_as.items()
        if target in count_as or source not in known or target not in candidates
    ]
    if stale:
        raise BuildError(f"count_as no longer fits the data: {stale}")
    by_ndb = {r.ndb: r for r in rows if r.ndb}
    attributions = {}
    for code in recipes:
        shares = _shares(code, recipes, by_ndb, ())
        weights: dict[str, float] = defaultdict(float)
        carried: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for row, share in shares.items():
            if row is not None:
                weights[row.family] += share
                carried[row.family][row.variant] += share
        families = _heaviest(
            {f: w for f, w in weights.items() if f not in water} or weights
        )
        variants = {
            variant for family in families for variant in _heaviest(carried[family])
        }
        attributions[code] = Attribution(
            frozenset(count_as.get(family, family) for family in families),
            frozenset(variants),
            shares.get(None, 0.0),
        )
    return attributions


def count(
    reports: Iterable[tuple[int, str]], attributions: Mapping[str, Attribution]
) -> Popularity:
    """Distinct participants: all of them, then per family and per variant."""
    everyone: set[int] = set()
    families: dict[str, set[int]] = defaultdict(set)
    variants: dict[str, set[int]] = defaultdict(set)
    for participant, code in reports:
        everyone.add(participant)
        for family in attributions[code].families:
            families[family].add(participant)
        for variant in attributions[code].variants:
            variants[variant].add(participant)
    return Popularity(
        len(everyone),
        {family: len(people) for family, people in families.items()},
        {variant: len(people) for variant, people in variants.items()},
    )


def _heaviest[K](weights: Mapping[K, float]) -> list[K]:
    """The keys at the largest weight: one, every key that ties for it, or
    none when there is no weight to compare."""
    top = max(weights.values(), default=0.0)
    return [key for key, weight in weights.items() if top - weight <= _TIE]


def _shares(
    code: str,
    recipes: Mapping[str, Sequence[tuple[str, float]]],
    by_ndb: Mapping[str, Row],
    above: tuple[str, ...],
) -> dict[Row | None, float]:
    """The share of an FNDDS food's weight each table row carries, nested
    recipes expanded. None holds what reaches no row: an ingredient the table
    lacks, a recipe that contains itself, or a food with no weight at all."""
    parts = recipes[code]
    total = sum(grams for _, grams in parts)
    if not total:
        return {None: 1.0}
    inside = (*above, code)
    shares: dict[Row | None, float] = defaultdict(float)
    for child, grams in parts:
        if child in recipes and child not in inside:
            for row, share in _shares(child, recipes, by_ndb, inside).items():
                shares[row] += share * grams / total
        else:
            shares[by_ndb.get(child)] += grams / total
    return shares
