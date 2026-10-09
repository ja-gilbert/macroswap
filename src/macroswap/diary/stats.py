"""Coverage, untracked days, the head/tail shape of distinct food names, and
the counted rows a swap reads."""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta

# Counted rows, as the README's Diary section defines them: tracked days, quick
# adds excluded. The name is the brand and food text together, which is also
# the matcher's input.
_NAME = """lower(CASE WHEN r.brand IS NULL THEN r.food_text
                  ELSE r.brand || ' - ' || r.food_text END)"""
_COUNTED = """FROM diary_rows AS r
JOIN diary_days AS d ON d.date = r.date
WHERE d.untracked = 0 AND r.is_quick_add = 0"""
_NAME_COUNTS_SQL = f"""
SELECT {_NAME} AS name, count(*) AS n
{_COUNTED}
GROUP BY name
ORDER BY n DESC, name
"""
_COUNTED_ROWS_SQL = f"""
SELECT {_NAME} AS name, r.date, r.protein, r.carbs, r.fat, r.lean_pct
{_COUNTED}
"""


def counted_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Each counted row as a swap reads it: its name, day, logged protein,
    carbs and fat, and leanness level."""
    return conn.execute(_COUNTED_ROWS_SQL).fetchall()


@dataclass(frozen=True)
class DiaryStats:
    files: int
    covered_from: date | None
    covered_to: date | None
    gap_days: tuple[date, ...]
    overlap_days: tuple[date, ...]
    empty_covered_days: tuple[date, ...]
    days_with_rows: int
    untracked_days: int
    rows: int
    distinct_names: int
    names_for_share: tuple[tuple[float, int], ...]


def compute_stats(conn: sqlite3.Connection, shares: tuple[float, ...]) -> DiaryStats:
    """Read the tables back: what the files cover, and what the rows look like."""
    files = conn.execute("SELECT from_date, to_date FROM diary_files").fetchall()
    coverage: Counter[date] = Counter()
    for row in files:
        coverage.update(
            _days_between(
                date.fromisoformat(row["from_date"]), date.fromisoformat(row["to_date"])
            )
        )
    untracked_by_day = {
        date.fromisoformat(row["date"]): row["untracked"]
        for row in conn.execute("SELECT date, untracked FROM diary_days")
    }
    covered_from = min(coverage, default=None)
    covered_to = max(coverage, default=None)
    gaps: tuple[date, ...] = ()
    if covered_from is not None and covered_to is not None:
        gaps = tuple(
            day
            for day in _days_between(covered_from, covered_to)
            if day not in coverage
        )
    counts = [n for _, n in name_counts(conn)]
    return DiaryStats(
        files=len(files),
        covered_from=covered_from,
        covered_to=covered_to,
        gap_days=gaps,
        overlap_days=tuple(sorted(day for day, n in coverage.items() if n > 1)),
        empty_covered_days=tuple(
            day for day in sorted(coverage) if day not in untracked_by_day
        ),
        days_with_rows=len(untracked_by_day),
        untracked_days=sum(untracked_by_day.values()),
        rows=conn.execute("SELECT count(*) AS n FROM diary_rows").fetchone()["n"],
        distinct_names=len(counts),
        names_for_share=tuple((share, names_needed(counts, share)) for share in shares),
    )


def name_counts(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    """Each distinct name and its counted rows, most-logged first, then by name."""
    return [(row["name"], row["n"]) for row in conn.execute(_NAME_COUNTS_SQL)]


def format_stats(stats: DiaryStats) -> str:
    covering = (
        f"{stats.covered_from} .. {stats.covered_to}"
        if stats.covered_from and stats.covered_to
        else "nothing"
    )
    lines = [
        f"files: {stats.files}, covering {covering}",
        f"gap days: {_counted(stats.gap_days)}",
        f"overlap days: {_counted(stats.overlap_days)}",
        f"empty covered days: {_counted(stats.empty_covered_days)}",
        f"days with rows: {stats.days_with_rows}, untracked: {stats.untracked_days}, "
        f"rows: {stats.rows}",
        f"distinct names: {stats.distinct_names}",
    ]
    lines.extend(
        f"names covering {share:.0%} of rows: {needed}"
        for share, needed in stats.names_for_share
    )
    return "\n".join(lines)


def names_needed(counts_desc: list[int], share: float) -> int:
    """How many of the most-logged names it takes to reach this share of rows."""
    total = sum(counts_desc)
    running = 0
    for needed, count in enumerate(counts_desc, start=1):
        running += count
        if running >= share * total:
            return needed
    return len(counts_desc)


def _counted(days: tuple[date, ...], limit: int = 10) -> str:
    """The count, then the days themselves: "2 (2026-08-04, 2026-08-06)"."""
    if not days:
        return "0"
    shown = ", ".join(day.isoformat() for day in days[:limit])
    more = f", +{len(days) - limit} more" if len(days) > limit else ""
    return f"{len(days)} ({shown}{more})"


def _days_between(start: date, end: date) -> list[date]:
    return [start + timedelta(days=n) for n in range((end - start).days + 1)]
