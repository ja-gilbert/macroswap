"""The labeled sample, and the session behind `macroswap match label`.

The sample is drawn once over the whole diary: the head, the fewest
most-logged names covering head_share of counted rows, and a seeded tail from
the rest, each bucket split into dev and test at drawing. A label is up to
three row ids of one food in one as-bought state, separated by spaces, the first
primary; NO_MATCH; or a family key for a leanness-family row not at the name's
level. The file holds names and counts only, never quantities or dates.
"""

from __future__ import annotations

import csv
import random
import re
from collections.abc import Callable
from dataclasses import astuple, dataclass, fields, replace
from pathlib import Path

from macroswap.config import LabelsConfig
from macroswap.diary.normalize import parse_leanness, tokens
from macroswap.diary.stats import names_needed
from macroswap.match.matcher import Hit, Matcher
from macroswap.usda.table import Row

NO_MATCH = "NO_MATCH"
_PROMPT = (
    "number, or up to 3 for one food, /text to search, 0 = no USDA food is right,"
    " q to stop: "
)
# A derived id and a family key hold spaces of their own, so only a space
# before a source prefix separates a label's ids.
_ID_SPACE = re.compile(r" (?=(?:sr|foundation|derived):)")


@dataclass(frozen=True)
class Label:
    name: str
    count: int
    bucket: str
    split: str
    # Empty until made.
    label: str
    # suggestion, search or no_match.
    label_source: str


def draw_sample(counts: list[tuple[str, int]], cfg: LabelsConfig) -> list[Label]:
    """The head and a seeded tail of the counts, most-logged first, then by
    name, as name_counts returns them. Each bucket is split by its own seeded
    shuffle, the first dev_share of it dev. The labels keep the counts' order,
    head first, the order labeling runs in."""
    cut = names_needed([n for _, n in counts], cfg.head_share)
    head, rest = counts[:cut], counts[cut:]
    tail = random.Random(cfg.seed).sample(rest, min(cfg.tail_size, len(rest)))
    drawn: dict[str, tuple[str, str]] = {}
    for bucket, names in (("head", head), ("tail", tail)):
        random.Random(cfg.seed).shuffle(names)
        dev = round(cfg.dev_share * len(names))
        for i, (name, _) in enumerate(names):
            drawn[name] = (bucket, "dev" if i < dev else "test")
    return [Label(name, n, *drawn[name], "", "") for name, n in counts if name in drawn]


def label_ids(label: str) -> list[str]:
    """The ids a label lists, the first primary; NO_MATCH or a family key is
    one."""
    return _ID_SPACE.split(label)


def read_labels(path: Path) -> list[Label]:
    with path.open(newline="", encoding="utf-8") as f:
        return [
            Label(
                r["name"],
                int(r["count"]),
                r["bucket"],
                r["split"],
                r["label"],
                r["label_source"],
            )
            for r in csv.DictReader(f)
        ]


def write_labels(path: Path, labels: list[Label]) -> None:
    """Through a temp file, so a crash mid-write never loses a label made."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    with partial.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(field.name for field in fields(Label))
        writer.writerows(astuple(label) for label in labels)
    partial.replace(path)


def suggestions(matcher: Matcher, name: str) -> list[Hit]:
    """Every method's top_k keys, whatever its threshold, one hit per key: the
    one whose row leads by the matcher's tie order, whichever method found it.
    Alphabetical by description, so the list never says which method found
    what."""
    hits = [hit for method in matcher.methods for hit in matcher.rank(name, method)]
    lead = matcher.tie_order(name)
    merged: dict[str, Hit] = {}
    for hit in sorted(hits, key=lambda hit: lead(hit.row)):
        merged.setdefault(hit.key, hit)
    return sorted(merged.values(), key=lambda hit: hit.row.description.casefold())


def search(rows: list[Row], text: str) -> list[Row]:
    """Rows whose description contains each word of the text, even inside a
    longer word, both read as lower-cased words with plurals folded;
    alphabetical by description."""
    words = tokens(text, {})
    found = []
    for row in rows:
        description = " ".join(tokens(row.description, {}))
        if all(word in description for word in words):
            found.append(row)
    return sorted(found, key=lambda row: row.description.casefold())


def label_session(
    path: Path,
    matcher: Matcher,
    rows: list[Row],
    cfg: LabelsConfig,
    ask: Callable[[str], str] = input,
    out: Callable[[str], None] = print,
) -> None:
    """Label from the first unlabeled name on, writing each label as it is
    made, until every name is labeled, q, ctrl-C or the end of input."""
    labels = read_labels(path)
    for i, label in enumerate(labels):
        if label.label:
            continue
        out(f"{i + 1} of {len(labels)}  {label.name}")
        made = _choose(label.name, matcher, rows, cfg.search_limit, ask, out)
        if made is None:
            break
        labels[i] = replace(label, label=made[0], label_source=made[1])
        write_labels(path, labels)
    out(f"{sum(bool(label.label) for label in labels)} of {len(labels)} labeled")


def _choose(
    name: str,
    matcher: Matcher,
    rows: list[Row],
    limit: int,
    ask: Callable[[str], str],
    out: Callable[[str], None],
) -> tuple[str, str] | None:
    """The label and its source for one name, or None to stop: up to three
    numbers from the list shown, rows in one as-bought state, their labels
    space-joined in the order given, each once. A pick that keys at its family,
    a leanness-family row not at the name's level, labels the family and takes
    no other label beside it. The picks are a suggestion when the suggestions
    offered any of their keys, even when found by search, so search counts the
    foods every method missed."""
    level = parse_leanness(name)
    shown = [(hit.row, hit.key) for hit in suggestions(matcher, name)]
    suggested = {key for _, key in shown}
    while True:
        for n, (row, key) in enumerate(shown, start=1):
            family = f"  (family key: {key})" if key == row.family else ""
            out(f"  {n:>2}. {row.description}{family}")
        if not shown:
            out("  nothing to pick; /text searches the whole table")
        try:
            choice = ask(_PROMPT).strip()
        except (EOFError, KeyboardInterrupt):
            choice = "q"
        if choice == "q":
            return None
        if choice == "0":
            return NO_MATCH, "no_match"
        if choice.startswith("/"):
            found = search(rows, choice[1:])
            if len(found) > limit:
                out(
                    f"  {len(found)} match; the first {limit} shown,"
                    " add a word to narrow"
                )
            shown = [(row, matcher.match_key(row, level)) for row in found[:limit]]
        elif 1 <= len(picks := choice.split()) <= 3 and all(
            p.isdecimal() and 1 <= int(p) <= len(shown) for p in picks
        ):
            chosen = [shown[int(p) - 1] for p in picks]
            made = dict.fromkeys(k if k == r.family else r.id for r, k in chosen)
            source = "suggestion" if suggested & {k for _, k in chosen} else "search"
            # A family key beside another label, or rows in two states: ask again.
            mixed = len(made) > 1 and any(k == r.family for r, k in chosen)
            if len({r.as_bought for r, _ in chosen}) == 1 and not mixed:
                return " ".join(made), source
            out(
                "  a family key takes no other pick"
                if mixed
                else "  picks are in different as-bought states; pick one state"
            )
