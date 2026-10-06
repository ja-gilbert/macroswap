"""A swap's target from a typed food and its grams.

A typed name resolves through a small table of everyday names, then through
the matcher. The table is a curated synonym layer for names the matcher
misses, kept out of the matcher so that no eval number counts it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import astuple, dataclass

from macroswap.config import Config
from macroswap.diary.normalize import name_key, parse_leanness, strip_leanness, tokens
from macroswap.match.matcher import Hit, Matcher
from macroswap.swap.fit import Macros, fit
from macroswap.swap.rank import DefaultLevel, Target
from macroswap.usda.table import Row, pools_of, split_carbs


class NoTarget(ValueError):
    """The method abstains on the typed text; nearest holds each method's top rows."""

    def __init__(self, text: str, nearest: dict[str, list[Hit]]) -> None:
        super().__init__(f"no food matches {text!r}")
        self.nearest = nearest


class TargetError(ValueError):
    """The target cannot be built from what was asked for or logged."""


@dataclass(frozen=True)
class Found:
    """The row a typed text stands on, its key, and what resolved it; no
    variant, and the level it was read at, when it resolved to a family; and
    what the header must add: a hit passed over, a level asked for and not
    there."""

    row: Row
    variant: str | None
    key: str
    source: str
    level: DefaultLevel | None
    notes: tuple[str, ...]


@dataclass(frozen=True)
class Resolved:
    """A target and what the header says of it: the USDA row it stands on,
    none for a diary food matched to no row; its key; what resolved it; the
    level a leanness family without one was read at; notes on how it was
    resolved; and, behind a median, the window's two days, none when the whole
    diary was read, and the names with the rows each gave."""

    target: Target
    row: Row | None
    key: str
    source: str
    level: DefaultLevel | None
    notes: tuple[str, ...]
    window: tuple[str, str] | None
    names: tuple[tuple[str, int], ...]


def typed(
    text: str,
    grams: float,
    rows: Sequence[Row],
    matcher: Matcher,
    method: str,
    config: Config,
    levels: Mapping[str, DefaultLevel],
) -> Resolved:
    """The typed food at the grams given, on a row holding all three macros."""
    found = find(text, rows, matcher, method, config, levels, complete=True)
    row = found.row
    if missing := _missing(row):
        raise TargetError(
            f"{row.id} lacks {', '.join(missing)} in the table ({row.description}); "
            "name the food more exactly"
        )
    per_100g = (row.protein, row.carbs, row.fat)
    macros = Macros(*((m or 0.0) * grams / 100 for m in per_100g))
    return resolved(found, macros, config, grams)


def find(
    text: str,
    rows: Sequence[Row],
    matcher: Matcher,
    method: str,
    config: Config,
    levels: Mapping[str, DefaultLevel],
    complete: bool = False,
) -> Found:
    """By the everyday names, compared exactly once both sides are the words
    the matcher reads, else by the method's top hit, raising NoTarget when it
    abstains. When complete is asked for and the top hit lacks a macro, the
    next hit with all three that the method, or for hybrid either method it
    fuses, ranks at or above its threshold stands in, and a note says so. A key
    that is a family keeps no variant, so each of its variants is another
    variant of the target, and stands on a row at the level levels gives it."""
    name = name_key(text)
    abbreviations = config.match.abbreviations
    staples = {
        " ".join(tokens(everyday, abbreviations)): key
        for everyday, key in config.swap.staples.items()
    }
    words = " ".join(tokens(name, abbreviations))
    notes = []
    if words in staples:
        key, source = staples[words], "everyday name"
        level = levels.get(key)
        # A variant and its state, else a family: its rows at the default level
        # when it has one. A row a swap may offer comes before one it may not.
        found = [r for r in rows if f"{r.variant} / {r.as_bought}" == key] or [
            r
            for r in rows
            if r.family == key and (level is None or r.lean_pct == level.lean_pct)
        ]
        if not found:
            raise TargetError(f"{name!r} resolves to {key!r}, which names no row")
        row = min(found, key=lambda r: r.exclusion_reason is not None)
    else:
        hits = matcher.run(name, method)
        if hits is None:
            raise NoTarget(text, {m: matcher.rank(name, m) for m in matcher.methods})
        hit = hits[0]
        if complete and (missing := _missing(hit.row)):
            # A hit counts when it is among a method's own hits at or above
            # that method's threshold; a hybrid hit by either method it fuses,
            # as hybrid's own abstention reads.
            no_match = config.match.no_match
            methods = [method] if method in no_match else list(no_match)
            above = {
                h.key
                for m in methods
                for h in matcher.rank(name, m)
                if h.score >= no_match[m]
            }
            usable = [h for h in hits if h.key in above and not _missing(h.row)]
            if usable:
                top = hit.row
                hit = usable[0]
                notes.append(
                    f"matched {top.id} {top.description}; using {hit.row.id} "
                    f"{hit.row.description}, {top.id} has no {', '.join(missing)} value"
                )
        row, key, source = hit.row, hit.key, method
        level = levels.get(key)
        if level is not None:
            # A family with a default level is the same text at that level, so
            # the matcher applies the level, and a cooking word, as if typed.
            lean = level.lean_pct
            at_level = f"{strip_leanness(name)} {lean}/{100 - lean}"
            again = matcher.run(at_level, method) or hits
            row = next((h.row for h in again if h.row.family == key), row)
    variant = None if key == row.family else row.variant
    asked = parse_leanness(name)
    if asked is not None and asked != row.lean_pct:
        notes.append(
            f"level asked for: {asked}/{100 - asked}, which {row.family} has no row at"
        )
    return Found(row, variant, key, source, level, tuple(notes))


def _missing(row: Row) -> list[str]:
    macros = {"protein": row.protein, "carbs": row.carbs, "fat": row.fat}
    return [macro for macro, value in macros.items() if value is None]


def resolved(
    found: Found,
    macros: Macros,
    config: Config,
    grams: float | None = None,
    window: tuple[str, str] | None = None,
    names: tuple[tuple[str, int], ...] = (),
) -> Resolved:
    """The found food as a target at those macros."""
    row = found.row
    target = target_at(
        found.key, macros, row.family, found.variant, row.roles, config, row, grams
    )
    return Resolved(
        target, row, found.key, found.source, found.level, found.notes, window, names
    )


def target_at(
    key: str,
    macros: Macros,
    family: str,
    variant: str | None,
    roles: str,
    config: Config,
    row: Row | None = None,
    grams: float | None = None,
) -> Target:
    """The target at those macros, refused when all are zero. Its pools are its
    family's roles; a family no swap offers has none, and then the pools the
    macros themselves reach, by the table's rule and threshold, the carbs sugar
    or starch by the row's own share and starch with no share known. Without
    grams, the row's fit to the macros weighs the food, and a food on no row
    with all three macros has no weight. A row of the non-starchy vegetable
    group under its kcal line makes the target one of those."""
    if not any(astuple(macros)):
        raise TargetError(f"{key} has no protein, carbs or fat to match")
    swap, usda = config.swap, config.usda
    share: float | None = None
    non_starchy = False
    if row is not None:
        if grams is None and not _missing(row):
            per_100g = Macros(row.protein or 0.0, row.carbs or 0.0, row.fat or 0.0)
            grams = fit(macros, per_100g, swap.fit_weights).grams
        if row.sugars is not None and row.carbs:
            share = row.sugars / row.carbs
        non_starchy = (
            row.category == swap.non_starchy_group
            and (row.kcal or 0.0) < swap.starchy_kcal_per_100g
        )
    if roles:
        pools = set(roles.split(","))
    else:
        reached = pools_of(
            macros.protein, macros.carbs, macros.fat, usda.role_share_threshold
        )
        pools = split_carbs(reached, share, usda.sugar_pool_share)
    return Target(macros, family, variant, frozenset(pools), grams, non_starchy)
