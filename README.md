# macroswap

Macro-equivalent food swaps from a MyFitnessPal diary and USDA data:
"I'm tired of this food; what else, and exactly how many grams of it,
gives me the same macros?"

## Development

    uv sync --extra embed
    uv run ruff check .
    uv run ruff format --check .
    uv run mypy
    uv run pytest

The `embed` extra adds sentence-transformers and a CPU-only torch for
`macroswap match --method embed`; without it, a plain `macroswap match` runs
lexical alone and `--method embed` exits 2 naming the install command.
The first embed run downloads the pinned model, about 88 MB, into
`~/.cache/huggingface`.

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
| Days an Export Covers with Nothing Logged | 14 |
| Untracked Days, where quick adds are half the day's calories or more | 288 |
| Distinct Foods in Counted Rows, by Brand and Food Text | 1,798 |
| Foods Covering 50%, 80% and 95% of counted rows | 60, 314, 1,019 |

Counted rows are the rows on tracked days that are not quick adds.

## The USDA Table

`macroswap data pull` fetches the two pinned USDA releases, SR Legacy and
Foundation Foods, and refuses either if its checksum differs;
`macroswap data build` turns them into one SQLite table of foods with
family and variant keys, macro roles and a single exclusion reason per
row; `macroswap data report` measures it. On the pinned releases,
2026-09-26:

    uv run macroswap data pull
    uv run macroswap data build
    uv run macroswap data report

| Measure | Count |
| --- | --- |
| Foundation Rows Dropped for Sharing an SR Number | 211 |
| Dry-Basis Rows Dropped at Load | 34 |
| Families | 2,961 |
| Single-Row Families | 1,828 |
| Rows in the Matcher Index | 8,022 |
| Swap Candidates | 3,271 |
| Rows Cooked beside a Raw Sibling | 2,399 |
| Rows in an Excluded Category | 2,269 |
| Foundation Rows Repeating an SR Row | 60 |
| Rows with Incomplete or All-Zero Macros | 23 |

A candidate is a row a swap may offer; every other row stays in the
index so a diary name can still be matched to it. The last five rows
partition the index: 3,271 + 2,399 + 2,269 + 60 + 23 = 8,022.
