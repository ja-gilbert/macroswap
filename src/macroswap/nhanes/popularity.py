"""How many NHANES participants reported each food family.

An FNDDS survey food counts toward the family of its largest ingredient by
weight, nested recipes expanded and water set aside, and toward each family
when several tie for the largest; a participant counts once per family,
however often and on whichever day they reported it.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from macroswap.config import PopularityConfig, UsdaConfig
from macroswap.nhanes.xpt import read_xpt
from macroswap.usda.table import BuildError, Row, category_excluded

LINK_RULE = (
    "An FNDDS survey food counts toward the family of its largest ingredient by "
    "weight, nested recipes expanded and water set aside, and toward each family "
    "when several tie for the largest. A cooked key that a count_as line names "
    "counts toward that line's family. A participant counts once per family, on "
    "either recall day."
)

# The reasons that leave a row out for its key alone, when its category does not.
_KEY_REASONS = ("cooked-with-raw-sibling", "analytical-duplicate")
# Shares this close are a tie. FNDDS builds its unspecified foods as equal
# blends, and equal weights summed in different orders differ in the last bits.
_TIE = 1e-9


@dataclass(frozen=True)
class Attribution:
    """Where an FNDDS food counts: its families, more than one when they tie
    for the largest weight; the variants that carried the most of each; and
    the share of the food's weight that reached no row of the table."""

    families: frozenset[str]
    variants: frozenset[str]
    unattributed: float


@dataclass(frozen=True)
class Popularity:
    """The participants with a reliable recall, and how many of them reported
    each family and each variant."""

    participants: int
    families: dict[str, int]
    variants: dict[str, int]


@dataclass(frozen=True)
class Table:
    """The popularity table as committed: a metadata block, then how many
    participants reported each family and each variant. unattributed is the
    share of a reported food's weight that reached no row, averaged over the
    reports; offered_families is how many families a swap can offer; crosswalk
    holds, per family, a WWEIA category with the family's count and the
    category's; before_count_as is the count each family count_as names had on
    its own; not_offered says, in the table's words, why the rows of a counted
    family without a candidate are left out. Each of those families is also
    filed once, by the rows its reports came through: by_design holds the ones
    whose every such row a category or a denied word leaves out, whatever
    reason the row carries, with the category holding the most of those rows,
    the first by name on a tie; not_reachable the ones with such a row left
    out for its key alone. A row no report came through decides nothing."""

    cycle: str
    participants: int
    link_rule: str
    unattributed: float
    offered_families: int
    crosswalk: dict[str, tuple[str, int, int]]
    families: dict[str, int]
    variants: dict[str, int]
    before_count_as: dict[str, int]
    not_offered: dict[str, str]
    by_design: dict[str, str]
    not_reachable: tuple[str, ...]


def measure(
    fndds: Path,
    recalls: Sequence[Path],
    rows: Sequence[Row],
    config: PopularityConfig,
    usda: UsdaConfig,
) -> Table:
    """The table from a pulled FNDDS release and the recall files of its
    cycle, day one first. A reported food code the release lacks is refused:
    the recall files and the release are not one cycle. So is a crosswalk line
    naming a family the table lacks or a category no survey food is filed
    under."""
    recipes = load_recipes(fndds, config.cycle)
    attributions = attribute(recipes, rows, config.water_families, config.count_as)
    categories = load_categories(fndds)
    reasons: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        reasons[row.family].add(row.exclusion_reason or "")
    if stale := [
        f"{family} -> {category}"
        for family, category in config.crosswalk.items()
        if family not in reasons or category not in categories.values()
    ]:
        raise BuildError(f"crosswalk no longer fits the data: {stale}")
    reports = [
        report
        for day, path in enumerate(recalls, start=1)
        for report in reliable_reports(path, day)
    ]
    if unknown := {code for _, code in reports} - attributions.keys():
        raise BuildError(
            f"{fndds.name} lacks {len(unknown)} of the food codes the recall files "
            f"report, {min(unknown)} among them: the recall files are not of its cycle"
        )
    counts = count(reports, attributions)
    unmapped = attribute(recipes, rows, config.water_families, {})
    before = count(reports, unmapped).families
    eaters: dict[str, set[int]] = defaultdict(set)
    for participant, code in reports:
        eaters[categories[code]].add(participant)
    lost = sum(attributions[code].unattributed for _, code in reports)
    reported = _reported_rows(reports, recipes, rows, attributions)
    designed, keyed = file_left_out(reported, usda)
    not_offered = {
        family: "; ".join(sorted(reasons[family]))
        for family in sorted(counts.families)
        if "" not in reasons[family]
    }
    return Table(
        cycle=config.cycle,
        participants=counts.participants,
        link_rule=LINK_RULE,
        unattributed=round(lost / len(reports), 6),
        offered_families=sum("" in found for found in reasons.values()),
        crosswalk={
            family: (category, counts.families.get(family, 0), len(eaters[category]))
            for family, category in config.crosswalk.items()
        },
        families=dict(sorted(counts.families.items())),
        variants=dict(sorted(counts.variants.items())),
        before_count_as={
            family: before.get(family, 0)
            for family in sorted({*config.count_as, *config.count_as.values()})
        },
        not_offered=not_offered,
        by_design={
            family: designed[family] for family in not_offered if family in designed
        },
        not_reachable=tuple(family for family in not_offered if family in keyed),
    )


def write_table(path: Path, table: Table) -> None:
    """One value to a line, so a changed count is a one-line diff."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(asdict(table), indent=1, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def load_categories(folder: Path) -> dict[str, str]:
    """Each FNDDS food code with the name of its WWEIA food category."""
    with (folder / "wweia_food_category.csv").open(newline="", encoding="utf-8") as f:
        names = {
            r["wweia_food_category"]: r["wweia_food_category_description"]
            for r in csv.DictReader(f)
        }
    with (folder / "survey_fndds_food.csv").open(newline="", encoding="utf-8") as f:
        return {
            r["food_code"]: names[r["wweia_category_number"]] for r in csv.DictReader(f)
        }


def load_recipes(folder: Path, cycle: str) -> dict[str, list[tuple[str, float]]]:
    """Each FNDDS food code with its ingredients as (code, grams); an
    ingredient's code is an NDB number or another FNDDS food's code. A release
    whose foods are dated to other survey years than the cycle's is refused."""
    with (folder / "survey_fndds_food.csv").open(newline="", encoding="utf-8") as f:
        survey = list(csv.DictReader(f))
    years = {f"{r['start_date'][:4]}-{r['end_date'][:4]}" for r in survey}
    if years != {cycle}:
        raise BuildError(
            f"{folder.name} covers {', '.join(sorted(years))}, not {cycle}, the "
            "[popularity] cycle in macroswap.toml that the popularity floor and the "
            "common threshold were read from"
        )
    codes = {r["fdc_id"]: r["food_code"] for r in survey}
    recipes: dict[str, list[tuple[str, float]]] = {c: [] for c in codes.values()}
    with (folder / "input_food.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ingredient = (r["sr_code"], float(r["gram_weight"]))
            recipes[codes[r["fdc_id"]]].append(ingredient)
    return recipes


def reliable_reports(path: Path, day: int) -> Iterator[tuple[int, str]]:
    """(participant, food code) for every food row of a reliable recall."""
    columns = ("SEQN", f"DR{day}DRSTZ", f"DR{day}IFDCD")
    for participant, status, code in read_xpt(path, columns):
        if status == 1 and participant is not None and code is not None:
            yield int(participant), str(int(code))


def attribute(
    recipes: Mapping[str, Sequence[tuple[str, float]]],
    rows: Sequence[Row],
    water: Collection[str],
    count_as: Mapping[str, str],
) -> dict[str, Attribution]:
    """Each FNDDS food's families: the heaviest among its ingredients' families
    outside water, every one of them when several tie, or water when the food
    is all water. A family in count_as then counts as its target. A food none
    of whose weight reaches a row counts nowhere, all of it unattributed."""
    known = {r.family for r in rows}
    candidates = {r.family for r in rows if r.exclusion_reason is None}
    stale = [
        f"{source} -> {target}"
        for source, target in count_as.items()
        if target in count_as or source not in known or target not in candidates
    ]
    if stale:
        raise BuildError(f"count_as no longer fits the data: {stale}")
    by_ndb = {r.ndb: r for r in rows if r.ndb}
    attributions = {}
    for code in recipes:
        shares = _shares(code, recipes, by_ndb, ())
        weights: dict[str, float] = defaultdict(float)
        carried: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for row, share in shares.items():
            if row is not None:
                weights[row.family] += share
                carried[row.family][row.variant] += share
        families = _heaviest(
            {f: w for f, w in weights.items() if f not in water} or weights
        )
        variants = {
            variant for family in families for variant in _heaviest(carried[family])
        }
        attributions[code] = Attribution(
            frozenset(count_as.get(family, family) for family in families),
            frozenset(variants),
            shares.get(None, 0.0),
        )
    return attributions


def count(
    reports: Iterable[tuple[int, str]], attributions: Mapping[str, Attribution]
) -> Popularity:
    """Distinct participants: all of them, then per family and per variant."""
    everyone: set[int] = set()
    families: dict[str, set[int]] = defaultdict(set)
    variants: dict[str, set[int]] = defaultdict(set)
    for participant, code in reports:
        everyone.add(participant)
        for family in attributions[code].families:
            families[family].add(participant)
        for variant in attributions[code].variants:
            variants[variant].add(participant)
    return Popularity(
        len(everyone),
        {family: len(people) for family, people in families.items()},
        {variant: len(people) for variant, people in variants.items()},
    )


def file_left_out(
    reported: Iterable[Row], usda: UsdaConfig
) -> tuple[dict[str, str], set[str]]:
    """How the families of these rows are filed where no swap offers them: the
    ones whose every row a category or a denied word leaves out, each with the
    category holding the most of the rows, the first by name on a tie; and the
    ones with a row left out for its key alone."""
    filed: dict[str, Counter[str]] = defaultdict(Counter)
    spared: set[str] = set()
    keyed: set[str] = set()
    for row in reported:
        if category_excluded(row, row.family, usda):
            filed[row.family][row.category] += 1
        else:
            spared.add(row.family)
            if row.exclusion_reason in _KEY_REASONS:
                keyed.add(row.family)
    by_design = {
        family: max(sorted(categories), key=categories.__getitem__)
        for family, categories in filed.items()
        if family not in spared
    }
    return by_design, keyed


def _reported_rows(
    reports: Iterable[tuple[int, str]],
    recipes: Mapping[str, Sequence[tuple[str, float]]],
    rows: Sequence[Row],
    attributions: Mapping[str, Attribution],
) -> set[Row]:
    """The rows some report came through: each row in a reported food whose
    family the food counts toward."""
    by_ndb = {r.ndb: r for r in rows if r.ndb}
    return {
        row
        for code in {code for _, code in reports}
        for row in _shares(code, recipes, by_ndb, ())
        if row is not None and row.family in attributions[code].families
    }


def _heaviest[K](weights: Mapping[K, float]) -> list[K]:
    """The keys at the largest weight: one, every key that ties for it, or
    none when there is no weight to compare."""
    top = max(weights.values(), default=0.0)
    return [key for key, weight in weights.items() if top - weight <= _TIE]


def _shares(
    code: str,
    recipes: Mapping[str, Sequence[tuple[str, float]]],
    by_ndb: Mapping[str, Row],
    above: tuple[str, ...],
) -> dict[Row | None, float]:
    """The share of an FNDDS food's weight each table row carries, nested
    recipes expanded. None holds what reaches no row: an ingredient the table
    lacks, a recipe that contains itself, or a food with no weight at all."""
    parts = recipes[code]
    total = sum(grams for _, grams in parts)
    if not total:
        return {None: 1.0}
    inside = (*above, code)
    shares: dict[Row | None, float] = defaultdict(float)
    for child, grams in parts:
        if child in recipes and child not in inside:
            for row, share in _shares(child, recipes, by_ndb, inside).items():
                shares[row] += share * grams / total
        else:
            shares[by_ndb.get(child)] += grams / total
    return shares
