"""macroswap as a library: a food name resolved to a USDA row, grams fitted to
logged macros, and a row's per-100 g macros read back.

The matcher, the fit and the table are the command's own; this module only
holds them behind frozen values, loads the model on first use and keeps it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from macroswap.config import Config, load_config
from macroswap.diary.normalize import name_key, strip_leanness
from macroswap.match.diary import check_labels, label_target
from macroswap.match.embed import Embedder, EmbedUnavailable
from macroswap.match.label import read_labels
from macroswap.match.matcher import Matcher as _Matcher
from macroswap.store import open_built, read_usda
from macroswap.swap.fit import Macros
from macroswap.swap.fit import fit as _fit
from macroswap.swap.logged import Diary, default_levels
from macroswap.swap.rank import DefaultLevel, score
from macroswap.usda.keys import FieldRules
from macroswap.usda.table import Row

Method = Literal["label", "lexical", "embed", "hybrid"]


@dataclass(frozen=True)
class Match:
    """A name's USDA row. The score is the method's own number, BM25 for
    lexical, a cosine for embed, a rank fusion for hybrid, so scores compare
    within a method and not across; a label has none."""

    row_id: str
    name: str
    family: str
    score: float | None
    method: Method


@dataclass(frozen=True)
class Fit:
    """A serving of a row in grams as bought, its macros minus the target's,
    and the weighted miss the swap ranks by."""

    row_id: str
    grams: float
    residual: float
    delta_protein_g: float
    delta_carbs_g: float
    delta_fat_g: float


@dataclass(frozen=True)
class Food:
    """A row's per-100 g macros as the table holds them; None where it has
    none."""

    row_id: str
    name: str
    family: str
    kcal: float | None
    protein_g: float | None
    carbs_g: float | None
    fat_g: float | None
    sugars_g: float | None


@dataclass(frozen=True)
class _Loaded:
    config: Config
    by_id: Mapping[str, Row]
    matcher: _Matcher
    method: Method
    made: Mapping[str, str]
    levels: Mapping[str, DefaultLevel]


def load_matcher(
    config: Config, rows: list[Row], cache_dir: Path, method: str | None, strict: bool
) -> tuple[_Matcher, str]:
    """The matcher every command and the library build: with the embedder,
    which caches the index's vectors in cache_dir, unless the method is
    lexical. Without the extra a strict caller gets the error; the rest get a
    lexical matcher and the reason, for a header."""
    embedder: Embedder | None = None
    note = ""
    if method != "lexical":
        try:
            embedder = Embedder(config.match.model, config.match.revision, cache_dir)
        except EmbedUnavailable as exc:
            if strict:
                raise
            note = f"; {exc}"
    return _Matcher(rows, config.match, FieldRules(config.usda), embedder), note


class Matcher:
    """Names resolved against one store by one method, the model and the
    index loaded on first use and kept. The store and the method default to
    the config's, the store path relative to the working directory. With a
    labels file, a labeled name takes its label's first id, as `diary match`
    does, and reports the method "label"; without one, the matcher alone."""

    def __init__(
        self,
        store: Path | None = None,
        method: str | None = None,
        labels: Path | None = None,
    ) -> None:
        self._store, self._method, self._labels = store, method, labels
        self._loaded: _Loaded | None = None

    def match(self, name: str) -> Match | None:
        """The name's row, or None where the command prints NO_MATCH."""
        return self.match_many([name])[0]

    def match_many(self, names: Sequence[str]) -> list[Match | None]:
        """match for each name, the names encoded in one call of the model, and
        one more for the names that stand on a family's default level."""
        loaded = self._load()
        keys = [name_key(n) for n in names]
        hits = iter(
            loaded.matcher.run_many(
                [k for k in keys if k not in loaded.made], loaded.method
            )
        )
        found: list[tuple[Row | None, float | None, Method]] = []
        # Names matched or labeled at a leanness family without a level, which
        # stand on the family's row at its configured default level.
        families: dict[int, str] = {}
        for i, key in enumerate(keys):
            if key in loaded.made:
                target = label_target(loaded.made[key], loaded.by_id)
                found.append(
                    (target if isinstance(target, Row) else None, None, "label")
                )
                if isinstance(target, str):
                    families[i] = target
            elif (top := next(hits)) is None:
                found.append((None, None, loaded.method))
            else:
                hit = top[0]
                found.append((hit.row, hit.score, loaded.method))
                if hit.key == hit.row.family:
                    families[i] = hit.key
        levelled = self._levelled(loaded, keys, families)
        matches: list[Match | None] = []
        for i, (row, hit_score, method) in enumerate(found):
            row = levelled.get(i) or row
            matches.append(
                Match(row.id, row.description, row.family, hit_score, method)
                if row
                else None
            )
        return matches

    def fit(self, match: Match, protein_g: float, carbs_g: float, fat_g: float) -> Fit:
        """The serving of the matched row closest to the macros, by the swap's
        own fit and its weighted miss."""
        loaded = self._load()
        row = loaded.by_id[match.row_id]
        macros = (("protein", row.protein), ("carbs", row.carbs), ("fat", row.fat))
        if missing := [name for name, value in macros if value is None]:
            lacks = f"{row.id} lacks {', '.join(missing)} in the table"
            raise ValueError(f"{lacks} ({row.description}); name the food more exactly")
        per_100g = Macros(row.protein or 0.0, row.carbs or 0.0, row.fat or 0.0)
        fitted = _fit(
            Macros(protein_g, carbs_g, fat_g), per_100g, loaded.config.swap.fit_weights
        )
        delta = fitted.delta
        residual = score(delta, loaded.config.swap.rank_weights)
        return Fit(
            row.id, fitted.grams, residual, delta.protein, delta.carbs, delta.fat
        )

    def food(self, row_id: str) -> Food:
        """The row's per-100 g macros; KeyError for an id the table lacks."""
        row = self._load().by_id[row_id]
        return Food(
            row.id,
            row.description,
            row.family,
            row.kcal,
            row.protein,
            row.carbs,
            row.fat,
            row.sugars,
        )

    def _load(self) -> _Loaded:
        if self._loaded is None:
            config = load_config()
            db = Path(self._store or config.paths.db)
            with closing(open_built(db)) as conn:
                rows = read_usda(conn)
            method = self._method or config.match.default_method
            if method not in ("lexical", "embed", "hybrid"):
                raise ValueError(f"unknown method {method!r}")
            matcher, _ = load_matcher(config, rows, db.parent, method, strict=True)
            labels = read_labels(self._labels) if self._labels else []
            made = {label.name: label.label for label in labels if label.label}
            check_labels(made, rows)
            levels = default_levels(Diary({}, []), rows, config)
            self._loaded = _Loaded(
                config,
                {r.id: r for r in rows},
                matcher,
                cast(Method, method),
                made,
                levels,
            )
        return self._loaded

    def _levelled(
        self, loaded: _Loaded, keys: list[str], families: Mapping[int, str]
    ) -> dict[int, Row | None]:
        """Per name matched or labeled at a family, the family's row at its
        configured default level, as a swap with no diary reads it: the matcher
        applies the level to the name as if typed, and to the family key when
        the name alone reaches no row of the family, every text in one call.
        None where neither does; the caller then keeps the row the name
        matched, as a swap does, or none for a label."""
        texts: list[tuple[int, str]] = []
        for i, family in families.items():
            if level := loaded.levels.get(family):
                at = f" {level.lean_pct}/{100 - level.lean_pct}"
                texts += [(i, strip_leanness(keys[i]) + at), (i, family + at)]
        runs = loaded.matcher.run_many([text for _, text in texts], loaded.method)
        rows: dict[int, Row | None] = {}
        for (i, _), hits in zip(texts, runs, strict=True):
            found = next(
                (h.row for h in hits or () if h.row.family == families[i]), None
            )
            rows[i] = rows.get(i) or found
        return rows
