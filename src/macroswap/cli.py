"""Command-line entry point. Exit codes: 0 success, 2 usage or data errors."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from macroswap.config import Config, ConfigError, load_config
from macroswap.diary.importer import DiaryImportError, import_directory
from macroswap.diary.parse import ParseError
from macroswap.diary.stats import compute_stats, format_stats
from macroswap.store import connect


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
    diary_commands.add_parser("stats", help="coverage, untracked days, name shape")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(Path(args.config) if args.config else None)
        db = Path(args.db or config.paths.db)
        if args.diary_command == "import":
            return _diary_import(config, db, args.directory)
        return _diary_stats(config, db)
    except (ConfigError, DiaryImportError, ParseError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _diary_import(config: Config, db: Path, directory: Path) -> int:
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


def _diary_stats(config: Config, db: Path) -> int:
    if not db.exists():
        raise DiaryImportError(f"no database at {db}; run `diary import` first")
    with connect(db) as conn:
        print(format_stats(compute_stats(conn, config.stats.coverage_shares)))
    return 0
