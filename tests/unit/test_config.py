from __future__ import annotations

from pathlib import Path

import pytest

from macroswap.config import ConfigError, load_config


def test_packaged_config_loads_with_expected_values() -> None:
    """The shipped macroswap.toml must load with exactly its documented values;
    the tuned ones are checked for shape, since tuning changes them."""
    config = load_config()
    assert config.diary.quick_add_pattern == "^quick add"
    assert config.diary.untracked_calorie_share == 0.5
    assert config.diary.max_kcal_per_gram == 9.5
    assert config.stats.coverage_shares == (0.5, 0.8, 0.95)
    assert config.paths.db == "data/build/macroswap.sqlite"
    assert config.swap.rank_weights == (48.0, 16.0, 81.0)
    assert set(config.match.no_match) == {"lexical", "embed"}
    assert all(isinstance(t, float) for t in config.match.no_match.values())
    assert config.match.default_method in {"lexical", "embed", "hybrid"}
    assert config.eval.tolerated_flips == {"lexical": 0, "embed": 1, "hybrid": 1}


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


def test_missing_file_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "absent.toml")
