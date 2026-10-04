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
`macroswap match --method embed` and `--method hybrid`; without it, a plain
`macroswap match` runs lexical alone and either `--method` exits 2 naming the
install command. The first run that needs the pinned model downloads it, about
88 MB, into `~/.cache/huggingface`.

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

    method: embed
    names: 1798; by label: 380; by matcher: 683; NO_MATCH: 735

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

`macroswap match` ranks the USDA table for a food name three ways: lexical,
BM25 over the words; embed, a pinned sentence-embedding model; and hybrid, the
two rankings fused by reciprocal rank. Lexical and embed each abstain, NO_MATCH,
below their own threshold, and hybrid only when its top food is, for each of the
two, below its threshold or not scored by it.

    uv run macroswap match "kirkland - chicken breast"

To measure them I labeled a sample of my diary's foods with
`macroswap match label`: the most-logged foods covering 80% of counted rows and
a seeded random sample of the rest, each split into dev and test. Dev tunes the
thresholds and picks the method `diary match` runs. Test is only reported, here,
from the table CI checks the eval against:

    uv run macroswap match eval --write-expected
    uv run python scripts/render_eval.py

<!-- eval:begin -->
| split | bucket | weighting | metric | lexical | embed | hybrid |
| --- | --- | --- | --- | --- | --- | --- |
| test | head | names | top1_ranking | 0.508 [0.437, 0.577] n=197 | 0.467 [0.399, 0.533] n=197 | 0.538 [0.468, 0.608] n=197 |
| test | head | names | top1_end_to_end | 0.455 [0.391, 0.518] n=220 | 0.409 [0.345, 0.468] n=220 | 0.491 [0.423, 0.559] n=220 |
| test | head | names | top5_ranking | 0.706 [0.641, 0.767] n=197 | 0.695 [0.629, 0.756] n=197 | 0.721 [0.655, 0.785] n=197 |
| test | head | names | top5_end_to_end | 0.627 [0.564, 0.691] n=220 | 0.532 [0.464, 0.595] n=220 | 0.645 [0.582, 0.709] n=220 |
| test | head | names | no_match_precision | 0.143 [0.000, 0.357] n=14 | 0.213 [0.131, 0.299] n=89 | 0.182 [0.043, 0.357] n=22 |
| test | head | names | no_match_recall | 0.087 [0.000, 0.222] n=23 | 0.826 [0.647, 0.960] n=23 | 0.174 [0.042, 0.353] n=23 |
| test | head | names | exact_id | 0.449 [0.379, 0.518] n=196 | 0.418 [0.352, 0.485] n=196 | 0.485 [0.417, 0.555] n=196 |
| test | head | rows | top1_ranking | 0.563 [0.423, 0.678] n=197 | 0.498 [0.365, 0.623] n=197 | 0.559 [0.432, 0.678] n=197 |
| test | head | rows | top1_end_to_end | 0.536 [0.403, 0.650] n=220 | 0.449 [0.321, 0.577] n=220 | 0.543 [0.416, 0.659] n=220 |
| test | head | rows | top5_ranking | 0.734 [0.620, 0.824] n=197 | 0.703 [0.582, 0.801] n=197 | 0.733 [0.618, 0.824] n=197 |
| test | head | rows | top5_end_to_end | 0.697 [0.587, 0.785] n=220 | 0.587 [0.456, 0.699] n=220 | 0.705 [0.593, 0.793] n=220 |
| test | head | rows | no_match_precision | 0.067 [0.000, 0.235] n=14 | 0.156 [0.080, 0.258] n=89 | 0.213 [0.026, 0.479] n=22 |
| test | head | rows | no_match_recall | 0.060 [0.000, 0.177] n=23 | 0.905 [0.767, 0.982] n=23 | 0.272 [0.039, 0.524] n=23 |
| test | head | rows | exact_id | 0.525 [0.380, 0.646] n=196 | 0.468 [0.333, 0.594] n=196 | 0.526 [0.392, 0.647] n=196 |
| test | tail | names | top1_ranking | 0.453 [0.342, 0.566] n=75 | 0.507 [0.395, 0.622] n=75 | 0.533 [0.419, 0.649] n=75 |
| test | tail | names | top1_end_to_end | 0.340 [0.252, 0.437] n=103 | 0.505 [0.408, 0.602] n=103 | 0.447 [0.350, 0.544] n=103 |
| test | tail | names | top5_ranking | 0.693 [0.587, 0.797] n=75 | 0.787 [0.687, 0.880] n=75 | 0.813 [0.714, 0.901] n=75 |
| test | tail | names | top5_end_to_end | 0.505 [0.408, 0.602] n=103 | 0.602 [0.515, 0.699] n=103 | 0.641 [0.544, 0.738] n=103 |
| test | tail | names | no_match_precision | 0.222 [0.000, 0.500] n=9 | 0.453 [0.314, 0.588] n=53 | 0.533 [0.267, 0.783] n=15 |
| test | tail | names | no_match_recall | 0.071 [0.000, 0.182] n=28 | 0.857 [0.706, 0.967] n=28 | 0.286 [0.125, 0.464] n=28 |
| test | tail | names | exact_id | 0.375 [0.266, 0.486] n=72 | 0.417 [0.304, 0.535] n=72 | 0.472 [0.360, 0.592] n=72 |
| test | tail | rows | top1_ranking | 0.523 [0.378, 0.663] n=75 | 0.585 [0.445, 0.717] n=75 | 0.580 [0.443, 0.716] n=75 |
| test | tail | rows | top1_end_to_end | 0.391 [0.271, 0.517] n=103 | 0.526 [0.408, 0.650] n=103 | 0.465 [0.344, 0.591] n=103 |
| test | tail | rows | top5_ranking | 0.756 [0.627, 0.865] n=75 | 0.835 [0.719, 0.922] n=75 | 0.847 [0.728, 0.932] n=75 |
| test | tail | rows | top5_end_to_end | 0.557 [0.428, 0.680] n=103 | 0.622 [0.507, 0.731] n=103 | 0.665 [0.541, 0.779] n=103 |
| test | tail | rows | no_match_precision | 0.158 [0.000, 0.455] n=9 | 0.436 [0.260, 0.603] n=53 | 0.450 [0.190, 0.750] n=15 |
| test | tail | rows | no_match_recall | 0.056 [0.000, 0.163] n=28 | 0.889 [0.732, 0.984] n=28 | 0.167 [0.062, 0.333] n=28 |
| test | tail | rows | exact_id | 0.433 [0.291, 0.584] n=72 | 0.485 [0.341, 0.629] n=72 | 0.503 [0.365, 0.655] n=72 |
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

## Swaps

`macroswap swap` answers the question at the top: other foods, and the grams of
each, that give a food's macros. The food is typed with its grams; typed with
`--like-log`, at the median macros I log for it; or named as a diary entry with
`--entry`. Every row prints its serving and its protein, carbs, fat and kcal
deltas, so a reader sees which macro a swap misses and by how much; no line
carries a single distance.

    uv run macroswap swap "egg whites" --grams 165
    uv run macroswap swap "ground beef 93/7" --grams 150 --variants
    uv run macroswap swap --entry "kirkland - chicken breast"

A typed name is looked up first in a table of four everyday names
(`[swap.staples]` in `macroswap.toml`: white rice, potatoes, greek yogurt and
salmon), compared exactly after the matcher's own normalization of the text, and
only then given to the matcher. The table is a curated synonym layer kept out of
the matcher, so every number in the eval block above is for the matcher alone.

Until the popularity table is built, every family counts as common, the header
says so, and the rows are the closest macro matches whatever the food: chicken
breast is answered with ostrich before turkey. `data/acceptance/swaps.toml` holds
the swaps I would accept, and the ones I call absurd, for 17 foods, marked from
the engine's top 25 on the USDA table alone, and CI holds the engine to them
within those 25 rows: 76 accepted swaps are there today and 5 absurd ones are
not; 40 more accepted and 189 absurd ones are tagged `requires = "popularity"`,
asserted once the popularity table exists.
