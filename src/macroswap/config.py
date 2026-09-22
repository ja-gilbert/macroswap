"""Frozen configuration loaded from macroswap.toml; unknown keys are errors."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields
from importlib.resources import files
from pathlib import Path
from typing import Any

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


@dataclass(frozen=True)
class Config:
    diary: DiaryConfig
    stats: StatsConfig
    paths: PathsConfig


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
    unknown = sorted(set(raw) - {f.name for f in fields(Config)})
    if unknown:
        raise ConfigError(f"{source}: unknown sections: {unknown}")
    return Config(
        diary=_section(DiaryConfig, raw, "diary", source),
        stats=_section(StatsConfig, raw, "stats", source),
        paths=_section(PathsConfig, raw, "paths", source),
    )


def _section[S: (DiaryConfig, StatsConfig, PathsConfig)](
    cls: type[S], raw: dict[str, Any], name: str, source: str
) -> S:
    table = raw.get(name, {})
    if not isinstance(table, dict):
        raise ConfigError(f"{source}: [{name}] must be a table")
    unknown = sorted(set(table) - {f.name for f in fields(cls)})
    if unknown:
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
