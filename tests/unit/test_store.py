from __future__ import annotations

from dataclasses import astuple
from pathlib import Path

from macroswap.store import connect, read_usda, write_usda
from macroswap.usda.table import Row


def test_connect_creates_schema_once_and_enforces_foreign_keys(tmp_path: Path) -> None:
    """Reconnecting re-applies the schema without failing or wiping rows."""
    path = tmp_path / "nested" / "macroswap.sqlite"
    with connect(path) as conn:
        conn.execute(
            "INSERT INTO diary_files(file, from_date, to_date) VALUES (?, ?, ?)",
            ("a.html", "2026-08-01", "2026-08-31"),
        )
    with connect(path) as conn:
        row = conn.execute("SELECT count(*) AS n FROM diary_files").fetchone()
        assert row["n"] == 1
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_read_usda_returns_the_rows_write_usda_stored(
    tmp_path: Path, usda_rows: list[Row]
) -> None:
    """Every column round-trips, so a swapped column cannot pass unseen."""
    with connect(tmp_path / "db.sqlite") as conn:
        write_usda(conn, [astuple(r) for r in usda_rows])
        assert read_usda(conn) == usda_rows
