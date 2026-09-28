"""Split MyFitnessPal food names into brand, food text, quantity and leanness,
and reduce any name or description to the words the matcher compares."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from fractions import Fraction

# MyFitnessPal writes "Brand - Food, <amount> <unit>": the brand ends at the
# first " - " and the quantity follows the last comma when it starts with a
# number and names a unit, e.g. "6 oz (112g)", "1 container (7 oz)", "0.38 cup",
# "1.5 servings". A percent is never a unit, so "Milk, 2%" and "Ground Beef,
# 93% lean" keep their figures.
_QUANTITY_RE = re.compile(
    r"^(?=.*[A-Za-z])(?P<amount>\d+/\d+|\d*\.?\d+)(?P<unit>[^(%]*?)"
    r"(?:\((?P<paren>[^)]*)\))?$"
)

_GRAMS_PER_UNIT = {
    "g": 1.0,
    "gram": 1.0,
    "grams": 1.0,
    "oz": 28.3495,
    "ounce": 28.3495,
    "ounces": 28.3495,
    "lb": 453.592,
    "lbs": 453.592,
    "pound": 453.592,
    "pounds": 453.592,
}
# A number naming a mass unit, or what a quantity counts or sizes, is a
# quantity wherever it stands, "rice 1 cup cooked" as much as after the comma;
# the matcher drops it. A bare percent is not one.
_UNIT_SPAN_RE = re.compile(
    r"\b(?:\d+/\d+|\d*\.?\d+)\s*(?:"
    + "|".join(_GRAMS_PER_UNIT)
    + r"|cup|tbsp|tsp|serving|piece|slice|small|medium|large)s?\b"
)
_APOSTROPHE_RE = re.compile("['\u2018\u2019]")
_LEAN_SLASH_RE = re.compile(r"\b(\d{2})\s*/\s*(\d{1,2})\b")
_LEAN_WORD_RE = re.compile(r"\b(\d{2})(?:\s*%\s*|\s+)lean\b", re.IGNORECASE)
# Letters and digits; every other character separates words.
_WORD_RE = re.compile(r"[^\W_]+")


@dataclass(frozen=True)
class NameParts:
    brand: str | None
    food_text: str
    quantity_text: str | None


@dataclass(frozen=True)
class Quantity:
    amount: float
    unit: str
    grams: float | None


def split_name(raw: str) -> NameParts:
    text = " ".join(raw.split())
    brand: str | None = None
    if " - " in text:
        brand, text = text.split(" - ", 1)
    food, _, quantity = text.rpartition(",")
    food, quantity = food.strip(), quantity.strip()
    if food and _QUANTITY_RE.match(quantity) and parse_leanness(quantity) is None:
        return NameParts(brand, food, quantity)
    return NameParts(brand, text, None)


def name_key(raw: str) -> str:
    """Brand and food text, lower-cased, the shape of the counted-name key: what
    the matcher reads for typed text. The counted names come from the stats SQL."""
    parts = split_name(raw)
    if parts.brand is None:
        return parts.food_text.lower()
    return f"{parts.brand} - {parts.food_text}".lower()


def parse_quantity(text: str) -> Quantity | None:
    """Amount, unit and grams. A mass unit wins over any parenthesized figure;
    a count unit takes its grams from a parenthesized mass, per unit."""
    match = _QUANTITY_RE.match(text.strip())
    if match is None:
        return None
    # Fraction reads "1/2" as well as "0.38".
    amount = float(Fraction(match["amount"]))
    unit = match["unit"].strip().lower()
    per_unit = _GRAMS_PER_UNIT.get(unit)
    if per_unit is None and match["paren"] is not None:
        # In "0.38 container (7 oz)" the parenthetical is one container.
        parenthetical = parse_quantity(match["paren"])
        per_unit = parenthetical.grams if parenthetical is not None else None
    grams = amount * per_unit if per_unit is not None else None
    return Quantity(amount, unit, grams)


def parse_leanness(text: str) -> int | None:
    """Lean percentage from "93/7" or "93% lean"; None otherwise."""
    for lean, fat in _LEAN_SLASH_RE.findall(text):
        if int(lean) + int(fat) == 100:
            return int(lean)
    if (match := _LEAN_WORD_RE.search(text)) is not None:
        return int(match[1])
    return None


def strip_leanness(text: str) -> str:
    """The text without what parse_leanness reads, since the matcher applies a
    level through the family, not by text."""
    text = _LEAN_SLASH_RE.sub(
        lambda m: "" if int(m[1]) + int(m[2]) == 100 else m[0], text
    )
    return " ".join(_LEAN_WORD_RE.sub("", text).split())


def parse_state(
    text: str, cooking_words: Iterable[str], state_fields: Iterable[str]
) -> set[str]:
    """The words of each cooking word the text holds, empty when none, once the
    table's own state phrases are deleted, so "not prepared" or "commercially
    prepared" never reads as cooked; all read as the index reads words. The
    matcher applies a cooked text through the family, as it does a level."""
    phrases = "|".join(re.escape(" ".join(tokens(p, {}))) for p in state_fields)
    plain = re.sub(rf"\b(?:{phrases})\b", " ", " ".join(tokens(text, {})))
    words = set(plain.split())
    held = (set(tokens(word, {})) for word in cooking_words)
    return {w for cooking in held if cooking <= words for w in cooking}


def tokens(text: str, abbreviations: Mapping[str, str]) -> list[str]:
    """Lower-cased words with accents dropped, apostrophes deleted rather than
    splitting a word, a number and its unit dropped wherever they stand,
    abbreviations expanded where they stand as whole words, plurals folded."""
    plain = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    plain = _UNIT_SPAN_RE.sub(" ", _APOSTROPHE_RE.sub("", plain))
    words = (abbreviations.get(w, w) for w in re.split(r"[\s,()]+", plain))
    return [singular(w) for w in _WORD_RE.findall(" ".join(words))]


def singular(word: str) -> str:
    """Folds the plurals food names use: berries, tomatoes, peaches, cookies."""
    if len(word) <= 3 or word.endswith("ss"):
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("ie") and len(word) > 4:
        return word[:-2] + "y"
    if word.endswith(("oes", "ches", "shes", "xes")):
        return word[:-2]
    return word.removesuffix("s")


def plausible_grams(
    grams: float | None, calories: float | None, max_kcal_per_gram: float
) -> float | None:
    """Reject gram values that would imply an impossible energy density."""
    if grams is None or grams <= 0:
        return None
    if calories is not None and calories / grams > max_kcal_per_gram:
        return None
    return grams
