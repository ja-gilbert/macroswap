"""Frozen configuration loaded from macroswap.toml; unknown keys are errors."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields, replace
from importlib.resources import files
from pathlib import Path
from typing import Any

from macroswap.swap.fit import Macros

_PACKAGED = "macroswap.toml"


class ConfigError(ValueError):
    """The configuration file is missing or malformed."""


@dataclass(frozen=True)
class DiaryConfig:
    quick_add_pattern: str
    untracked_calorie_share: float
    max_kcal_per_gram: float


@dataclass(frozen=True)
class StatsConfig:
    coverage_shares: tuple[float, ...]


@dataclass(frozen=True)
class PathsConfig:
    db: str
    raw: str
    manifest: str
    labels: str
    eval_expected: str
    popularity: str


@dataclass(frozen=True)
class SwapConfig:
    fit_weights: Macros
    rank_weights: Macros
    serving_bounds_g: tuple[float, float]
    serving_ratio: float
    non_starchy_group: str
    starchy_kcal_per_100g: float
    tie_epsilon: float
    popularity_floor: int
    common_threshold: int
    diary_window_days: int
    top: int
    staples: dict[str, str]


@dataclass(frozen=True)
class Leanness:
    family: str
    nominal: bool
    anchors: dict[str, str]
    retail: tuple[str, ...]
    default: str


@dataclass(frozen=True)
class UsdaConfig:
    note_pattern: str
    boilerplate_fields: tuple[str, ...]
    state_fields: tuple[str, ...]
    cooking_words: tuple[str, ...]
    cosmetic_patterns: tuple[str, ...]
    dry_basis_marker: str
    excluded_categories: tuple[str, ...]
    depth_one_families: tuple[str, ...]
    product_fields: tuple[str, ...]
    role_share_threshold: float
    sugar_pool_share: float
    varietal_threshold: float
    as_bought: dict[str, list[str]]
    allow_words: dict[str, list[str]]
    deny_words: dict[str, list[str]]
    deny_fields: dict[str, list[str]]
    family_aliases: dict[str, str]
    leanness: tuple[Leanness, ...]


@dataclass(frozen=True)
class MatchConfig:
    abbreviations: dict[str, str]
    top_k: int
    bm25_b: float
    model: str
    revision: str
    index_seconds: float
    default_method: str
    rrf_k: int
    no_match: dict[str, float]


@dataclass(frozen=True)
class LabelsConfig:
    head_share: float
    tail_size: int
    dev_share: float
    seed: int
    search_limit: int


@dataclass(frozen=True)
class EvalConfig:
    bootstrap_resamples: int
    bootstrap_seed: int
    interval: float
    tolerated_flips: dict[str, int]


@dataclass(frozen=True)
class PopularityConfig:
    cycle: str
    water_families: tuple[str, ...]
    must_pass: tuple[str, ...]
    allowlist: tuple[str, ...]
    count_as: dict[str, str]
    crosswalk: dict[str, str]


@dataclass(frozen=True)
class Config:
    diary: DiaryConfig
    stats: StatsConfig
    paths: PathsConfig
    swap: SwapConfig
    usda: UsdaConfig
    match: MatchConfig
    labels: LabelsConfig
    eval: EvalConfig
    popularity: PopularityConfig


def load_config(path: Path | None = None) -> Config:
    """Read the tunables. None reads the copy shipped inside the package."""
    if path is None:
        text = (files("macroswap") / _PACKAGED).read_text(encoding="utf-8")
        source = f"packaged {_PACKAGED}"
    else:
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ConfigError(f"config file not found: {path}") from exc
        source = str(path)
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{source}: {exc}") from exc
    if unknown := sorted(set(raw) - {f.name for f in fields(Config)}):
        raise ConfigError(f"{source}: unknown sections: {unknown}")
    # Sections are read in file order, so the first offender is the one named.
    diary = _section(DiaryConfig, raw, "diary", source)
    stats = _section(StatsConfig, raw, "stats", source)
    paths = _section(PathsConfig, raw, "paths", source)
    swap = _section(SwapConfig, raw, "swap", source)
    fit_weights = _section(Macros, raw["swap"], "fit_weights", source)
    rank_weights = _section(Macros, raw["swap"], "rank_weights", source)
    usda = _section(UsdaConfig, raw, "usda", source)
    leanness = tuple(
        _section(Leanness, {"leanness": table}, "leanness", source)
        for table in usda.leanness
    )
    return Config(
        diary,
        stats,
        paths,
        replace(swap, fit_weights=fit_weights, rank_weights=rank_weights),
        replace(usda, leanness=leanness),
        _section(MatchConfig, raw, "match", source),
        _section(LabelsConfig, raw, "labels", source),
        _section(EvalConfig, raw, "eval", source),
        _section(PopularityConfig, raw, "popularity", source),
    )


def _section[
    S: (
        DiaryConfig,
        StatsConfig,
        PathsConfig,
        SwapConfig,
        Macros,
        UsdaConfig,
        Leanness,
        MatchConfig,
        LabelsConfig,
        EvalConfig,
        PopularityConfig,
    )
](cls: type[S], raw: dict[str, Any], name: str, source: str) -> S:
    table = raw.get(name, {})
    if not isinstance(table, dict):
        raise ConfigError(f"{source}: [{name}] must be a table")
    if unknown := sorted(set(table) - {f.name for f in fields(cls)}):
        raise ConfigError(f"{source}: [{name}] has unknown keys {unknown}")
    # TOML arrays arrive as lists; dataclasses are frozen, so store as tuples
    values: dict[str, Any] = {
        key: tuple(value) if isinstance(value, list) else value
        for key, value in table.items()
    }
    try:
        return cls(**values)
    except TypeError as exc:
        # No dataclass defaults: a missing key is an error, never a fallback.
        raise ConfigError(f"{source}: [{name}] {exc}") from exc
