"""Score each method on the labeled sample, the numbers the README carries.

A name is right at top k when one of its first k hits has the key of any id
its label lists: a labeled row keys as a hit on it would for that name, a
family key is its own key, and NO_MATCH is right when the method abstains.
exact_id reads the label's first id. Ranking scores the hits whatever the
threshold and leaves out NO_MATCH labels; end-to-end applies the threshold.
Every cell carries its n and a seeded bootstrap interval over names, drawn once
per split and bucket so every method sees the same draws. CI compares the test
split with a committed table; the dev split tunes the thresholds and picks the
method, and is never gated.
"""

from __future__ import annotations

import csv
import math
import random
import re
from dataclasses import astuple, dataclass, fields
from itertools import pairwise, product
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from macroswap.config import EvalConfig
from macroswap.diary.normalize import parse_leanness
from macroswap.match.diary import LabelError
from macroswap.match.label import NO_MATCH, Label, label_ids
from macroswap.match.matcher import Hit, Matcher
from macroswap.usda.table import Row

_SPLITS = ("dev", "test")
_BUCKETS = ("head", "tail")
_WEIGHTINGS = ("names", "rows")
_METRICS = (
    "top1_ranking",
    "top1_end_to_end",
    "top5_ranking",
    "top5_end_to_end",
    "no_match_precision",
    "no_match_recall",
    "exact_id",
)
_BLOCK = re.compile(r"(<!-- eval:begin -->\n).*?(<!-- eval:end -->)", re.DOTALL)


@dataclass(frozen=True)
class Cell:
    method: str
    split: str
    bucket: str
    weighting: str
    metric: str
    # The names the metric counts, and the share of their weight it gets right.
    n: int
    value: float
    low: float
    high: float
    # The largest one name's share of that weight: what one flipped name moves.
    one_flip: float


@dataclass(frozen=True)
class Scored:
    """A labeled name under one method."""

    label: Label
    # The match key of each id the label lists, the first id's first; empty for
    # NO_MATCH.
    keys: tuple[str, ...]
    # The method's hits whatever its threshold, and whether it abstains at it.
    ranked: list[Hit]
    abstains: bool


def score(
    matcher: Matcher, rows: list[Row], labels: list[Label], method: str
) -> list[Scored]:
    """Each label's name under the method; every label must be made. A label
    listing an id that names no row and no leanness family is refused."""
    by_id = {row.id: row for row in rows}
    families = {row.family for row in rows if row.lean_pct is not None}
    scored = []
    for label in labels:
        ids = [] if label.label == NO_MATCH else label_ids(label.label)
        if any(i not in by_id and i not in families for i in ids):
            raise LabelError(
                f"label naming nothing in usda_foods: {label.name} = {label.label}"
            )
        level = parse_leanness(label.name)
        keys = tuple(
            matcher.match_key(by_id[i], level) if i in by_id else i for i in ids
        )
        ranked = matcher.rank(label.name, method)
        abstains = matcher.run(label.name, method) is None
        scored.append(Scored(label, keys, ranked, abstains))
    return scored


def evaluate(
    matcher: Matcher,
    rows: list[Row],
    labels: list[Label],
    cfg: EvalConfig,
    methods: tuple[str, ...],
) -> list[Cell]:
    """Every cell over the labels made, by method, split, bucket, weighting and
    metric; a metric that counts no name in a bucket has no cell."""
    made = [label for label in labels if label.label]
    groups = {
        where: [label for label in made if (label.split, label.bucket) == where]
        for where in product(_SPLITS, _BUCKETS)
    }
    draws = {
        where: np.array(bootstrap(len(group), cfg))
        for where, group in groups.items()
        if group
    }
    cells = []
    for method in methods:
        for (split, bucket), drawn in draws.items():
            group = groups[split, bucket]
            marks = [_marks(s) for s in score(matcher, rows, group, method)]
            for weighting in _WEIGHTINGS:
                weights = [
                    1 if weighting == "names" else label.count for label in group
                ]
                for metric in _METRICS:
                    stats = _stats([m[metric] for m in marks], weights, drawn, cfg)
                    if stats is not None:
                        cells.append(
                            Cell(method, split, bucket, weighting, metric, *stats)
                        )
    return cells


def bootstrap(n: int, cfg: EvalConfig) -> list[list[int]]:
    """The resamples of n names, with replacement, as indexes."""
    rng = random.Random(cfg.bootstrap_seed)
    return [rng.choices(range(n), k=n) for _ in range(cfg.bootstrap_resamples)]


def tune_threshold(scored: list[Scored]) -> float:
    """The cut that gets the most names right end to end at top 1, abstaining
    below it: -inf, or midway between two adjacent distinct top scores. A tie
    goes to the lowest cut."""
    tops = sorted({s.ranked[0].score for s in scored if s.ranked})
    cuts = [-math.inf, *((low + high) / 2 for low, high in pairwise(tops))]
    # max keeps the first of equals, and the cuts ascend.
    return max(cuts, key=lambda cut: _right_at(scored, cut))


def compare_methods(matcher: Matcher, rows: list[Row], labels: list[Label]) -> str:
    """Per method over the whole dev split, per name: end-to-end top-1 at its
    threshold, which picks the method `diary match` runs; then its dev-optimal
    threshold, as a line for [match.no_match]. Hybrid has no threshold of its
    own: it is scored at both of the others and gets no dev-optimal line."""
    dev = [label for label in labels if label.label and label.split == "dev"]
    no_match = sum(label.label == NO_MATCH for label in dev)
    scored = {method: score(matcher, rows, dev, method) for method in matcher.methods}
    lines = [
        f"method {method}: {sum(_right(s, s.abstains, 1) for s in names)} of "
        f"{len(names)} dev names right end to end at "
        f"{'both thresholds' if method == 'hybrid' else 'its threshold'}"
        for method, names in scored.items()
    ]
    for method, names in scored.items():
        if method == "hybrid":
            continue
        cut = tune_threshold(names)
        lines.append(
            f"{method} = {cut!r}  # dev-optimal: {_right_at(names, cut)} of "
            f"{len(names)} right; {no_match} dev names labeled NO_MATCH"
        )
    return "\n".join(lines)


def format_cells(cells: list[Cell]) -> str:
    """A markdown table, a column per method and a row per split, bucket,
    weighting and metric: the value, its interval and n."""
    methods = list(dict.fromkeys(cell.method for cell in cells))
    found = {_where(cell): cell for cell in cells}
    header = ("split", "bucket", "weighting", "metric", *methods)
    lines = ["| " + " | ".join(header) + " |", "|" + " --- |" * len(header)]
    for where in product(_SPLITS, _BUCKETS, _WEIGHTINGS, _METRICS):
        row = [found.get((method, *where)) for method in methods]
        if any(row):
            lines.append("| " + " | ".join((*where, *map(_entry, row))) + " |")
    return "\n".join(lines)


def render_readme(readme: str, cells: list[Cell]) -> str:
    """The README with the table between its eval markers replaced."""
    rendered, found = _BLOCK.subn(
        lambda block: f"{block[1]}{format_cells(cells)}\n{block[2]}", readme
    )
    if not found:
        raise ValueError("no <!-- eval:begin --> ... <!-- eval:end --> block")
    return rendered


def write_expected(path: Path, cells: list[Cell]) -> None:
    """At full precision, so lexical compares exactly."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(field.name for field in fields(Cell))
        writer.writerows(astuple(cell) for cell in cells)


def read_expected(path: Path) -> list[Cell]:
    with path.open(newline="", encoding="utf-8") as f:
        return [
            Cell(
                r["method"],
                r["split"],
                r["bucket"],
                r["weighting"],
                r["metric"],
                int(r["n"]),
                float(r["value"]),
                float(r["low"]),
                float(r["high"]),
                float(r["one_flip"]),
            )
            for r in csv.DictReader(f)
        ]


def compare(
    actual: list[Cell], expected: list[Cell], tolerated_flips: dict[str, int]
) -> list[str]:
    """Each cell that differs from the table: a value off by more than
    tolerated_flips[method] times the larger one_flip of the two, to six
    decimals, or a different n. no_match_precision counts the names that
    abstain, so each tolerated flip may also move its n by one, or make or drop
    a cell of that few names; the larger one_flip bounds what a name that
    starts or stops abstaining moves."""
    found = {_where(cell): cell for cell in actual}
    differ = []
    for want in expected:
        where = " ".join(_where(want))
        moves = _moves(want, tolerated_flips)
        got = found.pop(_where(want), None)
        if got is None:
            if want.n > moves:
                differ.append(f"{where}: no longer made")
            continue
        off = round(abs(got.value - want.value), 6)
        one_flip = max(want.one_flip, got.one_flip)
        allowed = round(tolerated_flips[want.method] * one_flip, 6)
        if abs(got.n - want.n) > moves or off > allowed:
            differ.append(
                f"{where}: n={got.n} {got.value:.6f}, "
                f"expected n={want.n} {want.value:.6f}"
            )
    differ.extend(
        f"{' '.join(where)}: not in the table"
        for where, extra in found.items()
        if extra.n > _moves(extra, tolerated_flips)
    )
    return differ


def _moves(cell: Cell, tolerated_flips: dict[str, int]) -> int:
    """How far the cell's n may move: the labels fix every n but
    no_match_precision's, which counts abstentions."""
    if cell.metric != "no_match_precision":
        return 0
    return tolerated_flips[cell.method]


def _right(s: Scored, abstains: bool, k: int) -> bool:
    """Abstaining is right for a NO_MATCH label and wrong for any other, which
    is right when any of its keys is among the top k hits."""
    if not s.keys:
        return abstains
    return not abstains and any(hit.key in s.keys for hit in s.ranked[:k])


def _right_at(scored: list[Scored], cut: float) -> int:
    """Names right end to end at top 1, abstaining below the cut."""
    return sum(_right(s, not s.ranked or s.ranked[0].score < cut, 1) for s in scored)


def _marks(s: Scored) -> dict[str, bool | None]:
    """Per metric, whether the name is right, or None where it is not counted.
    Ranking counts only the labels naming a food."""
    no_match = not s.keys
    # exact_id reads the first id, and only a row names one: a family key is
    # its own key.
    first = label_ids(s.label.label)[0]
    row_label = not no_match and first != s.keys[0]
    exact = bool(s.ranked) and s.ranked[0].row.id == first
    return {
        "top1_ranking": None if no_match else _right(s, False, 1),
        "top1_end_to_end": _right(s, s.abstains, 1),
        "top5_ranking": None if no_match else _right(s, False, 5),
        "top5_end_to_end": _right(s, s.abstains, 5),
        "no_match_precision": no_match if s.abstains else None,
        "no_match_recall": s.abstains if no_match else None,
        "exact_id": exact if row_label else None,
    }


def _stats(
    marks: list[bool | None],
    weights: list[int],
    draws: NDArray[np.int_],
    cfg: EvalConfig,
) -> tuple[int, float, float, float, float] | None:
    """n, value, low, high and one_flip over the names a metric counts, or None
    when it counts none. A draw holding none of them is skipped."""
    pairs = list(zip(marks, weights, strict=True))
    counted = np.array([w if m is not None else 0 for m, w in pairs], dtype=float)
    right = np.array([w if m else 0 for m, w in pairs], dtype=float)
    total = counted.sum()
    if not total:
        return None
    drawn = counted[draws].sum(axis=1)
    held = drawn > 0
    shares = right[draws].sum(axis=1)[held] / drawn[held]
    low, high = np.quantile(shares, [(1 - cfg.interval) / 2, (1 + cfg.interval) / 2])
    n = int(np.count_nonzero(counted))
    return (
        n,
        float(right.sum() / total),
        float(low),
        float(high),
        float(counted.max() / total),
    )


def _where(cell: Cell) -> tuple[str, str, str, str, str]:
    return cell.method, cell.split, cell.bucket, cell.weighting, cell.metric


def _entry(cell: Cell | None) -> str:
    if cell is None:
        return "-"
    return f"{cell.value:.3f} [{cell.low:.3f}, {cell.high:.3f}] n={cell.n}"
