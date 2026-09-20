"""Frozen configuration loaded from macroswap.toml; unknown keys are errors."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """The configuration file is missing or malformed."""


@dataclass(frozen=True)
class DiaryConfig:
    quick_add_pattern: str = "^quick add"
    untracked_calorie_share: float = 0.5
    max_kcal_per_gram: float = 9.5


@dataclass(frozen=True)
class StatsConfig:
    coverage_shares: tuple[float, ...] = (0.5, 0.8, 0.95)


@dataclass(frozen=True)
class PathsConfig:
    db: str = "data/build/macroswap.sqlite"


@dataclass(frozen=True)
class Config:
    diary: DiaryConfig
    stats: StatsConfig
    paths: PathsConfig


def load_config(path: Path) -> Config:
    """Read macroswap.toml. Unknown sections or keys raise ConfigError."""
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    unknown = sorted(set(raw) - {f.name for f in fields(Config)})
    if unknown:
        raise ConfigError(f"{path}: unknown sections: {unknown}")
    return Config(
        diary=_section(DiaryConfig, raw, "diary", path),
        stats=_section(StatsConfig, raw, "stats", path),
        paths=_section(PathsConfig, raw, "paths", path),
    )


def _section[S: (DiaryConfig, StatsConfig, PathsConfig)](
    cls: type[S], raw: dict[str, Any], name: str, path: Path
) -> S:
    table = raw.get(name, {})
    if not isinstance(table, dict):
        raise ConfigError(f"{path}: [{name}] must be a table")
    unknown = sorted(set(table) - {f.name for f in fields(cls)})
    if unknown:
        raise ConfigError(f"{path}: [{name}] has unknown keys {unknown}")
    # TOML arrays arrive as lists; dataclasses are frozen, so store as tuples
    values: dict[str, Any] = {
        key: tuple(value) if isinstance(value, list) else value
        for key, value in table.items()
    }
    return cls(**values)
