"""The library surface, on the fixture store and the stand-in model."""

from __future__ import annotations

import math
import sqlite3
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import astuple
from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray

from macroswap import Food, Match, Matcher
from macroswap.match.diary import LabelError
from macroswap.match.embed import EmbedUnavailable
from macroswap.match.label import Label, write_labels
from macroswap.store import connect, write_usda
from macroswap.usda.table import Row

from .conftest import FakeEmbedder

EGG_WHITE = "sr:172183"
YOGURT = "sr:170894"


@pytest.fixture
def db(tmp_path: Path, usda_rows: list[Row]) -> Path:
    path = tmp_path / "db.sqlite"
    with connect(path) as conn:
        write_usda(conn, [astuple(r) for r in usda_rows])
    return path


class CountingEmbedder(FakeEmbedder):
    calls = 0

    def encode(self, texts: Sequence[str]) -> NDArray[np.float32]:
        self.calls += 1
        return super().encode(texts)


def test_importing_the_package_loads_no_model() -> None:
    """A caller pays for the model on first use, never at import."""
    code = (
        "import sys, macroswap; "
        "print([m for m in ('torch', 'sentence_transformers') if m in sys.modules])"
    )
    run = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert run.stdout.strip() == "[]"


@pytest.mark.usefixtures("pinned_config")
def test_match_many_encodes_every_name_in_one_call(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One call of the model for the names and one for the index, however
    many names, and one more only for names that stand on a family's default
    level; a name's match is the command's top hit, or None where it abstains,
    as a bare level with no food does."""
    embedder = CountingEmbedder()
    monkeypatch.setattr("macroswap.api.Embedder", lambda *args: embedder)
    matcher = Matcher(db, method="embed")
    first, second, missing = matcher.match_many(["Egg Whites, 5 large", "oats", "93/7"])
    assert embedder.calls == 2
    assert first is not None and (first.row_id, first.method) == (EGG_WHITE, "embed")
    assert first.score == pytest.approx(1.0)
    assert second is not None and second.family == "cereals, oats"
    assert missing is None
    assert matcher.match("Egg Whites, 5 large") == first
    assert embedder.calls == 3


@pytest.mark.usefixtures("pinned_config")
def test_a_label_wins_where_the_matcher_disagrees(db: Path, fixtures_dir: Path) -> None:
    """With a labels file a labeled name takes its label as `diary match`
    does, to a row, to NO_MATCH, or to a leanness family at its default level,
    even for a name the matcher cannot read; without one the matcher
    decides."""
    labeled = Matcher(db, "lexical", fixtures_dir / "labels.csv")
    plain = Matcher(db, "lexical")
    assert labeled.match("Egg Whites, 5 large") == Match(
        YOGURT, labeled.food(YOGURT).name, "yogurt, greek", None, "label"
    )
    unlabeled = plain.match("Egg Whites, 5 large")
    assert unlabeled is not None
    assert (unlabeled.row_id, unlabeled.method) == (EGG_WHITE, "lexical")
    assert unlabeled.score is not None and unlabeled.score > 0
    assert labeled.match("ground turkey") is None
    assert plain.match("ground turkey") is not None
    for name in ("ground beef", "95% 5%"):
        labeled_beef = labeled.match(name)
        assert labeled_beef is not None, name
        assert (labeled_beef.row_id, labeled_beef.method) == ("sr:171796", "label")


@pytest.mark.usefixtures("pinned_config")
def test_a_label_naming_no_row_is_refused(db: Path, tmp_path: Path) -> None:
    """As `diary match` refuses it, before the model loads."""
    path = tmp_path / "labels.csv"
    write_labels(path, [Label("egg whites", 1, "head", "dev", "sr:0", "search")])
    with pytest.raises(LabelError, match="naming no row"):
        Matcher(db, "lexical", path).match("oats")


@pytest.mark.usefixtures("pinned_config")
def test_a_leanness_family_without_a_level_stands_on_its_default(db: Path) -> None:
    """Ground beef is the family's configured 85/15 row, as a swap with no
    diary reads it; a typed level picks its own row."""
    matcher = Matcher(db, "lexical")
    plain, typed = matcher.match_many(["ground beef", "ground beef 93/7"])
    assert plain is not None and (plain.row_id, plain.family) == (
        "sr:171796",
        "beef, ground",
    )
    assert typed is not None and typed.row_id == "sr:173110"


@pytest.mark.usefixtures("pinned_config")
def test_fit_reproduces_the_check_value_and_refuses_a_row_without_macros(
    db: Path,
) -> None:
    """Five large egg whites, 165 g, fit 170.7 g of plain nonfat Greek yogurt;
    a row the table holds no macros for cannot be fitted."""
    matcher = Matcher(db, "lexical")
    egg = matcher.food(EGG_WHITE)
    assert egg == Food(
        EGG_WHITE, "Egg, white, raw, fresh", "egg, white", 52.0, 10.9, 0.73, 0.17, 0.71
    )
    yogurt = Match(
        YOGURT, "Yogurt, Greek, plain, nonfat", "yogurt, greek", None, "label"
    )
    fitted = matcher.fit(yogurt, 1.65 * 10.9, 1.65 * 0.73, 1.65 * 0.17)
    assert fitted.row_id == YOGURT
    assert fitted.grams == pytest.approx(170.7, abs=0.05)
    assert fitted.delta_protein_g == pytest.approx(
        170.7 * 0.1019 - 1.65 * 10.9, abs=0.01
    )
    deltas = (fitted.delta_protein_g, fitted.delta_carbs_g, fitted.delta_fat_g)
    assert fitted.residual == pytest.approx(
        math.sqrt(sum(w * d**2 for w, d in zip((48, 16, 81), deltas, strict=True)))
    )
    oil = Match("foundation:748608", "", "", None, "label")
    with pytest.raises(ValueError, match="foundation:748608 lacks protein, carbs, fat"):
        matcher.fit(oil, 1.0, 1.0, 1.0)


@pytest.mark.usefixtures("pinned_config")
def test_food_refuses_an_unknown_id(db: Path) -> None:
    with pytest.raises(KeyError):
        Matcher(db, "lexical").food("sr:0")


@pytest.mark.usefixtures("pinned_config")
def test_the_loader_closes_the_store(
    db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Read once and closed, whether the store is built, refused, or not a
    database at all: a connection left to the garbage collector is a
    ResourceWarning on 3.13, which a consumer's suite may run with warnings
    as errors."""
    unbuilt = tmp_path / "diary.sqlite"
    connect(unbuilt).close()
    text = tmp_path / "text.sqlite"
    text.write_text("not a database")
    opened: list[sqlite3.Connection] = []
    real = sqlite3.connect

    def tracked(path: Path) -> sqlite3.Connection:
        conn = real(path)
        opened.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", tracked)
    Matcher(db, "lexical").match("egg whites")
    with pytest.raises(FileNotFoundError):
        Matcher(unbuilt, "lexical").match("egg whites")
    with pytest.raises(sqlite3.DatabaseError):
        Matcher(text, "lexical").match("egg whites")
    assert len(opened) == 3
    for conn in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")


@pytest.mark.usefixtures("pinned_config")
def test_an_unbuilt_store_names_data_build(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="run `data build` first"):
        Matcher(tmp_path / "none.sqlite", "lexical").match("egg whites")


@pytest.mark.usefixtures("pinned_config")
def test_without_the_extra_the_embed_method_names_it(db: Path) -> None:
    """The unit tier runs as if the extra were missing."""
    with pytest.raises(EmbedUnavailable, match="uv sync --extra embed"):
        Matcher(db, "embed").match("egg whites")
