from __future__ import annotations

import pytest

from macroswap.config import load_config
from macroswap.usda.keys import FieldRules, family_key, variant_key

RULES = FieldRules(load_config().usda)


@pytest.mark.parametrize(
    ("description", "level", "expected"),
    [
        pytest.param(
            "Chicken, broiler or fryers, breast, skinless, boneless, meat only, raw",
            None,
            ("chicken, breast", "chicken, breast, meat only", "raw"),
            id="cosmetic-and-both-boilerplate-spellings",
        ),
        pytest.param(
            "Chicken, broilers or fryers, breast, meat only, cooked, roasted",
            None,
            ("chicken, breast", "chicken, breast, meat only", "cooked"),
            id="cooked-row-keeps-its-variant",
        ),
        pytest.param(
            "Chicken, broilers or fryers, breast, meat and skin, raw",
            None,
            ("chicken, breast", "chicken, breast, meat and skin", "raw"),
            id="skin-is-a-macro-variant",
        ),
        pytest.param(
            "Chicken, broiler, rotisserie, BBQ, breast, meat only",
            None,
            (
                "chicken, rotisserie",
                "chicken, rotisserie, bbq, breast, meat only",
                "cooked",
            ),
            id="sold-cooked-class-reads-cooked",
        ),
        pytest.param(
            "Beans, baked, canned, no salt added",
            None,
            ("beans, canned", "beans, canned", "canned"),
            id="canned-beats-a-cooking-field-before-it",
        ),
        pytest.param(
            "Plums, dried (prunes), stewed, without added sugar",
            None,
            ("plums, dried", "plums, dried, without added sugar", "cooked"),
            id="cooking-after-the-bought-state",
        ),
        pytest.param(
            "Fish, salmon, sockeye, cooked, dry heat",
            None,
            ("fish, salmon", "fish, salmon, sockeye, dry heat", "cooked"),
            id="dry-heat-is-not-dry",
        ),
        pytest.param(
            'Beef, top sirloin, steak, separable lean only, trimmed to 1/8" fat, '
            "select, raw",
            None,
            (
                "beef, top sirloin",
                "beef, top sirloin, steak, separable lean only",
                "raw",
            ),
            id="grade-collides-and-trim-stays",
        ),
        pytest.param(
            "Lamb, New Zealand, imported, frozen, leg, whole (shank and sirloin), "
            "separable lean only, raw",
            None,
            (
                "lamb, leg",
                "lamb, leg, whole (shank and sirloin), separable lean only",
                "raw",
            ),
            id="origin-is-boilerplate",
        ),
        pytest.param(
            "Beans, black, mature seeds, canned, low sodium",
            None,
            ("beans, black", "beans, black, canned", "canned"),
            id="canned-is-a-macro-variant",
        ),
        pytest.param(
            "Peaches, canned, heavy syrup pack, solids and liquids",
            None,
            (
                "peaches, canned",
                "peaches, canned, heavy syrup pack, solids and liquids",
                "canned",
            ),
            id="macro-variant-in-field-two-joins-the-family",
        ),
        pytest.param(
            "Cereals, oats, regular and quick, not fortified, dry",
            None,
            ("cereals, oats", "cereals, oats, regular and quick, dry", "dry"),
            id="dry-as-bought",
        ),
        pytest.param(
            "Sweet potato, raw, unprepared (Includes foods for USDA's Food "
            "Distribution Program)",
            None,
            ("sweet potato", "sweet potato", "raw"),
            id="unprepared-is-a-state",
        ),
        pytest.param(
            "Apples, frozen, unsweetened, unheated (Includes foods for USDA's Food "
            "Distribution Program)",
            None,
            ("apples", "apples, unsweetened, unheated", "raw"),
            id="unheated-is-not-heated-and-the-note-goes",
        ),
        pytest.param(
            "Bread, whole-wheat, commercially prepared",
            None,
            ("bread", "bread, whole-wheat", "raw"),
            id="commercially-prepared-is-a-state",
        ),
        pytest.param(
            "Beverage, instant breakfast powder, chocolate, not reconstituted",
            None,
            (
                "beverage, instant breakfast powder",
                "beverage, instant breakfast powder, chocolate",
                "raw",
            ),
            id="negated-cooking-word-is-a-state",
        ),
        pytest.param(
            "Tofu, raw, firm, prepared with calcium sulfate",
            None,
            ("tofu, firm", "tofu, firm", "raw"),
            id="coagulant-is-cosmetic",
        ),
        pytest.param(
            "Potatoes, russet, flesh and skin, raw",
            None,
            ("potatoes", "potatoes, russet, flesh and skin", "raw"),
            id="depth-one-family",
        ),
        pytest.param(
            "Potatoes, raw, skin",
            None,
            ("potatoes, skin", "potatoes, skin", "raw"),
            id="product-form-keeps-depth-two",
        ),
        pytest.param(
            "Potatoes, canned, drained solids",
            None,
            ("potatoes, canned", "potatoes, canned, drained solids", "canned"),
            id="depth-one-is-for-raw-rows",
        ),
        pytest.param(
            "Onions, spring or scallions (includes tops and bulb), raw",
            None,
            ("onions", "onions, spring or scallions (includes tops and bulb)", "raw"),
            id="depth-one-takes-scallions-into-onions",
        ),
        pytest.param(
            "Chickpeas (garbanzo beans, bengal gram), mature seeds, raw",
            None,
            ("chickpeas", "chickpeas", "raw"),
            id="comma-inside-parentheses",
        ),
        pytest.param(
            "Turkey, ground, 85% lean, 15% fat, raw",
            "85/15",
            ("turkey, ground", "turkey, ground, 85/15", "raw"),
            id="leanness-over-two-fields",
        ),
        pytest.param(
            "Turkey, ground, fat free, raw",
            "99/1",
            ("turkey, ground", "turkey, ground, 99/1", "raw"),
            id="fat-free-anchor-level",
        ),
    ],
)
def test_keys(
    description: str, level: str | None, expected: tuple[str, str, str]
) -> None:
    fields = RULES.fields(description)
    depth = RULES.depth(fields)
    family = family_key(fields, depth)
    variant = variant_key(family, fields, depth, level)
    assert (family, variant, fields.as_bought) == expected
