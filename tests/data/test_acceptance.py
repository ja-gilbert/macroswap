from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from macroswap.config import load_config
from macroswap.match.embed import Embedder
from macroswap.match.matcher import Matcher
from macroswap.swap.logged import Diary, default_levels
from macroswap.swap.rank import Candidate, DefaultLevel, Ranking, Target, rank
from macroswap.swap.target import typed
from macroswap.usda.keys import FieldRules
from macroswap.usda.table import Row

ROOT = Path(__file__).resolve().parents[2]
CONFIG = load_config()
WINDOW = 25  # the --top the marks were made on
SWAPS = tomllib.loads((ROOT / "data/acceptance/swaps.toml").read_text(encoding="utf-8"))
TABLES = {
    t["text"] + (" (requires popularity)" if "requires" in t else ""): t
    for tables in SWAPS.values()
    for t in tables
}
SOURCES = {t["text"]: t for t in TABLES.values()}


@pytest.fixture(scope="module")
def matcher(real_rows: list[Row], cached_embedder: Embedder) -> Matcher:
    """The default method on the real table, as the command runs it."""
    return Matcher(real_rows, CONFIG.match, FieldRules(CONFIG.usda), cached_embedder)


@pytest.fixture(scope="module")
def levels(real_rows: list[Row]) -> dict[str, DefaultLevel]:
    """With no diary, each leanness family's configured default."""
    return default_levels(Diary({}, []), real_rows, CONFIG)


def candidates(rows: list[Row]) -> list[Candidate]:
    """Every row a swap may offer; a count once the popularity table is built."""
    return [Candidate(r) for r in rows if r.exclusion_reason is None]


def ranked(
    source: Mapping[str, Any],
    rows: list[Row],
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
        candidates(rows),
        CONFIG.swap,
        default_levels=levels,
        variants=variants,
        top=top,
    )
    return resolved.target, ranking


def families(ranking: Ranking) -> list[str]:
    return [f.best.candidate.row.family for f in (*ranking.common, *ranking.rest)]


@pytest.mark.parametrize("table", TABLES.values(), ids=TABLES.keys())
def test_the_marked_families_are_where_they_were_marked(
    real_rows: list[Row],
    matcher: Matcher,
    levels: dict[str, DefaultLevel],
    table: Mapping[str, Any],
) -> None:
    """Accepted families are among the first 25 family rows, the rows the
    marks were made on; absurd ones are not. A table tagged requires =
    "popularity" waits for the popularity table, whose task feeds the counts
    and lifts the skip."""
    if "requires" in table:
        pytest.skip("waits for the popularity table")
    _, ranking = ranked(table, real_rows, matcher, levels, top=WINDOW)
    first_25 = families(ranking)
    missing = sorted(set(table["accept"]) - set(first_25))
    shown = sorted(set(table["absurd"]) & set(first_25))
    assert (missing, shown) == ([], [])


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(SOURCES["ground beef 93/7"], id="a-family-with-other-variants"),
        pytest.param(SOURCES["oats"], id="a-family-with-one-variant"),
    ],
)
def test_the_own_family_is_left_out_unless_variants_are_asked_for(
    real_rows: list[Row],
    matcher: Matcher,
    levels: dict[str, DefaultLevel],
    source: Mapping[str, Any],
) -> None:
    """By default no row of the target's family is offered; with variants, its
    other variants are, each marked same food, and never the target's own. A
    family with one variant has nothing to re-admit."""
    target, ranking = ranked(source, real_rows, matcher, levels, top=len(real_rows))
    assert target.family not in families(ranking)
    _, with_variants = ranked(
        source, real_rows, matcher, levels, variants=True, top=len(real_rows)
    )
    own = [
        o
        for f in (*with_variants.common, *with_variants.rest)
        if f.best.candidate.row.family == target.family
        for o in (f.best, *f.others)
    ]
    others = {
        c.row.variant for c in candidates(real_rows) if c.row.family == target.family
    } - {target.variant}
    offered = {o.candidate.row.variant for o in own}
    assert offered == others and all(o.same_food for o in own)
