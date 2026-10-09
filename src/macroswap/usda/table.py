"""The USDA food table: every row with its keys, roles and exclusion reason.

The matcher indexes every row; `exclusion_reason` says which rows a swap may
offer. The first applicable reason in REASONS wins; the README's USDA Table
section names each.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, replace
from itertools import pairwise

from macroswap.config import Leanness, UsdaConfig
from macroswap.diary.normalize import parse_leanness
from macroswap.usda.keys import (
    FieldRules,
    Fields,
    cooked_family,
    family_key,
    plain,
    split_fields,
    variant_key,
)
from macroswap.usda.load import Food

REASONS = (
    "analytical-duplicate",
    "cooked-with-raw-sibling",
    "excluded-category",
    "excluded-part",
    "zero-macro",
    "incomplete-macros",
)
_POOLS = ("protein", "starch", "sugar", "fat")


class BuildError(ValueError):
    """The configuration no longer fits the data it keys."""


@dataclass(frozen=True)
class Row:
    id: str
    source: str
    ndb: str | None
    description: str
    category: str
    family: str
    variant: str
    lean_pct: int | None
    provenance: str
    as_bought: str
    protein: float | None
    carbs: float | None
    fat: float | None
    fiber: float | None
    sugars: float | None
    kcal: float | None
    roles: str
    exclusion_reason: str | None


@dataclass(frozen=True)
class _Keyed:
    """A food with its keys. An alias changes the family, so the grouping and
    the count, and not the name a swap prints: the variant keeps the row's own
    spelling. The aliased variant serves the duplicate check, and a duplicate,
    which restates an SR row and is never offered, reads as that row."""

    food: Food
    fields: Fields
    unaliased: str
    family: str
    variant: str
    aliased_variant: str
    level: str | None
    cooked_sibling: bool


def build_table(foods: list[Food], usda: UsdaConfig) -> list[Row]:
    rules = FieldRules(usda)
    leanness = {lean.family: lean for lean in usda.leanness}
    fielded = [(f, rules.fields(f.description)) for f in foods]
    # A cooked row whose first field some row in another state shares is that
    # food cooked, not a food sold cooked.
    other_state = {family_key(fl, 1) for _, fl in fielded if fl.as_bought != "cooked"}
    keyed = [
        _key(f, fl, rules, leanness, usda.family_aliases, other_state)
        for f, fl in fielded
    ]
    _check_aliases(keyed, usda.family_aliases)
    _check_anchors(keyed, leanness)
    sr_variants = {k.aliased_variant for k in keyed if k.food.source == "sr"}
    rows = [
        _row(k, _reason(k, usda, sr_variants), leanness.get(k.family)) for k in keyed
    ]
    rows += [d for lean in usda.leanness for d in _derived(lean, rows)]
    return _with_roles(rows, usda.role_share_threshold, usda.sugar_pool_share)


def _key(
    food: Food,
    fields: Fields,
    rules: FieldRules,
    leanness: dict[str, Leanness],
    aliases: dict[str, str],
    other_state: set[str],
) -> _Keyed:
    cooked_sibling = (
        fields.as_bought == "cooked"
        and not fields.sold_cooked
        and family_key(fields, 1) in other_state
    )
    if fields.as_bought == "cooked" and not cooked_sibling:
        fields, depth = cooked_family(fields), 2
    else:
        depth = rules.depth(fields)
    unaliased = family_key(fields, depth)
    family = aliases.get(unaliased, unaliased)
    level = _level(food, leanness.get(family))
    variant = variant_key(unaliased, fields, depth, level)
    aliased_variant = variant_key(family, fields, depth, level)
    return _Keyed(
        food, fields, unaliased, family, variant, aliased_variant, level, cooked_sibling
    )


def _level(food: Food, lean: Leanness | None) -> str | None:
    """A leanness family's level: an SR anchor's label, else the description's."""
    if lean is None:
        return None
    if food.source == "sr" and food.ndb in lean.anchors:
        return lean.anchors[food.ndb]
    pct = parse_leanness(food.description)
    return None if pct is None else f"{pct}/{100 - pct}"


def _reason(k: _Keyed, usda: UsdaConfig, sr_variants: set[str]) -> str | None:
    """The first applicable reason in REASONS; the two key-based ones lead. A
    Foundation row is a duplicate when its aliased variant is an SR row's, so
    a parallel spelling of an SR food restates it."""
    f = k.food
    if f.source == "foundation" and k.aliased_variant in sr_variants:
        return "analytical-duplicate"
    if k.cooked_sibling:
        return "cooked-with-raw-sibling"
    if category_excluded(f, deny_key(k.fields, usda.family_aliases), usda):
        return "excluded-category"
    if part_denied(f, usda):
        return "excluded-part"
    macros = (f.protein, f.carbs, f.fat)
    if macros == (0.0, 0.0, 0.0):
        return "zero-macro"
    if None in macros:
        return "incomplete-macros"
    return None


def category_excluded(food: Food | Row, key: str, usda: UsdaConfig) -> bool:
    """Whether the food's category, or a word its category denies in the key
    given, leaves it out; an allow word in the description clears it."""
    text = plain(food.description.lower())
    if any(_has(w, text) for w in usda.allow_words.get(food.category, [])):
        return False
    return food.category in usda.excluded_categories or any(
        _has(w, key) for w in usda.deny_words.get(food.category, [])
    )


def part_denied(food: Food | Row, usda: UsdaConfig) -> bool:
    """Whether a field of the description, whole and exactly as written, names
    a part its category denies: skin is such a field, skinless is not."""
    denied = usda.deny_fields.get(food.category, [])
    return any(field in denied for field in split_fields(food.description.lower()))


def deny_key(fields: Fields, aliases: Mapping[str, str]) -> str:
    """The key a deny word is matched against: the row's own two fields, under
    an alias where one names them, before any depth-one cut. A deny word is
    about the row's own name, not the family it is folded into, so a denied
    kind stays denied inside that family; an alias is the same food under
    another spelling, so both spellings are judged alike."""
    key = family_key(fields, 2)
    return aliases.get(key, key)


def _has(phrase: str, text: str) -> bool:
    return re.search(rf"\b{re.escape(phrase)}\b", text) is not None


def _row(k: _Keyed, reason: str | None, lean: Leanness | None) -> Row:
    f = k.food
    variant = k.aliased_variant if reason == "analytical-duplicate" else k.variant
    if f.source == "foundation":
        provenance = "foundation"
    elif lean is not None and lean.nominal:
        provenance = "sr-formula"
    else:
        provenance = "sr-analytical"
    return Row(
        id=f.id,
        source=f.source,
        ndb=f.ndb,
        description=f.description,
        category=f.category,
        family=k.family,
        variant=variant,
        lean_pct=_pct(k.level),
        provenance=provenance,
        as_bought=k.fields.as_bought,
        protein=f.protein,
        carbs=f.carbs,
        fat=f.fat,
        fiber=f.fiber,
        sugars=f.sugars,
        kcal=f.kcal,
        roles="",
        exclusion_reason=reason,
    )


def _derived(lean: Leanness, rows: list[Row]) -> list[Row]:
    """Retail levels between anchors, by linear interpolation of each nutrient."""
    anchors = sorted(
        (r for r in rows if r.source == "sr" and r.ndb in lean.anchors),
        key=lambda r: r.lean_pct or 0,
    )
    spans = [(a.lean_pct or 0, b.lean_pct or 0, a, b) for a, b in pairwise(anchors)]
    out = []
    for level in lean.retail:
        pct = _pct(level) or 0
        span = next((s for s in spans if s[0] < pct < s[1]), None)
        if span is None:
            raise BuildError(
                f"retail level {level} of {lean.family} is not between two anchors"
            )
        lo, hi, a, b = span
        t = (pct - lo) / (hi - lo)
        anchor_levels = ", ".join(r.variant.rsplit(", ", 1)[-1] for r in (a, b))
        out.append(
            Row(
                id=f"derived:{lean.family}:{level}",
                source="derived",
                ndb=None,
                description=f"{lean.family.capitalize()}, {level}",
                category=a.category,
                family=lean.family,
                variant=f"{lean.family}, {level}",
                lean_pct=pct,
                provenance=f"derived({anchor_levels})",
                as_bought="raw",
                protein=_lerp(a.protein, b.protein, t),
                carbs=_lerp(a.carbs, b.carbs, t),
                fat=_lerp(a.fat, b.fat, t),
                fiber=_lerp(a.fiber, b.fiber, t),
                sugars=_lerp(a.sugars, b.sugars, t),
                kcal=_lerp(a.kcal, b.kcal, t),
                roles="",
                exclusion_reason=None,
            )
        )
    return out


def _with_roles(rows: list[Row], threshold: float, sugar_cut: float) -> list[Row]:
    """A family joins every pool any of its candidates reaches, and every row
    of the family with usable macros carries the family's roles. Its carbs
    are sugar or starch by one share: the summed sugars of its candidates that
    carry a sugars value over those candidates' summed carbs.

    Rows without all three macros, or with all three at zero, get no roles
    whatever reason they record.
    """
    pools: dict[str, set[str]] = defaultdict(set)
    sugars: dict[str, float] = defaultdict(float)
    carbs: dict[str, float] = defaultdict(float)
    for r in rows:
        if r.exclusion_reason is None and _macros_usable(r):
            pools[r.family] |= pools_of(
                r.protein or 0.0, r.carbs or 0.0, r.fat or 0.0, threshold
            )
            if r.sugars is not None:
                sugars[r.family] += r.sugars
                carbs[r.family] += r.carbs or 0.0
    for family, found in pools.items():
        share = sugars[family] / carbs[family] if carbs[family] else None
        pools[family] = split_carbs(found, share, sugar_cut)
    return [
        replace(r, roles=",".join(p for p in _POOLS if p in pools[r.family]))
        if _macros_usable(r)
        else r
        for r in rows
    ]


def _macros_usable(r: Row) -> bool:
    macros = (r.protein, r.carbs, r.fat)
    return None not in macros and macros != (0.0, 0.0, 0.0)


def pools_of(protein: float, carbs: float, fat: float, threshold: float) -> set[str]:
    """The pools a food's macros reach: the one giving most of its calories,
    and any giving at least the threshold share of them."""
    kcal = {"protein": 4 * protein, "carbs": 4 * carbs, "fat": 9 * fat}
    total = sum(kcal.values())
    dominant = max(kcal, key=lambda p: kcal[p])
    return {dominant} | {p for p, v in kcal.items() if v / total >= threshold}


def split_carbs(pools: set[str], sugar_share: float | None, cut: float) -> set[str]:
    """The carb pool as sugar or starch: sugar at or above the cut, starch
    below it or where no sugars value is known."""
    if "carbs" not in pools:
        return pools
    pool = "sugar" if sugar_share is not None and sugar_share >= cut else "starch"
    return pools - {"carbs"} | {pool}


def _check_aliases(keyed: list[_Keyed], aliases: dict[str, str]) -> None:
    families = {k.unaliased for k in keyed}
    stale = [
        f"{src} -> {dst}"
        for src, dst in aliases.items()
        if src == dst or src not in families or dst not in families
    ]
    if stale:
        raise BuildError(f"family_aliases no longer fit the data: {stale}")


def _check_anchors(keyed: list[_Keyed], leanness: dict[str, Leanness]) -> None:
    for lean in leanness.values():
        for ndb in lean.anchors:
            hits = [k for k in keyed if k.food.source == "sr" and k.food.ndb == ndb]
            if len(hits) != 1 or hits[0].family != lean.family:
                raise BuildError(
                    f"{lean.family} anchor NDB {ndb} matches {len(hits)} SR rows "
                    f"in families {sorted({k.family for k in hits})}"
                )


def _pct(level: str | None) -> int | None:
    return None if level is None else int(level.split("/")[0])


def _lerp(a: float | None, b: float | None, t: float) -> float | None:
    return None if a is None or b is None else a + (b - a) * t
