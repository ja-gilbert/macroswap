from __future__ import annotations

import shutil
from dataclasses import astuple, replace
from pathlib import Path

import pytest

from macroswap.cli import main
from macroswap.config import Config
from macroswap.match.diary import check_fingerprint
from macroswap.match.label import Label, write_labels
from macroswap.match.matcher import Encoder
from macroswap.store import connect, write_usda
from macroswap.usda.table import Row

# The exit-code table, one row per case from this milestone on; the pull
# checksum row is in test_pull.py, and `diary match` refusing without the
# embed extra is in its own test.
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


def _repo_layout(tmp_path: Path, usda_dir: Path, pulled: bool) -> None:
    """The packaged config's relative paths, rooted at tmp_path."""
    data = tmp_path / "data"
    (data / "raw").mkdir(parents=True)
    shutil.copy(Path(__file__).resolve().parents[2] / "data" / "manifest.toml", data)
    if pulled:
        (data / "raw" / "usda").symlink_to(usda_dir, target_is_directory=True)


def test_data_build_then_report(
    tmp_path: Path,
    usda_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _repo_layout(tmp_path, usda_dir, pulled=True)
    monkeypatch.chdir(tmp_path)
    assert main(["--db", "db.sqlite", "data", "build"]) == 0
    assert "usda_foods: 208 rows" in capsys.readouterr().out
    assert main(["--db", "db.sqlite", "data", "report"]) == 0
    assert "families:" in capsys.readouterr().out


def test_data_report_before_build_is_exit_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "db.sqlite"
    db.touch()  # exists, holds no USDA table
    assert main(["--db", str(db), "data", "report"]) == 2
    assert "run `data build` first" in capsys.readouterr().err


def test_data_build_before_pull_is_exit_two(
    tmp_path: Path,
    usda_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _repo_layout(tmp_path, usda_dir, pulled=False)
    monkeypatch.chdir(tmp_path)
    assert main(["--db", "db.sqlite", "data", "build"]) == 2
    assert "data pull" in capsys.readouterr().err


@pytest.mark.usefixtures("pinned_config")
@pytest.mark.parametrize(
    ("flags", "methods"),
    [
        pytest.param(["--method", "lexical"], ["lexical"], id="lexical"),
        pytest.param(["--method", "embed"], ["embed"], id="embed"),
        pytest.param([], ["lexical", "embed"], id="default"),
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
    runs."""
    if "embed" in methods:
        monkeypatch.setattr("macroswap.cli.Embedder", lambda *args: fake_embedder)
    db = _database(tmp_path, usda_rows)
    assert main(["--db", str(db), "match", "Egg", "Whites,", "5", "large", *flags]) == 0
    lines = capsys.readouterr().out.splitlines()
    headers = [line for line in lines if line.startswith("method:")]
    assert headers == [f"method: {method}" for method in methods]
    assert lines[0] == headers[0]
    score, row_id, description, key = lines[1].split("  ")
    assert float(score) > 0
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


def _database(tmp_path: Path, rows: list[Row]) -> Path:
    """A database with the diary tables and, when given, these USDA rows."""
    db = tmp_path / "db.sqlite"
    with connect(db) as conn:
        if rows:
            write_usda(conn, [astuple(r) for r in rows])
    return db
