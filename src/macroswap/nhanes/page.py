"""The counts blocks of docs/popularity.md, rendered from the committed
popularity table so that none of their numbers is typed."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from macroswap.config import Config

_BLOCK = re.compile(r"(<!-- counts:(\w+) -->\n).*?(<!-- counts:end -->)", re.DOTALL)
# How the page files a counted family no swap offers, as the table has it:
# left out by design when every row its reports came through is left out by its
# category or a denied word, not reachable when one is left out for its key
# alone.
_BY_DESIGN, _NOT_REACHABLE, _OTHER = "left out by design", "not reachable", "other"
# The categories left out by design that the page names; the rest are one line.
_TOP = 10


def render_page(page: str, table: dict[str, Any], config: Config) -> str:
    """The page with the text of each counts block replaced. A page that lacks
    one of the blocks, or names another, is refused."""
    blocks = _format_counts(table, config)
    named = {block[2] for block in _BLOCK.finditer(page)}
    if named != blocks.keys():
        raise ValueError(f"counts blocks {sorted(named)} are not {sorted(blocks)}")
    return _BLOCK.sub(lambda block: f"{block[1]}{blocks[block[2]]}\n{block[3]}", page)


def _format_counts(table: dict[str, Any], config: Config) -> dict[str, str]:
    """Each block's text by its name."""
    families: dict[str, int] = table["families"]
    alone: dict[str, int] = table["before_count_as"]
    offered = [
        n for family, n in families.items() if family not in table["not_offered"]
    ]
    pairs = sum(families.values())
    cuts = {
        config.swap.popularity_floor: " (the floor)",
        config.swap.common_threshold: " (the common tier)",
    }
    left_out: dict[str, dict[str, int]] = {
        _BY_DESIGN: {},
        _NOT_REACHABLE: {},
        _OTHER: {},
    }
    for family in table["not_offered"]:
        if family in table["by_design"]:
            why = _BY_DESIGN
        elif family in table["not_reachable"]:
            why = _NOT_REACHABLE
        else:
            why = _OTHER
        left_out[why][family] = families[family]
    by_category: dict[str, list[int]] = defaultdict(list)
    for family, category in table["by_design"].items():
        by_category[category].append(families[family])
    ranked = sorted(by_category.items(), key=lambda item: (-sum(item[1]), item[0]))
    rest = [n for _, counts in ranked[_TOP:] for n in counts]
    blocks = {
        "totals": [
            f"NHANES {table['cycle']}: {table['participants']:,} participants "
            f"reported {len(families):,} families and {len(table['variants']):,} "
            f"variants, {pairs:,} participant-family pairs in all.",
        ],
        "tiers": [
            "| Reported by at least | Families a swap can offer |",
            "| --- | --- |",
            f"| any number | {table['offered_families']:,} |",
            *(
                f"| {cut}{cuts.get(cut, '')} | {sum(n >= cut for n in offered):,} |"
                for cut in sorted({1, 20, 100, *cuts})
            ),
        ],
        "staples": [
            "| Family | Participants |",
            "| --- | --- |",
            *(
                f"| {family} | {n:,} |"
                for n, family in sorted(
                    (families.get(family, 0), family)
                    for family in config.popularity.must_pass
                )
            ),
        ],
        "allowlist": [
            "| Family | Participants |",
            "| --- | --- |",
            *(
                f"| {family} | {families.get(family, 0):,} |"
                for family in config.popularity.allowlist
            ),
        ],
        "crosswalk": [
            "| Family | Participants | WWEIA category | Participants | Ratio |",
            "| --- | --- | --- | --- | --- |",
            *(
                f"| {family} | {n:,} | {category} | {m:,} "
                f"| {f'{n / m:.2f}' if m else 'n/a'} |"
                for family, (category, n, m) in table["crosswalk"].items()
            ),
        ],
        "count_as": [
            "| Family | Alone | Counts as | Alone | Together |",
            "| --- | --- | --- | --- | --- |",
            *(
                f"| {source} | {alone[source]:,} | {target} "
                f"| {alone[target]:,} | {families[target]:,} |"
                for source, target in config.popularity.count_as.items()
            ),
        ],
        "not_offered": [
            "| Why no swap offers the family | Families | Pairs | Share of all pairs |",
            "| --- | --- | --- | --- |",
            *(
                f"| {why} | {len(group):,} | {sum(group.values()):,} "
                f"| {sum(group.values()) / pairs:.1%} |"
                for why, group in left_out.items()
            ),
        ],
        "by_design": [
            "| Category left out by design | Families | Pairs | Share of all pairs |",
            "| --- | --- | --- | --- |",
            *(
                f"| {category} | {len(counts):,} | {sum(counts):,} "
                f"| {sum(counts) / pairs:.1%} |"
                for category, counts in ranked[:_TOP]
            ),
            f"| all others | {len(rest):,} | {sum(rest):,} | {sum(rest) / pairs:.1%} |",
        ],
        "not_reachable": [
            "| Family not reachable | Participants |",
            "| --- | --- |",
            *(
                f"| {family} | {n:,} |"
                for family, n in sorted(
                    left_out[_NOT_REACHABLE].items(), key=lambda item: -item[1]
                )
            ),
        ],
        "unattributed": [
            "Averaged over every food reported, a food counted each time it was "
            f"reported, {table['unattributed']:.2%} of a food's weight reaches no "
            "row of the table.",
        ],
    }
    return {name: "\n".join(lines) for name, lines in blocks.items()}
