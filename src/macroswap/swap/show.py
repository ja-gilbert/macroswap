"""A swap as text: a header that says what the target is and how it was
found, then the families, the common tier first.

No line carries a single distance: a row shows its grams and its four deltas,
so a reader sees which macro a swap misses and by how much.
"""

from __future__ import annotations

from collections.abc import Mapping

from macroswap.swap.rank import DefaultLevel, Offer, Ranking
from macroswap.swap.target import Resolved

DIVIDER = "-- less common --"


def header(resolved: Resolved, amount: str, fallback: str = "") -> list[str]:
    """The target and its amount; its row, or the family alone a diary food
    matched; what resolved it and, when the default method could not load, why;
    its macros; the level a leanness family was read at; the notes on how it
    was resolved; and the days and names behind a median."""
    target, row, level = resolved.target, resolved.row, resolved.level
    macros = target.macros
    family = f"; family {target.family}" if target.family else ""
    lines = [
        f"target: {resolved.key} ({amount})",
        f"row: {row.id} {row.description}" if row else f"row: none{family}",
        f"method: {resolved.source}{fallback}",
        f"macros: protein {macros.protein:.1f} g, carbs {macros.carbs:.1f} g, "
        f"fat {macros.fat:.1f} g",
    ]
    if level:
        lines.append(f"level: {level.lean_pct}/{100 - level.lean_pct}, {level.source}")
    lines += resolved.notes
    if resolved.names:
        days = " to ".join(resolved.window) if resolved.window else "the whole diary"
        names = "; ".join(f"{name} ({n})" for name, n in resolved.names)
        lines.append(f"logged: {days}; rows per name: {names}")
    return lines


def table(ranking: Ranking, levels: Mapping[str, DefaultLevel]) -> list[str]:
    """The common tier, a divider, then the rest. Under a family's best offer
    come its other variants when asked for, and for a leanness family whose
    best is at another level, its default level and where that came from."""
    lines = []
    for tier in (ranking.common, ranking.rest):
        if tier and tier is ranking.rest:
            lines.append(DIVIDER)
        for family in tier:
            lines.append(_offer(family.best))
            lines += [
                f"    {_offer(other)}"
                for other in family.others
                if other is not family.default_level
            ]
            if family.default_level:
                source = levels[family.best.candidate.row.family].source
                default = _offer(family.default_level)
                lines.append(f"    default level ({source}): {default}")
    return lines


def _offer(offer: Offer) -> str:
    """One offer as a line; a cooked, canned or dry serving names its state
    beside the grams so it is not read as raw weight."""
    row, delta = offer.candidate.row, offer.fit.delta
    state = "" if row.as_bought == "raw" else f" {row.as_bought}"
    same_food = " (same food)" if offer.same_food else ""
    count = offer.candidate.popularity
    return "  ".join(
        [
            f"{offer.fit.grams:.0f} g{state}",
            f"{row.variant}{same_food}",
            f"protein {delta.protein:+z.1f}",
            f"carbs {delta.carbs:+z.1f}",
            f"fat {delta.fat:+z.1f}",
            f"kcal {offer.fit.kcal_delta:+z.0f}",
            f"count {'n/a' if count is None else count}",
            row.provenance,
        ]
    )
