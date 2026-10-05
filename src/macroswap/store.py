"""SQLite schema and connection for the build database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from macroswap.nhanes.popularity import Table
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
CREATE TABLE IF NOT EXISTS diary_matches (
    name      TEXT PRIMARY KEY,
    rows      INTEGER NOT NULL,
    usda_id   TEXT,
    family    TEXT,
    variant   TEXT,
    as_bought TEXT,
    source    TEXT NOT NULL,
    score     REAL,
    -- A NULL family is NO_MATCH; a family without a row is a leanness-family
    -- name matched or labeled at its family, whose level the next milestone
    -- applies.
    CHECK ((usda_id IS NULL) = (variant IS NULL))
);
CREATE TABLE IF NOT EXISTS diary_matches_meta (
    method        TEXT NOT NULL,
    thresholds    TEXT NOT NULL,
    labels_digest TEXT NOT NULL,
    revision      TEXT NOT NULL
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
_POPULARITY_SCHEMA = """
DROP TABLE IF EXISTS popularity;
CREATE TABLE popularity (
    kind         TEXT NOT NULL CHECK (kind IN ('family', 'variant')),
    key          TEXT NOT NULL,
    participants INTEGER NOT NULL,
    PRIMARY KEY (kind, key)
);
DROP TABLE IF EXISTS popularity_meta;
CREATE TABLE popularity_meta (
    cycle        TEXT NOT NULL,
    participants INTEGER NOT NULL
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
    # Cleared before the schema script commits, so a failed insert never
    # leaves old matches beside an empty table.
    clear_diary_matches(conn)
    conn.executescript(_USDA_SCHEMA)
    with conn:
        conn.executemany(f"INSERT INTO usda_foods({columns}) VALUES ({marks})", rows)


def write_popularity(conn: sqlite3.Connection, table: Table) -> None:
    """Replace the participant counts whole, with the cycle they were counted
    in and how many participants had a reliable recall."""
    conn.executescript(_POPULARITY_SCHEMA)
    with conn:
        conn.execute(
            "INSERT INTO popularity_meta VALUES (?, ?)",
            (table.cycle, table.participants),
        )
        for kind, counts in (("family", table.families), ("variant", table.variants)):
            conn.executemany(
                "INSERT INTO popularity VALUES (?, ?, ?)",
                [(kind, key, n) for key, n in counts.items()],
            )


def read_usda(conn: sqlite3.Connection) -> list[Row]:
    """Every row of the USDA table, as build_table made it."""
    columns = ", ".join(_USDA_COLUMNS)
    return [Row(*r) for r in conn.execute(f"SELECT {columns} FROM usda_foods")]


def clear_diary_matches(conn: sqlite3.Connection) -> None:
    """Empty diary_matches and its fingerprint in the caller's transaction: a
    new USDA table or new diary rows leave every match stale."""
    conn.execute("DELETE FROM diary_matches")
    conn.execute("DELETE FROM diary_matches_meta")


def write_diary_matches(
    conn: sqlite3.Connection,
    rows: list[tuple[object, ...]],
    fingerprint: tuple[object, ...],
) -> None:
    """Replace every match and the fingerprint row together."""
    with conn:
        clear_diary_matches(conn)
        conn.executemany(
            "INSERT INTO diary_matches VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows
        )
        conn.execute("INSERT INTO diary_matches_meta VALUES (?, ?, ?, ?)", fingerprint)
