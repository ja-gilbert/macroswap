"""Command-line entry point. Exit codes: 0 success, 2 usage or data errors."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Callable, Sequence
from dataclasses import astuple
from pathlib import Path

from macroswap.config import Config, ConfigError, load_config
from macroswap.diary.importer import DiaryImportError, import_directory
from macroswap.diary.parse import ParseError
from macroswap.diary.stats import compute_stats, format_stats
from macroswap.pull import PullError, pull, release_dirs
from macroswap.store import connect, write_usda
from macroswap.usda.load import load_release, merge
from macroswap.usda.report import family_report
from macroswap.usda.table import BuildError, build_table

Handler = Callable[[Config, Path, argparse.Namespace], int]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="macroswap", description="Macro-equivalent food swaps."
    )
    parser.add_argument("--config", help="path to a macroswap.toml (default: packaged)")
    parser.add_argument("--db", help="SQLite path (default: paths.db from the config)")
    commands = parser.add_subparsers(dest="command", required=True)
    diary = commands.add_parser("diary", help="import and inspect the diary")
    diary_commands = diary.add_subparsers(dest="diary_command", required=True)
    diary_import = diary_commands.add_parser(
        "import", help="import mfp_<from>_<to>.html files from a directory"
    )
    diary_import.add_argument("directory", type=Path)
    diary_import.set_defaults(run=_diary_import)
    diary_commands.add_parser(
        "stats", help="coverage, untracked days, name shape"
    ).set_defaults(run=_diary_stats)
    data = commands.add_parser("data", help="fetch and build the USDA food table")
    data_commands = data.add_subparsers(dest="data_command", required=True)
    data_commands.add_parser(
        "pull", help="download the pinned USDA releases, verifying checksums"
    ).set_defaults(run=_data_pull)
    data_commands.add_parser(
        "build", help="build the USDA food table from the pulled releases"
    ).set_defaults(run=_data_build)
    data_commands.add_parser(
        "report", help="families, exclusion reasons, and override candidates"
    ).set_defaults(run=_data_report)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run: Handler = args.run
    try:
        config = load_config(Path(args.config) if args.config else None)
        return run(config, Path(args.db or config.paths.db), args)
    except (
        ConfigError,
        DiaryImportError,
        ParseError,
        PullError,
        BuildError,
        OSError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _diary_import(config: Config, db: Path, args: argparse.Namespace) -> int:
    directory: Path = args.directory
    if not directory.is_dir():
        raise DiaryImportError(f"not a directory: {directory}")
    with connect(db) as conn:
        reports = import_directory(conn, directory, config.diary)
    for report in reports:
        print(
            f"{report.file}: {report.days} days, {report.rows} rows, "
            f"{report.untracked_days} untracked, "
            f"{report.reconciled_days} of {report.days} reconciled, "
            f"{report.total_mismatches} total mismatches"
        )
    return 0


def _diary_stats(config: Config, db: Path, args: argparse.Namespace) -> int:
    with _existing(db, "diary import") as conn:
        print(format_stats(compute_stats(conn, config.stats.coverage_shares)))
    return 0


def _data_pull(config: Config, db: Path, args: argparse.Namespace) -> int:
    for line in pull(Path(config.paths.manifest), Path(config.paths.raw)):
        print(line)
    return 0


def _data_build(config: Config, db: Path, args: argparse.Namespace) -> int:
    dirs = release_dirs(Path(config.paths.manifest), Path(config.paths.raw))
    for folder in dirs.values():
        if not folder.is_dir():
            raise PullError(f"no USDA release at {folder}; run `data pull` first")
    loaded = merge(
        load_release(dirs["sr_legacy"], "sr"),
        load_release(dirs["foundation"], "foundation"),
        config.usda.dry_basis_marker,
    )
    rows = build_table(loaded.foods, config.usda)
    with connect(db) as conn:
        write_usda(conn, [astuple(r) for r in rows])
    candidates = sum(r.exclusion_reason is None for r in rows)
    print(f"usda_foods: {len(rows)} rows, {candidates} candidates")
    dropped = loaded.dry_basis_dropped
    distinct = sorted(set(dropped))
    print(
        f"foundation: {loaded.ndb_overlap} dropped for an SR NDB; "
        f"dry-basis rows dropped: {len(dropped)} ({len(distinct)} distinct)"
    )
    for description in distinct:
        print(f"  {description}")
    return 0


def _data_report(config: Config, db: Path, args: argparse.Namespace) -> int:
    with _existing(db, "data build") as conn:
        # diary import creates the database without the USDA table.
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'usda_foods'"
        ).fetchone():
            raise FileNotFoundError(f"no USDA table in {db}; run `data build` first")
        print(
            family_report(
                conn, config.swap.rank_weights, config.usda.varietal_threshold
            )
        )
    return 0


def _existing(db: Path, hint: str) -> sqlite3.Connection:
    # connect() creates the file it is pointed at, so a typo in --db would
    # otherwise report an empty database instead of a missing one.
    if not db.exists():
        raise FileNotFoundError(f"no database at {db}; run `{hint}` first")
    return connect(db)
