from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from macroswap.config import load_config
from macroswap.match.embed import Embedder
from macroswap.match.matcher import Matcher
from macroswap.nhanes.popularity import Table
from macroswap.swap.logged import Diary, default_levels
from macroswap.swap.rank import Candidate, DefaultLevel, Ranking, Target, rank
from macroswap.swap.target import typed
from macroswap.usda.keys import FieldRules
from macroswap.usda.table import Row

ROOT = Path(__file__).resolve().parents[2]
CONFIG = load_config()
WINDOW = 25  # the --top the marks were made on
SWAPS = tomllib.loads((ROOT / "data/acceptance/swaps.toml").read_text(encoding="utf-8"))
MISSES = SWAPS.pop("known_misses")
TABLES = {t["text"]: t for tables in SWAPS.values() for t in tables}


@pytest.fixture(scope="module")
def matcher(real_rows: list[Row], cached_embedder: Embedder) -> Matcher:
    """The default method on the real table, as the command runs it."""
    return Matcher(real_rows, CONFIG.match, FieldRules(CONFIG.usda), cached_embedder)


@pytest.fixture(scope="module")
def levels(real_rows: list[Row]) -> dict[str, DefaultLevel]:
    """With no diary, each leanness family's configured default."""
    return default_levels(Diary({}, []), real_rows, CONFIG)


@pytest.fixture(scope="module")
def first_25(
    real_rows: list[Row],
    popularity: Table,
    matcher: Matcher,
    levels: dict[str, DefaultLevel],
) -> dict[str, list[str]]:
    """Each source's first 25 family rows, ranked once for every table."""
    return {
        text: families(ranked(t, real_rows, popularity, matcher, levels, top=WINDOW)[1])
        for text, t in TABLES.items()
    }


def candidates(rows: list[Row], counts: Table) -> list[Candidate]:
    """Every row a swap may offer, with the counts the command reads: how
    many participants reported its family and its variant."""
    return [
        Candidate(
            r, counts.families.get(r.family, 0), counts.variants.get(r.variant, 0)
        )
        for r in rows
        if r.exclusion_reason is None
    ]


def ranked(
    source: Mapping[str, Any],
    rows: list[Row],
    counts: Table,
    matcher: Matcher,
    levels: Mapping[str, DefaultLevel],
    *,
    top: int,
    variants: bool = False,
) -> tuple[Target, Ranking]:
    method = CONFIG.match.default_method
    resolved = typed(
        source["text"], source["grams"], rows, matcher, method, CONFIG, levels
    )
    ranking = rank(
        resolved.target,
        candidates(rows, counts),
        CONFIG.swap,
        default_levels=levels,
        allowlist=CONFIG.popularity.allowlist,
        variants=variants,
        top=top,
    )
    return resolved.target, ranking


def families(ranking: Ranking) -> list[str]:
    return [f.best.candidate.row.family for f in (*ranking.common, *ranking.rest)]


@pytest.mark.parametrize("table", TABLES.values(), ids=TABLES.keys())
def test_the_marked_families_are_where_they_were_marked(
    first_25: dict[str, list[str]], table: Mapping[str, Any]
) -> None:
    """Accepted families are among the first 25 family rows, the rows the
    marks were made on with the counts the command reads; absurd ones are
    not."""
    first = first_25[table["text"]]
    missing = sorted(set(table["accept"]) - set(first))
    shown = sorted(set(table["absurd"]) & set(first))
    assert (missing, shown) == ([], [])


@pytest.mark.parametrize(
    "entry",
    MISSES,
    ids=[re.split(r" for | where | beside |[:(]", m["why"])[0] for m in MISSES],
)
def test_a_known_miss_is_still_offered(
    first_25: dict[str, list[str]], entry: Mapping[str, Any]
) -> None:
    """A known miss is a measured fact: every pair's family is in the first
    25 for its source, as an accepted swap is. A pair that stops being
    offered fails here, and its line goes."""
    gone = []
    for pair in entry["pairs"]:
        source, family = pair.split(": ", 1)
        if family not in first_25[source]:
            gone.append(pair)
    assert gone == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(TABLES["ground beef 93/7"], id="a-family-with-other-variants"),
        pytest.param(TABLES["oats"], id="a-family-with-one-variant"),
    ],
)
def test_the_own_family_is_left_out_unless_variants_are_asked_for(
    real_rows: list[Row],
    popularity: Table,
    matcher: Matcher,
    levels: dict[str, DefaultLevel],
    source: Mapping[str, Any],
) -> None:
    """By default no row of the target's family is offered; with variants, its
    other variants are, each marked same food, and never the target's own. A
    family with one variant has nothing to re-admit."""
    every = len(real_rows)
    target, ranking = ranked(source, real_rows, popularity, matcher, levels, top=every)
    assert target.family not in families(ranking)
    _, with_variants = ranked(
        source, real_rows, popularity, matcher, levels, variants=True, top=every
    )
    own = [
        o
        for f in (*with_variants.common, *with_variants.rest)
        if f.best.candidate.row.family == target.family
        for o in (f.best, *f.others)
    ]
    others = {
        c.row.variant
        for c in candidates(real_rows, popularity)
        if c.row.family == target.family
    } - {target.variant}
    offered = {o.candidate.row.variant for o in own}
    assert offered == others and all(o.same_food for o in own)
