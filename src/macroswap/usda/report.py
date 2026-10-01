"""What `data build` produced, and what to decide next: the family report.

Varietal override candidates and Foundation alias candidates are measured, not
guessed, so the config lists they feed are chosen from data. Spec 4.2.
"""

from __future__ import annotations

import math
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import astuple
from statistics import median

from macroswap.swap.fit import Macros

_MACROS = ("protein", "carbs", "fat")
_STOP_WORDS = frozenset({"and", "or", "with", "in"})


def family_report(conn: sqlite3.Connection, weights: Macros, threshold: float) -> str:
    rows = conn.execute(
        "SELECT source, family, exclusion_reason, as_bought, protein, carbs, fat "
        "FROM usda_foods"
    ).fetchall()
    per_family = Counter(r["family"] for r in rows)
    reasons = Counter(r["exclusion_reason"] for r in rows)
    candidates = reasons.pop(None, 0)
    lines = [
        f"rows in the matcher index: {len(rows)}",
        f"candidates: {candidates}",
        f"families: {len(per_family)}, of which single-row: "
        f"{sum(n == 1 for n in per_family.values())}",
        "largest families: "
        + "; ".join(f"{f} ({n})" for f, n in per_family.most_common(10)),
        "exclusion reasons:",
        *(f"  {reason}: {n}" for reason, n in reasons.most_common()),
        *_varietal(_representatives(rows, "raw"), astuple(weights), threshold),
        *_alias_candidates(rows, _representatives(rows), astuple(weights)),
    ]
    return "\n".join(lines)


def _representatives(
    rows: list[sqlite3.Row], state: str | None = None
) -> dict[str, tuple[float, ...]]:
    """Each family's median candidate macros per 100 g, over one as_bought
    state when given, so a dried variety cannot mask the raw ones."""
    by_family: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in rows:
        if r["exclusion_reason"] is None and (state is None or r["as_bought"] == state):
            by_family[r["family"]].append(r)
    return {
        family: tuple(median(r[m] for r in members) for m in _MACROS)
        for family, members in by_family.items()
    }


def _distance(
    a: tuple[float, ...], b: tuple[float, ...], weights: tuple[float, ...]
) -> float:
    """The rank score between two foods at 100 g each (spec 4.5)."""
    return math.sqrt(
        sum(w * (x - y) ** 2 for w, x, y in zip(weights, a, b, strict=True))
    )


def _varietal(
    macros: dict[str, tuple[float, ...]], weights: tuple[float, ...], threshold: float
) -> list[str]:
    """Field-one groups whose families cluster within the threshold: each
    group's largest cluster, by its share of the group."""
    groups: dict[str, list[str]] = defaultdict(list)
    for family in macros:
        groups[family.split(", ")[0]].append(family)
    flagged = []
    for head, families in groups.items():
        cluster = _largest_cluster(families, macros, weights, threshold)
        if len(cluster) > 1:
            flagged.append((-len(cluster) / len(families), head, families, cluster))
    return [
        f"varietal override candidates (raw families within {threshold:g}): "
        f"{len(flagged)}",
        *(
            f"  {head}: {len(cluster)} of {len(families)} raw families: "
            + "; ".join(cluster)
            for _, head, families, cluster in sorted(flagged)
        ),
    ]


def _largest_cluster(
    families: list[str],
    macros: dict[str, tuple[float, ...]],
    weights: tuple[float, ...],
    threshold: float,
) -> list[str]:
    """Single linkage: a family joins a cluster when it is within the threshold
    of any member, so a spread of varieties is not masked by its ends."""
    left = set(families)
    best: list[str] = []
    while left:
        start = min(left)  # by name, so a size tie resolves the same way each run
        left.remove(start)
        cluster: list[str] = []
        frontier = [start]
        while frontier:
            family = frontier.pop()
            cluster.append(family)
            near = {
                g
                for g in left
                if _distance(macros[family], macros[g], weights) < threshold
            }
            left -= near
            frontier += near
        best = max(best, sorted(cluster), key=len)
    return best


def _alias_candidates(
    rows: list[sqlite3.Row],
    macros: dict[str, tuple[float, ...]],
    weights: tuple[float, ...],
) -> list[str]:
    sources: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        sources[r["family"]].add(r["source"])
    # Only SR families with candidates are worth aliasing into.
    sr_words = {f: _words(f) for f, s in sources.items() if "sr" in s and f in macros}
    foundation_only = sorted(f for f, s in sources.items() if s == {"foundation"})
    lines = [f"foundation-only families: {len(foundation_only)}"]
    for family in foundation_only:
        words = _words(family)
        ranked = sorted(
            (-len(common), _macro_gap(family, sr, macros, weights), sr)
            for sr, theirs in sr_words.items()
            if (common := words & theirs)
        )[:3]
        shown = "; ".join(
            f"{sr} (shared words {-shared}, distance {gap:.0f})"
            for shared, gap, sr in ranked
        )
        lines.append(f"  {family} -> {shown or 'no SR family shares a word'}")
    return lines


def _words(family: str) -> set[str]:
    return {_singular(w) for w in re.findall(r"[a-z]+", family)} - _STOP_WORDS


def _singular(word: str) -> str:
    # Enough to put "potatoes" beside "potato" and "mushrooms" beside "mushroom".
    if word.endswith("oes"):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _macro_gap(
    a: str, b: str, macros: dict[str, tuple[float, ...]], weights: tuple[float, ...]
) -> float:
    if a in macros and b in macros:
        return _distance(macros[a], macros[b], weights)
    return math.inf
