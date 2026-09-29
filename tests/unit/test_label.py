from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from macroswap.config import load_config
from macroswap.diary.importer import import_directory
from macroswap.diary.stats import name_counts
from macroswap.match.label import (
    Label,
    draw_sample,
    label_ids,
    label_session,
    read_labels,
    suggestions,
    write_labels,
)
from macroswap.match.matcher import Encoder, Matcher
from macroswap.store import connect
from macroswap.usda.keys import FieldRules
from macroswap.usda.table import Row

CONFIG = load_config()
RULES = FieldRules(CONFIG.usda)


@pytest.fixture
def matcher(usda_rows: list[Row]) -> Matcher:
    return Matcher(usda_rows, CONFIG.match, RULES)


def test_sample_on_the_fixture_diary(tmp_path: Path, fixtures_dir: Path) -> None:
    """A seeded tail sample, each bucket split by its own shuffle. Head first,
    then by count and name, the order labeling runs in."""
    cfg = replace(CONFIG.labels, head_share=0.5, tail_size=4)
    with connect(tmp_path / "db.sqlite") as conn:
        import_directory(conn, fixtures_dir, CONFIG.diary)
        sample = draw_sample(name_counts(conn), cfg)
    assert [(s.name, s.bucket, s.split) for s in sample] == [
        ("egg whites", "head", "test"),
        ("kirkland - chicken breast", "head", "dev"),
        ("chipotle - chicken bowl", "head", "test"),
        ("fage - total 0% greek yogurt", "head", "test"),
        ("great value - jasmine rice", "tail", "test"),
        ("jennie-o - 93% lean ground turkey", "tail", "test"),
        ("pictsweet farms - sweet potatoes", "tail", "test"),
        ("quaker - old fashioned oats", "tail", "dev"),
    ]


def test_suggestions_merge_every_method_one_per_key_by_description(
    usda_rows: list[Row], fake_embedder: Encoder
) -> None:
    """One row per key, alphabetical by description, shown even when every
    method abstains: embed reaches the whey key through another row than
    lexical and hybrid do, and the key order differs from the description
    order. A key's row is the one leading by the tie order: for "banana ripe"
    lexical reaches the bananas key through an analytical duplicate, embed
    through the SR row."""
    abstaining = {"lexical": math.inf, "embed": math.inf}
    config = replace(CONFIG.match, no_match=abstaining)
    matcher = Matcher(usda_rows, config, RULES, fake_embedder)
    assert [hit.key for hit in suggestions(matcher, "protein powder")] == [
        "beverages, protein powder whey based / raw",
        "english muffins, plain, without calcium propionate(includes sourdough) / raw",
        "gelatins, dry powder, unsweetened / dry",
        "muffins, english, whole-wheat / raw",
        "cereals, oats, steel cut / raw",
        "pumpkin / raw",
    ]
    assert suggestions(matcher, "banana ripe")[0].row.id == "sr:173944"
    # Case folds: "Muffins, blueberry" leads "Muffins, English".
    muffins = [hit.row.id for hit in suggestions(matcher, "muffin")]
    assert muffins.index("sr:172765") < muffins.index("sr:172762")


def test_a_session_labels_by_suggestion_and_search(
    tmp_path: Path, usda_rows: list[Row], matcher: Matcher
) -> None:
    path = tmp_path / "labels.csv"
    write_labels(
        path,
        [
            Label("egg whites", 2, "head", "dev", "", ""),
            Label("ground beef", 1, "head", "test", "", ""),
            Label("pictsweet farms - sweet potatoes", 1, "tail", "dev", "", ""),
            Label("sweet potato", 1, "tail", "test", "", ""),
            Label("chipotle - chicken bowl", 1, "tail", "test", "", ""),
            Label("laura's lean 93/7 - ground beef", 1, "tail", "dev", "", ""),
            Label("potatoes", 1, "tail", "test", "", ""),
        ],
    )
    answers = _script(
        "1 1",  # Egg, white, raw, fresh: first by description, once
        "/bee",  # inside longer words; the first by description: Beef, ground
        "1",  # a name without a level labels the family
        "/sweet potatoes raw",  # Sweet potato, raw only once plurals fold
        "3",  # beyond the list: asked again
        "1",
        "1 2 3 4",  # more than three: asked again
        "3 4",  # baked and raw, two states: asked again
        "4 5",  # the SR and the Foundation raw sweet potato
        "chicken bowl",  # not a choice: asked again
        "/beverage",  # the first is "Beverages, almond milk": the sort folds case
        "1",
        "1 5",  # a family key beside a row: asked again
        "/beef ground 93",  # a name with a level labels the row at it
        "1",
        "/flesh skin",  # the potatoes offered, then the red ones only search found
        "1 2",
    )
    lines: list[str] = []
    cfg = replace(CONFIG.labels, search_limit=2)
    label_session(path, matcher, usda_rows, cfg, answers, lines.append)
    # A key the suggestions offered is a suggestion, however it was picked.
    labels = read_labels(path)
    assert [(s.label, s.label_source) for s in labels] == [
        ("sr:172183", "suggestion"),
        ("beef, ground", "suggestion"),
        ("sr:168482", "suggestion"),
        ("sr:168482 foundation:2346404", "suggestion"),
        ("sr:174832", "search"),
        ("sr:173110", "suggestion"),
        ("sr:170026 sr:170029", "suggestion"),
    ]
    # A family key and a derived id hold spaces of their own.
    assert label_ids(labels[3].label) == ["sr:168482", "foundation:2346404"]
    assert label_ids(labels[1].label) == ["beef, ground"]
    assert label_ids("sr:173110 derived:beef, ground:88/12") == [
        "sr:173110",
        "derived:beef, ground:88/12",
    ]
    assert "   1. Egg, white, raw, fresh" in lines
    assert (
        "   1. Beef, ground, 70% lean meat / 30% fat, raw  (family key: beef, ground)"
        in lines
    )
    assert "  21 match; the first 2 shown, add a word to narrow" in lines


def test_each_label_is_written_as_made_and_a_restart_continues(
    tmp_path: Path, usda_rows: list[Row], matcher: Matcher
) -> None:
    path = tmp_path / "labels.csv"
    write_labels(
        path,
        [
            Label("egg whites", 2, "head", "dev", "sr:172183", "suggestion"),
            Label("banana", 1, "head", "test", "", ""),
            Label("zzzz", 1, "tail", "test", "", ""),
        ],
    )
    lines: list[str] = []

    def session(*answers: str | BaseException) -> None:
        lines.clear()
        ask = _script(*answers)
        label_session(path, matcher, usda_rows, CONFIG.labels, ask, lines.append)

    # A crash after one label: that label is already on disk, and the columns
    # the session does not set are kept.
    with pytest.raises(RuntimeError):
        session("0", RuntimeError())
    assert [s.label for s in read_labels(path)] == ["sr:172183", "NO_MATCH", ""]
    assert path.read_text(encoding="utf-8").splitlines()[2] == (
        "banana,1,head,test,NO_MATCH,no_match"
    )
    # ctrl-C stops; the 0 after it is never read.
    session(KeyboardInterrupt(), "0")
    assert (lines[0], lines[-1]) == ("3 of 3  zzzz", "2 of 3 labeled")
    # q stops too.
    session("q", "0")
    assert (lines[0], lines[-1]) == ("3 of 3  zzzz", "2 of 3 labeled")
    # The end of input stops too, as ctrl-D or a closed pipe does.
    session()
    assert lines[-1] == "2 of 3 labeled"
    assert read_labels(path)[2].label == ""


def _script(*answers: str | BaseException) -> Callable[[str], str]:
    """Answers the prompts in order, raising any exception in its turn, then
    ends input as ctrl-D does."""
    queue = list(answers)

    def ask(prompt: str) -> str:
        answer = queue.pop(0) if queue else EOFError()
        if isinstance(answer, BaseException):
            raise answer
        return answer

    return ask
