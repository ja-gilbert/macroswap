from __future__ import annotations

from dataclasses import astuple, replace
from pathlib import Path

import pytest

from macroswap.cli import main
from macroswap.config import Config
from macroswap.store import connect, write_usda
from macroswap.usda.table import Row

# The swap rows of the exit-code table; the other commands' rows are in
# test_cli.py.
EXIT_CODES = {
    "swap-no-method-resolves-the-text": (
        ["swap", "zzzz", "--grams", "100"],
        True,
        1,
        "no food matches 'zzzz'; --method tries another method\n",
    ),
    "swap-every-candidate-left-out": (
        ["swap", "egg whites", "--grams", "0.5"],
        True,
        1,
        "no swap: every candidate was left out (no-shared-pool 83; serving-bounds 82; "
        "own-family 1)",
    ),
    "swap-target-with-all-macros-zero": (
        ["swap", "tap water", "--grams", "500"],
        True,
        2,
        "has no protein, carbs or fat to match",
    ),
    "swap-entry-not-in-the-diary": (
        ["swap", "--entry", "chicken"],
        True,
        2,
        "no diary food named 'chicken'",
    ),
    "swap-without-an-amount": (
        ["swap", "egg whites"],
        True,
        2,
        "give a food with --grams or --like-log, or --entry with a diary name",
    ),
    "swap-grams-not-above-zero": (
        ["swap", "egg whites", "--grams", "0"],
        True,
        2,
        "--grams must be above zero",
    ),
    "swap-grams-without-end": (
        ["swap", "egg whites", "--grams", "inf"],
        True,
        2,
        "--grams must be above zero",
    ),
    "swap-variants-lists-the-targets-own-food": (
        ["swap", "atlantic cod", "--grams", "165", "--variants"],
        True,
        0,
        "fish, cod, wild caught (same food)",
    ),
    "swap-top-below-one": (
        ["swap", "egg whites", "--grams", "165", "--top", "0"],
        True,
        2,
        "--top at least 1",
    ),
    "swap-entry-with-grams": (
        ["swap", "--entry", "chicken", "--grams", "100"],
        True,
        2,
        "give a food with --grams or --like-log, or --entry with a diary name",
    ),
    "swap-before-data-build": (
        ["swap", "egg whites", "--grams", "165"],
        False,
        2,
        "run `data build` first",
    ),
    "swap-embed-by-name-without-the-extra": (
        ["swap", "egg whites", "--grams", "165", "--method", "embed"],
        True,
        2,
        "embed extra not installed (uv sync --extra embed)",
    ),
}


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty database, from a directory that is not the repository: the
    labels path is relative."""
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "db.sqlite"
    connect(path).close()
    return path


def build(db: Path, rows: list[Row]) -> None:
    with connect(db) as conn:
        write_usda(conn, [astuple(r) for r in rows])


@pytest.mark.usefixtures("pinned_config")
@pytest.mark.parametrize(
    ("args", "built", "code", "says"), EXIT_CODES.values(), ids=EXIT_CODES.keys()
)
def test_exit_code(
    db: Path,
    usda_rows: list[Row],
    capsys: pytest.CaptureFixture[str],
    args: list[str],
    built: bool,
    code: int,
    says: str,
) -> None:
    if built:
        build(db, usda_rows)
    assert main(["--db", str(db), *args]) == code
    captured = capsys.readouterr()
    assert says in captured.out + captured.err


@pytest.mark.usefixtures("pinned_config")
def test_swap_prints_the_header_then_one_line_per_family(
    db: Path, usda_rows: list[Row], capsys: pytest.CaptureFixture[str]
) -> None:
    """A typed food at its grams, on a store with no diary: the header, the
    popularity note, then --top families, none of them the target's own. The
    twelfth, ground turkey at 99/1, adds its default level."""
    build(db, usda_rows)
    args = ["swap", "Egg", "Whites", "--grams", "165", "--top", "12"]
    assert main(["--db", str(db), *args]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[:5] == [
        "target: egg, white / raw (165 g)",
        "row: sr:172183 Egg, white, raw, fresh",
        "method: lexical",
        "macros: protein 18.0 g, carbs 1.2 g, fat 0.3 g",
        "popularity: not built; every family counts as common",
    ]
    assert len([line for line in lines[5:] if not line.startswith(" ")]) == 12
    assert lines[-1].startswith(
        "    default level (config default): 90 g  turkey, ground, 93/7"
    )
    assert "egg, white" not in "".join(lines[5:])


def test_swap_lists_the_nearest_rows_when_the_method_abstains(
    db: Path,
    usda_rows: list[Row],
    pinned_config: Config,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Jasmine rice scores 4.0 against a threshold of 5."""
    cautious = replace(pinned_config.match, no_match={"lexical": 5.0, "embed": 5.0})
    config = replace(pinned_config, match=cautious)
    monkeypatch.setattr("macroswap.cli.load_config", lambda path=None: config)
    build(db, usda_rows)
    assert main(["--db", str(db), "swap", "jasmine rice", "--grams", "100"]) == 1
    assert capsys.readouterr().out.splitlines()[1:3] == [
        "no food matches 'jasmine rice'; --method tries another method. The nearest "
        "rows:",
        "  lexical  sr:168877  Rice, white, long-grain, regular, raw, enriched  "
        "[rice, white, long-grain, regular / raw]",
    ]


def test_swap_by_default_without_the_extra_runs_lexical_and_says_why(
    db: Path,
    usda_rows: list[Row],
    pinned_config: Config,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    embed = replace(pinned_config.match, default_method="embed")
    by_default = replace(pinned_config, match=embed)
    monkeypatch.setattr("macroswap.cli.load_config", lambda path=None: by_default)
    build(db, usda_rows)
    assert main(["--db", str(db), "swap", "egg whites", "--grams", "165"]) == 0
    assert (
        "method: lexical; embed extra not installed (uv sync --extra embed)"
        in capsys.readouterr().out
    )


@pytest.mark.usefixtures("pinned_config")
def test_swap_reads_the_diary_once_it_is_matched(
    db: Path,
    usda_rows: list[Row],
    fixtures_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Unmatched diary rows are refused, typed targets too, since the diary's
    families shape every answer. Once matched, a diary food is read as logged,
    and --new-only counts the diary families it leaves out, Greek yogurt among
    them, and the names that matched nothing."""
    build(db, usda_rows)
    run = ["--db", str(db)]
    assert main([*run, "diary", "import", str(fixtures_dir)]) == 0
    assert main([*run, "swap", "egg whites", "--grams", "165"]) == 2
    assert "run `macroswap diary match`" in capsys.readouterr().err
    assert main([*run, "diary", "match"]) == 0
    like_log = ["swap", "egg whites", "--like-log", "--top", "40"]
    assert main([*run, *like_log]) == 0
    assert main([*run, *like_log, "--new-only"]) == 0
    logged, new_only = capsys.readouterr().out.split("target: ")[1:]
    assert logged.splitlines()[4] == (
        "logged: 2026-05-08 to 2026-08-05; rows per name: egg whites (2)"
    )
    assert new_only.splitlines()[5] == (
        "new only: 9 diary families left out; 1 diary names matched nothing"
    )
    assert ("yogurt, greek" in logged, "yogurt, greek" in new_only) == (True, False)
    assert main([*run, "swap", "--entry", "Kirkland - Chicken Breast"]) == 0
    assert capsys.readouterr().out.splitlines()[:3] == [
        "target: kirkland - chicken breast (as logged)",
        "row: sr:171077 Chicken, broiler or fryers, breast, skinless, boneless, "
        "meat only, raw",
        "method: diary",
    ]
