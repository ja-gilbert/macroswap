"""Every counted diary name resolved once, into diary_matches.

A made label wins over the matcher, through its first id. A name stores the
identity a swap shows: a row with its family, variant and as-bought state; the
family alone for a leanness-family name matched or labeled at its family,
whose level the next milestone applies; or NULLs for NO_MATCH. The fingerprint
row records what made the table, so a reader can refuse a stale one.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import astuple, dataclass
from pathlib import Path

from macroswap.config import MatchConfig
from macroswap.diary.stats import name_counts
from macroswap.match.label import NO_MATCH, Label, label_ids
from macroswap.match.matcher import Matcher
from macroswap.store import read_usda, write_diary_matches
from macroswap.usda.table import Row


class LabelError(ValueError):
    """A label names no row and no leanness family in usda_foods."""


class StaleMatches(ValueError):
    """diary_matches is missing, or was made under another method, thresholds,
    label file or model."""


@dataclass(frozen=True)
class Fingerprint:
    method: str
    # The no_match thresholds as sorted JSON.
    thresholds: str
    # The label file's sha256, or "none" without one.
    labels_digest: str
    revision: str

    @classmethod
    def current(cls, config: MatchConfig, labels_path: Path) -> Fingerprint:
        """What a `diary match` run now would record."""
        digest = (
            hashlib.sha256(labels_path.read_bytes()).hexdigest()
            if labels_path.exists()
            else "none"
        )
        return cls(
            config.default_method,
            json.dumps(config.no_match, sort_keys=True),
            digest,
            config.revision,
        )


@dataclass(frozen=True)
class Summary:
    by_label: int
    by_matcher: int
    no_match: int


def match_diary(
    conn: sqlite3.Connection,
    labels: list[Label],
    make_matcher: Callable[[list[Row]], Matcher],
    fingerprint: Fingerprint,
) -> Summary:
    """Resolve each counted name by its label's first id, else by the
    fingerprint's method, and replace the table and its fingerprint together. A
    label listing an id that names no row and no leanness family is refused
    before the matcher is made, so before a model loads or anything is
    written."""
    rows = read_usda(conn)
    by_id = {row.id: row for row in rows}
    made = {label.name: label.label for label in labels if label.label}
    check_labels(made, rows)
    matcher = make_matcher(rows)
    counts = name_counts(conn)
    unlabeled = [name for name, _ in counts if name not in made]
    matched = dict(
        zip(
            unlabeled, matched_many(matcher, unlabeled, fingerprint.method), strict=True
        )
    )
    matches: list[tuple[object, ...]] = []
    tally: Counter[str] = Counter()
    for name, count in counts:
        if name in made:
            target, score, source = label_target(made[name], by_id), None, "label"
        else:
            (target, score), source = matched[name], fingerprint.method
        matches.append((name, count, *_identity(target), source, score))
        if target is None:
            tally["no_match"] += 1
        else:
            tally["by_label" if source == "label" else "by_matcher"] += 1
    write_diary_matches(conn, matches, astuple(fingerprint))
    return Summary(tally["by_label"], tally["by_matcher"], tally["no_match"])


def check_fingerprint(
    conn: sqlite3.Connection, config: MatchConfig, labels_path: Path
) -> None:
    """Refuse diary_matches unless the current configuration and label file
    made it."""
    stored = conn.execute(
        "SELECT method, thresholds, labels_digest, revision FROM diary_matches_meta"
    ).fetchone()
    current = Fingerprint.current(config, labels_path)
    if stored is None or Fingerprint(*stored) != current:
        raise StaleMatches(
            "diary_matches is missing or stale; run `macroswap diary match`"
        )


def check_labels(made: Mapping[str, str], rows: Sequence[Row]) -> None:
    """Refuse a made label listing an id that names no row and no leanness
    family, before a model loads or anything is written."""
    by_id = {row.id for row in rows}
    leanness_families = {row.family for row in rows if row.lean_pct is not None}
    if orphans := [
        f"{name} = {label}"
        for name, label in made.items()
        if label != NO_MATCH
        and any(i not in by_id and i not in leanness_families for i in label_ids(label))
    ]:
        raise LabelError(
            f"labels naming no row or leanness family in usda_foods: "
            f"{'; '.join(orphans)}"
        )


def label_target(label: str, by_id: Mapping[str, Row]) -> Row | str | None:
    """What a made label resolves to: its first id's row, a family key alone,
    or None for NO_MATCH."""
    primary = label_ids(label)[0]
    return None if primary == NO_MATCH else by_id.get(primary, primary)


def matched_many(
    matcher: Matcher, names: Sequence[str], method: str
) -> list[tuple[Row | str | None, float | None]]:
    """Per name, the top hit, a row or its family key, and its score under the
    method, the fused score for hybrid; on NO_MATCH, no target, and the top
    score the method refused when anything scored. The names are encoded in
    one call, and the refused ones once more."""
    hits = matcher.run_many(names, method)
    refused = iter(
        matcher.rank_many(
            [n for n, h in zip(names, hits, strict=True) if h is None], method
        )
    )
    matched: list[tuple[Row | str | None, float | None]] = []
    for found in hits:
        if found is None:
            ranked = next(refused)
            matched.append((None, ranked[0].score if ranked else None))
        else:
            top = found[0]
            target = top.key if top.key == top.row.family else top.row
            matched.append((target, top.score))
    return matched


def _identity(
    target: Row | str | None,
) -> tuple[str | None, str | None, str | None, str | None]:
    """usda_id, family, variant and as_bought for a row, a family key alone,
    or NO_MATCH."""
    if isinstance(target, Row):
        return target.id, target.family, target.variant, target.as_bought
    return None, target, None, None
