"""Command-line entry point. Exit codes: 0 success, 1 no match or no swap, 2
usage or missing data."""

from __future__ import annotations

import argparse
import math
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import astuple
from pathlib import Path

from macroswap.api import load_matcher
from macroswap.config import Config, ConfigError, load_config
from macroswap.diary.importer import DiaryImportError, import_directory
from macroswap.diary.normalize import name_key
from macroswap.diary.parse import ParseError
from macroswap.diary.stats import compute_stats, format_stats, name_counts
from macroswap.match.diary import Fingerprint, LabelError, StaleMatches, match_diary
from macroswap.match.embed import EmbedUnavailable
from macroswap.match.evaluate import (
    compare_methods,
    evaluate,
    format_cells,
    write_expected,
)
from macroswap.match.label import draw_sample, label_session, read_labels, write_labels
from macroswap.match.matcher import Matcher
from macroswap.nhanes.popularity import measure, write_table
from macroswap.pull import PullError, pull, release_dirs
from macroswap.store import (
    connect,
    open_built,
    open_existing,
    read_popularity,
    read_usda,
    write_popularity,
    write_usda,
)
from macroswap.swap.logged import (
    default_levels,
    diary_families,
    entry,
    like_log,
    read_diary,
)
from macroswap.swap.rank import Candidate, rank
from macroswap.swap.show import header, table
from macroswap.swap.target import NoTarget, TargetError, typed
from macroswap.usda.load import load_release, merge
from macroswap.usda.report import family_report
from macroswap.usda.table import BuildError, Row, build_table

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
    diary_commands.add_parser(
        "match", help="resolve every diary name once (writes diary_matches)"
    ).set_defaults(run=_diary_match)
    data = commands.add_parser(
        "data", help="fetch the pinned sources and build the food table"
    )
    data_commands = data.add_subparsers(dest="data_command", required=True)
    data_commands.add_parser(
        "pull", help="download the pinned sources, verifying checksums"
    ).set_defaults(run=_data_pull)
    build = data_commands.add_parser(
        "build",
        help="build the USDA food table and count who reported each food family",
    )
    build.add_argument(
        "--write-popularity",
        action="store_true",
        help="also rewrite the committed popularity table from the counts",
    )
    build.set_defaults(run=_data_build)
    data_commands.add_parser(
        "report", help="families, exclusion reasons, and override candidates"
    ).set_defaults(run=_data_report)
    match = commands.add_parser("match", help="the top USDA rows for a food name")
    match.add_argument(
        "text",
        nargs="+",
        help='e.g. "greek yogurt w/ berries"; `label` labels the sample, `eval` '
        "scores every method on it",
    )
    match.add_argument(
        "--method",
        choices=["lexical", "embed", "hybrid"],
        help="one method (default: every method that loads); not for `label` or `eval`",
    )
    match.add_argument(
        "--test", action="store_true", help="eval only: print the test split too"
    )
    match.add_argument(
        "--write-expected",
        action="store_true",
        help="eval only: rewrite the committed expected table from the test split",
    )
    match.set_defaults(run=_match)
    swap = commands.add_parser(
        "swap", help="other foods, and the grams of each, that match a food's macros"
    )
    swap.add_argument("text", nargs="*", help='a food, e.g. "egg whites"')
    swap.add_argument("--grams", type=float, help="how much of the typed food")
    swap.add_argument(
        "--like-log",
        action="store_true",
        help="the typed food at the median macros the diary logs for it",
    )
    swap.add_argument(
        "--entry", metavar="NAME", help="a diary food by its name, as logged"
    )
    swap.add_argument(
        "--top", type=int, help="family rows to print (default: swap.top)"
    )
    swap.add_argument(
        "--variants",
        action="store_true",
        help="each family's other variants, and the target's own family",
    )
    swap.add_argument(
        "--new-only", action="store_true", help="leave out families the diary logs"
    )
    swap.add_argument(
        "--include-obscure",
        action="store_true",
        help="keep families below the popularity floor",
    )
    swap.add_argument(
        "--method",
        choices=["lexical", "embed", "hybrid"],
        help="how the typed food is matched (default: match.default_method); "
        "not for --entry",
    )
    swap.set_defaults(run=_swap)
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
        EmbedUnavailable,
        LabelError,
        StaleMatches,
        TargetError,
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
    with open_existing(db, "diary import") as conn:
        print(format_stats(compute_stats(conn, config.stats.coverage_shares)))
    return 0


def _diary_match(config: Config, db: Path, args: argparse.Namespace) -> int:
    path = Path(config.paths.labels)
    labels = read_labels(path) if path.exists() else []
    fingerprint = Fingerprint.current(config.match, path)
    method = config.match.default_method

    def make_matcher(rows: list[Row]) -> Matcher:
        # No fallback to lexical: the fingerprint names the method that ran.
        return load_matcher(config, rows, db.parent, method, strict=True)[0]

    with open_built(db) as conn:
        summary = match_diary(conn, labels, make_matcher, fingerprint)
    names = summary.by_label + summary.by_matcher + summary.no_match
    print(f"method: {method}")
    print(
        f"names: {names}; by label: {summary.by_label}; "
        f"by matcher: {summary.by_matcher}; NO_MATCH: {summary.no_match}"
    )
    return 0


def _data_pull(config: Config, db: Path, args: argparse.Namespace) -> int:
    for line in pull(Path(config.paths.manifest), Path(config.paths.raw)):
        print(line)
    return 0


def _data_build(config: Config, db: Path, args: argparse.Namespace) -> int:
    dirs = release_dirs(Path(config.paths.manifest), Path(config.paths.raw))
    for source in dirs.values():
        if not source.exists():
            raise PullError(f"nothing pulled at {source}; run `data pull` first")
    loaded = merge(
        load_release(dirs["sr_legacy"], "sr"),
        load_release(dirs["foundation"], "foundation"),
        config.usda.dry_basis_marker,
    )
    rows = build_table(loaded.foods, config.usda)
    # Counted before anything is written, so a refusal leaves the store as it was.
    recalls = (dirs["nhanes_day1"], dirs["nhanes_day2"])
    popularity = measure(dirs["fndds"], recalls, rows, config.popularity, config.usda)
    with connect(db) as conn:
        write_usda(conn, [astuple(r) for r in rows])
        write_popularity(conn, popularity)
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
    print(
        f"popularity: NHANES {popularity.cycle}, "
        f"{popularity.participants} participants, "
        f"{len(popularity.families)} families reported"
    )
    if args.write_popularity:
        committed = Path(config.paths.popularity)
        write_table(committed, popularity)
        print(f"{committed}: written")
    return 0


def _data_report(config: Config, db: Path, args: argparse.Namespace) -> int:
    with open_built(db) as conn:
        print(
            family_report(
                conn, config.swap.rank_weights, config.usda.varietal_threshold
            )
        )
    return 0


def _match(config: Config, db: Path, args: argparse.Namespace) -> int:
    if args.text == ["label"]:
        return _match_label(config, db)
    if args.text == ["eval"]:
        return _match_eval(config, db, args)
    with open_built(db) as conn:
        rows = read_usda(conn)
    matcher, fallback = load_matcher(
        config, rows, db.parent, args.method, strict=args.method is not None
    )
    text = name_key(" ".join(args.text))
    methods = [args.method] if args.method else matcher.methods
    results = {method: matcher.run(text, method) for method in methods}
    for method, hits in results.items():
        print(f"method: {method}{fallback}")
        if hits is None:
            print("NO_MATCH")
        for hit in hits or []:
            print(f"{hit.score:#.4g}  {hit.row.id}  {hit.row.description}  [{hit.key}]")
    return 1 if all(hits is None for hits in results.values()) else 0


def _match_label(config: Config, db: Path) -> int:
    path = Path(config.paths.labels)
    if not path.exists():
        with open_existing(db, "diary import") as conn:
            counts = name_counts(conn)
        if not counts:
            raise FileNotFoundError(f"no diary names in {db}; run `diary import` first")
        labels = draw_sample(counts, config.labels)
        write_labels(path, labels)
        cells = Counter(f"{label.bucket} {label.split}" for label in labels)
        sizes = ", ".join(f"{cell} {n}" for cell, n in sorted(cells.items()))
        print(f"{path}: {len(labels)} names, {sizes}")
        print("the tail, for review; delete the row of any name you will not publish:")
        for label in labels:
            if label.bucket == "tail":
                print(f"  {label.name}")
        return 0
    with open_built(db) as conn:
        rows = read_usda(conn)
    # Every method or no labels: a label picked from one method's list alone
    # would favour that method in the eval.
    matcher, _ = load_matcher(config, rows, db.parent, None, strict=True)
    label_session(path, matcher, rows, config.labels)
    return 0


def _match_eval(config: Config, db: Path, args: argparse.Namespace) -> int:
    path = Path(config.paths.labels)
    if not path.exists():
        raise FileNotFoundError(f"no labels at {path}; run `match label` first")
    labels = read_labels(path)
    with open_built(db) as conn:
        rows = read_usda(conn)
    # The committed table needs every method, since CI checks each; lexical
    # alone is still worth measuring, and the header says what is missing.
    matcher, note = load_matcher(
        config, rows, db.parent, None, strict=args.write_expected
    )
    if note:
        print(f"method: lexical{note}")
    # The test split is scored only when asked for, and never tunes anything.
    splits = ("dev", "test") if args.test or args.write_expected else ("dev",)
    wanted = [label for label in labels if label.split in splits]
    cells = evaluate(matcher, rows, wanted, config.eval, matcher.methods)
    print(format_cells([cell for cell in cells if cell.split == "dev" or args.test]))
    print(compare_methods(matcher, rows, labels))
    if args.write_expected:
        expected = Path(config.paths.eval_expected)
        test = [cell for cell in cells if cell.split == "test"]
        write_expected(expected, test)
        print(f"{expected}: {len(test)} test cells")
    return 0


def _swap(config: Config, db: Path, args: argparse.Namespace) -> int:
    text = " ".join(args.text)
    amounts = (args.grams is not None, args.like_log, bool(args.entry))
    if sum(amounts) != 1 or bool(text) == bool(args.entry):
        raise TargetError(
            "give a food with --grams or --like-log, or --entry with a diary name"
        )
    if (args.grams is not None and not 0 < args.grams < math.inf) or (
        args.top is not None and args.top < 1
    ):
        raise TargetError("--grams must be above zero and --top at least 1")
    with open_built(db) as conn:
        rows = read_usda(conn)
        counted = read_popularity(conn)
        if counted is None:
            raise FileNotFoundError(
                f"no participant counts in {db}; run `data build` again"
            )
        diary = read_diary(conn, config)
    cycle, counts = counted
    levels = default_levels(diary, rows, config)
    fallback = ""
    if args.entry:
        resolved = entry(args.entry, diary, rows, config)
    else:
        method = args.method or config.match.default_method
        matcher, fallback = load_matcher(
            config, rows, db.parent, method, strict=args.method is not None
        )
        if "embed" not in matcher.methods:
            method = "lexical"
        try:
            if args.like_log:
                resolved = like_log(text, diary, rows, matcher, method, config, levels)
            else:
                grams = args.grams
                resolved = typed(text, grams, rows, matcher, method, config, levels)
        except NoTarget as exc:
            print(f"method: {method}{fallback}")
            nearest = [
                (name, hit) for name, hits in exc.nearest.items() for hit in hits
            ]
            rows_follow = ". The nearest rows:" if nearest else ""
            print(f"{exc}; --method tries another method{rows_follow}")
            for name, hit in nearest:
                print(f"  {name}  {hit.row.id}  {hit.row.description}  [{hit.key}]")
            return 1
    families, unmatched = diary_families(diary)
    ranking = rank(
        resolved.target,
        [
            Candidate(
                row,
                counts.families.get(row.family, 0),
                counts.variants.get(row.variant, 0),
            )
            for row in rows
            if row.exclusion_reason is None
        ],
        config.swap,
        default_levels=levels,
        diary_families=families,
        allowlist=config.popularity.allowlist,
        variants=args.variants,
        new_only=args.new_only,
        include_obscure=args.include_obscure,
        top=args.top,
    )
    amount = "as logged" if args.grams is None else f"{args.grams:g} g"
    print("\n".join(header(resolved, amount, fallback)))
    if args.new_only:
        print(
            f"new only: {len(families)} diary families left out; "
            f"{unmatched} diary names matched nothing"
        )
    print(
        f"popularity: NHANES {cycle}, {counts.participants} participants; "
        "count is how many reported the family"
    )
    if not ranking.common and not ranking.rest:
        reasons = "; ".join(f"{reason} {n}" for reason, n in ranking.filtered.items())
        print(f"no swap: every candidate was left out ({reasons})")
        return 1
    print("\n".join(table(ranking, levels)))
    return 0
