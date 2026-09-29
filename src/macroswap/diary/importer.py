"""Import monthly printable-diary files into SQLite, replacing whole days."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from macroswap.config import DiaryConfig
from macroswap.diary.normalize import (
    parse_leanness,
    parse_quantity,
    plausible_grams,
    split_name,
)
from macroswap.diary.parse import parse_diary_html
from macroswap.store import clear_diary_matches

_FILENAME_RE = re.compile(r"^mfp_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.html$")
# The page rounds each cell to a whole number, so a day's rows may differ
# from its TOTALS by rounding; anything beyond that is a misread cell.
_TOTAL_TOLERANCE_KCAL = 1.0


class DiaryImportError(ValueError):
    """A file cannot be imported as named."""


@dataclass(frozen=True)
class ImportReport:
    file: str
    days: int
    rows: int
    untracked_days: int
    reconciled_days: int
    total_mismatches: int


def file_range(path: Path) -> tuple[date, date]:
    """The dates an export covers, from its mfp_<from>_<to>.html name."""
    match = _FILENAME_RE.match(path.name)
    if match is None:
        raise DiaryImportError(
            f"{path.name}: expected a name like mfp_YYYY-MM-DD_YYYY-MM-DD.html"
        )
    try:
        start, end = (date.fromisoformat(part) for part in match.groups())
    except ValueError as exc:
        raise DiaryImportError(f"{path.name}: {exc}") from exc
    if end < start:
        raise DiaryImportError(f"{path.name}: range ends before it starts")
    return start, end


def import_directory(
    conn: sqlite3.Connection, directory: Path, config: DiaryConfig
) -> list[ImportReport]:
    files = sorted(directory.glob("mfp_*.html"))
    if not files:
        raise DiaryImportError(f"no mfp_*.html files in {directory}")
    return [import_file(conn, path, config) for path in files]


def import_file(
    conn: sqlite3.Connection, path: Path, config: DiaryConfig
) -> ImportReport:
    """Replace every day inside the file's range with what the file contains."""
    start, end = file_range(path)
    days = parse_diary_html(path.read_text(encoding="utf-8"))
    for day in days:
        if not start <= day.date <= end:
            raise DiaryImportError(
                f"{path.name}: {day.date} is outside the filename range {start}..{end}"
            )
    quick_add = re.compile(config.quick_add_pattern, re.IGNORECASE)
    day_records = []
    row_records = []
    untracked_days = 0
    reconciled = 0
    mismatches = 0
    for day in days:
        calories = 0.0
        quick_calories = 0.0
        for row in day.rows:
            parts = split_name(row.raw_name)
            # The ratio sits in either half: "Laura's Lean 93/7 - Ground Beef".
            brand_and_food = " ".join(filter(None, (parts.brand, parts.food_text)))
            quantity = parse_quantity(parts.quantity_text or "")
            grams = plausible_grams(
                quantity.grams if quantity is not None else None,
                row.calories,
                config.max_kcal_per_gram,
            )
            # Real quick adds read "Quick Add - Myfitnesspal Premium, 1 serving(s)",
            # so the pattern must see the raw name, not the split food text.
            is_quick = quick_add.search(row.raw_name) is not None
            kcal = row.calories or 0.0
            calories += kcal
            if is_quick:
                quick_calories += kcal
            row_records.append(
                (
                    day.date.isoformat(),
                    row.meal,
                    row.position,
                    row.raw_name,
                    parts.brand,
                    parts.food_text,
                    parts.quantity_text,
                    grams,
                    parse_leanness(brand_and_food),
                    int(is_quick),
                    row.calories,
                    row.carbs,
                    row.fat,
                    row.protein,
                    row.cholesterol,
                    row.sodium,
                    row.sugar,
                    row.fiber,
                )
            )
        untracked = (
            calories > 0 and quick_calories / calories >= config.untracked_calorie_share
        )
        untracked_days += int(untracked)
        reported = day.reported_total_calories
        if reported is not None:
            reconciled += 1
            if abs(reported - calories) > _TOTAL_TOLERANCE_KCAL:
                mismatches += 1
        day_records.append(
            (
                day.date.isoformat(),
                path.name,
                calories,
                quick_calories,
                int(untracked),
                reported,
            )
        )
    span = (start.isoformat(), end.isoformat())
    with conn:
        clear_diary_matches(conn)
        # Foreign keys are on: children go out first and parents come back first.
        conn.execute("DELETE FROM diary_rows WHERE date BETWEEN ? AND ?", span)
        conn.execute("DELETE FROM diary_days WHERE date BETWEEN ? AND ?", span)
        conn.execute(
            "INSERT OR REPLACE INTO diary_files(file, from_date, to_date) "
            "VALUES (?, ?, ?)",
            (path.name, *span),
        )
        conn.executemany(
            "INSERT INTO diary_days(date, file, calories, quick_add_calories, "
            "untracked, reported_total_calories) VALUES (?, ?, ?, ?, ?, ?)",
            day_records,
        )
        conn.executemany(
            "INSERT INTO diary_rows(date, meal, position, raw_name, brand, food_text, "
            "quantity_text, grams, lean_pct, is_quick_add, calories, carbs, fat, "
            "protein, cholesterol, sodium, sugar, fiber) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            row_records,
        )
    return ImportReport(
        file=path.name,
        days=len(days),
        rows=len(row_records),
        untracked_days=untracked_days,
        reconciled_days=reconciled,
        total_mismatches=mismatches,
    )
