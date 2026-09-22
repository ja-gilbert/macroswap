from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from macroswap.config import load_config
from macroswap.diary.importer import DiaryImportError, import_directory, import_file
from macroswap.store import connect

CONFIG = load_config().diary


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    return connect(tmp_path / "macroswap.sqlite")


def test_rows_are_normalized_and_days_are_flagged(
    conn: sqlite3.Connection, fixtures_dir: Path
) -> None:
    """Rows carry brand, food text, grams, leanness and the quick-add flag;
    days carry calories, quick-add calories, the untracked flag and the total."""
    report = import_file(conn, fixtures_dir / "mfp_2026-08-01_2026-08-02.html", CONFIG)
    assert (report.days, report.rows, report.reconciled_days) == (2, 8, 2)
    assert (report.untracked_days, report.total_mismatches) == (1, 0)
    chicken, potatoes, cheddar, rice, beef, eggs = conn.execute(
        "SELECT * FROM diary_rows WHERE date = '2026-08-01' ORDER BY position"
    ).fetchall()
    assert (chicken["brand"], chicken["food_text"]) == ("Kirkland", "Chicken Breast")
    assert chicken["grams"] == pytest.approx(170.097, abs=0.01)
    assert potatoes["grams"] == 283.0
    assert cheddar["grams"] is None, "2.25 g at 90 kcal is a wrong unit"
    assert (rice["grams"], rice["quantity_text"]) == (None, "1.5 servings")
    assert (beef["lean_pct"], beef["protein"]) == (93, 23.0), "93/7 is the brand"
    assert eggs["food_text"] == "Egg Whites"
    assert (eggs["brand"], eggs["lean_pct"]) == (None, None)
    quick, banana = conn.execute(
        "SELECT * FROM diary_rows WHERE date = '2026-08-02' ORDER BY position"
    ).fetchall()
    assert (quick["is_quick_add"], banana["is_quick_add"]) == (1, 0)
    day1, day2 = conn.execute("SELECT * FROM diary_days ORDER BY date").fetchall()
    assert (day1["calories"], day1["reported_total_calories"]) == (990.0, 990.0)
    assert day1["untracked"] == 0
    assert (day2["calories"], day2["quick_add_calories"]) == (2105.0, 2000.0)
    assert day2["untracked"] == 1


def test_later_file_replaces_whole_overlapping_days_and_reimport_is_stable(
    conn: sqlite3.Connection, fixtures_dir: Path
) -> None:
    """Two exports covering Aug 2: the later one wins, and importing it again
    changes nothing."""
    import_file(conn, fixtures_dir / "mfp_2026-08-01_2026-08-02.html", CONFIG)
    later = fixtures_dir / "mfp_2026-08-02_2026-08-03.html"
    import_file(conn, later, CONFIG)
    import_file(conn, later, CONFIG)
    rows = conn.execute(
        "SELECT food_text FROM diary_rows WHERE date = '2026-08-02' ORDER BY position"
    )
    assert [row["food_text"] for row in rows] == ["Egg Whites", "Chicken Breast"]
    day = conn.execute("SELECT * FROM diary_days WHERE date = '2026-08-02'").fetchone()
    assert (day["file"], day["untracked"]) == (later.name, 0)
    counts = conn.execute(
        "SELECT (SELECT count(*) FROM diary_days) AS days, "
        "(SELECT count(*) FROM diary_rows) AS rows, "
        "(SELECT count(*) FROM diary_files) AS files"
    ).fetchone()
    assert (counts["days"], counts["rows"], counts["files"]) == (3, 10, 2)


def test_directory_imports_in_name_order_and_reconciles_totals(
    conn: sqlite3.Connection, fixtures_dir: Path
) -> None:
    """Files go in sorted order, and a TOTALS row that disagrees is counted."""
    reports = import_directory(conn, fixtures_dir, CONFIG)
    assert [r.file for r in reports] == [
        "mfp_2026-08-01_2026-08-02.html",
        "mfp_2026-08-02_2026-08-03.html",
        "mfp_2026-08-05_2026-08-06.html",
    ]
    assert [r.total_mismatches for r in reports] == [0, 0, 1]
    assert conn.execute("SELECT count(*) AS n FROM diary_rows").fetchone()["n"] == 13
    turkey = conn.execute(
        "SELECT lean_pct FROM diary_rows WHERE raw_name LIKE 'Jennie-O%'"
    ).fetchone()
    assert turkey["lean_pct"] == 93, "93% Lean is in the food text"


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("diary-august.html", "mfp_YYYY-MM-DD_YYYY-MM-DD.html"),
        ("mfp_2026-08-01_2026-08-32.html", "day is out of range"),
        ("mfp_2026-09-01_2026-09-30.html", "outside"),
    ],
    ids=["bad-name", "impossible-date", "days-outside-range"],
)
def test_misnamed_exports_are_refused_before_any_write(
    conn: sqlite3.Connection,
    fixtures_dir: Path,
    tmp_path: Path,
    name: str,
    message: str,
) -> None:
    """A mislabeled export must not overwrite the wrong month."""
    path = tmp_path / name
    path.write_bytes((fixtures_dir / "mfp_2026-08-05_2026-08-06.html").read_bytes())
    with pytest.raises(DiaryImportError, match=message):
        import_file(conn, path, CONFIG)
    assert conn.execute("SELECT count(*) AS n FROM diary_rows").fetchone()["n"] == 0
