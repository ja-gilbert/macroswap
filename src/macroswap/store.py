"""SQLite schema and connection for the build database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

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


def connect(path: Path) -> sqlite3.Connection:
    """Open the build database, creating directories and tables as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    return conn
