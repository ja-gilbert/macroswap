# Popularity

A swap leaves out foods almost nobody eats and lists ordinary foods first.
"Ordinary" is counted, not guessed: every food family carries the number
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
NHANES 2021-2023: 6,694 participants reported 905 families and 1,370 variants, 134,402 participant-family pairs in all.
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

One bread family, measured on 2026-10-06 against the table of commit
`a382034`, where every kind of bread was its own family. Since that day every
bread row bought as bread, not cooked or dried, is one family, `bread`, its
kinds the variants. The merge changed more than the key. FNDDS builds a
sandwich's bread as a blend of several bread rows, so before the merge no
single kind outweighed the filling and the filling won the rule above; as one
family the bread wins. `bread` went from 3,181 participants, the union of the
32 kinds that merged, to 3,709, and 44 FNDDS foods moved to it from their
fillings, 41 of them reported: the ham, turkey and peanut butter sandwiches,
the grilled cheese. The ten families that lost the most, before and after:
`ham, sliced` 369 to 132; `turkey breast, sliced` 344 to 123; `peanut butter`
728 to 512; `egg, whole` 2,381 to 2,326; `cheese, cheddar` 1,195 to 1,148;
`salami, dry or hard` 126 to 84; `beef, ground` 1,126 to 1,086; `bologna, meat
and poultry` 46 to 16; `roast beef, deli style` 30 to 4; `pepperoni, beef and
pork` 62 to 47. One offered family changed tier: `nuts, almond butter`, from
50 to 40, below the common threshold. `roast beef, deli style` fell below the
floor, but its category is left out by design, so no swap offered it at
either count. Nothing was added to the rule to put the numbers back: the
counts after the merge are the honest ones. A deli meat's count now means
the people who reported it outside a sandwich, or in one where the filling
outweighs the bread. Two sweet breads, pan dulce and the Salvadoran pound-cake
bread, key as `bread` and are denied as kinds by their own second field, so no
swap offers them; their reports still count toward `bread`, since counts follow
keys.

Aliases follow the same reading, measured on 2026-10-07 at commit `4c208a0`:
an alias is a key too, so a merged family's count is the count under the
merged key. It equals the union of the parts' counts unless the merge makes
the family the largest or tied-largest ingredient of some food, when it can
exceed it. Three families do: `chicken, thigh` 395 against a union of 392,
because in two mixed-part chicken foods the thigh and the dark-meat drumstick
folded into it together weigh as much as the breast, a tie the merge made;
`tomatoes` 1,942 against 1,937; and `grape juice, canned or bottled` 107
against 75, a family left out by design. Every other family equals its union.

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
  excludes on purpose, carries a word its category denies in the row's own
  two-field key, or names a part of a bird nobody plates: drinks, sweets,
  snacks, cakes,
  cookies, pies and pastries, fast food and restaurant dishes, mixed dishes,
  soups and sauces, sausages and lunch meats, spices, baby food; fruit
  juices, soy sauce, catsup, garlic, ginger and salad dressings, because
  condiments, dressings and juices are drinks and seasonings, not food swaps;
  flour, an ingredient and not a food on a plate; and poultry organs, skin,
  neck, back, feet and fat. These were never meant to be swaps, whatever
  their key says.
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
| left out by design | 423 | 58,202 | 43.3% |
| not reachable | 8 | 614 | 0.5% |
| other | 0 | 0 | 0.0% |
<!-- counts:end -->

What is left out by design is mostly drinks and sweets; its meat comes as
fast food and boxed dishes, not as a cut, and the grain it holds as a bag is
flour, left out as an ingredient. Its ten
largest categories, by pairs, a family counted under the category with the
most of the rows its reports came through and the first by name on a tie:

<!-- counts:by_design -->
| Category left out by design | Families | Pairs | Share of all pairs |
| --- | --- | --- | --- |
| Beverages | 65 | 20,363 | 15.2% |
| Sweets | 72 | 10,134 | 7.5% |
| Snacks | 41 | 5,648 | 4.2% |
| Baked Products | 62 | 4,082 | 3.0% |
| Fast Foods | 23 | 3,665 | 2.7% |
| Soups, Sauces, and Gravies | 30 | 2,669 | 2.0% |
| Fruits and Fruit Juices | 20 | 2,363 | 1.8% |
| Fats and Oils | 17 | 1,861 | 1.4% |
| Meals, Entrees, and Side Dishes | 25 | 1,393 | 1.0% |
| Cereal Grains and Pasta | 4 | 1,380 | 1.0% |
| all others | 64 | 4,644 | 3.5% |
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
| sausage, breakfast sausage | 36 |
| sweet potatoes, frozen as packaged | 36 |
| noodles, flat | 30 |
| sausage, turkey and pork | 13 |
| cereals ready-to-eat, wheat germ | 6 |
<!-- counts:end -->

## The floor and the common tier

A family below the floor is not offered. A family at or above the common
threshold is listed in the first tier. Both are absolute counts, frozen in
`macroswap.toml` for this cycle: `data build` refuses survey foods of another
cycle, so the two numbers never silently come to mean something else.

Four more rules decide what a swap offers, none of them a count, all of them
in `macroswap.toml`, and this page records them because they shape the lists
the counts order:

- **Starch and sugar are two pools.** A family's carbs are sugar when its
  candidate rows' sugars, summed over the rows that carry a sugars value, are
  at least half those rows' carbs, summed, and starch below that, so a bowl of
  rice is answered with potatoes and not with grapes. A family whose
  candidate rows carry no sugars value is starch.
  Measured on 2026-10-05 at commit `eb0943b`: 224 of the 894 carb-pool
  families have no sugars value, six of them at or above the floor, all
  starch in fact: chia seeds (64 participants), quinoa (50), gluten-free
  pasta (36), dry couscous (21), large lima beans (12) and yellow beans (10);
  the other 218 sit below the floor.
- **A serving is at most six times the target's grams.** The largest serving
  an accepted swap needs, measured on 2026-10-05 at commit `eb0943b` over the
  acceptance file, is 5.1 times (potatoes for white rice). A diary food
  matched to no USDA row has no grams, so it gets no serving cap, and the
  swap's header says so.
- **Non-starchy vegetables are not swaps.** A family of the Vegetables group
  whose candidate rows' median calories per 100 g fall below 50 is not
  offered for any target, whatever macro it is nearest, unless the target's
  own row is in that group and under the line; a target on no row keeps the
  rule on. The 50 is the dietary guidelines' line between
  starchy and non-starchy vegetables, measured on the table instead of
  listed. Measured on 2026-10-05 at commit `eb0943b`, medians of the family's
  candidate rows as bought: potatoes 76, sweet corn 76.5, sweet potato 91,
  yam 118, cassava 160 and taro 112 stay; carrots 36, onions 34, beets 43,
  winter squash 40 and mixed vegetables 49 drop; canned potatoes, at 60,
  stay; plantains sit in the Fruits group and are untouched; green peas have
  a row filed under Legumes and are outside the rule. 142 of the group's
  234 families fall below the line.
- **Denied words and parts.** The words named under "left out by design",
  matched on the row's own two-field key within their categories, under the
  alias where one names it, before the depth-one cut: `Flour, semolina`,
  keyed as `semolina` by its alias, is kept, and pan dulce is denied inside
  `bread`. An allow word in the
  description still wins, as `mayonnaise` does against `dressing` in Fats and
  Oils, and as `sausage`, `bratwurst` and `rice cakes` do against their
  categories. A poultry row whose description names a part nobody plates,
  heart, liver, gizzard, giblets, neck, back, feet, skin or separable fat, as
  one whole field, is left out whatever family it is folded into, so a
  turkey family shows its meat and not its heart.

<!-- counts:tiers -->
| Reported by at least | Families a swap can offer |
| --- | --- |
| any number | 1,351 |
| 1 | 474 |
| 10 (the floor) | 328 |
| 20 | 265 |
| 50 (the common tier) | 189 |
| 100 | 142 |
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
| fish, salmon | 378 |
| pork, loin | 415 |
| yogurt, greek | 505 |
| chicken, breast | 814 |
| beef, ground | 1,086 |
| cereals, oats | 1,335 |
| pasta, dry | 1,339 |
| bananas | 1,570 |
| rice, white | 1,609 |
| potatoes | 1,701 |
| egg, whole | 2,326 |
| bread | 3,709 |
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
| beef, ground | 1,086 | Ground beef | 178 | 6.10 |
| rice, white | 1,609 | Rice | 1,268 | 1.27 |
| egg, whole | 2,326 | Eggs and omelets | 2,237 | 1.04 |
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
