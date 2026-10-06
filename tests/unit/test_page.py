from __future__ import annotations

from dataclasses import replace

import pytest

from macroswap.config import load_config
from macroswap.nhanes.page import render_page

PACKAGED = load_config()
CONFIG = replace(
    PACKAGED,
    swap=replace(PACKAGED.swap, popularity_floor=10, common_threshold=50),
    popularity=replace(
        PACKAGED.popularity,
        must_pass=("rice, white", "lentils", "pasta, dry"),
        allowlist=("tofu",),
        count_as={"pasta": "pasta, dry"},
    ),
)
TABLE = {
    "cycle": "2021-2023",
    "participants": 2000,
    "unattributed": 0.00125,
    "offered_families": 6,
    "crosswalk": {"rice, white": ["Rice", 1500, 1200], "bananas": ["Bananas", 30, 0]},
    "families": {
        "bananas": 30,
        "beverages, water": 1900,
        "cookies, sugar": 40,
        "fast foods, chicken": 250,
        "fish, fish sticks": 36,
        "gelatins, dry powder": 5,
        "pasta, dry": 60,
        "rice, white": 1500,
        "tofu": 10,
        "waffle, buttermilk": 40,
        # Twelve more left out by design: kinds 0 and 1 share a category, as do
        # 10 and 11.
        **{f"sweets, kind {k}": max(k, 1) for k in range(12)},
    },
    "variants": {"rice, white, long-grain": 1400},
    "before_count_as": {"pasta": 55, "pasta, dry": 10},
    "not_offered": {
        "beverages, water": "excluded-category",
        "cookies, sugar": "cooked-with-raw-sibling; excluded-category",
        "fast foods, chicken": "cooked-with-raw-sibling",
        "fish, fish sticks": "cooked-with-raw-sibling",
        "gelatins, dry powder": "zero-macro",
        "waffle, buttermilk": "analytical-duplicate; cooked-with-raw-sibling",
        **{f"sweets, kind {k}": "excluded-category" for k in range(12)},
    },
    "by_design": {
        "beverages, water": "Beverages",
        "cookies, sugar": "Baked Products",
        "fast foods, chicken": "Fast Foods",
        **{
            f"sweets, kind {k}": f"Category {min(max(k, 1), 10):02d}" for k in range(12)
        },
    },
    "not_reachable": ["fish, fish sticks", "waffle, buttermilk"],
}
BLOCKS = {
    "totals": [
        "NHANES 2021-2023: 2,000 participants reported 22 families and 1 variants, "
        "3,938 participant-family pairs in all.",
    ],
    "tiers": [
        "| Reported by at least | Families a swap can offer |",
        "| --- | --- |",
        "| any number | 6 |",
        "| 1 | 4 |",
        "| 10 (the floor) | 4 |",
        "| 20 | 3 |",
        "| 50 (the common tier) | 2 |",
        "| 100 | 1 |",
    ],
    "staples": [
        "| Family | Participants |",
        "| --- | --- |",
        "| lentils | 0 |",
        "| pasta, dry | 60 |",
        "| rice, white | 1,500 |",
    ],
    "allowlist": ["| Family | Participants |", "| --- | --- |", "| tofu | 10 |"],
    "crosswalk": [
        "| Family | Participants | WWEIA category | Participants | Ratio |",
        "| --- | --- | --- | --- | --- |",
        "| rice, white | 1,500 | Rice | 1,200 | 1.25 |",
        "| bananas | 30 | Bananas | 0 | n/a |",
    ],
    "count_as": [
        "| Family | Alone | Counts as | Alone | Together |",
        "| --- | --- | --- | --- | --- |",
        "| pasta | 55 | pasta, dry | 10 | 60 |",
    ],
    "not_offered": [
        "| Why no swap offers the family | Families | Pairs | Share of all pairs |",
        "| --- | --- | --- | --- |",
        "| left out by design | 15 | 2,257 | 57.3% |",
        "| not reachable | 2 | 76 | 1.9% |",
        "| other | 1 | 5 | 0.1% |",
    ],
    "by_design": [
        "| Category left out by design | Families | Pairs | Share of all pairs |",
        "| --- | --- | --- | --- |",
        "| Beverages | 1 | 1,900 | 48.2% |",
        "| Fast Foods | 1 | 250 | 6.3% |",
        "| Baked Products | 1 | 40 | 1.0% |",
        "| Category 10 | 2 | 21 | 0.5% |",
        "| Category 09 | 1 | 9 | 0.2% |",
        "| Category 08 | 1 | 8 | 0.2% |",
        "| Category 07 | 1 | 7 | 0.2% |",
        "| Category 06 | 1 | 6 | 0.2% |",
        "| Category 05 | 1 | 5 | 0.1% |",
        "| Category 04 | 1 | 4 | 0.1% |",
        "| all others | 4 | 7 | 0.2% |",
    ],
    "not_reachable": [
        "| Family not reachable | Participants |",
        "| --- | --- |",
        "| waffle, buttermilk | 40 |",
        "| fish, fish sticks | 36 |",
    ],
    "unattributed": [
        "Averaged over every food reported, a food counted each time it was "
        "reported, 0.12% of a food's weight reaches no row of the table."
    ],
}


def test_each_block_of_the_page_is_rendered_in_place() -> None:
    """The floor and the common tier are named among the cuts, which count
    only the families a swap can offer; the staples go from the least reported,
    one the table lacks at 0; a category nobody reported has no ratio. Every
    family without a candidate row is filed once, as the table has it and not
    by its reasons: the fried chicken, a cooked key the table files by design,
    is left out by design; the waffle and the fish sticks are not reachable;
    the gelatin, in neither list, is other. What is left out by design is
    shown by category, the ten largest by pairs, two families of one category
    summed, among the ten and among all others. The families not reachable are
    listed, the most reported first. Rendering twice changes nothing, so CI's
    diff check holds, and a page missing a block is refused."""
    page = "# Counts\n" + "".join(
        f"\n<!-- counts:{name} -->\nold\n<!-- counts:end -->\n\nKept.\n"
        for name in BLOCKS
    )
    rendered = render_page(page, TABLE, CONFIG)
    assert rendered == "# Counts\n" + "".join(
        f"\n<!-- counts:{name} -->\n{'\n'.join(lines)}\n<!-- counts:end -->\n\nKept.\n"
        for name, lines in BLOCKS.items()
    )
    assert render_page(rendered, TABLE, CONFIG) == rendered
    missing = page.replace("<!-- counts:totals -->\nold\n<!-- counts:end -->\n", "")
    with pytest.raises(ValueError, match="totals"):
        render_page(missing, TABLE, CONFIG)
