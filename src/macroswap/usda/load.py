"""Read SR Legacy and Foundation Foods releases into one list, SR first."""

from __future__ import annotations

import csv
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

# FoodData Central nutrient ids.
_PROTEIN = "1003"
_FAT = "1004"
_CARBS = "1005"  # carbohydrate by difference
_FIBER = "1079"
_SUGARS = "2000"  # total sugars
_SUGARS_NLEA = "1063"  # total sugars as labelled, where 2000 is not given
_ENERGY = "1008"
_ATWATER = "2047"  # energy from Atwater general factors
NUTRIENT_IDS = {
    _PROTEIN,
    _FAT,
    _CARBS,
    _FIBER,
    _SUGARS,
    _SUGARS_NLEA,
    _ENERGY,
    _ATWATER,
}
# Each release's data type, which also names its NDB file.
_DATA_TYPES = {"sr": "sr_legacy_food", "foundation": "foundation_food"}


@dataclass(frozen=True)
class Food:
    id: str
    source: str
    ndb: str | None
    description: str
    category: str
    protein: float | None
    carbs: float | None
    fat: float | None
    fiber: float | None
    sugars: float | None
    kcal: float | None


@dataclass(frozen=True)
class Loaded:
    foods: list[Food]
    ndb_overlap: int
    dry_basis_dropped: tuple[str, ...]


def load_release(folder: Path, source: str) -> list[Food]:
    """Every food of one release with the nutrients the table uses."""
    data_type = _DATA_TYPES[source]
    categories = {
        r["id"]: r["description"] for r in _rows(folder / "food_category.csv")
    }
    ndb = {
        r["fdc_id"]: r["NDB_number"] or None for r in _rows(folder / f"{data_type}.csv")
    }
    rows = {
        r["fdc_id"]: r
        for r in _rows(folder / "food.csv")
        if r["data_type"] == data_type
    }
    amounts: dict[str, dict[str, float]] = {fdc_id: {} for fdc_id in rows}
    for r in _rows(folder / "food_nutrient.csv"):
        if r["fdc_id"] in amounts and r["nutrient_id"] in NUTRIENT_IDS and r["amount"]:
            amounts[r["fdc_id"]][r["nutrient_id"]] = float(r["amount"])
    return [
        _food(source, fdc_id, ndb.get(fdc_id), row, categories, amounts[fdc_id])
        for fdc_id, row in rows.items()
    ]


def merge(sr: list[Food], foundation: list[Food], dry_basis_marker: str) -> Loaded:
    """SR is primary: a Foundation food joins only when no SR food has its NDB.

    A dry-basis Foundation row restates a food on a basis nobody weighs and
    carries no carbs, so it could never be a candidate or a target; every one
    is dropped, and `data build` lists them so SR's coverage can be checked.
    """
    sr_ndb = {f.ndb for f in sr if f.ndb}
    joining = [f for f in foundation if f.ndb not in sr_ndb]
    dry = [f for f in joining if dry_basis_marker in f.description]
    return Loaded(
        foods=sr + [f for f in joining if dry_basis_marker not in f.description],
        ndb_overlap=len(foundation) - len(joining),
        dry_basis_dropped=tuple(f.description for f in dry),
    )


def _food(
    source: str,
    fdc_id: str,
    ndb: str | None,
    row: dict[str, str],
    categories: dict[str, str],
    amounts: dict[str, float],
) -> Food:
    protein, carbs, fat = amounts.get(_PROTEIN), amounts.get(_CARBS), amounts.get(_FAT)
    if carbs is not None:
        carbs = max(0.0, carbs)  # Foundation's carbs by difference can go negative
    kcal = amounts.get(_ATWATER, amounts.get(_ENERGY))
    if kcal is None and protein is not None and carbs is not None and fat is not None:
        kcal = 4 * protein + 4 * carbs + 9 * fat
    return Food(
        id=f"{source}:{fdc_id}",
        source=source,
        ndb=ndb,
        description=row["description"],
        category=categories.get(row["food_category_id"], ""),
        protein=protein,
        carbs=carbs,
        fat=fat,
        fiber=amounts.get(_FIBER),
        sugars=amounts.get(_SUGARS, amounts.get(_SUGARS_NLEA)),
        kcal=kcal,
    )


def _rows(path: Path) -> Iterator[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        yield from csv.DictReader(f)
