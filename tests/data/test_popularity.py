from __future__ import annotations

from pathlib import Path

from macroswap.config import load_config
from macroswap.nhanes.popularity import measure
from macroswap.usda.table import Row

CONFIG = load_config().popularity


def test_both_days_are_counted_on_the_real_table(
    releases: dict[str, Path], real_rows: list[Row]
) -> None:
    """6,694 participants have a reliable recall on either day. Oatmeal made
    with water counts as oats, not water. Baked potatoes count as potatoes and
    the orange-flesh sweet potato as sweet potato, the families a swap can
    offer. Rib eye counts whoever reported a steak that FNDDS blends equally
    from four cuts: 96 if one cut had to win the tie."""
    recalls = (releases["nhanes_day1"], releases["nhanes_day2"])
    popularity = measure(releases["fndds"], recalls, real_rows, CONFIG)
    families = {
        "cereals, oats": 1335,
        "potatoes": 1701,
        "sweet potato": 204,
        "beef, rib eye steak": 199,
    }
    assert popularity.participants == 6694
    assert {family: popularity.families[family] for family in families} == families
