"""Copy the USDA test fixture out of the pulled releases, row by row, by fdc_id.

Run after `macroswap data pull`:  uv run python scripts/extract_usda_fixture.py
Every row is copied verbatim, never typed, so the fixture regenerates exactly
when a release changes. Each id says which rule it pins.
"""

from __future__ import annotations

import csv
from pathlib import Path

from macroswap.config import load_config
from macroswap.pull import release_dirs
from macroswap.usda.load import NUTRIENT_IDS

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "usda"
ROWS = {
    "sr_legacy": {
        "168652": "beef 70/30 anchor",
        "174037": "beef 75/25 anchor",
        "174036": "beef 80/20 anchor",
        "171796": "beef 85/15 anchor, program note in parentheses",
        "174030": "beef 90/10 anchor",
        "173110": "beef 93/7 anchor",
        "171790": "beef 95/5 anchor",
        "173111": "beef 97/3 anchor",
        "174493": "turkey 85/15 anchor, leanness split over two fields",
        "172850": "turkey 93/7 anchor",
        "172847": "turkey fat free anchor, enters as 99/1",
        "168372": "pork 84/16 anchor",
        "169190": "pork 96/4 anchor",
        "171077": "chicken breast skinless boneless, 'broiler or fryers' spelling",
        "171519": "rotisserie drumstick, the word in field three: chicken, rotisserie",
        "171477": "chicken breast meat only roasted: same variant, cooked",
        "171474": "chicken breast meat and skin: same family, other variant",
        "172385": "chicken thigh: other family",
        "171116": "ground chicken: single-row family, no leanness family",
        "168249": "pork tenderloin under 'pork, loin'",
        "168263": "pork loin chop, parenthetical cut note",
        "174763": "top sirloin choice, separable lean only",
        "171804": "top sirloin select: grade collides, trim stays in the variant",
        "173709": "tuna canned in water",
        "175159": "tuna fresh yellowfin",
        "171955": "cod: target of the Foundation alias",
        "175167": "salmon farmed",
        "173723": "canned sockeye spelled 'Salmon, sockeye': aliased into fish, salmon",
        "173734": "black beans dry",
        "175238": "black beans canned: macro variant",
        "173756": "chickpeas, commas inside parentheses",
        "172420": "lentils",
        "171269": "milk nonfat: its own family",
        "171265": "milk whole: its own family",
        "170894": "Greek yogurt plain nonfat",
        "170901": "Greek yogurt strawberry nonfat",
        "172183": "egg white",
        "171287": "whole egg",
        "172182": "cottage cheese",
        "173430": "butter: fat-pool foil",
        "172470": "peanut butter",
        "173177": "whey isolate under Beverages: allowlisted, aliased into 173180",
        "173180": "whey-based protein powder under Beverages: allowlisted",
        "172941": "sliced turkey breast under Luncheon Meats: allowlisted",
        "174612": "'Turkey, breast' spelling under Luncheon Meats: allowlisted",
        "173874": "sliced chicken breast under Luncheon Meats: allowlisted",
        "167536": "jerky under Snacks: allowlisted",
        "169599": "gelatin under Sweets: excluded",
        "169640": "honey under Sweets: excluded",
        "173647": "tap water: zero macros, but Beverages outranks",
        "175040": "baking soda: zero-macro",
        "168877": "rice raw",
        "169753": "rice cooked: cooked with a raw sibling",
        "169736": "pasta dry",
        "172688": "bread commercially prepared: a state field, not cooking",
        "174899": "bagel: kept",
        "175063": "english muffin: allowlisted past the muffin denial",
        "172762": "'Muffins, English' spelling: allowlisted by the inverted phrase",
        "172765": "blueberry muffin: denied in Baked Products",
        "172715": "cookies: denied in Baked Products",
        "167535": "flour tortilla: kept",
        "175036": "corn tortilla: kept",
        "170567": "almonds raw",
        "170158": "almonds dry roasted: cooked with a raw sibling",
        "173904": "oats dry",
        "173905": "oats cooked with water: cooked with a raw sibling",
        "168482": "sweet potato 'raw, unprepared': unprepared is not 'prepared'",
        "168483": "sweet potato baked flesh: cooked, and field one has a raw row",
        "170026": "potatoes flesh and skin: depth one",
        "170027": "potatoes russet: a raw variety collapsing into potatoes",
        "170032": "potato skin: a product form, kept out of the depth-one family",
        "170028": "potatoes white: depth one",
        "170029": "potatoes red: depth one",
        "167793": "apples fuji: depth one",
        "168204": "apples gala: depth one",
        "173944": "bananas",
        "171711": "blueberries",
        "169928": "peaches raw",
        "169112": "peaches canned: macro variant in field two",
        "169934": "peaches dried: dried fruit is its own family, apart from canned",
        "174421": "bison ground",
        "171445": "rotisserie chicken, BBQ: sold cooked, its own family, a candidate",
        "174908": "cornbread mix: 'muffin' only inside a parenthetical, kept",
        "175084": "Oreo cookie crumb topping: the deny word sits in field three",
        "171964": "haddock raw: clusters with cod in the report; depth two stays",
        "170000": "onions raw",
        "170004": "sauteed onions: cooked, and the fat that must not reach the pools",
        "169251": "mushrooms white: target of the mushroom alias",
        "169376": "'Mushroom, white' spelling: aliased into mushrooms",
        "175139": "sardines canned: no raw row, so outside the varietal spread",
        "170379": "broccoli raw: Foundation repeats it without an NDB",
    },
    "foundation": {
        "321360": "energy from Atwater general factors (2047); tomatoes at depth one",
        "321900": "energy from 1008 only; repeats SR broccoli: analytical-duplicate",
        "322559": "repeats SR nonfat milk: analytical-duplicate",
        "2727567": "negative carbs by difference, clamped to zero",
        "748608": "olive oil with no macros: incomplete-macros",
        "335433": "dry-basis carioca beans: dropped at load",
        "2747654": "Pacific cod: aliased into fish, cod",
        "2747673": "ahi tuna: aliased into fish, tuna",
        "2644282": "chickpeas with a parenthetical second field",
        "2644283": "lentils, dry: aliased into lentils",
        "790774": "bananas overripe: aliased into bananas",
        "790991": "bananas ripe: aliased into bananas",
        "2346397": "steel-cut oats: aliased into cereals, oats",
        "2346404": "orange-flesh sweet potatoes: Foundation-only, alias candidate",
        "334194": "canned tuna sharing SR's NDB: dropped",
        "2514743": "ground beef 90/10 sharing SR's NDB: dropped",
    },
}


def main() -> None:
    config = load_config()
    dirs = release_dirs(Path(config.paths.manifest), Path(config.paths.raw))
    for source, wanted in ROWS.items():
        src = dirs[source]
        dst = FIXTURE / src.name
        dst.mkdir(parents=True, exist_ok=True)
        ids = set(wanted)
        _copy(src, dst, "food.csv", fdc_id=ids)
        _copy(src, dst, f"{source}_food.csv", fdc_id=ids)
        _copy(src, dst, "food_nutrient.csv", fdc_id=ids, nutrient_id=NUTRIENT_IDS)
        _copy(src, dst, "food_category.csv")


def _copy(src: Path, dst: Path, name: str, **keep: set[str]) -> None:
    """Copy the rows whose every column named in keep holds one of its values;
    with no keep, every row is copied."""
    with (src / name).open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [r for r in reader if all(r[col] in keep[col] for col in keep)]
        header = reader.fieldnames or []
    with (dst / name).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
