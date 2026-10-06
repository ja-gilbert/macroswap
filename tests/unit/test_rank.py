from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from macroswap.config import SwapConfig
from macroswap.swap.fit import Macros
from macroswap.swap.rank import Candidate, DefaultLevel, FamilyRow, Target, rank, score
from macroswap.usda.table import Row

CONFIG = SwapConfig(
    fit_weights=Macros(3, 1, 1),
    rank_weights=Macros(48, 16, 81),
    serving_bounds_g=(5.0, 1000.0),
    serving_ratio=6.0,
    non_starchy_group="Vegetables and Vegetable Products",
    starchy_kcal_per_100g=50.0,
    tie_epsilon=10.0,
    popularity_floor=20,
    common_threshold=50,
    diary_window_days=90,
    top=10,
    staples={},
)
LEAN = Macros(20, 0, 0)
# Against this target a food at (20, 0, f) per 100 g scores about 9f.
TARGET = Target(LEAN, "egg white", None, frozenset({"protein"}))
SALMON = Target(
    Macros(20.42, 0.0, 13.42), "salmon", None, frozenset({"protein", "fat"})
)
TOFU = frozenset({"tofu"})
VEG = "Vegetables and Vegetable Products"


def row(
    family: str,
    per_100g: Macros = LEAN,
    *,
    variant: str = "",
    lean_pct: int | None = None,
    roles: str = "protein",
    row_id: str = "",
    category: str = "test",
    kcal: float = 0.0,
) -> Row:
    return Row(
        id=row_id or family,
        source="sr",
        ndb=None,
        description=family,
        category=category,
        family=family,
        variant=variant or family,
        lean_pct=lean_pct,
        provenance="sr-analytical",
        as_bought="raw",
        protein=per_100g.protein,
        carbs=per_100g.carbs,
        fat=per_100g.fat,
        fiber=0.0,
        sugars=None,
        kcal=kcal,
        roles=roles,
        exclusion_reason=None,
    )


def beef(lean_pct: int, protein: float, fat: float) -> Candidate:
    level = f"{lean_pct}/{100 - lean_pct}"
    per_100g = Macros(protein, 0.0, fat)
    return Candidate(
        row("beef", per_100g, variant=level, lean_pct=lean_pct, roles="protein,fat")
    )


BEEF = [beef(93, 20.85, 7.0), beef(85, 18.7, 15.0), beef(80, 17.17, 20.0)]


def families(rows: tuple[FamilyRow, ...]) -> list[str]:
    return [r.best.candidate.row.family for r in rows]


def test_score_prices_each_delta_in_kcal() -> None:
    """At 48, 16 and 81, the squares of 4, 4 and 9 kcal a gram with protein's
    counted three times, deltas of 1, -2 and 3 g score sqrt(48 + 64 + 729) = 29."""
    assert score(Macros(1, -2, 3), CONFIG.rank_weights) == pytest.approx(29)


def test_fit_weights_fit_the_serving_and_rank_weights_score_it() -> None:
    """Salmon for 100 g of chicken breast: 98.78 g, 2.33 g of protein short and
    10.64 g of fat over, which the rank weights price at 97.07."""
    chicken = Target(Macros(22.5, 0.0, 2.62), "chicken", None, frozenset({"protein"}))
    salmon = Candidate(row("salmon", SALMON.macros, roles="protein,fat"))
    best = rank(chicken, [salmon], CONFIG).common[0].best
    assert (best.fit.grams, best.score) == pytest.approx((98.78, 97.07), abs=0.01)


def test_a_family_is_offered_when_its_roles_share_a_pool_with_the_target() -> None:
    """A protein and fat target reaches a fat family, and a family whose roles
    reach protein though this row of it is nearly all carbs; rice, in starch
    alone, is left out and counted."""
    candidates = [
        Candidate(row("olive oil", Macros(0.0, 0.0, 100.0), roles="fat")),
        Candidate(row("beans", Macros(5.0, 60.0, 0.5), roles="protein,starch")),
        Candidate(row("rice", Macros(7.13, 79.95, 0.66), roles="starch")),
    ]
    ranking = rank(SALMON, candidates, CONFIG)
    assert (sorted(families(ranking.common)), ranking.filtered) == (
        ["beans", "olive oil"],
        {"no-shared-pool": 1},
    )


@pytest.mark.parametrize(
    ("variant", "variants", "offered", "filtered"),
    [
        pytest.param(
            "93/7", False, {("pork", False)}, {"own-family": 3}, id="family-left-out"
        ),
        pytest.param(
            "93/7",
            True,
            {("85/15", True), ("80/20", True), ("pork", False)},
            {"own-family": 1},
            id="other-variants-are-the-same-food",
        ),
        pytest.param(
            None,
            True,
            {("93/7", True), ("85/15", True), ("80/20", True), ("pork", False)},
            {},
            id="family-target-gets-every-variant",
        ),
    ],
)
def test_the_targets_own_family(
    variant: str | None,
    variants: bool,
    offered: set[tuple[str, bool]],
    filtered: dict[str, int],
) -> None:
    """The target's family is left out row by row; under variants its other
    variants come back as the same food, but never the target's own variant."""
    target = Target(Macros(20.85, 0.0, 7.0), "beef", variant, SALMON.pools)
    pork = Candidate(row("pork", Macros(16.88, 0.0, 21.19), roles="protein,fat"))
    ranking = rank(target, [*BEEF, pork], CONFIG, variants=variants)
    got = {
        (o.candidate.row.variant, o.same_food)
        for r in ranking.common
        for o in (r.best, *r.others)
    }
    assert (got, ranking.filtered) == (offered, filtered)


def test_a_serving_outside_the_bounds_is_left_out() -> None:
    """For 4 g of protein, foods of 80 g and 0.4 g protein per 100 g take exactly
    5 g and 1000 g, the bounds, and are offered; at 4 g and 2000 g they are not."""
    target = Target(Macros(4, 0, 0), "egg white", None, TARGET.pools)
    candidates = [Candidate(row(str(p), Macros(p, 0, 0))) for p in (100, 80, 0.4, 0.2)]
    ranking = rank(target, candidates, CONFIG)
    assert (sorted(families(ranking.common)), ranking.filtered) == (
        ["0.4", "80"],
        {"serving-bounds": 2},
    )


@pytest.mark.parametrize(
    ("variants", "others"),
    [
        pytest.param(False, [], id="one-offer-per-family"),
        pytest.param(True, ["c1", "a2"], id="other-variants-in-score-order"),
    ],
)
def test_a_family_is_one_row_led_by_its_best_variant(
    variants: bool, others: list[str]
) -> None:
    """Rows sharing a variant are one offer, the lower score, the earlier row on
    a tie: variant a is a2, at 6.3 to a1's 9, and b is b1, tied with b2."""
    fat = {"a1": 1.0, "b1": 0.5, "c1": 0.6, "a2": 0.7, "b2": 0.5}
    candidates = [
        Candidate(row("fish", Macros(20, 0, f), variant=row_id[0], row_id=row_id))
        for row_id, f in fat.items()
    ]
    (fish,) = rank(TARGET, candidates, CONFIG, variants=variants).common
    got = (fish.best.candidate.row.id, [o.candidate.row.id for o in fish.others])
    assert got == ("b1", others)


@pytest.mark.parametrize(
    ("default_levels", "lean_pct"),
    [
        pytest.param({"beef": DefaultLevel(80, "test")}, 80, id="best-elsewhere"),
        pytest.param({"beef": DefaultLevel(85, "test")}, None, id="best-at-the-level"),
        pytest.param(
            {"beef": DefaultLevel(70, "test")}, None, id="no-offer-at-the-level"
        ),
    ],
)
def test_default_level_is_offered_beside_a_best_at_another_level(
    default_levels: dict[str, DefaultLevel], lean_pct: int | None
) -> None:
    """Salmon is nearest 85/15 beef, then 93/7, then 80/20; the default level is
    found among every variant, not only those shown, and a level no offer is at
    gives none."""
    (family_row,) = rank(SALMON, BEEF, CONFIG, default_levels=default_levels).common
    level = family_row.default_level
    assert (None if level is None else level.candidate.row.lean_pct) == lean_pct


@pytest.mark.parametrize(
    ("default_levels", "reported", "shown"),
    [
        pytest.param({}, (0, 20), "near", id="the-most-reported-near-tie"),
        pytest.param({}, (0, 19), "closest", id="reported-by-fewer-than-the-floor"),
        pytest.param({}, (20, 20), "closest", id="reported-alike"),
        pytest.param(
            {"fish": DefaultLevel(90, "test")},
            (0, 20),
            "closest",
            id="a-leanness-family",
        ),
    ],
)
def test_a_family_shows_its_most_reported_variant_and_keeps_its_place(
    default_levels: dict[str, DefaultLevel], reported: tuple[int, int], shown: str
) -> None:
    """Fish's variants score 0, 10 and 11.0 and were reported by the two numbers
    given and by 900 participants. Near is shown when the floor, 20, reported
    it and fewer reported the closest, being exactly the epsilon, 10, from the
    closest; far is past it. Below the floor, reported alike, and for a
    leanness family always, the closest is shown. Either way fish keeps the
    place its closest gives it, so tofu, at 11.0, starts a second cluster;
    placed by near's 10, fish would tie with tofu and follow it, the less
    reported."""
    target = Target(Macros(20, 2.5, 0), "egg white", None, TARGET.pools)
    fatty = Macros(20, 0, 0.5)
    closest_reported, near_reported = reported
    fish = {
        "closest": (target.macros, closest_reported),
        "near": (LEAN, near_reported),
        "far": (fatty, 900),
    }
    candidates = [
        Candidate(row("fish", per_100g, variant=variant), 60, reported)
        for variant, (per_100g, reported) in fish.items()
    ]
    candidates.append(Candidate(row("tofu", fatty), 90))
    ranking = rank(
        target, candidates, CONFIG, default_levels=default_levels, variants=True
    )
    first, second = ranking.common
    got = [o.candidate.row.variant for o in (first.best, *first.others)]
    assert got == [shown, *(v for v in fish if v != shown)]
    assert second.best.candidate.row.family == "tofu"


def test_ties_cluster_on_their_first_score_and_order_by_popularity() -> None:
    """a to e score 0, 4.5, 8.1, 16.2 and 18.0. A family joins a cluster within
    epsilon, 10, of the cluster's first score, so d starts one though it is
    within epsilon of c; in each cluster the more popular family leads, an
    unknown popularity last."""
    fat = {"d": 1.8, "c": 0.9, "e": 2.0, "a": 0.0, "b": 0.5}
    popularity = {"d": 70, "c": None, "e": 80, "a": 60, "b": 90}
    candidates = [
        Candidate(row(f, Macros(20, 0, x)), popularity[f]) for f, x in fat.items()
    ]
    ranking = rank(TARGET, candidates, CONFIG)
    assert families(ranking.common) == ["b", "a", "c", "e", "d"]


def test_a_score_exactly_epsilon_past_the_first_joins_its_cluster() -> None:
    """Missing 2.5 g of carbs and nothing else scores sqrt(16 * 2.5^2) = 10, the
    epsilon, so the more popular family leads the exact match."""
    target = Target(Macros(20, 2.5, 0), "egg white", None, TARGET.pools)
    candidates = [
        Candidate(row("exact", target.macros), 60),
        Candidate(row("lean"), 90),
    ]
    ranking = rank(target, candidates, CONFIG)
    scores = {r.best.candidate.row.family: r.best.score for r in ranking.common}
    assert scores["lean"] - scores["exact"] == CONFIG.tie_epsilon
    assert families(ranking.common) == ["lean", "exact"]


@pytest.mark.parametrize(
    ("popularity", "asked", "outcome"),
    [
        pytest.param(
            None, {"new_only": True}, "common", id="new-only-keeps-a-new-family"
        ),
        pytest.param(50, {}, "common", id="at-the-common-threshold"),
        pytest.param(20, {}, "rest", id="at-the-floor"),
        pytest.param(19, {}, "below-floor", id="below-the-floor"),
        pytest.param(
            19, {"diary_families": TOFU}, "common diary", id="diary-family-is-common"
        ),
        pytest.param(
            50, {"diary_families": TOFU}, "common", id="a-diary-family-on-its-count"
        ),
        pytest.param(
            19, {"allowlist": TOFU}, "common allowlist", id="allowlisted-is-common"
        ),
        pytest.param(
            19,
            {"diary_families": TOFU, "allowlist": TOFU},
            "common diary",
            id="the-diary-before-the-allowlist",
        ),
        pytest.param(19, {"include_obscure": True}, "rest", id="include-obscure"),
        pytest.param(
            60,
            {"diary_families": TOFU, "new_only": True},
            "diary-family",
            id="new-only",
        ),
    ],
)
def test_where_a_family_lands(
    popularity: int | None, asked: dict[str, Any], outcome: str
) -> None:
    """A lone family lands in a tier or under the one reason it is left out. The
    floor and the common threshold each belong to the tier above them. A diary
    family is common at any popularity unless new_only leaves it out, and says
    so when its count alone would not make it; so is a family on the
    allowlist, and one in both says diary."""
    ranking = rank(TARGET, [Candidate(row("tofu"), popularity)], CONFIG, **asked)
    tiers = {"common": ranking.common, "rest": ranking.rest}
    landed = [f"{t} {r.common_by}".strip() for t, rows in tiers.items() for r in rows]
    assert [*landed, *ranking.filtered] == [outcome]


@pytest.mark.parametrize(
    ("top", "config", "common", "rest"),
    [
        pytest.param(3, CONFIG, ["a", "b"], ["c"], id="counts-across-both-tiers"),
        pytest.param(None, replace(CONFIG, top=1), ["a"], [], id="none-is-config-top"),
    ],
)
def test_top_counts_family_rows_in_output_order(
    top: int | None, config: SwapConfig, common: list[str], rest: list[str]
) -> None:
    """Equal scores, so popularity orders each tier: a and b common, c and d
    rest. The input runs least popular first, so a cut made before ordering
    keeps the wrong rows."""
    popularity = {"d": 25, "c": 30, "b": 80, "a": 90}
    candidates = [Candidate(row(f), p) for f, p in popularity.items()]
    ranking = rank(TARGET, candidates, config, top=top)
    assert (families(ranking.common), families(ranking.rest)) == (common, rest)


@pytest.mark.parametrize(
    ("candidate", "reason"),
    [
        pytest.param(
            Candidate(row("walnut oil", Macros(0, 0, 100), roles="fat"), 5),
            "no-shared-pool",
            id="no-pool-before-the-floor-and-the-bounds",
        ),
        pytest.param(
            Candidate(row("cress", Macros(3, 0, 0), category=VEG, kcal=11), 5),
            "below-floor",
            id="the-floor-before-the-vegetable-rule",
        ),
        pytest.param(
            Candidate(row("cress", Macros(3, 0, 0), category=VEG, kcal=11), 50),
            "non-starchy-vegetable",
            id="the-vegetable-rule-before-the-serving",
        ),
    ],
)
def test_a_row_left_out_for_several_reasons_counts_once_under_the_first(
    candidate: Candidate, reason: str
) -> None:
    """An obscure oil for a protein target shares no pool, is below the floor
    and fits at 0 g; it counts once, as sharing no pool. Cress at 11 kcal is a
    non-starchy vegetable needing 667 g, over six times the target's 100 g: it
    counts under the floor when few reported it, else under the vegetable
    rule."""
    target = Target(LEAN, "egg white", None, TARGET.pools, 100.0)
    assert rank(target, [candidate], CONFIG).filtered == {reason: 1}


@pytest.mark.parametrize(
    ("grams", "filtered"),
    [
        pytest.param(100.0, {"serving-ratio": 1}, id="over-the-ratio"),
        pytest.param(None, {}, id="a-target-with-no-weight-has-no-ratio"),
    ],
)
def test_a_serving_over_the_ratio_times_the_targets_grams_is_left_out(
    grams: float | None, filtered: dict[str, int]
) -> None:
    """20 g of protein from 100 g of a food takes 667 g of one at 3 g per 100
    g, more than six times the target's grams; a diary food on no row has no
    grams, and the ratio does not apply."""
    target = Target(LEAN, "egg white", None, TARGET.pools, grams)
    broth = Candidate(row("broth", Macros(3, 0, 0)))
    assert rank(target, [broth], CONFIG).filtered == filtered


@pytest.mark.parametrize(
    ("non_starchy", "offered", "filtered"),
    [
        pytest.param(
            False,
            ["peas", "potatoes", "squash"],
            {"non-starchy-vegetable": 3},
            id="under-the-kcal-line",
        ),
        pytest.param(
            True,
            ["lettuce", "peas", "potatoes", "squash"],
            {},
            id="a-non-starchy-target-lifts-the-rule",
        ),
    ],
)
def test_a_non_starchy_vegetable_family_is_left_out_unless_the_target_is_one(
    non_starchy: bool, offered: list[str], filtered: dict[str, int]
) -> None:
    """Lettuce's three rows have a median of 20 kcal, under the line of 50,
    where their mean, 55, is not; squash's two rows have a median of exactly
    50 and stay; peas have a row filed under Legumes, so the rule does not
    reach them; potatoes are 77. A target that is itself a non-starchy
    vegetable, boiled carrots say, turns the rule off for the swap."""
    kcal = {"lettuce": (15, 20, 130), "squash": (40, 60), "potatoes": (77,)}
    candidates = [
        Candidate(row(f, variant=f"{f} {k}", category=VEG, kcal=k))
        for f, kcals in kcal.items()
        for k in kcals
    ]
    for category in (VEG, "Legumes and Legume Products"):
        candidates.append(
            Candidate(row("peas", variant=category, category=category, kcal=42))
        )
    target = Target(LEAN, "carrots, drained", None, TARGET.pools, None, non_starchy)
    ranking = rank(target, candidates, CONFIG)
    assert (sorted(families(ranking.common)), ranking.filtered) == (offered, filtered)
