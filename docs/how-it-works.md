# How it works

This page follows a swap from the public data to the printed list and gives
the reason for each step. The commands are in the [README](../README.md); how
the survey counts are made, and what they miss, is in
[popularity.md](popularity.md); the Python API is in [library.md](library.md).
A measurement carries the date it was taken, and the commit when it was taken
at one.

## The sources

`macroswap data pull` fetches five pinned public sources into `data/raw/usda/`
and refuses any whose checksum differs: SR Legacy and Foundation Foods, the
USDA's two food-composition releases, which become the table; the FNDDS survey
foods, the recipes behind what survey participants report; and the two NHANES
2021-2023 dietary recall files, one for each recall day. `macroswap data build`
turns them into one SQLite store, `data/build/macroswap.sqlite`, and
`macroswap data report` measures the table.

## The table

SR Legacy and Foundation Foods become one table. A Foundation row that shares
an SR number with an SR Legacy row is dropped, and so are rows given on a dry
basis. Five ground-beef levels the USDA does not publish are interpolated
between the published levels around them and added as rows of their own.

### Families and variants

Before a row is keyed, its description loses the program note in parentheses,
boilerplate fields (`broilers or fryers`, `mature seeds`, `usda commodity`),
state fields such as `raw`, and cosmetic fields (salt, enrichment, grades,
`boneless`, `skinless`, `trimmed to`). Its family is the first two fields left,
and every kept field, lower-cased, the family's two included, names its
variant, a leanness written as NN/MM:
`Beef, ground, 93% lean meat / 7% fat, raw` is the family `beef, ground` at the
variant `beef, ground, 93/7`. A cooked row with no sibling in another state
keys at its first field and the field that names how it was cooked:
`Chicken, broilers or fryers, rotisserie, ...` is `chicken, rotisserie`. The
family is what a swap offers, so the keys decide what counts as the same food:

- `canned` or `dried` in the second field makes a family of its own,
  `sweet potato, canned`; in the third field it names a variant.
- A product form stays out of the raw family: `potatoes, mashed` and
  `potatoes, hash brown` are families of their own.
- 49 families key at one field, so their kinds fold together: russet and red
  potatoes are one family, `potatoes`, every bread bought as bread is `bread`,
  its kinds the variants, and onions, carrots, tomatoes, lentils and peanut
  butter key the same way. A canned, dried or other product-form row of one of
  them still keys at two fields.
- An alias, named in `macroswap.toml`, folds one family into another: the
  whole-bird turkey keys into `turkey, all classes`, `chicken, dark meat` into
  `chicken, thigh`, `beef, tenderloin` and `beef, top sirloin` into
  `beef, loin`. An alias changes the family and never what prints: a line
  prints the row's own variant, which is why `turkey, whole, meat only`, the
  variant of `Turkey, whole, meat only, raw`, stands for the merged turkey
  family in the README's example. Only the header's `row:` line prints a USDA
  description as it is.

### What cannot be a swap

Every USDA row stays in the matcher's index, so a diary name can still be
matched to it, but a row is given at most one reason it cannot be offered as a
swap, the first of these that applies: a Foundation row repeating an SR row;
cooked beside a raw sibling, an uncooked row (raw, canned or dry) sharing its
first field, which stands for it; an excluded category, or a word its category
denies; a poultry part nobody plates; all-zero macros; incomplete macros.

The excluded categories are Beverages; Sweets; Snacks; Fast Foods; Restaurant
Foods; Meals, Entrees, and Side Dishes; Soups, Sauces, and Gravies; Sausages
and Luncheon Meats; Spices and Herbs; Baby Foods; and American Indian/Alaska
Native Foods. An allow word in a row's description keeps it, as `sausage` and
`bratwurst` do among the sausages. Baked Products is not excluded: cakes,
cookies, pies and pastries are its denied words. The denied words and parts
are [rules of their own](#the-four-rules). On the pinned sources, 2026-10-06,
as `data report` prints it:

| Measure | Count |
| --- | --- |
| Foundation Rows Dropped for Sharing an SR Number | 211 |
| Dry-Basis Rows Dropped at Load | 34 |
| Families | 2,927 |
| Single-Row Families | 1,822 |
| Rows in the Matcher Index | 8,022 |
| Swap Candidates | 3,104 |
| Rows Cooked beside a Raw Sibling | 2,399 |
| Rows in an Excluded Category | 2,405 |
| Rows Left Out for a Poultry Part | 34 |
| Foundation Rows Repeating an SR Row | 60 |
| Rows with Incomplete or All-Zero Macros | 20 |

A candidate is a row a swap may offer. The last six rows partition the table:
3,104 + 2,399 + 2,405 + 34 + 60 + 20 = 8,022. Those 8,022 include the five
derived ground-beef levels: the matcher indexes the 8,017 USDA rows and
reaches a derived level through its family. The 2,405 rows of an excluded
category are 2,034 rows of the categories themselves and 371 rows a denied
word leaves out.

## The counts

Every family carries the number of the 6,694 NHANES 2021-2023 participants who
reported eating it: a reported food counts toward the family of its largest
ingredient by weight in its FNDDS recipe, and a participant counts once for a
family, however often they reported it. [popularity.md](popularity.md) has the
rule in full and what it misses.

A family fewer than 10 participants reported is below the floor and is not
offered, unless the allowlist, your diary or `--include-obscure` admits it. One
50 or more reported is in the first tier, listed before the rest, and so are
the allowlisted families, bison and cream of rice, ordinary foods the recalls
rarely name, and the families in your diary.

## Matching a name

`macroswap match` ranks the 8,017 USDA rows of the index for a food name three
ways, and prints each:

- **lexical**: BM25 over the food fields of each description, with the note,
  boilerplate, state and cosmetic fields removed and abbreviations expanded;
- **embed**: cosine similarity under a pinned sentence-embedding model, named
  with its revision in `macroswap.toml`; the index's vectors are computed once
  and cached beside the store;
- **hybrid**: the two rankings fused by reciprocal rank.

Lexical and embed each abstain, NO_MATCH, below their own threshold, and hybrid
only when its top food is, for each of the two, below its threshold or not
scored by it. The three scores are on different scales, BM25, cosine and a
fused rank, and mean nothing across methods. The default method, the one
`diary match`, `swap` and the library use, is embed.

A ground-meat name without a level, `ground beef`, matches the family, and a
name with one, `ground beef 93/7`, picks the level. The library stands a
family on its configured default level. `swap` stands it on the level your
diary logs most in the last 90 days, then in the whole diary, then the
configured default, and says which in its header. A level the table has no row
at, `ground beef 91/9`, falls back to the default level, and `swap` says that
in its header too.

`swap` looks a typed name up in a table of five everyday names first, white
rice, rice, potatoes, greek yogurt and salmon (`[swap.staples]` in
`macroswap.toml`), compared exactly after the matcher's own normalization of
the text, and only then asks the matcher. The table is a synonym layer kept out
of the matcher, so the eval measures the matcher alone, and `match` and the
library give the matcher's own answer for those names. The bare name `rice` is
white rice; `wild rice` and `black rice` reach those.

## Your diary

`macroswap diary import` reads a folder of MyFitnessPal printable-diary exports
into the store, each named `mfp_YYYY-MM-DD_YYYY-MM-DD.html` for the first and
last day it covers. Each day is checked against the page's own TOTALS row: for
each file, the import counts the days whose calories match it within 1 kcal and
the days that do not, and a day without a TOTALS row is neither. A day is
untracked when quick adds, calories logged without a food, are half its
calories or more; counted rows are the rows of tracked days that are not quick
adds. On my own diary, 2026-09-22:

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

`macroswap diary match` resolves each of those 1,798 foods once: to a USDA row,
to a family for ground meat matched or labeled at its family, or to NO_MATCH. A
food I have labeled takes my label, and the default method resolves the rest:

    method: embed
    names: 1798; by label: 380; by matcher: 683; NO_MATCH: 735

The three counts add up to the names. NO_MATCH covers both the foods I labeled
as having no USDA match and the ones the matcher abstained on. Unlike `match`,
`diary match` never falls back to lexical: a default method that needs the
missing `embed` extra exits 2. The names are encoded in two calls of the model,
one for every unlabeled name and one more for the names it abstains on, to
record the score it refused at: on these 1,798 it takes 20 s where one call per
name took 36 s, with the same table name for name (2026-10-08).

`diary match` reads `data/labels/labels.csv` relative to the working directory,
and says so when the file is not there. A swap relies on its table and refuses
it when it is missing, when a new import or a new `data build` has cleared it,
or when it was made under a different default method, thresholds, labels file
or model revision. `swap` reads the labels file relative to the working
directory too, for that check, so run both from the clone's root.

## A swap

### The target

A swap starts from a food and its macros: a typed name with `--grams`, at that
amount; a typed name with `--like-log`, at the median of each macro over the
diary rows of every name resolved to the same variant, or family; or a diary
name with `--entry`, at the same medians over that name's rows. The medians are
taken over rows logging all three macros, in the 90 days ending at the diary's
last counted day, or over the whole diary when those days have none. The header
prints the target, the USDA row it resolved to, the method, the macros, the
level and the window when they apply, the rows per name, and the survey the
counts come from.

### The fit

For each candidate row, the serving is the number of grams `s` that best
reproduces the target's protein, carbs and fat, a weighted least-squares fit
with a closed form:

    s* = Σ wᵢ·xᵢ·tᵢ / Σ wᵢ·xᵢ²

`xᵢ` is the candidate's grams of macro `i` in a gram of the food, `tᵢ` the
target's grams of it, and `w` is 3, 1 and 1 for protein, carbs and fat
(`[swap] fit_weights` in `macroswap.toml`), so a swap holds protein first. A
serving prints in grams of the food as bought, with its state when that is not
raw: `121 g cooked` for rotisserie chicken, bought cooked, and `56 g dry` for
mashed-potato granules.

### The score

What the serving still misses, its macros minus the target's, is measured in
calories:

    score = √( 3·(4·Δprotein)² + (4·Δcarbs)² + (9·Δfat)² )

That is 4, 4 and 9 kcal a gram, with protein's term weighted 3 as in the fit
(`[swap] rank_weights` holds the squared, weighted factors: 48, 16 and 81), so
a gram of fat missed costs more than a gram of carbs. Doubling the target's
grams doubles every serving and every miss, so the scores keep their order.
The printed order can still change with the amount, since the tie window of 5
and the serving bounds of 5 to 1,000 g are fixed: at 300 g of chicken breast,
rotisserie chicken is fifth and ham leaves the first eight. A printed line
carries the four deltas, never the score: a reader sees which macro a swap
misses and by how much.

### What is left out

Before ranking, a family is left out for the first of these that applies: it
is the target's own family; it shares no pool with the target; with
`--new-only`, it is already in your diary; it is below the floor; it is a
non-starchy vegetable; none of its variants has a serving between 5 and
1,000 g; or, when the target has grams, none has a serving within six times
them. A family stays while any of its variants fits.

A family's pools are the macros that give at least a quarter of the calories
of any of its candidate rows (`role_share_threshold`, 0.25), its carbs counted
as starch or as sugar by the rule below, so a protein is answered with a
protein and a starch with a starch.

### The four rules

Four rules decide what a swap offers beyond the counts, all of them set in
`macroswap.toml`. When something absurd still gets through every filter, it
goes on the README's list of known misses rather than into a new rule.

- **Starch and sugar are two pools.** A family's carbs are sugar when its
  candidate rows' sugars, summed over the rows that carry a sugars value, are
  at least half those rows' carbs, summed, and starch below that, so a bowl of
  rice is answered with potatoes and not with grapes. A family whose candidate
  rows carry no sugars value is starch. Measured on 2026-10-05 at commit
  `eb0943b`: 224 of the 894 carb-pool families have no sugars value, six of
  them at or above the floor, all starch in fact: chia seeds (64
  participants), quinoa (50), gluten-free pasta (36), dry couscous (21), large
  lima beans (12) and yellow beans (10); the other 218 sit below the floor.
- **A serving is at most six times the target's grams.** The largest serving
  an accepted swap needs, measured on 2026-10-05 at commit `eb0943b` over the
  acceptance file, is 5.1 times (potatoes for white rice). A diary food
  matched to no USDA row has no grams, so it gets no serving cap, and the
  swap's header says so.
- **Non-starchy vegetables are not swaps.** A family of the Vegetables group
  whose candidate rows' median calories per 100 g fall below 50 is not offered
  for any target, whatever macro it is nearest, unless the target's own row is
  in that group and under the line; a target on no row keeps the rule on. The
  50 is the dietary guidelines' line between starchy and non-starchy
  vegetables, measured on the table instead of listed. Measured on 2026-10-05
  at commit `eb0943b`, medians of the family's candidate rows as bought:
  potatoes 76, sweet corn 76.5, sweet potato 91, yam 118, cassava 160 and taro
  112 stay; carrots 36, onions 34, beets 43, winter squash 40 and mixed
  vegetables 49 drop; canned potatoes, at 60, stay; plantains sit in the
  Fruits group and are untouched; green peas have a row filed under Legumes
  and are outside the rule. 142 of the group's 234 families fall below the
  line.
- **Denied words and parts.** The denied words are set per category; they
  include juice for fruits, soy sauce for legumes, catsup, garlic and ginger
  for vegetables, flour for cereal grains, dressing for fats and oils, and
  cakes, cookies, pies and pastries for baked products, because condiments,
  dressings and juices are drinks and seasonings, not food swaps, flour is an
  ingredient, not a food on a plate, and sweets are not swaps. A word is
  matched on the row's own two-field key within its category, under the alias
  where one names it, before the one-field cut: `Flour, semolina`, keyed as
  `semolina` by its alias, is kept, and pan dulce is denied inside `bread`. An
  allow word in the description still wins, as `mayonnaise` does against
  `dressing` among fats and oils, and as `sausage`, `bratwurst` and
  `rice cake` do against their categories. A poultry row whose description
  names a part nobody plates, heart, liver, gizzard, giblets, neck, back,
  feet, skin or separable fat, as one whole field, is left out whatever family
  it is folded into, so a turkey family shows its meat and not its heart.

### The order

The families left are listed in two tiers, the first tier first. Within a
tier, close scores count as a tie: the best remaining family opens a group of
every family within 5 of its score, and the group is listed by how many
participants reported each family, most first. In the README's example, bison
and tilapia fit almost exactly, with scores of 0.23 and 0.36, and rotisserie
chicken misses by about half a gram of fat, a score of 4.18, so all five of the
first group are within 5 of the best and rotisserie chicken, reported by 1,037,
leads it. The next group opens with pork loin at 5.37; beef round, at 5.46, and
ham, at 6.74, join it, and ham leads it, reported by 932.

Within a family, the variant shown is picked the same way: of the variants
within 5 of the family's closest, the one most participants reported, when at
least 10 did; otherwise the closest. A family is placed by its closest variant
whichever is shown. A leanness family shows its closest level, with its
default level on a second line when the two differ and that level is offered.

The count column prints the number of participants, and a word only where the
word is why the family is in its tier: `4 allowlist`, `3 diary`. The last
column is the source of the row's numbers: `sr-analytical`, `sr-formula`,
`foundation`, or `derived(85/15, 90/10)` for a ground-beef level interpolated
between two published ones.

## How it is checked

**The matcher.** I labeled 462 of my diary's food names by hand with
`macroswap match label`: the head, the most-logged foods covering 80% of
counted rows, and a seeded random sample of the tail, each split into dev and
test. Dev tuned the thresholds and picked the default method; test is only
reported, in the README's table, which CI checks against the committed
expected table. On test no method wins everywhere: hybrid leads on most
measures, while embed has the best top hit end to end on the tail and abstains
on most of the foods that have no USDA match, at the cost of abstaining on
many that have one.

**The swaps.** `data/acceptance/swaps.toml` holds, for 17 foods, the swaps I
accept, the ones I call absurd and the known misses, marked from the command's
first 25 with the counts on. The tests hold the engine to every line: an
accepted swap must be in the first 25, an absurd one must not be, and a known
miss must still be there, so the README's list of misses is measured, not
remembered.

**The counts.** The tests count again from the pinned sources and fail if the
committed table differs; [popularity.md](popularity.md) has the rest.

## Known gaps

- The cooked-row rule in the README's limits: a cooked row keyed at two fields
  where its raw family keys at one.
- A level the table has no row at falls back to the default level silently in
  the library's `Match`; `swap` says so, the library does not yet.
- `diary match` and `swap` read the labels path relative to the working
  directory rather than resolving it against the config.
- There is no prebuilt store to download; every install builds its own.
- `--help` names the config keys a default comes from rather than their
  values.
