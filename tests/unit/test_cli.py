from __future__ import annotations

import shutil
from dataclasses import astuple
from pathlib import Path

import pytest

from macroswap.cli import main
from macroswap.store import connect, write_usda
from macroswap.usda.table import Row

# The exit-code table, one row per case from this milestone on; the pull
# checksum row is in test_pull.py.
EXIT_CODES = {
    "match-where-every-method-abstains": (["match", "zzzz"], True, 1, "NO_MATCH"),
    "match-before-data-build": (
        ["match", "egg whites"],
        False,
        2,
        "run `data build` first",
    ),
}


@pytest.mark.parametrize(
    ("args", "built", "code", "says"), EXIT_CODES.values(), ids=EXIT_CODES.keys()
)
def test_exit_code(
    tmp_path: Path,
    usda_rows: list[Row],
    capsys: pytest.CaptureFixture[str],
    args: list[str],
    built: bool,
    code: int,
    says: str,
) -> None:
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


def test_match_prints_the_method_then_one_line_per_hit(
    tmp_path: Path, usda_rows: list[Row], capsys: pytest.CaptureFixture[str]
) -> None:
    """A typed name sheds its quantity before matching."""
    db = _database(tmp_path, usda_rows)
    assert main(["--db", str(db), "match", "Egg", "Whites,", "5", "large"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "method: lexical"
    score, row_id, description, key = lines[1].split("  ")
    assert float(score) > 0
    assert (row_id, description, key) == (
        "sr:172183",
        "Egg, white, raw, fresh",
        "[egg, white / raw]",
    )


def _database(tmp_path: Path, rows: list[Row]) -> Path:
    """A database with the diary tables and, when given, these USDA rows."""
    db = tmp_path / "db.sqlite"
    with connect(db) as conn:
        if rows:
            write_usda(conn, [astuple(r) for r in rows])
    return db
