"""Parse the rendered MyFitnessPal printable diary into days and food rows.

The page is read as two kinds of event: a date heading (text outside any
table that reads like "Aug 19, 2026") and a table row (its cell texts).
Rows are classified by shape, not by tag or class, so the parser survives
markup changes as long as each food table keeps a FOODS header row, a meal
row whose remaining cells are empty before each meal, food rows with numeric
cells and a TOTALS row. An EXERCISES header stops rows being read until the
next FOODS header.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from html.parser import HTMLParser

_DATE_RE = re.compile(r"[A-Z][a-z]{2,8}\.? \d{1,2}, \d{4}")
_DATE_FORMATS = ("%b %d, %Y", "%B %d, %Y", "%b. %d, %Y")
_NUMBER_RE = re.compile(r"-?\d*\.?\d+")
_COLUMNS = {
    "calories": "calories",
    "carbs": "carbs",
    "carbohydrates": "carbs",
    "fat": "fat",
    "protein": "protein",
    "cholest": "cholesterol",
    "cholesterol": "cholesterol",
    "sodium": "sodium",
    "sugar": "sugar",
    "sugars": "sugar",
    "fiber": "fiber",
}


class ParseError(ValueError):
    """The page does not have the structure the parser relies on."""


@dataclass(frozen=True)
class ParsedRow:
    date: date
    meal: str
    position: int
    raw_name: str
    calories: float | None
    carbs: float | None
    fat: float | None
    protein: float | None
    cholesterol: float | None
    sodium: float | None
    sugar: float | None
    fiber: float | None


@dataclass(frozen=True)
class ParsedDay:
    date: date
    rows: tuple[ParsedRow, ...]
    reported_total_calories: float | None


class _Events(HTMLParser):
    """Collect date headings outside tables and table rows, in page order."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.events: list[date | tuple[str, ...]] = []
        self._table_depth = 0
        self._row: list[str] = []
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._table_depth += 1
        elif tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None:
            self._row.append(" ".join(self._cell))
            self._cell = None
        elif tag == "tr":
            self.events.append(tuple(self._row))
            self._row = []
        elif tag == "table":
            self._table_depth = max(0, self._table_depth - 1)

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        if self._cell is not None:
            self._cell.append(text)
        elif self._table_depth == 0 and _DATE_RE.fullmatch(text):
            self.events.append(_parse_date(text))


def parse_diary_html(text: str) -> tuple[ParsedDay, ...]:
    """Return one ParsedDay per date heading that has at least one food row."""
    reader = _Events()
    reader.feed(text)
    reader.close()

    days: list[ParsedDay] = []
    current: date | None = None
    rows: list[ParsedRow] = []
    total: float | None = None
    meal = ""
    in_foods = False
    columns: dict[str, int] = {}

    def flush() -> None:
        if current is not None and rows:
            days.append(ParsedDay(current, tuple(rows), total))

    for event in reader.events:
        if isinstance(event, date):
            flush()
            current, rows, total, meal, in_foods = event, [], None, "", False
            continue
        cells = event
        if not any(cells):
            continue
        first = cells[0]
        label = first.upper()
        if label == "FOODS":
            in_foods = True
            columns = _column_map(cells)
            continue
        if label == "EXERCISES":
            in_foods = False
            continue
        if not in_foods:
            continue
        if current is None:
            raise ParseError(f"food table before any date heading: {first!r}")
        if not any(cells[1:]):
            meal = first
            continue
        if label.rstrip(":") in ("TOTAL", "TOTALS"):
            total = _number(cells, columns, "calories")
            continue
        if not meal:
            raise ParseError(
                f"food row before any meal heading on {current}: {first!r}"
            )
        rows.append(
            ParsedRow(
                date=current,
                meal=meal,
                position=len(rows),
                raw_name=first,
                calories=_number(cells, columns, "calories"),
                carbs=_number(cells, columns, "carbs"),
                fat=_number(cells, columns, "fat"),
                protein=_number(cells, columns, "protein"),
                cholesterol=_number(cells, columns, "cholesterol"),
                sodium=_number(cells, columns, "sodium"),
                sugar=_number(cells, columns, "sugar"),
                fiber=_number(cells, columns, "fiber"),
            )
        )
    flush()
    return tuple(days)


def _column_map(header: tuple[str, ...]) -> dict[str, int]:
    """Locate the nutrients by header name, since the column order varies."""
    columns: dict[str, int] = {}
    for index, cell in enumerate(header):
        name = _COLUMNS.get(cell.lower())
        if name is not None:
            columns[name] = index
    return columns


def _number(cells: tuple[str, ...], columns: dict[str, int], name: str) -> float | None:
    """Read one nutrient cell: "1,300mg" is 1300.0 and "--" is None."""
    index = columns.get(name)
    if index is None or index >= len(cells):
        return None
    match = _NUMBER_RE.match(cells[index].replace(",", ""))
    return float(match.group(0)) if match else None


def _parse_date(text: str) -> date:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ParseError(f"unrecognized date heading: {text!r}")
