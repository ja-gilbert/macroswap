from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from macroswap.config import load_config
from macroswap.diary.importer import import_directory, import_file
from macroswap.diary.stats import compute_stats, format_stats
from macroswap.store import connect

CONFIG = load_config().diary
SHARES = (0.5, 0.8, 0.95)


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    return connect(tmp_path / "macroswap.sqlite")


def test_empty_database(conn: sqlite3.Connection) -> None:
    stats = compute_stats(conn, SHARES)
    assert (stats.files, stats.rows) == (0, 0)
    assert (stats.covered_from, stats.covered_to) == (None, None)
    assert stats.names_for_share == ((0.5, 0), (0.8, 0), (0.95, 0))


def test_coverage_gaps_overlaps_empty_days_and_shape(
    conn: sqlite3.Connection, fixtures_dir: Path
) -> None:
    """Three exports covering Aug 1-2, 2-3 and 5-6: Aug 4 is a gap, Aug 2 an
    overlap, and Aug 6 is covered by a file but carries no rows."""
    import_directory(conn, fixtures_dir, CONFIG)
    stats = compute_stats(conn, SHARES)
    assert stats.files == 3
    assert stats.covered_from == date(2026, 8, 1)
    assert stats.covered_to == date(2026, 8, 6)
    assert stats.gap_days == (date(2026, 8, 4),)
    assert stats.overlap_days == (date(2026, 8, 2),)
    assert stats.empty_covered_days == (date(2026, 8, 6),)
    assert (stats.days_with_rows, stats.untracked_days, stats.rows) == (4, 0, 13)
    assert stats.distinct_names == 10
    assert stats.names_for_share == ((0.5, 4), (0.8, 8), (0.95, 10))


def test_untracked_days_and_quick_adds_are_excluded_from_names(
    conn: sqlite3.Connection, fixtures_dir: Path
) -> None:
    import_file(conn, fixtures_dir / "mfp_2026-08-01_2026-08-02.html", CONFIG)
    stats = compute_stats(conn, SHARES)
    assert (stats.days_with_rows, stats.untracked_days, stats.rows) == (2, 1, 8)
    assert stats.distinct_names == 6, "Aug 2 is untracked, so its banana is not counted"


def test_format_is_one_fact_per_line(
    conn: sqlite3.Connection, fixtures_dir: Path
) -> None:
    import_directory(conn, fixtures_dir, CONFIG)
    text = format_stats(compute_stats(conn, SHARES))
    assert "files: 3, covering 2026-08-01 .. 2026-08-06" in text
    assert "gap days: 1 (2026-08-04)" in text
    assert "overlap days: 1 (2026-08-02)" in text
    assert "empty covered days: 1 (2026-08-06)" in text
    assert "days with rows: 4, untracked: 0, rows: 13" in text
    assert "distinct names: 10" in text
    assert "names covering 50% of rows: 4" in text
    assert "names covering 95% of rows: 10" in text
