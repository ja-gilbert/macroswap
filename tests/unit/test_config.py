from __future__ import annotations

from importlib.resources import files
from pathlib import Path

import pytest

from macroswap.config import ConfigError, load_config
from macroswap.swap.fit import Macros


def test_packaged_config_loads_with_expected_values() -> None:
    """The shipped macroswap.toml must load with exactly its documented values;
    the tuned ones are checked for shape, since tuning changes them."""
    config = load_config()
    assert config.diary.quick_add_pattern == "^quick add"
    assert config.diary.untracked_calorie_share == 0.5
    assert config.diary.max_kcal_per_gram == 9.5
    assert config.stats.coverage_shares == (0.5, 0.8, 0.95)
    assert config.paths.db == "data/build/macroswap.sqlite"
    assert config.swap.fit_weights == Macros(3.0, 1.0, 1.0)
    assert config.swap.rank_weights == Macros(48.0, 16.0, 81.0)
    assert config.swap.serving_bounds_g == (5.0, 1000.0)
    assert config.swap.tie_epsilon == 10.0
    assert 0 <= config.swap.popularity_floor <= config.swap.common_threshold
    assert config.swap.diary_window_days == 90
    assert config.swap.top == 10
    assert {lean.family: lean.default for lean in config.usda.leanness} == {
        "beef, ground": "85/15",
        "turkey, ground": "93/7",
        "pork, ground": "84/16",
    }
    assert set(config.match.no_match) == {"lexical", "embed"}
    assert all(isinstance(t, float) for t in config.match.no_match.values())
    assert config.match.default_method in {"lexical", "embed", "hybrid"}
    assert config.eval.tolerated_flips == {"lexical": 0, "embed": 1, "hybrid": 1}
    assert config.popularity.cycle == "2021-2023"
    assert config.popularity.water_families == ("beverages, water", "water, bottled")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('[diary]\nquick_add_patern = "^quick add"\n', "quick_add_patern"),
        ("[diarry]\n", "diarry"),
        ("diary = 5\n", "must be a table"),
        ('[diary]\nquick_add_pattern = "^quick add"\n', "max_kcal_per_gram"),
    ],
    ids=["unknown-key", "unknown-section", "not-a-table", "missing-key"],
)
def test_malformed_config_is_rejected(tmp_path: Path, text: str, message: str) -> None:
    """A bad file must fail, naming the offender, not fall back to a default."""
    path = tmp_path / "macroswap.toml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match=message):
        load_config(path)


def test_weights_as_a_positional_list_are_rejected(tmp_path: Path) -> None:
    """The form an older file held must fail naming the key, not load with the
    macros in whatever order the list had."""
    table = "rank_weights = { protein = 48.0, carbs = 16.0, fat = 81.0 }"
    packaged = (files("macroswap") / "macroswap.toml").read_text(encoding="utf-8")
    path = tmp_path / "macroswap.toml"
    path.write_text(
        packaged.replace(table, "rank_weights = [48.0, 16.0, 81.0]"), encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="rank_weights"):
        load_config(path)


def test_missing_file_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "absent.toml")
