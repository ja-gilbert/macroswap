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

`macroswap diary match` resolves each of those foods once: to a USDA row, to a
family for ground meat matched or labeled at its family, or to NO_MATCH. A food
I have labeled takes my label, and the default method resolves the rest:

    uv run macroswap diary match

    method: lexical
    names: 1798; by label: 380; by matcher: 1206; NO_MATCH: 212

The three counts add up to the names. NO_MATCH covers both the foods I
labeled as having no USDA match and the ones the matcher abstained on. Unlike
`match`, `diary match` never falls back to lexical: a default method that needs
the missing `embed` extra exits 2.

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

## The Matcher

`macroswap match` ranks the USDA table for a food name two ways: lexical, BM25
over the words, and embed, a pinned sentence-embedding model. Each abstains,
NO_MATCH, below its own threshold.

    uv run macroswap match "kirkland - chicken breast"

To measure them I labeled a sample of my diary's foods with
`macroswap match label`: the most-logged foods covering 80% of counted rows and
a seeded random sample of the rest, each split into dev and test. Dev tunes the
thresholds and picks the method `diary match` runs. Test is only reported, here,
from the table CI checks the eval against:

    uv run macroswap match eval --write-expected
    uv run python scripts/render_eval.py

<!-- eval:begin -->
| split | bucket | weighting | metric | lexical | embed |
| --- | --- | --- | --- | --- | --- |
| test | head | names | top1_ranking | 0.508 [0.437, 0.577] n=197 | 0.467 [0.399, 0.533] n=197 |
| test | head | names | top1_end_to_end | 0.455 [0.391, 0.518] n=220 | 0.409 [0.345, 0.468] n=220 |
| test | head | names | top5_ranking | 0.706 [0.641, 0.767] n=197 | 0.695 [0.629, 0.756] n=197 |
| test | head | names | top5_end_to_end | 0.627 [0.564, 0.691] n=220 | 0.532 [0.464, 0.595] n=220 |
| test | head | names | no_match_precision | 0.143 [0.000, 0.357] n=14 | 0.213 [0.131, 0.299] n=89 |
| test | head | names | no_match_recall | 0.087 [0.000, 0.222] n=23 | 0.826 [0.647, 0.960] n=23 |
| test | head | names | exact_id | 0.449 [0.379, 0.518] n=196 | 0.418 [0.352, 0.485] n=196 |
| test | head | rows | top1_ranking | 0.563 [0.423, 0.678] n=197 | 0.498 [0.365, 0.623] n=197 |
| test | head | rows | top1_end_to_end | 0.536 [0.403, 0.650] n=220 | 0.449 [0.321, 0.577] n=220 |
| test | head | rows | top5_ranking | 0.734 [0.620, 0.824] n=197 | 0.703 [0.582, 0.801] n=197 |
| test | head | rows | top5_end_to_end | 0.697 [0.587, 0.785] n=220 | 0.587 [0.456, 0.699] n=220 |
| test | head | rows | no_match_precision | 0.067 [0.000, 0.235] n=14 | 0.156 [0.080, 0.258] n=89 |
| test | head | rows | no_match_recall | 0.060 [0.000, 0.177] n=23 | 0.905 [0.767, 0.982] n=23 |
| test | head | rows | exact_id | 0.525 [0.380, 0.646] n=196 | 0.468 [0.333, 0.594] n=196 |
| test | tail | names | top1_ranking | 0.453 [0.342, 0.566] n=75 | 0.507 [0.395, 0.622] n=75 |
| test | tail | names | top1_end_to_end | 0.340 [0.252, 0.437] n=103 | 0.505 [0.408, 0.602] n=103 |
| test | tail | names | top5_ranking | 0.693 [0.587, 0.797] n=75 | 0.787 [0.687, 0.880] n=75 |
| test | tail | names | top5_end_to_end | 0.505 [0.408, 0.602] n=103 | 0.602 [0.515, 0.699] n=103 |
| test | tail | names | no_match_precision | 0.222 [0.000, 0.500] n=9 | 0.453 [0.314, 0.588] n=53 |
| test | tail | names | no_match_recall | 0.071 [0.000, 0.182] n=28 | 0.857 [0.706, 0.967] n=28 |
| test | tail | names | exact_id | 0.375 [0.266, 0.486] n=72 | 0.417 [0.304, 0.535] n=72 |
| test | tail | rows | top1_ranking | 0.523 [0.378, 0.663] n=75 | 0.585 [0.445, 0.717] n=75 |
| test | tail | rows | top1_end_to_end | 0.391 [0.271, 0.517] n=103 | 0.526 [0.408, 0.650] n=103 |
| test | tail | rows | top5_ranking | 0.756 [0.627, 0.865] n=75 | 0.835 [0.719, 0.922] n=75 |
| test | tail | rows | top5_end_to_end | 0.557 [0.428, 0.680] n=103 | 0.622 [0.507, 0.731] n=103 |
| test | tail | rows | no_match_precision | 0.158 [0.000, 0.455] n=9 | 0.436 [0.260, 0.603] n=53 |
| test | tail | rows | no_match_recall | 0.056 [0.000, 0.163] n=28 | 0.889 [0.732, 0.984] n=28 |
| test | tail | rows | exact_id | 0.433 [0.291, 0.584] n=72 | 0.485 [0.341, 0.629] n=72 |
<!-- eval:end -->

A food is right when its top hit, or for top5 one of its first five, is
the food I labeled, at the identity a swap shows: its variant and whether
it is bought raw, cooked, canned or dry, or its family for ground meat
logged without its leanness. A label may list up to three rows of one
food in one state, and a hit counts at any of them. Each
entry is the share right, its seeded bootstrap 95% interval and n, counting
foods once (names) or by how often I logged them (rows). Ranking ignores the
thresholds and leaves out the foods labeled NO_MATCH; end to end, an abstention
is right only for a food labeled NO_MATCH. `no_match_precision` is the share of
abstentions that were right, `no_match_recall` the share of NO_MATCH foods that
abstained, and `exact_id` the share whose top hit is the very row I picked
first.
