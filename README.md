# macroswap

Macro-equivalent food swaps from a MyFitnessPal diary and USDA data:
"I'm tired of this food; what else, and exactly how many grams of it,
gives me the same macros?"

macroswap resolves a food, typed or taken from a diary, to a USDA food, fits
the grams of every candidate that best reproduce its protein, carbs and fat,
ranks the candidates by what they still miss, and leaves out the foods almost
nobody eats, as counted by a national dietary survey.

## Example

On 2026-10-09, on a store with no diary imported:

    $ uv run macroswap swap "chicken breast" --grams 150 --top 8
    target: chicken, breast / raw (150 g)
    row: foundation:2646170 Chicken, breast, boneless, skinless, raw
    method: embed
    macros: protein 33.8 g, carbs 0.0 g, fat 2.9 g
    popularity: NHANES 2021-2023, 6694 participants; count is how many reported the family
    121 g cooked  chicken, rotisserie, original seasoning, breast, meat only  protein +0.0  carbs +0.0  fat +0.5  kcal +4  count 1037  sr-analytical
    149 g  turkey, whole, meat only  protein +0.0  carbs +0.2  fat +0.0  kcal +1  count 147  sr-analytical
    168 g  fish, tilapia  protein +0.0  carbs +0.0  fat +0.0  kcal +0  count 117  sr-analytical
    143 g  turkey, ground, 99/1  protein +0.0  carbs +0.0  fat -0.1  kcal -1  count 74  sr-analytical
        default level (config default): 171 g  turkey, ground, 93/7  protein -1.7  carbs +0.0  fat +11.4  kcal +96  count 74  sr-analytical
    156 g  game meat, bison, separable lean only  protein +0.0  carbs +0.0  fat +0.0  kcal +0  count 4 allowlist  sr-analytical
    181 g  pork, cured, ham -- water added, shank, separable lean only, unheated  protein +0.0  carbs +1.3  fat +0.5  kcal +9  count 932  sr-analytical
    161 g  pork, loin, tenderloin, separable lean only  protein +0.0  carbs +0.0  fat +0.6  kcal +5  count 415  sr-analytical
    143 g  beef, round, top round roast, separable lean only  protein +0.0  carbs +0.0  fat +0.6  kcal +5  count 362  sr-analytical

Each line is one food family, shown at one of its variants: the serving that
best gives the target's macros, weighed as the food is bought (rotisserie
chicken is bought cooked); how much protein, carbs, fat and calories that
serving gives above or below the target; how many of the survey's 6,694
participants reported the family; and the USDA data behind the row. Foods
that fit about equally well are listed by how many people eat them, which is
why rotisserie chicken leads tilapia, the closer fit. Ground turkey shows its
closest level, 99/1, and under it the configured default, 93/7; with a diary
imported, the default is the level you log most. Bison sits with the ordinary
foods by an allowlist, though only 4 participants reported it.

## Quick start

macroswap needs Python 3.12 and [uv](https://docs.astral.sh/uv/).

    git clone https://github.com/ja-gilbert/macroswap && cd macroswap
    uv sync --extra embed
    uv run macroswap data pull      # about 140 MB, verified by checksum
    uv run macroswap data build
    uv run macroswap swap "chicken breast" --grams 150

`data pull` fetches five pinned public sources into `data/raw/usda/`: SR
Legacy, Foundation Foods, the FNDDS survey foods and the two NHANES 2021-2023
recall files, about 140 MB to download and 238 MB on disk once unpacked.
`data build` turns them into one SQLite store, `data/build/macroswap.sqlite`.
Run the commands from the clone's root. The first command that needs the
embedding model downloads it, about 88 MB, into `~/.cache/huggingface` and
says so; a Hugging Face notice about unauthenticated requests may follow and
is harmless, since the model is public.

The `embed` extra adds sentence-transformers and torch; installed by uv in a
clone, torch is the CPU-only build. Without the extra, `match` and `swap` fall
back to lexical and say so on their `method:` line; `--method embed` or
`--method hybrid` exits 2 naming the install command, and `diary match`,
`match label` and `match eval --write-expected` exit 2.

## Your diary

Everything above needs only the public data. With a MyFitnessPal diary,
macroswap also swaps the foods you actually log. Save MyFitnessPal's printable
diary as `mfp_YYYY-MM-DD_YYYY-MM-DD.html`, named for the first and last day it
covers (I save a month per file), all in one folder, then:

    uv run macroswap diary import path/to/folder
    uv run macroswap diary stats
    uv run macroswap diary match
    uv run macroswap swap --entry "kirkland - chicken breast"

`diary match` resolves each distinct food in the diary once, and `swap` relies
on its table: when the table is missing, cleared by a new import or a new
`data build`, or made under a different method, thresholds, labels file or
model, `swap` stops and asks you to run `diary match` again. Both read the
labels file relative to the working directory, so run them from the clone's
root.

The clone carries my labels, `data/labels/labels.csv`, and `diary match`
applies them: a name in your diary that matches one of mine takes my label.
Move the file aside to match your diary with the matcher alone, or to label a
sample of your own with `match label`.

What enters this repository from my own diary is that labeled sample: 462 of
my food names, each as a lower-cased "brand - food" key without its serving
text, with how many of my rows it covers, its bucket and split, the USDA row I
chose for it or NO_MATCH, and where the label came from; and the counts quoted
in these docs. Dates, amounts and macros never do. The diary HTML lives under
`data/raw/` and the built store under `data/build/`, both ignored, as is a
store, an embeddings cache or an export saved anywhere else in a clone outside
the test fixtures, and CI fails if one is tracked.

## Commands

| Command | What it does |
| --- | --- |
| `data pull` | Downloads the five pinned sources into `data/raw/usda/` and refuses any whose checksum differs. |
| `data build` | Builds the store: the USDA table with its families and exclusions, and the survey counts. |
| `data report` | Measures the table. |
| `match NAME` | Ranks USDA foods for a name by each method: lexical, embed and hybrid. |
| `match label` | Labels a sample of diary foods by hand, for the eval; in a clone it resumes mine. |
| `match eval` | Scores the three methods against the labels. |
| `diary import FOLDER` | Reads printable-diary exports into the store. |
| `diary stats` | Reports what the diary holds. |
| `diary match` | Resolves each distinct diary food once. |
| `swap FOOD --grams N` | Swaps for a food and an amount. |
| `swap FOOD --like-log` | Swaps at the median macros you log for that food. |
| `swap --entry NAME` | Swaps for a food in your diary, at the median macros you log for it. |

In a clone each runs as `uv run macroswap …`. `match` and `swap FOOD --grams N`
need only the built store; `diary stats`, `diary match`, `swap --entry` and
`--like-log` need an imported diary, and `--new-only` runs without one but then
leaves nothing out. `swap` also takes `--top N`, `--method`, `--variants`,
`--include-obscure` and `--new-only`, and `--help` on any command explains its
options.

## Using it as a library

The matcher, the fit and the table import as `macroswap`, pinned by tag; the
`embed` extra is the default method's:

    macroswap[embed] @ git+https://github.com/ja-gilbert/macroswap@v0.1.0

    from pathlib import Path
    from macroswap import Matcher

    # the store `data pull` and `data build` made in ~/macroswap-data
    m = Matcher(store=Path.home() / "macroswap-data/data/build/macroswap.sqlite")
    match = m.match("kirkland - chicken breast")  # None when the matcher abstains
    if match:
        fit = m.fit(match, protein_g=31.0, carbs_g=0.0, fat_g=3.6)  # grams for these macros
        food = m.food(match.row_id)  # the food's macros per 100 g

The store is built once by the installed command, in any directory;
[docs/library.md](docs/library.md) has how, and the rest of the API.

## How it works

1. **The table.** SR Legacy and Foundation Foods become one table of 8,017
   USDA foods, plus five ground-beef levels interpolated between published
   ones. Each row is keyed into a family, `beef, ground`, and a variant,
   `beef, ground, 93/7`, and given at most one reason it cannot be a swap:
   3,104 can be.
2. **The counts.** Every family carries how many of the 6,694 NHANES
   2021-2023 participants reported eating it, traced through the FNDDS recipes
   of what they reported. Fewer than 10 and it is left out; 50 or more and it
   is listed with the ordinary foods.
3. **The match.** A food name goes to a USDA food by word overlap (BM25), by a
   sentence-embedding model, the default, or by the two fused, and each may
   answer NO_MATCH.
4. **The fit.** For every candidate, the grams that best reproduce the
   target's protein, carbs and fat, protein weighted three times.
5. **The rank.** Candidates are ranked by what they still miss, in calories,
   after rules that keep a swap on the same kind of plate: starch for starch
   and not sugar, no serving over six times the target's grams, no non-starchy
   vegetables, no denied words (fruit juice, dressings, soy sauce, catsup,
   cereal flours) and no poultry parts.

[docs/how-it-works.md](docs/how-it-works.md) walks each step with its reasons
and measurements, and [docs/popularity.md](docs/popularity.md) gives the counts
in full.

## Results

### Matching

I labeled 462 of my diary's food names by hand with `macroswap match label`:
the most-logged foods covering 80% of counted rows (the head) and a seeded
random sample of the rest (the tail), each split into dev and test. Dev tuned
the thresholds and chose embed as the default method; test is only reported.
Counting each name once, end to end, the right food is the top hit for a third
to a half of the test names, depending on the method and the bucket, and among
the first five for a half to two thirds; leaving out the foods labeled
NO_MATCH, 45% to 54% and 69% to 81%. Diary names are hard: brands,
abbreviations, restaurant dishes and foods the USDA has no row for; 735 of my
1,798 end as NO_MATCH, labeled as having no USDA food or abstained on.

<details>
<summary>The test table: every metric, with 95% intervals</summary>

A food is right when its top hit, or for top5 one of its first five, is the
food I labeled, at the identity a swap shows: its variant and whether it is
bought raw, cooked, canned or dry, or its family for ground meat logged
without its leanness. A label may list up to three rows of one food in one
state, and a hit counts at any of them. Each entry is the share right, its
seeded bootstrap 95% interval and n, counting foods once (names) or by how
often I logged them (rows). Ranking ignores the thresholds and leaves out the
foods labeled NO_MATCH; end to end, an abstention is right only for a food
labeled NO_MATCH. `no_match_precision` is the share of abstentions that were
right, `no_match_recall` the share of NO_MATCH foods that abstained, and
`exact_id` the share whose top hit is the very row I picked first.

<!-- eval:begin -->
| split | bucket | weighting | metric | lexical | embed | hybrid |
| --- | --- | --- | --- | --- | --- | --- |
| test | head | names | top1_ranking | 0.508 [0.437, 0.577] n=197 | 0.467 [0.399, 0.533] n=197 | 0.538 [0.468, 0.608] n=197 |
| test | head | names | top1_end_to_end | 0.455 [0.391, 0.518] n=220 | 0.409 [0.345, 0.468] n=220 | 0.491 [0.423, 0.559] n=220 |
| test | head | names | top5_ranking | 0.706 [0.641, 0.767] n=197 | 0.695 [0.629, 0.756] n=197 | 0.716 [0.649, 0.781] n=197 |
| test | head | names | top5_end_to_end | 0.627 [0.564, 0.691] n=220 | 0.532 [0.464, 0.595] n=220 | 0.641 [0.577, 0.705] n=220 |
| test | head | names | no_match_precision | 0.143 [0.000, 0.357] n=14 | 0.213 [0.131, 0.299] n=89 | 0.182 [0.043, 0.357] n=22 |
| test | head | names | no_match_recall | 0.087 [0.000, 0.222] n=23 | 0.826 [0.647, 0.960] n=23 | 0.174 [0.042, 0.353] n=23 |
| test | head | names | exact_id | 0.449 [0.379, 0.518] n=196 | 0.418 [0.352, 0.485] n=196 | 0.485 [0.417, 0.555] n=196 |
| test | head | rows | top1_ranking | 0.563 [0.423, 0.678] n=197 | 0.498 [0.365, 0.623] n=197 | 0.559 [0.432, 0.678] n=197 |
| test | head | rows | top1_end_to_end | 0.536 [0.403, 0.650] n=220 | 0.449 [0.321, 0.577] n=220 | 0.543 [0.416, 0.659] n=220 |
| test | head | rows | top5_ranking | 0.734 [0.620, 0.824] n=197 | 0.703 [0.582, 0.801] n=197 | 0.730 [0.617, 0.820] n=197 |
| test | head | rows | top5_end_to_end | 0.697 [0.587, 0.785] n=220 | 0.587 [0.456, 0.699] n=220 | 0.702 [0.591, 0.791] n=220 |
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

</details>

### Swaps

For 17 foods, `data/acceptance/swaps.toml` records the swaps I accept and the
ones I call absurd, marked on 2026-10-06 from the command's first 25 with the
counts on, and the test suite holds the engine to them: 151 accepted swaps are
in the first 25 and 170 absurd ones are not. The same file names the known
misses: swaps offered in the first 25 today that pass the shared pool, the
serving ratio, the vegetable rule and the floor, and that I chose not to add a
rule for. Each is held to the first 25 the way an accepted swap is, so the
list is measured, not remembered.

<details>
<summary>The known misses</summary>

<!-- misses:begin -->
- cheese for a meat, egg-white, yogurt or cottage-cheese target: the protein and the fat of meat, so the fit is real; nobody plates it in meat's place. Offered today for greek yogurt: `cheese, cheddar`, `cheese, cream`, `cheese, american`, `cheese, mozzarella`, `cheese, swiss`; for salmon: `cheese, parmesan`, `cheese, mozzarella`, `cheese, cheddar`, `cheese, monterey`; for chicken breast: `cheese, mozzarella`; for ground beef 93/7: `cheese, pasteurized process`, `cheese, swiss`; for ground beef 75/25: `cheese, cheddar`, `cheese, pasteurized process`, `cheese, monterey`, `cheese, feta`, `cheese, colby`, `cheese, queso fresco`, `cheese, pasteurized process cheese food or product`, `cheese product, pasteurized process`, `cheese, mozzarella`, `cheese, swiss`, `cheese, cream`, `cheese spread, pasteurized process`; for egg whites: `cheese, mozzarella`, `cheese, swiss`, `cheese, cheddar`; for chicken thighs: `cheese, pasteurized process`; for tilapia: `cheese, mozzarella`; for Yogurt, plain, low fat: `cheese, cream`; for Cheese, cottage, lowfat, 2% milkfat: `cheese, cream`, `cheese, pasteurized process`, `cheese, swiss`, `cheese, american`.
- nuts and nut butters for 75/25 beef. Offered today for ground beef 75/25: `peanuts`, `peanut butter`, `nuts, walnuts`, `nuts, almonds`.
- sprouted beans for a yogurt or cottage cheese target. Offered today for Yogurt, plain, low fat: `beans, kidney`, `beans, pinto`; for Cheese, cottage, lowfat, 2% milkfat: `beans, kidney`.
- imitation shellfish, surimi, for a yogurt or cottage cheese target: the only shellfish rows with carbs. Offered today for Yogurt, plain, low fat: `crustaceans, shrimp`, `crustaceans, crab`; for Cheese, cottage, lowfat, 2% milkfat: `crustaceans, shrimp`.
- sweetened milks, chocolate and sweetened condensed, for bread. Offered today for bread: `milk, chocolate`, `milk, canned`.
- the Quaker brand key beside the generic grits and oats families: two of 25 slots for one food. Offered today for white rice: `cereals, quaker`; for potatoes: `cereals, quaker`; for sweet potato: `cereals, quaker`; for oats: `cereals, quaker`; for bread: `cereals, quaker`; for brown rice: `cereals, quaker`.
- soy foods where the macros fit and the plate does not: a veggie burger for a bowl of plain yogurt. Offered today for Yogurt, plain, low fat: `veggie burgers or soyburgers`.
<!-- misses:end -->

</details>

## Limits

- Matching a diary name to the right USDA food is the weakest step; the test
  table above measures it.
- The counts are unweighted survey participants, children included, not an
  estimate of how many Americans eat a food. A food that FNDDS builds from its
  ingredients rather than from its own row earns little or no count of its
  own: ready-to-eat cereals are built from grain, flour and sugar, so their
  1,790 reporters count toward oats, cornmeal, wheat flour, rice flour and
  sugar, and no ready-to-eat family reaches the floor.
- A cooked row keys at two fields where its raw sibling keys at one, so
  toasted white bread sits under `bread, white` and a baked potato under
  `potatoes, flesh`, and a typed cooked food is offered its raw family first.
  A rule measured on 2026-10-07 would move 182 rows, 25 of them with
  participants, into 21 one-field families; it is not in this version.
- There is no prebuilt store to download: `data build` makes one from the
  public sources on your machine.

The other known gaps are at the end of
[docs/how-it-works.md](docs/how-it-works.md#known-gaps).

## Development

    uv sync --extra embed
    uv run ruff check .
    uv run ruff format --check .
    uv run mypy
    uv run pytest

In a fresh clone `uv run pytest` skips the data tests, the acceptance file's
among them, until `data pull` has run, since they build their own table and
counts from the pulled sources; with `MACROSWAP_REQUIRE_DATA=1` they are
required. The test table and the known misses above, and the counts in
`docs/popularity.md`, are rendered from committed data: each has its script
under `scripts/`, and CI fails if a block differs from what its data renders.
The eval's expected table is rewritten from the labels by
`uv run macroswap match eval --write-expected`, and the counts table by
`uv run macroswap data build --write-popularity`.

## License

MIT; see [LICENSE](LICENSE).

## Authorship

I built macroswap with AI tools. Claude Code wrote the code, the tests and the
measurement scripts; Claude reviewed the design with me and wrote most of this
documentation. The problem, the scope and the design decisions were mine, many
of them made between options the tools laid out. I labeled the evaluation set
by hand, set the criteria an acceptable swap has to meet and reviewed the marks
that apply them, and I checked and merged every change myself.
