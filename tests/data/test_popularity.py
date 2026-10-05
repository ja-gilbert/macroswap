from __future__ import annotations

from pathlib import Path

from macroswap.config import load_config
from macroswap.nhanes.popularity import Table, write_table

CONFIG = load_config()
ROOT = Path(__file__).resolve().parents[2]


def test_both_days_are_counted_on_the_real_table(popularity: Table) -> None:
    """6,694 participants have a reliable recall on either day. Oatmeal made
    with water counts as oats, not water. Baked potatoes count as potatoes and
    the orange-flesh sweet potato as sweet potato, the families a swap can
    offer. Rib eye counts whoever reported a steak that FNDDS blends equally
    from four cuts: 96 if one cut had to win the tie."""
    families = {
        "cereals, oats": 1335,
        "potatoes": 1701,
        "sweet potato": 204,
        "beef, rib eye steak": 199,
    }
    assert popularity.participants == 6694
    assert {family: popularity.families[family] for family in families} == families


def test_every_staple_is_offered_in_the_common_tier(popularity: Table) -> None:
    """The common threshold was set so that no staple falls below it; a
    staple the table no longer offers fails here too."""
    short = {
        family: popularity.families.get(family, 0)
        for family in CONFIG.popularity.must_pass
        if popularity.families.get(family, 0) < CONFIG.swap.common_threshold
        or family in popularity.not_offered
    }
    assert not short


def test_the_committed_table_is_the_one_the_build_writes(
    popularity: Table, tmp_path: Path
) -> None:
    """The committed table has to be what the pinned sources give under the
    rules as they are now: any drift fails here until `data build
    --write-popularity` is run again and the change reviewed."""
    write_table(tmp_path / "popularity.json", popularity)
    committed = (ROOT / CONFIG.paths.popularity).read_text(encoding="utf-8")
    assert (tmp_path / "popularity.json").read_text(encoding="utf-8") == committed
