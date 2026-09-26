from __future__ import annotations

from pathlib import Path

from macroswap.config import load_config
from macroswap.usda.load import load_release, merge
from macroswap.usda.table import build_table


def test_pinned_releases_build_with_every_anchor_and_formula_beef(
    releases: dict[str, Path],
) -> None:
    """Every anchor resolves to one SR row (build_table refuses otherwise), SR
    wins 211 NDB overlaps, and derived beef keeps fat at 100 minus lean."""
    usda = load_config().usda
    loaded = merge(
        load_release(releases["sr_legacy"], "sr"),
        load_release(releases["foundation"], "foundation"),
        usda.dry_basis_marker,
    )
    rows = build_table(loaded.foods, usda)
    assert loaded.ndb_overlap == 211
    assert len(loaded.dry_basis_dropped) == 34
    derived = [r for r in rows if r.source == "derived"]
    assert {r.variant for r in derived} == {
        f"beef, ground, {level}" for level in usda.leanness[0].retail
    }
    assert all(abs((r.fat or 0) - (100 - (r.lean_pct or 0))) < 0.01 for r in derived)
    assert sum(r.exclusion_reason is None for r in rows) > 3000
