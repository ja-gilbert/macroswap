from __future__ import annotations

import json
import shutil
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import astuple, replace
from pathlib import Path

import pytest

from macroswap.cli import main
from macroswap.config import Config
from macroswap.match.diary import check_fingerprint
from macroswap.match.evaluate import read_expected
from macroswap.match.label import NO_MATCH, Label, write_labels
from macroswap.match.matcher import Encoder
from macroswap.nhanes.popularity import LINK_RULE
from macroswap.pull import release_dirs
from macroswap.store import connect, write_usda
from macroswap.usda.table import Row

# The exit-code table, one row per case from this milestone on; the pull
# checksum row is in test_pull.py, and `diary match` and `match eval
# --write-expected` refusing without the embed extra are in their own tests.
EXIT_CODES = {
    "match-where-every-method-abstains": (["match", "zzzz"], True, 1, "NO_MATCH"),
    "match-before-data-build": (
        ["match", "egg whites"],
        False,
        2,
        "run `data build` first",
    ),
    "match-embed-by-name-without-the-extra": (
        ["match", "egg whites", "--method", "embed"],
        True,
        2,
        "embed extra not installed (uv sync --extra embed)",
    ),
    "match-hybrid-by-name-without-the-extra": (
        ["match", "egg whites", "--method", "hybrid"],
        True,
        2,
        "embed extra not installed (uv sync --extra embed)",
    ),
    "match-by-default-without-the-extra-runs-lexical": (
        ["match", "egg whites"],
        True,
        0,
        "method: lexical; embed extra not installed (uv sync --extra embed)",
    ),
    "match-label-before-diary-import": (
        ["match", "label"],
        True,
        2,
        "run `diary import` first",
    ),
    "diary-match-before-data-build": (
        ["diary", "match"],
        False,
        2,
        "run `data build` first",
    ),
    "match-eval-before-match-label": (
        ["match", "eval"],
        True,
        2,
        "run `match label` first",
    ),
}


@pytest.mark.usefixtures("pinned_config")
@pytest.mark.parametrize(
    ("args", "built", "code", "says"), EXIT_CODES.values(), ids=EXIT_CODES.keys()
)
def test_exit_code(
    tmp_path: Path,
    usda_rows: list[Row],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    args: list[str],
    built: bool,
    code: int,
    says: str,
) -> None:
    # The labels path is relative: never the repository's own file.
    monkeypatch.chdir(tmp_path)
    db = _database(tmp_path, usda_rows if built else [])
    assert main(["--db", str(db), *args]) == code
    captured = capsys.readouterr()
    assert says in captured.out + captured.err


def test_no_command_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    """Running with no command exits 2 and prints usage, not a traceback."""
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2
    assert "usage" in capsys.readouterr().err.lower()


def test_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


def test_diary_import_reports_each_file(
    tmp_path: Path, fixtures_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "build" / "macroswap.sqlite"
    assert main(["--db", str(db), "diary", "import", str(fixtures_dir)]) == 0
    out = capsys.readouterr().out
    assert "08-02.html: 2 days, 8 rows, 1 untracked, 2 of 2 reconciled" in out
    assert "08-06.html: 1 days, 3 rows, 0 untracked, 1 of 1 reconciled" in out
    assert "1 total mismatches" in out
    assert db.exists()


@pytest.mark.parametrize("subdir", ["missing", "empty"])
def test_unusable_directory_is_exit_two(
    tmp_path: Path, subdir: str, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "db.sqlite"
    (tmp_path / "empty").mkdir()
    assert main(["--db", str(db), "diary", "import", str(tmp_path / subdir)]) == 2
    assert subdir in capsys.readouterr().err


def test_bad_config_is_exit_two(
    tmp_path: Path, fixtures_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "macroswap.toml"
    config.write_text("[diarry]\n", encoding="utf-8")
    args = ["--config", str(config), "--db", str(tmp_path / "db.sqlite")]
    assert main([*args, "diary", "import", str(fixtures_dir)]) == 2
    assert "diarry" in capsys.readouterr().err


def test_diary_stats_after_import(
    tmp_path: Path, fixtures_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "macroswap.sqlite"
    assert main(["--db", str(db), "diary", "import", str(fixtures_dir)]) == 0
    capsys.readouterr()
    assert main(["--db", str(db), "diary", "stats"]) == 0
    out = capsys.readouterr().out
    assert "files: 3, covering 2026-08-01 .. 2026-08-06" in out
    assert "empty covered days: 1 (2026-08-06)" in out


def test_diary_stats_without_database_is_exit_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--db", str(tmp_path / "missing.sqlite"), "diary", "stats"]) == 2
    assert "diary import" in capsys.readouterr().err


# FNDDS foods by food code, each ingredient an NDB number of the USDA fixture
# with its grams: rice boiled in more water than rice; a plate that is mostly
# chicken, a tenth of it an ingredient the table lacks, filed under rice; a
# baked sweet potato, a cooked key that counts as the raw family; tap water,
# left out by its category; sauteed onions, a cooked key nothing claims; and
# olive oil, a row without all its macros.
SURVEY = """fdc_id,food_code,wweia_category_number,start_date,end_date
1,100,4002,2021-01-01,2023-12-31
2,200,4002,2021-01-01,2023-12-31
3,300,6410,2021-01-01,2023-12-31
4,400,7702,2021-01-01,2023-12-31
5,500,6410,2021-01-01,2023-12-31
6,600,8012,2021-01-01,2023-12-31
"""
CATEGORIES = """wweia_food_category,wweia_food_category_description
4002,Rice
6410,Other red and orange vegetables
7702,Tap water
8012,Fats and oils
"""
INGREDIENTS = """fdc_id,sr_code,gram_weight
1,14411,60.0
1,20345,40.0
2,20345,30.0
2,5064,60.0
2,99999,10.0
3,11508,100.0
4,14411,100.0
5,11286,100.0
6,4063,100.0
"""
# Recall rows: participant, recall status (1 is reliable), food code.
DAY_ONE = [(1, 1, 100), (1, 1, 200), (2, 2, 100)]
DAY_TWO = [
    (2, 1, 200),
    (3, 1, 300),
    (3, 1, 100),
    (4, 1, 100),
    (5, 1, 400),
    (5, 1, 500),
    (5, 1, 600),
]


def _whole(number: int) -> str:
    """A whole number above zero as an IBM float in hex: its hex digits as the
    fraction, behind an exponent that counts them."""
    digits = f"{number:x}"
    return f"{64 + len(digits):02x}{digits.ljust(14, '0')}"


def _repo_layout(tmp_path: Path, usda_dir: Path) -> dict[str, Path]:
    """The packaged config's relative paths, rooted at tmp_path, with the two
    USDA releases pulled; where each source of the manifest lands."""
    data = tmp_path / "data"
    (data / "raw" / "usda").mkdir(parents=True)
    shutil.copy(Path(__file__).resolve().parents[2] / "data" / "manifest.toml", data)
    dirs = release_dirs(data / "manifest.toml", data / "raw")
    for release in (dirs["sr_legacy"], dirs["foundation"]):
        release.symlink_to(usda_dir / release.name, target_is_directory=True)
    return dirs


def _pull_recalls(
    dirs: dict[str, Path],
    transport: Callable[[list[str], list[str]], bytes],
    survey: str = SURVEY,
    day_two: Sequence[tuple[int, int, int]] = DAY_TWO,
) -> None:
    """The hand-made survey foods and both days' recall files, where the pull
    would have put them."""
    dirs["fndds"].mkdir()
    (dirs["fndds"] / "survey_fndds_food.csv").write_text(survey, encoding="utf-8")
    (dirs["fndds"] / "input_food.csv").write_text(INGREDIENTS, encoding="utf-8")
    (dirs["fndds"] / "wweia_food_category.csv").write_text(CATEGORIES, encoding="utf-8")
    for day, reports in ((1, DAY_ONE), (2, day_two)):
        columns = ["SEQN", f"DR{day}DRSTZ", f"DR{day}IFDCD"]
        rows = [" ".join(map(_whole, report)) for report in reports]
        dirs[f"nhanes_day{day}"].write_bytes(transport(columns, rows))


@pytest.mark.usefixtures("pinned_config")
def test_data_build_then_report(
    tmp_path: Path,
    usda_dir: Path,
    transport: Callable[[list[str], list[str]], bytes],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The counts are distinct participants over both days: participant 2's
    first day is not a reliable recall, so its rice is not counted, and their
    second day is. Water is set aside, the plate is chicken by weight, and the
    baked sweet potato counts as sweet potato under its own variant.
    Five participants report six families, so neither count can pass for
    the other. A build writes the store and nothing else; a second build
    replaces the counts and, asked to, writes the table to commit: the plate is
    filed under rice, so the rice category holds one participant more than the
    rice family; the sweet potato had no count of its own before the cooked
    key's was added; and a tenth of the plate, reported twice among nine
    reports, reaches no row. Of the three families no swap offers, water is
    left out by design, the onions are not reachable, and the oil is neither."""
    _pull_recalls(_repo_layout(tmp_path, usda_dir), transport)
    monkeypatch.chdir(tmp_path)
    assert main(["--db", "db.sqlite", "data", "build"]) == 0
    assert not Path("data/popularity").exists()
    assert main(["--db", "db.sqlite", "data", "build", "--write-popularity"]) == 0
    out = capsys.readouterr().out
    assert "usda_foods: 224 rows" in out
    assert "popularity: NHANES 2021-2023, 5 participants, 6 families reported" in out
    with sqlite3.connect("db.sqlite") as conn:
        counts = set(conn.execute("SELECT * FROM popularity"))
        meta = conn.execute("SELECT * FROM popularity_meta").fetchall()
    assert meta == [("2021-2023", 5)]
    families = {
        "beverages, water": 1,
        "chicken, breast": 2,
        "oil, olive": 1,
        "onions, yellow": 1,
        "rice, white": 3,
        "sweet potato": 1,
    }
    variants = {
        "beverages, water, tap, drinking": 1,
        "chicken, breast, meat only": 2,
        "oil, olive, extra virgin": 1,
        "onions, yellow": 1,
        "rice, white, long-grain, regular": 3,
        "sweet potato, flesh": 1,
    }
    assert counts == {
        *(("family", family, n) for family, n in families.items()),
        *(("variant", variant, n) for variant, n in variants.items()),
    }
    table = json.loads(Path("data/popularity/popularity.json").read_text("utf-8"))
    assert table == {
        "cycle": "2021-2023",
        "participants": 5,
        "link_rule": LINK_RULE,
        "unattributed": 0.022222,
        "offered_families": 88,
        "crosswalk": {"rice, white": ["Rice", 3, 4]},
        "families": families,
        "variants": variants,
        "before_count_as": {"sweet potato": 0, "sweet potato, flesh": 1},
        "not_offered": {
            "beverages, water": "excluded-category",
            "oil, olive": "incomplete-macros",
            "onions, yellow": "cooked-with-raw-sibling",
        },
        "by_design": {"beverages, water": "Beverages"},
        "not_reachable": ["onions, yellow"],
    }
    assert main(["--db", "db.sqlite", "data", "report"]) == 0
    assert "families:" in capsys.readouterr().out


def test_data_report_before_build_is_exit_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "db.sqlite"
    db.touch()  # exists, holds no USDA table
    assert main(["--db", str(db), "data", "report"]) == 2
    assert "run `data build` first" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("pulled", "survey", "day_two", "crosswalk", "says"),
    [
        pytest.param(
            False, SURVEY, DAY_TWO, {}, "data pull", id="only-the-usda-releases"
        ),
        pytest.param(
            True,
            SURVEY.replace("6410,2021-01-01,2023-12-31", "6410,2023-01-01,2025-12-31"),
            DAY_TWO,
            {},
            "covers 2021-2023, 2023-2025, not 2021-2023",
            id="a-survey-food-of-another-cycle",
        ),
        pytest.param(
            True,
            SURVEY,
            [*DAY_TWO, (3, 1, 999)],
            {},
            "lacks 1 of the food codes the recall files report, 999",
            id="recall-files-of-another-cycle",
        ),
        pytest.param(
            True,
            SURVEY,
            DAY_TWO,
            {"rice, whit": "Rice"},
            "crosswalk no longer fits the data: ['rice, whit -> Rice']",
            id="a-crosswalk-family-the-table-lacks",
        ),
        pytest.param(
            True,
            SURVEY,
            DAY_TWO,
            {"rice, white": "Rices"},
            "crosswalk no longer fits the data: ['rice, white -> Rices']",
            id="a-crosswalk-category-the-survey-foods-lack",
        ),
    ],
)
def test_data_build_refused_is_exit_two_and_writes_nothing(
    tmp_path: Path,
    usda_dir: Path,
    transport: Callable[[list[str], list[str]], bytes],
    pinned_config: Config,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    pulled: bool,
    survey: str,
    day_two: Sequence[tuple[int, int, int]],
    crosswalk: dict[str, str],
    says: str,
) -> None:
    """With only the two USDA releases pulled, the build stops for the pull.
    One survey food dated to another cycle, a reported food code the survey
    foods lack, or a crosswalk line with a misspelt family or category stops it
    before the USDA table is written."""
    dirs = _repo_layout(tmp_path, usda_dir)
    if pulled:
        _pull_recalls(dirs, transport, survey, day_two)
    popularity = replace(pinned_config.popularity, crosswalk=crosswalk)
    monkeypatch.setattr(
        "macroswap.cli.load_config",
        lambda path=None: replace(pinned_config, popularity=popularity),
    )
    monkeypatch.chdir(tmp_path)
    assert main(["--db", "db.sqlite", "data", "build"]) == 2
    assert says in capsys.readouterr().err
    assert not Path("db.sqlite").exists()


@pytest.mark.usefixtures("pinned_config")
@pytest.mark.parametrize(
    ("flags", "methods"),
    [
        pytest.param(["--method", "lexical"], ["lexical"], id="lexical"),
        pytest.param(["--method", "embed"], ["embed"], id="embed"),
        pytest.param([], ["lexical", "embed", "hybrid"], id="default"),
    ],
)
def test_match_prints_the_method_then_one_line_per_hit(
    tmp_path: Path,
    usda_rows: list[Row],
    fake_embedder: Encoder,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    flags: list[str],
    methods: list[str],
) -> None:
    """A typed name sheds its quantity before matching; a method asked for by
    name runs alone, lexical without the extra, and by default every method
    runs. A score shows four significant digits, so fused scores stay apart."""
    if "embed" in methods:
        monkeypatch.setattr("macroswap.api.Embedder", lambda *args: fake_embedder)
    db = _database(tmp_path, usda_rows)
    assert main(["--db", str(db), "match", "Egg", "Whites,", "5", "large", *flags]) == 0
    lines = capsys.readouterr().out.splitlines()
    headers = [line for line in lines if line.startswith("method:")]
    assert headers == [f"method: {method}" for method in methods]
    assert lines[0] == headers[0]
    score, row_id, description, key = lines[1].split("  ")
    assert float(score) > 0
    scores = [line.split("  ")[0] for line in lines if line not in headers]
    assert scores == [f"{float(shown):#.4g}" for shown in scores]
    assert (row_id, description, key) == (
        "sr:172183",
        "Egg, white, raw, fresh",
        "[egg, white / raw]",
    )


def test_match_label_draws_the_sample_then_needs_every_method(
    tmp_path: Path,
    fixtures_dir: Path,
    usda_rows: list[Row],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The first run draws, prints the tail for review and labels nothing; a
    label taken from lexical's list alone would favour lexical in the eval."""
    monkeypatch.chdir(tmp_path)
    db = str(_database(tmp_path, usda_rows))
    assert main(["--db", db, "diary", "import", str(fixtures_dir)]) == 0
    capsys.readouterr()
    # Only the whole text `label` labels; any other text is a food to match.
    assert main(["--db", db, "match", "label", "maker"]) == 1
    assert capsys.readouterr().out.startswith("method: lexical")
    assert main(["--db", db, "match", "label"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "data/labels/labels.csv: 10 names, "
        "head dev 2, head test 6, tail dev 1, tail test 1",
        "the tail, for review; delete the row of any name you will not publish:",
        "  pictsweet farms - sweet potatoes",
        "  quaker - old fashioned oats",
    ]
    labels = tmp_path / "data" / "labels" / "labels.csv"
    drawn = labels.read_text(encoding="utf-8")
    assert drawn.splitlines()[:2] == [
        "name,count,bucket,split,label,label_source",
        "egg whites,2,head,test,,",
    ]
    assert main(["--db", db, "match", "label"]) == 2
    assert "embed extra not installed" in capsys.readouterr().err
    assert labels.read_text(encoding="utf-8") == drawn


def test_diary_match_refuses_an_orphan_label_then_prints_the_counts(
    tmp_path: Path,
    fixtures_dir: Path,
    usda_rows: list[Row],
    pinned_config: Config,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The orphan label is reported before the model loads, and a default
    method that needs the missing extra exits 2 rather than run lexical under
    its name. Relabeled, under lexical, one name resolves by label, and the
    cheddar, which nothing in the fixture table scores, is NO_MATCH, and the
    recorded fingerprint is the one a reader recomputes."""
    monkeypatch.chdir(tmp_path)
    db = str(_database(tmp_path, usda_rows))
    assert main(["--db", db, "diary", "import", str(fixtures_dir)]) == 0
    capsys.readouterr()
    embed = replace(pinned_config.match, default_method="embed")
    monkeypatch.setattr(
        "macroswap.cli.load_config",
        lambda path=None: replace(pinned_config, match=embed),
    )
    labels = Path(pinned_config.paths.labels)
    write_labels(labels, [Label("egg whites", 2, "head", "dev", "sr:1", "search")])
    assert main(["--db", db, "diary", "match"]) == 2
    assert "egg whites = sr:1" in capsys.readouterr().err
    write_labels(labels, [Label("egg whites", 2, "head", "dev", "sr:172183", "search")])
    assert main(["--db", db, "diary", "match"]) == 2
    assert "embed extra not installed (uv sync --extra embed)" in (
        capsys.readouterr().err
    )
    monkeypatch.setattr("macroswap.cli.load_config", lambda path=None: pinned_config)
    assert main(["--db", db, "diary", "match"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "method: lexical",
        "names: 10; by label: 1; by matcher: 8; NO_MATCH: 1",
    ]
    check_fingerprint(connect(Path(db)), pinned_config.match, labels)


def test_match_eval_prints_dev_then_writes_the_test_table(
    tmp_path: Path,
    usda_rows: list[Row],
    pinned_config: Config,
    fake_embedder: Encoder,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Without the extra the eval runs lexical alone and says so, but will not
    write the table CI checks every method against. The test split prints only
    with --test; --write-expected writes it without printing it."""
    monkeypatch.chdir(tmp_path)
    db = str(_database(tmp_path, usda_rows))
    write_labels(
        Path(pinned_config.paths.labels),
        [
            Label("egg whites", 2, "head", "dev", "sr:172183", "suggestion"),
            Label("chipotle - chicken bowl", 1, "tail", "test", NO_MATCH, "no_match"),
        ],
    )
    assert main(["--db", db, "match", "eval"]) == 0
    dev = capsys.readouterr().out.splitlines()
    assert dev[:3] == [
        "method: lexical; embed extra not installed (uv sync --extra embed)",
        "| split | bucket | weighting | metric | lexical |",
        "| --- | --- | --- | --- | --- |",
    ]
    assert "| dev | head | rows | top1_end_to_end | 1.000 [1.000, 1.000] n=1 |" in dev
    assert not [line for line in dev if line.startswith("| test")]
    assert dev[-2:] == [
        "method lexical: 1 of 1 dev names right end to end at its threshold",
        "lexical = -inf  # dev-optimal: 1 of 1 right; 0 dev names labeled NO_MATCH",
    ]
    assert main(["--db", db, "match", "eval", "--test"]) == 0
    recall = "| test | tail | names | no_match_recall | 0.000 [0.000, 0.000] n=1 |"
    assert recall in capsys.readouterr().out.splitlines()
    expected = Path(pinned_config.paths.eval_expected)
    assert main(["--db", db, "match", "eval", "--write-expected"]) == 2
    assert "embed extra not installed" in capsys.readouterr().err
    assert not expected.exists()
    monkeypatch.setattr("macroswap.api.Embedder", lambda *args: fake_embedder)
    assert main(["--db", db, "match", "eval", "--write-expected"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert not [line for line in out if line.startswith("| test")]
    assert out[-1] == f"{expected}: 18 test cells"
    written = {(cell.method, cell.split) for cell in read_expected(expected)}
    assert written == {(method, "test") for method in ("lexical", "embed", "hybrid")}


def _database(tmp_path: Path, rows: list[Row]) -> Path:
    """A database with the diary tables and, when given, these USDA rows."""
    db = tmp_path / "db.sqlite"
    with connect(db) as conn:
        if rows:
            write_usda(conn, [astuple(r) for r in rows])
    return db
