"""Split MyFitnessPal food names into brand, food text, quantity and leanness."""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

# MyFitnessPal writes "Brand - Food, <amount> <unit>": the brand ends at the
# first " - " and the quantity follows the last comma when it starts with a
# number, e.g. "6 oz (112g)", "1 container (7 oz)", "0.38 cup", "1.5 servings".

_QUANTITY_RE = re.compile(
    r"^(?P<amount>\d+/\d+|\d*\.?\d+)(?P<unit>[^(]*?)(?:\((?P<paren>[^)]*)\))?$"
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
_LEAN_SLASH_RE = re.compile(r"\b(\d{2})\s*/\s*(\d{1,2})\b")
_LEAN_WORD_RE = re.compile(r"\b(\d{2})(?:\s*%\s*|\s+)lean\b", re.IGNORECASE)


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
    if food and _QUANTITY_RE.match(quantity):
        return NameParts(brand, food, quantity)
    return NameParts(brand, text, None)


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


def plausible_grams(
    grams: float | None, calories: float | None, max_kcal_per_gram: float
) -> float | None:
    """Reject gram values that would imply an impossible energy density."""
    if grams is None or grams <= 0:
        return None
    if calories is not None and calories / grams > max_kcal_per_gram:
        return None
    return grams
