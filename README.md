# macroswap

Macro-equivalent food swaps from a MyFitnessPal diary and USDA data:
"I'm tired of this food; what else, and exactly how many grams of it,
gives me the same macros?"

## Development

    uv sync
    uv run ruff check .
    uv run ruff format --check .
    uv run mypy
    uv run pytest

My personal data never enters the repository: the diary HTML lives under
`data/raw/` and the built database under `data/build`, both are ignored.

## The Diary

`macroswap diary import` reads a folder of monthly MyFitnessPal printable-diary exports into SQLite, and `macroswap diary stats`
reports what they hold. On my own diary, 2026-09-22:

    uv run macroswap diary import data/raw/diary
    uv run macroswap diary stats

| Measure | Count |
| --- | --- |
| Monthly Exports | 44 |
| Days with Food Logged | 1,314 |
| Food Rows | 18,743 |
| Days Whose Calories Match the Page's TOTALS Row, to Within 1 kcal | 1,314 of 1,314 |
| Days No Export Covers | 0 |
| Distinct Foods in Counted Rows, by Brand and Food Text | 1,798 |
| Untracked Days, where quick adds are half the day's calories or more | 288 |
| Distinct Foods, by Brand and Food Text | 1,798 |
| Foods Covering 50%, 80% and 95% of counted rows | 60, 314, 1,019 |

Counted rows are the rows on tracked days that are not quick adds.

