# Popularity

A swap should leave out foods almost nobody eats and list ordinary foods
first. "Ordinary" is counted, not guessed: every food family carries the number
of people in a national dietary survey who reported eating it. This page says
what that number is, how it is made and what it misses.

Every number inside a marked block is rendered from the committed table,
`data/popularity/popularity.json`, and from `macroswap.toml`, which holds the
floor, the threshold and the lists. `macroswap data build` counts from the
pinned sources into the local database and writes nothing else; asked to, it
also rewrites the committed table, and a script renders this page from it:

    uv run macroswap data pull
    uv run macroswap data build --write-popularity
    uv run python scripts/render_popularity.py

The tests count again from the same sources and fail if the committed table
differs, and CI fails if this page is not what the table renders. The numbers
outside the blocks are one-off measurements, each with its date and the commit
it was measured at.

## What a count is

A count is unweighted distinct participants across both recall days of one
NHANES cycle, 2021 to 2023. A participant counts once for a family, however
often they reported it and on whichever day, and only a recall NHANES marks as
reliable is read. Children are included: no age filter is applied. Survey
weights are not used, so a count is a number of survey participants and not an
estimate of how many Americans eat a food. That is all a floor and a tie-break
need.

<!-- counts:totals -->
NHANES 2021-2023: 6,694 participants reported 934 families and 1,370 variants, 135,448 participant-family pairs in all.
<!-- counts:end -->

## How a reported food reaches a family

NHANES records what people ate as FNDDS survey foods, and FNDDS gives each
survey food a recipe of USDA ingredients, some of them other survey foods. A
survey food counts toward the family of its largest ingredient by weight:

- Nested recipes are expanded, each ingredient weighted by its share of the
  recipe it sits in.
- Water is set aside. The largest ingredient is taken among those outside the
  water families, and a food that is all water counts as water. Oatmeal
  made with water is mostly water by recipe and would otherwise count as water.
- When several families tie for the largest weight, the food counts toward each
  of them. Two shares tie when they are equal within 1e-9; anything else is not
  a tie, however close.
- "Any ingredient anywhere" is not the rule: cornstarch and gelatin would
  inherit the count of every dish they appear in.

The water rule, measured on 2026-10-05 at commit `ed2786a` with the rule off
and on: `cereals, oats` 815 and 1,335 participants, `rice, white` 1,559 and
1,609, `cereals, cream of wheat` 0 and 26.

The tie rule, measured on 2026-10-05 at commit `ed2786a`. FNDDS builds its
unspecified foods as equal blends ("Beef, steak, NFS" is four cuts at 24.8%
each), so 222 of its 5,432 foods tie for their largest family and 2,915
participants reported at least one of them. Counting one family of a tie lets
recipe order or spelling decide, so every tied family counts:

| Family | First in the recipe | First by name | Every tied family |
| --- | --- | --- | --- |
| beef, loin | 220 | 319 | 319 |
| beef, round | 268 | 165 | 362 |
| beef, rib eye steak | 96 | 96 | 199 |
| beef, short loin | 25 | 25 | 129 |
| cheese, monterey | 71 | 71 | 175 |
| cheese, american | 1 | 1 | 186 |
| peppers, jalapeno | 57 | 12 | 132 |
| cream, sour | 427 | 594 | 599 |
| carrots | 868 | 887 | 988 |
| chicken, breast | 775 | 798 | 814 |
| potatoes | 1,692 | 1,665 | 1,701 |
| participant-family pairs | 131,317 | 131,347 | 135,448 |

## Weight that reaches no table row

An ingredient the table has no row for carries its weight nowhere: its weight
goes to no family and is measured here instead.

<!-- counts:unattributed -->
Averaged over every food reported, a food counted each time it was reported, 0.02% of a food's weight reaches no row of the table.
<!-- counts:end -->

## Cooked keys

Most NHANES foods are eaten cooked, and FNDDS builds them from cooked USDA
rows. Where a cooked row keys with its raw family, the count lands on a family
a swap can offer. Where it keys apart, a `count_as` line in `macroswap.toml`
sends its count to the family it is: one hop, to a family a swap offers, each
line confirmed from these counts. "Together" is the participants who reported the
family or any key that counts as it, not a sum.

<!-- counts:count_as -->
| Family | Alone | Counts as | Alone | Together |
| --- | --- | --- | --- | --- |
| peanuts, all types | 383 | peanuts | 3 | 383 |
| broccoli, chopped | 234 | broccoli | 550 | 766 |
| cauliflower, drained | 141 | cauliflower | 128 | 262 |
| quinoa | 50 | quinoa, uncooked | 0 | 50 |
| rice noodles | 40 | rice noodles, dry | 0 | 40 |
| chicken patty | 29 | chicken patty, uncooked | 0 | 29 |
| brussels sprouts, drained | 22 | brussels sprouts | 72 | 92 |
| couscous | 21 | couscous, dry | 0 | 21 |
| okra, drained | 16 | okra | 15 | 31 |
| buckwheat groats | 4 | buckwheat groats, dry | 0 | 4 |
| collards, chopped | 3 | collards | 58 | 61 |
| bulgur | 3 | bulgur, dry | 0 | 3 |
| lotus root, drained | 2 | lotus root | 0 | 2 |
| kale, drained | 3 | kale | 114 | 117 |
| pumpkin flowers, drained | 2 | pumpkin flowers | 0 | 2 |
| parsnips, drained | 1 | parsnips | 0 | 1 |
| pasta | 1,339 | pasta, dry | 0 | 1,339 |
| potatoes, flesh | 1,079 | potatoes | 464 | 1,701 |
| potatoes, flesh and skin | 579 | potatoes | 464 | 1,701 |
| spinach, chopped or leaf | 19 | spinach | 398 | 415 |
| turnip greens, drained | 18 | turnip greens | 0 | 18 |
| onions, whole | 11 | onions | 1,191 | 1,198 |
| onions, drained | 1 | onions | 1,191 | 1,198 |
| asparagus, drained | 6 | asparagus | 166 | 172 |
| carrots, drained | 81 | carrots | 927 | 988 |
| cowpeas, immature seeds | 10 | cowpeas | 0 | 10 |
| peas, split | 23 | peas, green | 204 | 227 |
| sweet potatoes, orange flesh | 204 | sweet potato | 0 | 204 |
| bison, ground | 4 | game meat, bison | 0 | 4 |
<!-- counts:end -->

## What no swap can offer

Some reports land on a family with no candidate row, so no swap can offer it.
Such a pair is there for one of two different reasons, and the two do not add
up to one number that means anything. A family is filed by the rows its
reports came through; a row no report came through decides nothing.

- **Left out by design.** Every one of those rows is in a category the table
  excludes on purpose, or carries a word its category denies: drinks, sweets,
  snacks, cakes, cookies, pies and pastries, fast food and restaurant dishes,
  mixed dishes, soups and sauces, sausages and lunch meats, spices, baby food.
  These were never meant to be swaps, whatever their key says.
- **Not reachable.** At least one of those rows is left out for its key alone,
  a cooked key no `count_as` line names or a duplicate of another row: a food
  a swap could offer if the key were fixed. This is the second gap in the
  counts, after the weight above: in participants, not weight.

A family that is neither is filed as other, so the three lines below hold every
family no swap offers, the last even when it is empty. This filing is made for
this page. The table still gives each row one reason, and files a cooked row
that has a raw sibling as cooked before it looks at the category, so fast-food
fried chicken is a cooked key in the table and left out by design here.

<!-- counts:not_offered -->
| Why no swap offers the family | Families | Pairs | Share of all pairs |
| --- | --- | --- | --- |
| left out by design | 383 | 52,275 | 38.6% |
| not reachable | 8 | 573 | 0.4% |
| other | 0 | 0 | 0.0% |
<!-- counts:end -->

What is left out by design is mostly drinks and sweets; its meat and grain come
as sausage, fast food and boxed dishes, not as a cut or a bag of rice. Its ten
largest categories, by pairs, a family counted under the category with the
most of the rows its reports came through and the first by name on a tie:

<!-- counts:by_design -->
| Category left out by design | Families | Pairs | Share of all pairs |
| --- | --- | --- | --- |
| Beverages | 65 | 20,363 | 15.0% |
| Sweets | 72 | 10,148 | 7.5% |
| Snacks | 42 | 5,711 | 4.2% |
| Baked Products | 63 | 4,174 | 3.1% |
| Fast Foods | 23 | 3,665 | 2.7% |
| Soups, Sauces, and Gravies | 30 | 2,669 | 2.0% |
| Sausages and Luncheon Meats | 30 | 1,870 | 1.4% |
| Meals, Entrees, and Side Dishes | 25 | 1,393 | 1.0% |
| Restaurant Foods | 5 | 989 | 0.7% |
| Spices and Herbs | 4 | 936 | 0.7% |
| all others | 24 | 357 | 0.3% |
<!-- counts:end -->

Of the families not reachable, three I considered as `count_as` lines and
refused. French fries (`potatoes, all types`) and sweet potato fries (`sweet
potatoes, frozen as packaged`) are product forms the table keeps out of the raw
family, so their counts stay out too. Buttermilk waffles (`waffle,
buttermilk`) are a different variety from plain ones, not a cooked key of them.

<!-- counts:not_reachable -->
| Family not reachable | Participants |
| --- | --- |
| potatoes, all types | 279 |
| waffle, buttermilk | 160 |
| fish, fish sticks | 54 |
| sweet potatoes, frozen as packaged | 36 |
| noodles, flat | 30 |
| turkey, light or dark meat | 7 |
| cereals ready-to-eat, wheat germ | 6 |
| chicken, feet | 1 |
<!-- counts:end -->

## The floor and the common tier

A family below the floor is not offered. A family at or above the common
threshold is listed in the first tier. Both are absolute counts, frozen in
`macroswap.toml` for this cycle: `data build` refuses survey foods of another
cycle, so the two numbers never silently come to mean something else.

<!-- counts:tiers -->
| Reported by at least | Families a swap can offer |
| --- | --- |
| any number | 1,468 |
| 1 | 543 |
| 10 (the floor) | 369 |
| 20 | 300 |
| 50 (the common tier) | 213 |
| 100 | 159 |
<!-- counts:end -->

The threshold was set so that no staple falls out of the first tier, and a
test holds each of these at or above it:

<!-- counts:staples -->
| Family | Participants |
| --- | --- |
| turkey, ground | 74 |
| fish, cod | 90 |
| beverages, protein powder whey based | 104 |
| egg, white | 105 |
| fish, tilapia | 117 |
| lentils | 118 |
| sweet potato | 204 |
| cheese, cottage | 216 |
| beans, black | 249 |
| fish, tuna | 296 |
| crustaceans, shrimp | 310 |
| bread, whole-wheat | 331 |
| fish, salmon | 378 |
| pork, loin | 415 |
| yogurt, greek | 505 |
| chicken, breast | 814 |
| beef, ground | 1,126 |
| cereals, oats | 1,335 |
| pasta, dry | 1,339 |
| bananas | 1,570 |
| rice, white | 1,609 |
| potatoes | 1,701 |
| egg, whole | 2,381 |
<!-- counts:end -->

These families are offered in the first tier whatever their count, ordinary
foods the recalls rarely name:

<!-- counts:allowlist -->
| Family | Participants |
| --- | --- |
| game meat, bison | 4 |
| cereals, cream of rice | 4 |
<!-- counts:end -->

## A sanity check against NHANES's own categories

NHANES files every survey food under one WWEIA food category. A family's count
beside its category's is a sanity check on the link rule, not a validation: the
two are not meant to be equal, and each ratio has a reason.

<!-- counts:crosswalk -->
| Family | Participants | WWEIA category | Participants | Ratio |
| --- | --- | --- | --- | --- |
| chicken, breast | 814 | Chicken, whole pieces | 1,840 | 0.44 |
| beef, ground | 1,126 | Ground beef | 178 | 6.33 |
| rice, white | 1,609 | Rice | 1,268 | 1.27 |
| egg, whole | 2,381 | Eggs and omelets | 2,237 | 1.06 |
<!-- counts:end -->

- `chicken, breast` is under half of its category: the family is breast only,
  and WWEIA's whole-piece chicken is any cut.
- `beef, ground` is several times its category: the rule credits every dish
  whose largest ingredient is ground beef (burgers, tacos, chili, sauces),
  while WWEIA's category is plain ground beef.
- `rice, white` is a little above 1: the food and the category mostly coincide,
  dishes that are mostly white rice (rice dishes, sushi) add to the family, and
  rice in the category that is not white rice does not.
- `egg, whole` is near 1: the food and the category coincide.

## Reading the recall files

The recall files are SAS transport files, read with the standard library
alone. Checked against pandas on 2026-10-05 at commit `ed2786a`: every value of
all 84 columns of both files (100,116 and 88,032 rows) is identical except for
the zero. Where this reader gives 0.0, pandas gives an IBM zero as
5.397605346934028e-79, which is 16^-65.
