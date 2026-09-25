from __future__ import annotations

from pathlib import Path

import pytest

from macroswap.usda.load import Food, load_release, merge

SR = "FoodData_Central_sr_legacy_food_csv_2018-04"
FOUNDATION = "FoodData_Central_foundation_food_csv_2026-04-30"


@pytest.fixture
def foundation(usda_dir: Path) -> dict[str, Food]:
    return {f.id: f for f in load_release(usda_dir / FOUNDATION, "foundation")}


def test_sr_comes_first_and_dry_basis_rows_are_dropped(
    usda_dir: Path, foundation: dict[str, Food]
) -> None:
    """Foundation rows sharing an SR NDB never join; dry-basis rows are dropped
    and named."""
    sr = load_release(usda_dir / SR, "sr")
    loaded = merge(sr, list(foundation.values()), "(0% moisture)")
    ids = {f.id for f in loaded.foods}
    assert loaded.ndb_overlap == 2
    assert {"foundation:334194", "foundation:2514743"}.isdisjoint(ids)
    assert loaded.dry_basis_dropped == ("Beans, Dry, Carioca (0% moisture)",)
    assert "foundation:335433" not in ids


@pytest.mark.parametrize(
    ("food_id", "kcal", "carbs"),
    [
        ("foundation:321360", 31.0, 5.51),
        ("foundation:321900", 32.0, 6.29),
        ("foundation:2727567", 187.9, 0.0),
        ("foundation:748608", None, None),
    ],
    ids=["atwater-2047", "energy-1008", "negative-carbs", "no-macros"],
)
def test_energy_fallbacks_and_carb_clamp(
    foundation: dict[str, Food], food_id: str, kcal: float | None, carbs: float | None
) -> None:
    food = foundation[food_id]
    assert food.kcal == pytest.approx(kcal, abs=0.1)
    assert food.carbs == carbs


def test_energy_formula_when_a_release_reports_no_energy(tmp_path: Path) -> None:
    """No pinned row needs 4P + 4C + 9F, so a one-row release exercises it."""
    files = {
        "food.csv": "fdc_id,data_type,description,food_category_id\n"
        "1,foundation_food,Test,1\n",
        "foundation_food.csv": "fdc_id,NDB_number\n1,\n",
        "food_category.csv": "id,description\n1,Test\n",
        "food_nutrient.csv": "fdc_id,nutrient_id,amount\n"
        "1,1003,10\n1,1005,20\n1,1004,5\n",
    }
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    assert load_release(tmp_path, "foundation")[0].kcal == 165.0
