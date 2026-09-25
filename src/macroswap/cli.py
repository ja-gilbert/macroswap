"""Command-line entry point. Exit codes: 0 success, 2 usage or data errors."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from macroswap.config import Config, ConfigError, load_config
from macroswap.diary.importer import DiaryImportError, import_directory
from macroswap.diary.parse import ParseError
from macroswap.diary.stats import compute_stats, format_stats
from macroswap.pull import PullError, pull
from macroswap.store import connect

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


def _existing(db: Path, hint: str) -> sqlite3.Connection:
    # connect() creates the file it is pointed at, so a typo in --db would
    # otherwise report an empty database instead of a missing one.
    if not db.exists():
        raise FileNotFoundError(f"no database at {db}; run `{hint}` first")
    return connect(db)
