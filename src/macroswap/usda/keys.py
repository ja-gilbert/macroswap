"""Family and variant keys, built from USDA description's comma fields

A description is fields in order: "Beef, ground, 93% lean meat / 7% fat, raw".
Boilerplate, state, cosmetic and cooking fields are dropped; the family is the
first two surviving fields (one for a depth-one family's raw rows) and the
variant is the family plus the rest.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, replace

from macroswap.config import UsdaConfig
from macroswap.diary.normalize import parse_leanness

_PARENTHETICAL = re.compile(r"\([^()]*\)")


@dataclass(frozen=True)
class Fields:
    kept: tuple[str, ...]
    as_bought: str
    # The field that cooked the food, when as_bought reads cooked.
    cooked_by: str | None
    # The as-bought class named cooked matched: sold cooked, never a raw
    # sibling's cooked twin.
    sold_cooked: bool


class FieldRules:
    """The field classes from the config, compiled once."""

    def __init__(self, usda: UsdaConfig) -> None:
        self._note = re.compile(usda.note_pattern, re.IGNORECASE)
        self._dropped = set(usda.boilerplate_fields) | set(usda.state_fields)
        self._cosmetic = _full_field(usda.cosmetic_patterns)
        self._cooking = _any_word(usda.cooking_words)
        self._as_bought = {s: _full_field(p) for s, p in usda.as_bought.items()}
        self._depth_one = set(usda.depth_one_families)
        self._product = _full_field(usda.product_fields)

    def fields(self, description: str) -> Fields:
        text = self._note.sub("", description).lower()
        kept: list[str] = []
        cooking: str | None = None
        states: dict[str, str] = {}
        cooked_after = False
        for field in split_fields(text):
            bare = plain(field)
            if bare in self._dropped or self._cosmetic.fullmatch(bare):
                continue
            if self._cooking.search(bare):
                cooking = cooking or bare
                cooked_after = cooked_after or bool(states)
                continue
            kept.append(field)
            for state, rx in self._as_bought.items():
                if rx.fullmatch(bare):
                    states.setdefault(state, bare)
        # Config order decides: canned and dry lead, so a food canned or dried
        # after cooking is bought in that state. A cooking field after the
        # bought state is cooking after purchase ("dried, stewed").
        bought = next((s for s in self._as_bought if s in states), None)
        if cooked_after and bought != "cooked":
            bought = None
        as_bought = bought or ("cooked" if cooking else "raw")
        cooked_by = states.get("cooked", cooking) if as_bought == "cooked" else None
        return Fields(tuple(kept), as_bought, cooked_by, bought == "cooked")

    def depth(self, fields: Fields) -> int:
        """How many leading fields name the family: one for a depth-one
        family's raw rows, unless a later field names a product form."""
        depth_one = (
            fields.as_bought == "raw"
            and family_key(fields, 1) in self._depth_one
            and not any(self._product.fullmatch(plain(f)) for f in fields.kept[1:])
        )
        return 1 if depth_one else 2


def split_fields(text: str) -> list[str]:
    """Comma-separated fields; a comma inside parentheses does not split."""
    fields = [""]
    depth = 0
    for ch in text:
        if ch == "," and depth == 0:
            fields.append("")
        else:
            depth += {"(": 1, ")": -1}.get(ch, 0)
            fields[-1] += ch
    return [" ".join(f.split()) for f in fields if f.strip()]


def plain(text: str) -> str:
    """The text with its parentheticals removed and whitespace normalized."""
    return " ".join(_PARENTHETICAL.sub("", text).split())


def family_key(fields: Fields, depth: int) -> str:
    """The leading fields, parentheticals removed: synonyms and cut notes."""
    return ", ".join(f for f in map(plain, fields.kept[:depth]) if f)


def cooked_family(fields: Fields) -> Fields:
    """A cooked candidate's fields, rekeyed as its first field plus the field
    that cooked it, so no family mixes cooked and raw rows."""
    rest = [f for f in fields.kept[1:] if plain(f) != fields.cooked_by]
    return replace(fields, kept=(fields.kept[0], fields.cooked_by or "", *rest))


def variant_key(family: str, fields: Fields, depth: int, level: str | None) -> str:
    """The family plus the remaining fields. A leanness family's level leads them
    and replaces every leanness field, so every spelling reads NN/MM."""
    rest = fields.kept[depth:]
    if level is not None:
        rest = (level, *(f for f in rest if not _is_leanness_field(f)))
    return ", ".join((family, *rest))


def _is_leanness_field(field: str) -> bool:
    return parse_leanness(field) is not None or "% fat" in field or field == "fat free"


def _any_word(words: Iterable[str]) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(map(re.escape, words)) + r")\b")


def _full_field(patterns: Iterable[str]) -> re.Pattern[str]:
    return re.compile("|".join(f"(?:{p})" for p in patterns))
