from __future__ import annotations

from dataclasses import replace

import pytest

from macroswap.config import load_config
from macroswap.usda.load import Food
from macroswap.usda.table import BuildError, Row, build_table

USDA = load_config().usda


@pytest.fixture
def rows(foods: list[Food]) -> dict[str, Row]:
    return {r.id: r for r in build_table(foods, USDA)}


EXCLUSION_CASES = {
    "cooked-rice": ("sr:169753", "cooked-with-raw-sibling"),
    "dry-roasted-almonds": ("sr:170158", "cooked-with-raw-sibling"),
    "oats-cooked-with-water": ("sr:173905", "cooked-with-raw-sibling"),
    "baked-sweet-potato-shares-field-one-with-raw": (
        "sr:168483",
        "cooked-with-raw-sibling",
    ),
    "bread-commercially-prepared": ("sr:172688", None),
    "rotisserie-sold-cooked": ("sr:171445", None),
    "rotisserie-in-field-three": ("sr:171519", None),
    "sauteed-onions": ("sr:170004", "cooked-with-raw-sibling"),
    "english-muffin-allowed-past-deny": ("sr:175063", None),
    "inverted-english-muffin-allowed": ("sr:172762", None),
    "tortilla": ("sr:167535", None),
    "muffin-denied": ("sr:172765", "excluded-category"),
    "cookies-denied": ("sr:172715", "excluded-category"),
    "deny-word-in-the-description-not-the-key": ("sr:175084", None),
    "deny-word-in-field-two-under-depth-one": ("sr:167935", "excluded-category"),
    "aliased-spelling-of-an-undenied-food": ("foundation:2003589", None),
    "juice-denied-on-the-key": ("sr:173041", "excluded-category"),
    "catsup-denied": ("sr:168556", "excluded-category"),
    "flour-denied": ("sr:169761", "excluded-category"),
    "dressing-denied": ("sr:173592", "excluded-category"),
    "mayonnaise-allowed-past-dressing": ("sr:171009", None),
    "turkey-heart-is-a-denied-part": ("sr:171484", "excluded-part"),
    "skin-light-and-dark-is-one-whole-field": ("sr:171482", "excluded-part"),
    "skinless-is-not-the-skin-field": ("sr:171077", None),
    "potato-skin-is-not-a-poultry-part": ("sr:170032", None),
    "deny-word-only-inside-a-parenthetical": ("sr:174908", None),
    "gelatin-in-sweets": ("sr:169599", "excluded-category"),
    "whey-allowed": ("sr:173177", None),
    "protein-powder-allowed": ("sr:173180", None),
    "sliced-turkey-allowed": ("sr:172941", None),
    "inverted-turkey-breast-is-deli-and-stays-out": ("sr:174612", "excluded-category"),
    "sliced-chicken-allowed": ("sr:173874", None),
    "jerky-allowed": ("sr:167536", None),
    "water-category-outranks-zero-macro": ("sr:173647", "excluded-category"),
    "baking-soda-zero-macro": ("sr:175040", "zero-macro"),
    "olive-oil-without-macros": ("foundation:748608", "incomplete-macros"),
    "foundation-broccoli-repeats-sr": ("foundation:321900", "analytical-duplicate"),
    "aliased-lentils-repeat-sr": ("foundation:2644283", "analytical-duplicate"),
    "aliased-cod-is-a-new-variant": ("foundation:2747654", None),
}


@pytest.mark.parametrize(
    ("row_id", "reason"), EXCLUSION_CASES.values(), ids=EXCLUSION_CASES.keys()
)
def test_exclusion_reason(
    rows: dict[str, Row], row_id: str, reason: str | None
) -> None:
    assert rows[row_id].exclusion_reason == reason


def test_cooked_candidates_key_as_first_field_plus_the_cooking_field(
    rows: dict[str, Row],
) -> None:
    """Both rotisserie spellings, the word in field two or three, land in one
    family that no raw row shares; derived rows read raw."""
    assert rows["sr:171445"].family == "chicken, rotisserie"
    assert rows["sr:171519"].family == "chicken, rotisserie"
    assert (
        rows["sr:171519"].variant
        == "chicken, rotisserie, drumstick, original seasoning, meat only"
    )
    assert rows["sr:171445"].as_bought == "cooked"
    assert rows["derived:beef, ground:88/12"].as_bought == "raw"


def test_depth_one_keeps_products_out_and_pools_come_from_candidates(
    rows: dict[str, Row],
) -> None:
    """A raw variety collapses into potatoes and potato skin does not; every
    kind of bread bought as bread is one family and a dry cornbread mix keeps
    its two fields; the sauteed onion keys as `onions, yellow`, a family with
    no candidate, so its fat reaches no pool."""
    assert rows["sr:170027"].family == "potatoes"
    assert rows["sr:170032"].family == "potatoes, skin"
    assert rows["sr:170027"].roles == "starch"
    assert rows["sr:174908"].family == "bread, cornbread"
    assert rows["sr:170004"].family == "onions, yellow"
    assert rows["sr:170004"].roles == ""


def test_key_reasons_outrank_the_category(foods: list[Food]) -> None:
    """analytical-duplicate and cooked-with-raw-sibling are decided at the key
    and lead the category rule, so the published counts do not depend on which
    excluded category a duplicate or cooked row sits in."""
    moved = {"foundation:321900": "Baby Foods", "sr:169753": "Fast Foods"}
    built = [replace(f, category=moved.get(f.id, f.category)) for f in foods]
    rows = {r.id: r for r in build_table(built, USDA)}
    assert rows["foundation:321900"].exclusion_reason == "analytical-duplicate"
    assert rows["sr:169753"].exclusion_reason == "cooked-with-raw-sibling"


def test_field_two_macro_variants_split_the_family(rows: dict[str, Row]) -> None:
    """Canned and dried fruit are different products from the raw one and from
    each other, so a field-two macro variant joins the family."""
    assert rows["sr:169928"].family == "peaches, yellow"
    assert rows["sr:169112"].family == "peaches, canned"
    assert rows["sr:169934"].family == "peaches, dried"


def test_derived_levels_interpolate_and_beef_is_formula_linear(
    rows: dict[str, Row],
) -> None:
    """Derived 88/12 lies on the 85/15 to 90/10 line, and dropping any interior
    beef anchor, its neighbours predict it within 0.1 g. Every row
    carries its provenance tag, and an anchor's level comes from config."""
    derived = rows["derived:beef, ground:88/12"]
    assert derived.protein == pytest.approx(19.436, abs=0.001)
    assert derived.fat == 12.0
    assert derived.provenance == "derived(85/15, 90/10)"
    assert rows["sr:168652"].provenance == "sr-formula"
    assert rows["sr:172850"].provenance == "sr-analytical"
    assert rows["foundation:2747654"].provenance == "foundation"
    assert rows["sr:172847"].variant == "turkey, ground, 99/1"
    beef = sorted(
        (
            r
            for r in rows.values()
            if r.source == "sr" and r.variant.startswith("beef, ground, ")
        ),
        key=lambda r: r.lean_pct or 0,
    )
    for a, mid, b in zip(beef, beef[1:], beef[2:], strict=False):
        t = ((mid.lean_pct or 0) - (a.lean_pct or 0)) / (
            (b.lean_pct or 0) - (a.lean_pct or 0)
        )
        for m in ("protein", "fat"):
            lo, hi = getattr(a, m), getattr(b, m)
            assert getattr(mid, m) == pytest.approx(lo + (hi - lo) * t, abs=0.1)


def test_roles_are_family_level_and_absent_without_usable_macros(
    foods: list[Food], rows: dict[str, Row]
) -> None:
    assert rows["sr:168652"].roles == "protein,fat", "70/30 joins protein via 97/3"
    assert rows["sr:172420"].roles == "protein,starch", "27% protein clears 0.25"
    assert rows["sr:171265"].roles == "sugar,fat", "fat leads only at 9 kcal/g"
    assert rows["sr:173430"].roles == "fat"
    cod = next(f for f in foods if f.id == "sr:171955")
    blank = replace(cod, id="sr:0", protein=None)
    with_blank = {r.id: r for r in build_table([*foods, blank], USDA)}
    assert with_blank["sr:171955"].roles == "protein"
    assert with_blank["sr:0"].roles == "", "no macro, no roles, whatever the family"


def test_a_familys_carbs_are_sugar_by_one_summed_share(foods: list[Food]) -> None:
    """Whole milk's 5.05 g of sugars in 4.8 g of carbs make it sugar; with no
    sugars value it is starch. Potatoes' four rows are 5% sugar; one of them
    made a 100 g all-sugar row carries the family past the cut when the shares
    are summed over grams, where a mean of the rows' own shares, 29%, would
    not; and a row with no sugars value, the white potato made 1,000 g of
    carbs, adds nothing to either sum."""
    by_id = {f.id: f for f in foods}
    changed = {
        "sr:171265": replace(by_id["sr:171265"], sugars=None),
        "sr:170027": replace(by_id["sr:170027"], carbs=100.0, sugars=100.0),
        "sr:170028": replace(by_id["sr:170028"], carbs=1000.0, sugars=None),
    }
    rows = {r.id: r for r in build_table([changed.get(f.id, f) for f in foods], USDA)}
    assert rows["sr:171265"].roles == "starch,fat"
    assert rows["sr:170026"].roles == "sugar"


def test_aliases_apply_to_any_source_and_stale_config_is_refused(
    foods: list[Food], rows: dict[str, Row]
) -> None:
    aliased = {
        "foundation:2747654": "fish, cod",
        "foundation:2747673": "fish, tuna",
        "foundation:2644283": "lentils",
        "foundation:790774": "bananas",
        "foundation:790991": "bananas",
        "foundation:2346397": "cereals, oats",
        "sr:169705": "cereals, oats",
    }
    assert {i: rows[i].family for i in aliased} == aliased
    assert rows["sr:173723"].family == "fish, salmon"
    assert rows["sr:169376"].family == "mushrooms"
    # The family changes; the row keeps its own name as its variant, unless it
    # restates an SR row, when it reads as that row.
    assert rows["foundation:2747654"].variant == "cod, pacific or alaskan, wild caught"
    assert rows["sr:173177"].variant == "beverages, whey protein powder isolate"
    assert rows["foundation:2644283"].variant == rows["sr:172420"].variant == "lentils"
    beef = USDA.leanness[0]
    unknown_anchor = replace(beef, anchors={**beef.anchors, "99999": "91/9"})
    for bad in (
        replace(USDA, family_aliases={"cod, atlantic": "fish, cod"}),
        replace(USDA, family_aliases={"cod, pacific or alaskan": "fish, hake"}),
        replace(USDA, family_aliases={"fish, cod": "fish, cod"}),
        replace(USDA, leanness=(unknown_anchor,)),
    ):
        with pytest.raises(BuildError):
            build_table(foods, bad)
