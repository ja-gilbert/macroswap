from __future__ import annotations

import os
from pathlib import Path

import pytest

from macroswap.config import load_config
from macroswap.pull import release_dirs
from macroswap.usda.load import Food, load_release, merge
from macroswap.usda.table import Row, build_table

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def usda_dir() -> Path:
    return FIXTURES / "usda"


@pytest.fixture
def foods(usda_dir: Path) -> list[Food]:
    """The USDA fixture's SR and Foundation foods, merged."""
    return merge(
        load_release(usda_dir / "FoodData_Central_sr_legacy_food_csv_2018-04", "sr"),
        load_release(
            usda_dir / "FoodData_Central_foundation_food_csv_2026-04-30", "foundation"
        ),
        load_config().usda.dry_basis_marker,
    ).foods


@pytest.fixture
def usda_rows(foods: list[Food]) -> list[Row]:
    """The fixture's USDA table, derived leanness rows included."""
    return build_table(foods, load_config().usda)


@pytest.fixture(scope="session")
def releases() -> dict[str, Path]:
    """The pulled sources, for tests/data. Without them the tier skips,
    except in CI, where MACROSWAP_REQUIRE_DATA=1 turns the skip into a failure
    so a broken pull can never pass by skipping the tier."""
    config = load_config()
    dirs = release_dirs(ROOT / config.paths.manifest, ROOT / config.paths.raw)
    if missing := [str(d) for d in dirs.values() if not d.exists()]:
        message = f"sources not pulled: {missing}; run `macroswap data pull`"
        if os.environ.get("MACROSWAP_REQUIRE_DATA") == "1":
            pytest.fail(message)
        pytest.skip(message)
    return dirs
