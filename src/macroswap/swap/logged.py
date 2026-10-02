"""A swap's target from the diary: a food as it was logged.

The target is the median of what was logged, each macro on its own, so grams
are never needed and the target need not be a row a swap could offer, or a
USDA row at all.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from difflib import get_close_matches
from pathlib import Path
from statistics import median

from macroswap.config import Config
from macroswap.diary.normalize import name_key
from macroswap.diary.stats import counted_rows
from macroswap.match.diary import check_fingerprint
from macroswap.match.matcher import Matcher
from macroswap.swap.fit import Macros
from macroswap.swap.rank import DefaultLevel
from macroswap.swap.target import Resolved, TargetError, find, resolved, target_at
from macroswap.usda.table import Row

_MACROS = ("protein", "carbs", "fat")


@dataclass(frozen=True)
class Diary:
    """What a swap reads of the diary: each counted name's match, and every
    counted row with its logged macros."""

    matches: Mapping[str, sqlite3.Row]
    logged: Sequence[sqlite3.Row]


def read_diary(conn: sqlite3.Connection, config: Config) -> Diary:
    """The matched diary, refused when its matches are stale. A store with no
    counted rows has nothing to match, so nothing to refuse."""
    logged = counted_rows(conn)
    if not logged:
        return Diary({}, [])
    check_fingerprint(conn, config.match, Path(config.paths.labels))
    matches = conn.execute(
        "SELECT name, usda_id, family, variant, as_bought FROM diary_matches"
    )
    return Diary({m["name"]: m for m in matches}, logged)


def diary_families(diary: Diary) -> tuple[frozenset[str], int]:
    """The families the diary's matched names resolved to, and how many names
    resolved to none."""
    families = [m["family"] for m in diary.matches.values()]
    return frozenset(filter(None, families)), families.count(None)


def default_levels(
    diary: Diary, rows: Sequence[Row], config: Config
) -> dict[str, DefaultLevel]:
    """Per leanness family, the level logged most often in the window, then in
    the whole diary, then the configured default. A logged level counts only
    when the family has a candidate at it; on a tie the leaner level wins."""
    days = config.swap.diary_window_days
    levels = {}
    for lean in config.usda.leanness:
        # None is the family's row without a level, and a row logged without one.
        offered = {
            r.lean_pct
            for r in rows
            if r.family == lean.family and r.exclusion_reason is None
        } - {None}
        names = {n for n, m in diary.matches.items() if m["family"] == lean.family}
        logged = [
            r for r in diary.logged if r["name"] in names and r["lean_pct"] in offered
        ]
        recent, window = _recent(logged, diary, days)
        counts = Counter(r["lean_pct"] for r in recent)
        if counts:
            span = f"last {days} days" if window else "all time"
            level = max(counts, key=lambda pct: (counts[pct], pct))
            levels[lean.family] = DefaultLevel(level, f"your diary, {span}")
        else:
            default = int(lean.default.partition("/")[0])
            levels[lean.family] = DefaultLevel(default, "config default")
    return levels


def like_log(
    text: str,
    diary: Diary,
    rows: Sequence[Row],
    matcher: Matcher,
    method: str,
    config: Config,
    levels: Mapping[str, DefaultLevel],
) -> Resolved:
    """The typed food as the diary logs it: the medians over every diary name
    that resolved to the same variant, or for a text that resolved to a family,
    to that family, at whatever levels it was logged."""
    food = find(text, rows, matcher, method, config, levels)
    column, value = "variant", food.variant
    if value is None:
        column, value = "family", food.row.family
    names = {n for n, m in diary.matches.items() if m[column] == value}
    days = config.swap.diary_window_days
    macros, window, counts = _medians(diary, names, days, food.key)
    food = replace(food, level=None)
    return resolved(food, macros, config.usda.role_share_threshold, window, counts)


def entry(name: str, diary: Diary, rows: Sequence[Row], config: Config) -> Resolved:
    """The diary food of that name at the medians of its logged rows. A name
    nothing matched has no family to leave out, and its pools are the ones its
    medians reach."""
    # The store lower-cases ASCII letters only, so compare names lowered here.
    typed = name_key(name)
    stored = {n.lower(): n for n in diary.matches}
    if typed not in stored:
        containing = [n for n in diary.matches if typed in n.lower()]
        near = containing[:5] or get_close_matches(typed, diary.matches, 5)
        hint = f"; near: {'; '.join(near)}" if near else ""
        raise TargetError(f"no diary food named {typed!r}{hint}")
    key = stored[typed]
    days = config.swap.diary_window_days
    macros, window, counts = _medians(diary, {key}, days, key)
    match = diary.matches[key]
    family = match["family"] or ""
    row = next((r for r in rows if r.id == match["usda_id"]), None)
    roles = next((r.roles for r in rows if r.family == family and r.roles), "")
    threshold = config.usda.role_share_threshold
    target = target_at(key, macros, family, match["variant"], roles, threshold)
    return Resolved(target, row, key, "diary", None, (), window, counts)


def _recent(
    logged: Sequence[sqlite3.Row], diary: Diary, days: int
) -> tuple[Sequence[sqlite3.Row], tuple[str, str] | None]:
    """The rows inside the window ending at the diary's last counted day, with
    the window's two days; every row and no window when none is inside."""
    if not diary.logged:
        return logged, None
    last = date.fromisoformat(max(r["date"] for r in diary.logged))
    first = (last - timedelta(days=days - 1)).isoformat()
    recent = [r for r in logged if r["date"] >= first]
    return (recent, (first, last.isoformat())) if recent else (logged, None)


def _medians(
    diary: Diary, names: Collection[str], days: int, key: str
) -> tuple[Macros, tuple[str, str] | None, tuple[tuple[str, int], ...]]:
    """The median of each macro over the names' rows that log all three, with
    the window and the rows each name gave."""
    usable = [
        r
        for r in diary.logged
        if r["name"] in names and None not in [r[m] for m in _MACROS]
    ]
    if not usable:
        raise TargetError(
            f"no diary row for {key} logs protein, carbs and fat; give --grams "
            "against a matched food instead"
        )
    rows, window = _recent(usable, diary, days)
    macros = Macros(*(median(r[m] for r in rows) for m in _MACROS))
    counts = Counter(r["name"] for r in rows)
    return macros, window, tuple(sorted(counts.items(), key=lambda c: (-c[1], c[0])))
