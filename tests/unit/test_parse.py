from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from macroswap.diary.parse import ParseError, parse_diary_html


def test_parses_days_meals_rows_totals_and_missing_cells(fixtures_dir: Path) -> None:
    """One day per heading, rows in order under their meals, '--' is None,
    thousands separators parse, and the TOTALS row is reported, not a food."""
    text = (fixtures_dir / "mfp_2026-08-01_2026-08-02.html").read_text()
    first, second = parse_diary_html(text)
    assert (first.date, second.date) == (date(2026, 8, 1), date(2026, 8, 2))
    assert [r.meal for r in first.rows] == [
        "Breakfast",
        "Breakfast",
        "Breakfast",
        "Lunch",
        "Lunch",
        "Dinner",
    ]
    assert [r.position for r in first.rows] == [0, 1, 2, 3, 4, 5]
    chicken = first.rows[0]
    assert chicken.raw_name == "Kirkland - Chicken Breast, 6 oz (112g)"
    assert (chicken.calories, chicken.carbs, chicken.fat, chicken.protein) == (
        165.0,
        0.0,
        2.0,
        37.0,
    )
    assert (chicken.cholesterol, chicken.sodium, chicken.sugar, chicken.fiber) == (
        105.0,
        300.0,
        0.0,
        0.0,
    )
    assert first.rows[2].fiber is None
    assert first.reported_total_calories == 990.0
    assert second.rows[0].calories == 2000.0
    assert second.reported_total_calories == 2105.0
    assert all(r.raw_name != "TOTALS" for r in second.rows)


def test_columns_follow_the_header_and_exercise_tables_are_ignored(
    fixtures_dir: Path,
) -> None:
    """A reordered header maps cells by name; an EXERCISES table adds no rows."""
    text = (fixtures_dir / "mfp_2026-08-05_2026-08-05.html").read_text()
    (day,) = parse_diary_html(text)
    oats = day.rows[0]
    assert (oats.protein, oats.carbs, oats.fat, oats.fiber) == (5.0, 27.0, 3.0, 4.0)
    assert (oats.sugar, oats.sodium, oats.cholesterol) == (1.0, 0.0, 0.0)
    assert day.rows[1].sodium == 1300.0
    assert [r.meal for r in day.rows] == ["Breakfast", "Lunch"]
    assert day.reported_total_calories == 855.0


@pytest.mark.parametrize(
    ("html", "message"),
    [
        pytest.param(
            "<table><tr><th>FOODS</th><th>Calories</th></tr><tr><td>Breakfast</td><td></td></tr>"
            "<tr><th>Egg Whites, 5 large</th><th>85</th></tr></table>",
            "before any date heading",
            id="table-before-date",
        ),
        pytest.param(
            "<p>Aug 1, 2026</p><table><tr><th>FOODS</th><th>Calories</th></tr>"
            "<tr><th>Egg Whites, 5 large</th><th>85</th></tr></table>",
            "before any meal heading",
            id="row-before-meal",
        ),
    ],
)
def test_structural_errors_are_reported(html: str, message: str) -> None:
    with pytest.raises(ParseError, match=message):
        parse_diary_html(html)
