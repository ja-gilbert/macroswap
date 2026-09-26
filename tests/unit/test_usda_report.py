from __future__ import annotations

from dataclasses import astuple
from pathlib import Path

from macroswap.config import load_config
from macroswap.store import connect, write_usda
from macroswap.usda.load import Food
from macroswap.usda.report import family_report
from macroswap.usda.table import build_table


def test_report_counts_and_measured_candidates(
    foods: list[Food], tmp_path: Path
) -> None:
    """The report sizes the table and lists override and alias candidates from
    the data: cod and haddock sit within the threshold while canned sardines
    have no raw row to compare, and orange-flesh sweet potatoes' nearest SR
    families with candidates are ranked by shared words, plurals folded, then
    distance."""
    config = load_config()
    with connect(tmp_path / "db.sqlite") as conn:
        write_usda(conn, [astuple(r) for r in build_table(foods, config.usda)])
        text = family_report(
            conn, config.swap.rank_weights, config.usda.varietal_threshold
        )
    assert "rows in the matcher index: 109" in text
    assert "varietal override candidates (raw families within 15): 1" in text
    assert "  fish: 2 of 4 raw families: fish, cod; fish, haddock" in text
    assert (
        "  sweet potatoes, orange flesh -> sweet potato (shared words 2, "
        "distance 12); potatoes (shared words 1, distance 4)"
    ) in text
