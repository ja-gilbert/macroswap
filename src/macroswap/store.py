"""SQLite schema and connection for the build database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from macroswap.usda.table import Row

_SCHEMA = """
CREATE TABLE IF NOT EXISTS diary_files (
    file      TEXT PRIMARY KEY,
    from_date TEXT NOT NULL,
    to_date   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS diary_days (
    date                    TEXT PRIMARY KEY,
    file                    TEXT NOT NULL REFERENCES diary_files(file),
    calories                REAL NOT NULL,
    quick_add_calories      REAL NOT NULL,
    untracked               INTEGER NOT NULL CHECK (untracked IN (0, 1)),
    reported_total_calories REAL
);
CREATE TABLE IF NOT EXISTS diary_rows (
    date          TEXT NOT NULL REFERENCES diary_days(date),
    meal          TEXT NOT NULL,
    position      INTEGER NOT NULL,
    raw_name      TEXT NOT NULL,
    brand         TEXT,
    food_text     TEXT NOT NULL,
    quantity_text TEXT,
    grams         REAL,
    lean_pct      INTEGER,  -- read by the swap engine's default level, spec 4.2
    is_quick_add  INTEGER NOT NULL CHECK (is_quick_add IN (0, 1)),
    calories      REAL,
    carbs         REAL,
    fat           REAL,
    protein       REAL,
    cholesterol   REAL,
    sodium        REAL,
    sugar         REAL,
    fiber         REAL,
    PRIMARY KEY (date, meal, position)
);
"""


_USDA_COLUMNS = (
    "id",
    "source",
    "ndb",
    "description",
    "category",
    "family",
    "variant",
    "lean_pct",
    "provenance",
    "as_bought",
    "protein",
    "carbs",
    "fat",
    "fiber",
    "kcal",
    "roles",
    "exclusion_reason",
)
_USDA_SCHEMA = """
DROP TABLE IF EXISTS usda_foods;
CREATE TABLE usda_foods (
    id               TEXT PRIMARY KEY,
    source           TEXT NOT NULL CHECK (source IN ('sr', 'foundation', 'derived')),
    ndb              TEXT,
    description      TEXT NOT NULL,
    category         TEXT NOT NULL,
    family           TEXT NOT NULL,
    variant          TEXT NOT NULL,
    lean_pct         INTEGER,
    provenance       TEXT NOT NULL,
    as_bought        TEXT NOT NULL,
    protein          REAL,
    carbs            REAL,
    fat              REAL,
    fiber            REAL,
    kcal             REAL,
    roles            TEXT NOT NULL,
    exclusion_reason TEXT
);
"""


def connect(path: Path) -> sqlite3.Connection:
    """Open the build database, creating directories and tables as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    return conn


def write_usda(conn: sqlite3.Connection, rows: list[tuple[object, ...]]) -> None:
    """Replace the USDA table whole, schema included, so a rebuild never
    inherits columns or rows from an older build."""
    columns = ", ".join(_USDA_COLUMNS)
    marks = ", ".join("?" * len(_USDA_COLUMNS))
    conn.executescript(_USDA_SCHEMA)
    with conn:
        conn.executemany(f"INSERT INTO usda_foods({columns}) VALUES ({marks})", rows)


def read_usda(conn: sqlite3.Connection) -> list[Row]:
    """Every row of the USDA table, as build_table made it."""
    columns = ", ".join(_USDA_COLUMNS)
    return [Row(*r) for r in conn.execute(f"SELECT {columns} FROM usda_foods")]
