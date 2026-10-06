from __future__ import annotations

import math
import sqlite3
from dataclasses import astuple, replace
from pathlib import Path

import pytest

from macroswap.config import Config, load_config
from macroswap.diary.importer import import_directory
from macroswap.match.diary import Fingerprint, StaleMatches, match_diary
from macroswap.match.matcher import Matcher
from macroswap.store import connect, write_usda
from macroswap.swap.logged import (
    Diary,
    default_levels,
    diary_families,
    entry,
    like_log,
    read_diary,
)
from macroswap.swap.rank import DefaultLevel
from macroswap.swap.target import TargetError
from macroswap.usda.keys import FieldRules
from macroswap.usda.table import Row

PACKAGED = load_config()
# The fixture diary runs to 2026-08-05, so its 90 days start here.
WINDOW = ("2026-05-08", "2026-08-05")


@pytest.fixture
def config(tmp_path: Path) -> Config:
    """The packaged config with what tuning changes pinned: lexical with a
    threshold between the fixture diary's top scores, a 90-day window, no
    everyday names, and a label file that does not exist."""
    return replace(
        PACKAGED,
        match=replace(
            PACKAGED.match,
            default_method="lexical",
            no_match={"lexical": 5.0, "embed": -math.inf},
        ),
        paths=replace(PACKAGED.paths, labels=str(tmp_path / "labels.csv")),
        swap=replace(PACKAGED.swap, diary_window_days=90, staples={}),
    )


@pytest.fixture
def matcher(usda_rows: list[Row], config: Config) -> Matcher:
    return Matcher(usda_rows, config.match, FieldRules(config.usda))


@pytest.fixture
def conn(
    tmp_path: Path, fixtures_dir: Path, usda_rows: list[Row], config: Config
) -> sqlite3.Connection:
    conn = connect(tmp_path / "db.sqlite")
    import_directory(conn, fixtures_dir, config.diary)
    write_usda(conn, [astuple(r) for r in usda_rows])
    return conn


def log(
    conn: sqlite3.Connection,
    day: str,
    name: str,
    macros: tuple[float | None, float | None, float | None],
    lean_pct: int | None = None,
) -> None:
    """One more counted row, on a day the fixture diary may not have."""
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO diary_days(date, file, calories, "
            "quick_add_calories, untracked) "
            "VALUES (?, 'mfp_2026-08-01_2026-08-02.html', 0, 0, 0)",
            (day,),
        )
        position = conn.execute("SELECT count(*) FROM diary_rows").fetchone()[0]
        conn.execute(
            "INSERT INTO diary_rows(date, meal, position, raw_name, food_text, "
            "lean_pct, is_quick_add, protein, carbs, fat) "
            "VALUES (?, 'Dinner', ?, ?, ?, ?, 0, ?, ?, ?)",
            (day, position, name, name, lean_pct, *macros),
        )


def matched(conn: sqlite3.Connection, config: Config, matcher: Matcher) -> Diary:
    fingerprint = Fingerprint.current(config.match, Path(config.paths.labels))
    match_diary(conn, [], lambda rows: matcher, fingerprint)
    return read_diary(conn, config)


def test_like_log_pools_names_and_takes_each_median_alone(
    conn: sqlite3.Connection, usda_rows: list[Row], matcher: Matcher, config: Config
) -> None:
    """Two names resolve to raw egg white. Their five rows with all three
    macros give medians no row holds; the row missing protein is left out. The
    name with more rows comes first."""
    log(conn, "2026-08-03", "Kirkland - Egg Whites", (10, 5, 2))
    log(conn, "2026-08-03", "Kirkland - Egg Whites", (30, 3, 1))
    log(conn, "2026-08-03", "Kirkland - Egg Whites", (20, 2, 4))
    log(conn, "2026-08-05", "Kirkland - Egg Whites", (None, 90, 90))
    diary = matched(conn, config, matcher)
    got = like_log("egg whites", diary, usda_rows, matcher, "lexical", config, {})
    assert (astuple(got.target.macros), got.window, got.names) == (
        (18, 2, 1),
        WINDOW,
        (("kirkland - egg whites", 3), ("egg whites", 2)),
    )


def test_like_log_stands_on_a_top_hit_without_macros(
    conn: sqlite3.Connection, usda_rows: list[Row], matcher: Matcher, config: Config
) -> None:
    """The extra virgin olive oil row has no macros in the table and the diary
    gives them, so the name matched to it is pooled, not anchovies in olive oil."""
    log(conn, "2026-08-03", "Olive Oil", (0, 0, 14))
    diary = matched(conn, config, matcher)
    got = like_log("olive oil", diary, usda_rows, matcher, "lexical", config, {})
    assert got.names == (("olive oil", 1),)


@pytest.mark.parametrize(
    ("text", "names"),
    [
        pytest.param(
            "ground beef",
            ["ground beef 80/20", "laura's lean 93/7 - ground beef"],
            id="a-family-pools-every-name-matched-into-it",
        ),
        pytest.param(
            "ground beef 93/7",
            ["laura's lean 93/7 - ground beef"],
            id="a-variant-pools-its-own-names",
        ),
    ],
)
def test_like_log_pools_by_what_the_text_resolved_to(
    conn: sqlite3.Connection,
    usda_rows: list[Row],
    matcher: Matcher,
    config: Config,
    text: str,
    names: list[str],
) -> None:
    """The fixture diary logs 93/7 beef; a second name logs 80/20. Medians over
    a family span its logged levels, so the default level is not reported."""
    log(conn, "2026-08-03", "Ground Beef 80/20", (17, 0, 20), 80)
    diary = matched(conn, config, matcher)
    levels = {"beef, ground": DefaultLevel(93, "test")}
    got = like_log(text, diary, usda_rows, matcher, "lexical", config, levels)
    assert ([name for name, _ in got.names], got.level) == (names, None)


@pytest.mark.parametrize(
    ("name", "row_id", "family", "variant", "pools", "window"),
    [
        pytest.param(
            "Laura's Lean 93/7 - Ground Beef, 4 oz",
            "sr:173110",
            "beef, ground",
            "beef, ground, 93/7",
            frozenset({"protein", "fat"}),
            WINDOW,
            id="matched",
        ),
        pytest.param(
            "kirkland - chicken breast",
            "sr:171077",
            "chicken, breast",
            "chicken, breast, meat only",
            frozenset({"protein", "fat"}),
            WINDOW,
            id="matched-takes-its-familys-pools",
        ),
        pytest.param(
            "bobs - trail bar",
            None,
            "",
            None,
            frozenset({"protein", "starch"}),
            None,
            id="unmatched-and-older-than-the-window",
        ),
        pytest.param(
            "ÉPI BAR",
            None,
            "",
            None,
            frozenset({"protein", "starch"}),
            WINDOW,
            id="a-capital-outside-ascii",
        ),
    ],
)
def test_entry_is_the_named_diary_food_as_logged(
    conn: sqlite3.Connection,
    usda_rows: list[Row],
    matcher: Matcher,
    config: Config,
    name: str,
    row_id: str | None,
    family: str,
    variant: str | None,
    pools: frozenset[str],
    window: tuple[str, str] | None,
) -> None:
    """A matched name takes its family, variant and pools from its row, and is
    weighed by that row: the chicken breast as logged reaches protein alone,
    and its family fat too. The trail bar, logged in January and matched to
    nothing, is read from the whole diary, has no family and no weight, and
    reaches the pools its macros do: fat gives 24% of its calories, under the
    25% a pool takes, and carbs with no sugars value are starch. The store
    lower-cases ASCII letters only, so the bar logged as "Épi Bar" is kept as
    "Épi bar"."""
    log(conn, "2026-01-10", "Bobs - Trail Bar", (30, 40, 10))
    log(conn, "2026-08-03", "Épi Bar", (30, 40, 10))
    got = entry(name, matched(conn, config, matcher), usda_rows, config)
    target = got.target
    assert (
        got.row and got.row.id,
        target.family,
        target.variant,
        target.pools,
        got.window,
        target.grams is not None,
    ) == (row_id, family, variant, pools, window, row_id is not None)


@pytest.mark.parametrize(
    ("name", "message"),
    [
        pytest.param(
            "chicken",
            "near: kirkland - chicken breast; chipotle - chicken bowl",
            id="not-a-diary-name",
        ),
        pytest.param("mystery", "give --grams", id="no-row-logs-all-three-macros"),
        pytest.param("diet soda", "no protein, carbs or fat", id="all-zero"),
    ],
)
def test_entry_refuses_a_name_it_cannot_read(
    conn: sqlite3.Connection,
    usda_rows: list[Row],
    matcher: Matcher,
    config: Config,
    name: str,
    message: str,
) -> None:
    log(conn, "2026-08-03", "Mystery", (None, None, None))
    log(conn, "2026-08-03", "Diet Soda", (0, 0, 0))
    with pytest.raises(TargetError, match=message):
        entry(name, matched(conn, config, matcher), usda_rows, config)


@pytest.mark.parametrize(
    ("logged", "family", "level"),
    [
        pytest.param(
            [("2026-01-10", "Ground Beef 80/20", 80)] * 2,
            "beef, ground",
            DefaultLevel(93, "your diary, last 90 days"),
            id="the-window-before-the-whole-diary",
        ),
        pytest.param(
            [("2026-01-10", "Ground Pork 96/4", 96)],
            "pork, ground",
            DefaultLevel(96, "your diary, all time"),
            id="the-whole-diary-when-the-window-is-empty",
        ),
        pytest.param(
            [], "pork, ground", DefaultLevel(84, "config default"), id="config-default"
        ),
        pytest.param(
            [
                ("2026-08-03", "Ground Pork 84/16", 84),
                ("2026-08-03", "Ground Pork 84/16", 84),
                ("2026-08-03", "Ground Pork 96/4", 96),
            ],
            "pork, ground",
            DefaultLevel(84, "your diary, last 90 days"),
            id="the-level-logged-most",
        ),
        pytest.param(
            [("2026-08-03", "Ground Turkey 90/10", 90)] * 2,
            "turkey, ground",
            DefaultLevel(93, "your diary, last 90 days"),
            id="a-level-no-swap-offers-is-not-counted",
        ),
        pytest.param(
            [("2026-08-03", "Ground Turkey", None)] * 2,
            "turkey, ground",
            DefaultLevel(93, "your diary, last 90 days"),
            id="a-row-logged-without-a-level-is-not-counted",
        ),
        pytest.param(
            [
                ("2026-08-03", "Ground Pork 84/16", 84),
                ("2026-08-03", "Ground Pork 96/4", 96),
            ],
            "pork, ground",
            DefaultLevel(96, "your diary, last 90 days"),
            id="a-tie-goes-to-the-leaner-level",
        ),
        pytest.param(
            [("2026-08-03", "Ground Turkey 85/15", 85)] * 3,
            "beef, ground",
            DefaultLevel(93, "your diary, last 90 days"),
            id="another-familys-levels-do-not-count",
        ),
    ],
)
def test_default_level_is_the_one_logged_most(
    conn: sqlite3.Connection,
    usda_rows: list[Row],
    matcher: Matcher,
    config: Config,
    logged: list[tuple[str, str, int | None]],
    family: str,
    level: DefaultLevel,
) -> None:
    """The fixture diary logs 93/7 beef and 93/7 turkey once each, in August.
    The real table has what the fixture lacks, so two ground turkey rows are
    added: one without a level, and one at 90/10 that no swap offers."""
    for day, name, lean_pct in logged:
        log(conn, day, name, (20, 0, 10), lean_pct)
    diary = matched(conn, config, matcher)
    turkey = next(r for r in usda_rows if r.id == "sr:172850")
    cooked = replace(turkey, id="sr:2", lean_pct=90, exclusion_reason="excluded")
    rows = [*usda_rows, replace(turkey, id="sr:1", lean_pct=None), cooked]
    assert default_levels(diary, rows, config)[family] == level


def test_the_diary_gives_its_families_and_counts_the_unmatched_names(
    conn: sqlite3.Connection, matcher: Matcher, config: Config
) -> None:
    families, unmatched = diary_families(matched(conn, config, matcher))
    assert (sorted(families), unmatched) == (
        [
            "beef, ground",
            "chicken, breast",
            "egg, white",
            "sweet potato",
            "turkey, ground",
            "yogurt, greek",
        ],
        4,
    )


def test_stale_matches_are_refused_and_a_store_without_a_diary_is_not(
    conn: sqlite3.Connection, tmp_path: Path, usda_rows: list[Row], config: Config
) -> None:
    """The fixture diary is imported but never matched; the second store holds
    the table alone."""
    with pytest.raises(StaleMatches):
        read_diary(conn, config)
    with connect(tmp_path / "no-diary.sqlite") as empty:
        write_usda(empty, [astuple(r) for r in usda_rows])
        assert read_diary(empty, config) == Diary({}, [])
