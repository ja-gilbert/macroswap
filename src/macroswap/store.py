"""SQLite schema and connection for the build database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from macroswap.nhanes.popularity import Popularity, Table
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
    lean_pct      INTEGER,  -- read by the swap's default level (README, Swaps)
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
    -- name matched or labeled at its family, whose level the swap and the
    -- library apply.
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
    "sugars",
    "kcal",
    "roles",
    "exclusion_reason",
)
_USDA_SCHEMA = """
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
    sugars           REAL,
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


def open_existing(db: Path, hint: str) -> sqlite3.Connection:
    """The store, which must already exist: connect() creates the file it is
    pointed at, so a typo in --db would otherwise report an empty database
    instead of a missing one."""
    if not db.exists():
        raise FileNotFoundError(f"no database at {db}; run `{hint}` first")
    return connect(db)


def open_built(db: Path) -> sqlite3.Connection:
    """The store with its USDA table: diary import creates the database
    without it, and an older build cut short while writing it could leave it
    empty. A refused store is closed, not left to the garbage collector."""
    conn = open_existing(db, "data build")
    try:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'usda_foods'"
        ).fetchone():
            raise FileNotFoundError(f"no USDA table in {db}; run `data build` first")
        if not conn.execute("SELECT 1 FROM usda_foods LIMIT 1").fetchone():
            raise FileNotFoundError(f"no USDA rows in {db}; run `data build` again")
    except BaseException:
        conn.close()
        raise
    return conn


def connect(path: Path) -> sqlite3.Connection:
    """Open the build database, creating directories and tables as needed; a
    file that is not a database is refused with the connection closed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(_SCHEMA)
    except BaseException:
        conn.close()
        raise
    return conn


def write_usda(conn: sqlite3.Connection, rows: list[tuple[object, ...]]) -> None:
    """Replace the USDA table whole, schema included, in one transaction: a
    rebuild never inherits columns or rows from an older build, and a write
    cut short leaves the previous build in place."""
    columns = ", ".join(_USDA_COLUMNS)
    marks = ", ".join("?" * len(_USDA_COLUMNS))
    with conn:
        # One transaction on purpose, whatever statement comes first.
        conn.execute("BEGIN")
        clear_diary_matches(conn)
        conn.execute("DROP TABLE IF EXISTS usda_foods")
        conn.execute(_USDA_SCHEMA)
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


def read_popularity(conn: sqlite3.Connection) -> tuple[str, Popularity] | None:
    """The cycle and the participant counts as write_popularity stored them;
    None from a store built before the build counted participants, or by a
    build cut short before it stored them."""
    built = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'popularity_meta'"
    ).fetchone()
    meta = built and conn.execute("SELECT * FROM popularity_meta").fetchone()
    if not meta:
        return None
    cycle, participants = meta
    counts: dict[str, dict[str, int]] = {"family": {}, "variant": {}}
    for kind, key, n in conn.execute("SELECT * FROM popularity"):
        counts[kind][key] = n
    return cycle, Popularity(participants, counts["family"], counts["variant"])


def read_usda(conn: sqlite3.Connection) -> list[Row]:
    """Every row of the USDA table, as build_table made it; a table an older
    build wrote without a column the rows now carry is refused."""
    have = {column[1] for column in conn.execute("PRAGMA table_info(usda_foods)")}
    if missing := [c for c in _USDA_COLUMNS if c not in have]:
        raise FileNotFoundError(
            f"the USDA table lacks {', '.join(missing)}; run `data build` again"
        )
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
