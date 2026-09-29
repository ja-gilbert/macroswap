from __future__ import annotations

import math
import sqlite3
from dataclasses import astuple, replace
from pathlib import Path
from typing import Any

import pytest

from macroswap.config import load_config
from macroswap.diary.importer import import_directory, import_file
from macroswap.match.diary import (
    Fingerprint,
    LabelError,
    StaleMatches,
    Summary,
    check_fingerprint,
    match_diary,
)
from macroswap.match.label import NO_MATCH, Label, write_labels
from macroswap.match.matcher import Matcher
from macroswap.store import connect, write_usda
from macroswap.usda.keys import FieldRules
from macroswap.usda.table import Row

CONFIG = load_config()
# Between the fixture diary's top scores, so some names abstain; lexical,
# whatever the packaged default.
THRESHOLD = 5.0
TUNED = replace(
    CONFIG.match,
    default_method="lexical",
    no_match={"lexical": THRESHOLD, "embed": -math.inf},
)


@pytest.fixture
def conn(
    tmp_path: Path, fixtures_dir: Path, usda_rows: list[Row]
) -> sqlite3.Connection:
    conn = connect(tmp_path / "db.sqlite")
    import_directory(conn, fixtures_dir, CONFIG.diary)
    write_usda(conn, [astuple(r) for r in usda_rows])
    return conn


def _make_matcher(rows: list[Row]) -> Matcher:
    return Matcher(rows, TUNED, FieldRules(CONFIG.usda))


# name: rows, usda_id, family, variant, as_bought, source, and whether the
# score reaches THRESHOLD: 1 for a hit, 0 for an abstention that kept its top
# score, None for a label or when nothing scored.
EXPECTED = {
    "egg whites": (2, "sr:172183", "egg, white", "egg, white", "raw", "lexical", 1),
    "quaker - old fashioned oats": (
        1,
        "sr:173904",
        "cereals, oats",
        "cereals, oats, regular and quick, dry",
        "dry",
        "label",
        None,
    ),
    "ground beef": (1, None, "beef, ground", None, None, "label", None),
    "chipotle - chicken bowl": (1, None, None, None, None, "label", None),
    "ground turkey": (1, None, "turkey, ground", None, None, "lexical", 1),
    "great value - jasmine rice": (1, None, None, None, None, "lexical", 0),
    "irish cheddar - irish cheddar": (1, None, None, None, None, "lexical", None),
}


def test_a_made_label_wins_and_the_matcher_resolves_the_rest(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """Every counted name once, at the identity a swap shows: a row, for a
    label its first, the family alone for a ground meat without a level, or
    NULLs for NO_MATCH. A second run replaces the first."""
    # Ground meats logged without a level, beside the fixture diary's ten names.
    with conn:
        conn.executemany(
            "INSERT INTO diary_rows(date, meal, position, raw_name, food_text, "
            "is_quick_add) VALUES ('2026-08-05', 'Dinner', ?, ?, ?, 0)",
            [
                (10, "Ground Beef, 1 lb", "Ground Beef"),
                (11, "Ground Turkey, 4 oz", "Ground Turkey"),
            ],
        )
    labels = [
        Label("egg whites", 2, "head", "dev", "", ""),
        Label(
            "quaker - old fashioned oats",
            1,
            "head",
            "test",
            "sr:173904 foundation:2346397",
            "search",
        ),
        Label("ground beef", 1, "head", "test", "beef, ground", "suggestion"),
        Label("chipotle - chicken bowl", 1, "tail", "dev", NO_MATCH, "no_match"),
    ]
    fingerprint = Fingerprint.current(TUNED, tmp_path / "labels.csv")
    summary = match_diary(conn, labels, _make_matcher, fingerprint)
    assert match_diary(conn, labels, _make_matcher, fingerprint) == summary
    stored = {
        name: tuple(rest)
        for name, *rest in conn.execute(
            "SELECT name, rows, usda_id, family, variant, as_bought, source, "
            "score >= ? FROM diary_matches",
            (THRESHOLD,),
        )
    }
    assert {name: stored[name] for name in EXPECTED} == EXPECTED
    assert summary == Summary(by_label=2, by_matcher=7, no_match=3)
    assert [
        conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in ("diary_matches", "diary_matches_meta")
    ] == [12, 1]


def test_a_label_naming_nothing_in_the_table_is_refused_before_any_write(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """A label can name a row a newer USDA release dropped, at any of its ids,
    or a family that is not a leanness family; the refusal comes before any
    write."""
    fingerprint = Fingerprint.current(TUNED, tmp_path / "labels.csv")
    match_diary(conn, [], _make_matcher, fingerprint)
    before = [tuple(r) for r in conn.execute("SELECT * FROM diary_matches")]
    orphans = [
        Label("egg whites", 2, "head", "dev", "sr:172183 foundation:1999631", "search"),
        Label(
            "kirkland - chicken breast", 2, "head", "dev", "chicken, breast", "search"
        ),
    ]
    with pytest.raises(LabelError) as refused:
        match_diary(conn, orphans, _make_matcher, fingerprint)
    assert str(refused.value).endswith(
        "egg whites = sr:172183 foundation:1999631; "
        "kirkland - chicken breast = chicken, breast"
    )
    assert [tuple(r) for r in conn.execute("SELECT * FROM diary_matches")] == before


@pytest.mark.parametrize(
    ("changes", "relabel"),
    [
        pytest.param({}, True, id="labels-made-since"),
        pytest.param(
            {"no_match": {"lexical": 6.0, "embed": -math.inf}},
            False,
            id="thresholds-tuned-since",
        ),
        pytest.param({"default_method": "embed"}, False, id="method-changed-since"),
        pytest.param({"revision": "0" * 40}, False, id="model-revision-changed-since"),
    ],
)
def test_matches_go_stale_when_what_made_them_changes(
    conn: sqlite3.Connection, tmp_path: Path, changes: dict[str, Any], relabel: bool
) -> None:
    labels = tmp_path / "labels.csv"
    write_labels(labels, [Label("egg whites", 2, "head", "dev", "", "")])
    match_diary(conn, [], _make_matcher, Fingerprint.current(TUNED, labels))
    check_fingerprint(conn, TUNED, labels)
    if relabel:
        write_labels(
            labels, [Label("egg whites", 2, "head", "dev", NO_MATCH, "no_match")]
        )
    with pytest.raises(StaleMatches, match="run `macroswap diary match`"):
        check_fingerprint(conn, replace(TUNED, **changes), labels)


@pytest.mark.parametrize("rebuilt", ["data-build", "diary-import"])
def test_a_new_table_or_diary_clears_the_matches(
    conn: sqlite3.Connection,
    usda_rows: list[Row],
    fixtures_dir: Path,
    tmp_path: Path,
    rebuilt: str,
) -> None:
    labels = tmp_path / "labels.csv"
    match_diary(conn, [], _make_matcher, Fingerprint.current(TUNED, labels))
    if rebuilt == "data-build":
        write_usda(conn, [astuple(r) for r in usda_rows])
    else:
        import_file(conn, fixtures_dir / "mfp_2026-08-05_2026-08-06.html", CONFIG.diary)
    assert conn.execute("SELECT count(*) FROM diary_matches").fetchone()[0] == 0
    with pytest.raises(StaleMatches):
        check_fingerprint(conn, TUNED, labels)
