"""Rank USDA rows for a diary name or a typed food, or abstain (NO_MATCH).

The index is every non-derived row, exclusion_reason ignored, so NO_MATCH means
no USDA food is right, never that the right one was filtered out. Lexical and
embed rank by their own scores; hybrid fuses their ranks.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray
from rank_bm25 import BM25Okapi

from macroswap.config import MatchConfig
from macroswap.diary.normalize import (
    parse_leanness,
    parse_state,
    strip_leanness,
    tokens,
)
from macroswap.usda.keys import FieldRules, is_leanness_field
from macroswap.usda.table import Row


class Encoder(Protocol):
    """Unit vectors for texts: the pinned model, or a stand-in in tests."""

    def encode(self, texts: Sequence[str]) -> NDArray[np.float32]: ...

    def index_vectors(self, texts: Sequence[str]) -> NDArray[np.float32]: ...


@dataclass(frozen=True)
class Hit:
    row: Row
    score: float
    key: str


def index_text(description: str, rules: FieldRules, leanness: bool = False) -> str:
    """What the index reads for a row: its food fields, so "egg whites" ranks
    the raw row over the dried one and a typed "cooked" can reach a cooked row.
    A leanness family's row drops its leanness fields, which the variant key
    rewrites to NN/MM and the matcher applies through the family, so every
    levelled spelling of "ground beef" reaches the family's level row."""
    fields = rules.food_fields(description)
    if leanness:
        fields = [f for f in fields if not is_leanness_field(f)]
    return " ".join(fields)


def fuse(
    scores: Sequence[NDArray[np.floating]], lags: NDArray[np.int_], rrf_k: int
) -> NDArray[np.float64]:
    """Reciprocal rank fusion: each method ranks the rows it scores above zero,
    from 1 and in the order of its own hits, an equal score going to the row
    with the smaller lag and then to the index order, and a ranked row gains
    1 / (rrf_k + rank). An unscored row gains nothing, where a rank would come
    from the tie order alone."""
    fused = np.zeros(len(scores[0]))
    for s in scores:
        order = np.lexsort((lags, -s))
        ranked = order[s[order] > 0]
        fused[ranked] += 1 / (rrf_k + np.arange(1, len(ranked) + 1))
    return fused


class Matcher:
    """Ranks the index for a text by each method it can run."""

    def __init__(
        self,
        rows: list[Row],
        config: MatchConfig,
        rules: FieldRules,
        embedder: Encoder | None = None,
    ) -> None:
        self._config = config
        self._rules = rules
        self._leanness = {r.family for r in rows if r.lean_pct is not None}
        words = {
            r.id: tokens(
                index_text(r.description, rules, r.family in self._leanness),
                config.abbreviations,
            )
            for r in rows
        }
        # The tie order after the first-field count, which needs the text: a
        # candidate before an index-only row, an analytical duplicate last, then
        # the shorter index text, then SR before Foundation and the lower number
        # within a source.
        ordered = sorted(
            rows,
            key=lambda r: (
                r.exclusion_reason is not None,
                r.exclusion_reason == "analytical-duplicate",
                len(words[r.id]),
                r.source != "sr",
                int(r.id.partition(":")[2]) if r.source != "derived" else 0,
            ),
        )
        self._index = [r for r in ordered if r.source != "derived"]
        self._position = {r.id: i for i, r in enumerate(ordered)}
        self._words = words
        self._first = {
            r.id: set(tokens(rules.food_fields(r.description)[0], config.abbreviations))
            for r in rows
        }
        # A leanness family's row at a level is its plain "<family>, NN/MM" row.
        self._at_level: dict[tuple[str, int], Row] = {}
        for r in ordered:
            if r.lean_pct is not None and r.variant == _plain(r):
                self._at_level.setdefault((r.family, r.lean_pct), r)
        # A family's cooked rows, at a level for a leanness family: its plain
        # row first when it has one there, then the tie order.
        self._cooked: dict[tuple[str, int | None], list[Row]] = {}
        for r in sorted(ordered, key=lambda r: r.variant != _plain(r)):
            if r.as_bought == "cooked":
                self._cooked.setdefault((r.family, r.lean_pct), []).append(r)
        documents = [words[r.id] for r in self._index]
        self._bm25 = BM25Okapi(documents, b=config.bm25_b)
        self._rankers: dict[str, Callable[[str], list[Hit]]] = {"lexical": self.lexical}
        if embedder is not None:
            self._embedder = embedder
            # Each distinct text is encoded once, so rows sharing a text share a
            # vector and tie exactly, and the tie order decides as in BM25.
            texts = [" ".join(d) for d in documents]
            distinct, inverse = np.unique(texts, return_inverse=True)
            self._vectors = embedder.index_vectors(distinct.tolist())[inverse]
            self._rankers["embed"] = self.embed
            self._rankers["hybrid"] = self.hybrid
        self.methods = tuple(self._rankers)

    def lexical(self, text: str) -> list[Hit]:
        """BM25 over the index text; a row scoring zero is never a hit."""
        words, level, cooking = self._query(text)
        scores = self._bm25.get_scores(words)
        return self._hits(scores, self._lags(words), level, cooking)

    def embed(self, text: str) -> list[Hit]:
        """Cosine similarity between the text and each row's index text, both
        normalized the same way; a text with no words scores nothing."""
        words, level, cooking = self._query(text)
        return self._hits(self._cosines(words), self._lags(words), level, cooking)

    def hybrid(self, text: str) -> list[Hit]:
        """Lexical and embed fused by rank, so neither method's score scale
        counts; each ranking is whole, not cut at top_k."""
        return self._fused(text)[0]

    def rank(self, text: str, method: str) -> list[Hit]:
        """The method's hits, whatever its threshold."""
        return self._rankers[method](text)

    def run(self, text: str, method: str) -> list[Hit] | None:
        """The method's hits, or None for NO_MATCH: nothing scored, or the top
        score is below the method's threshold. A fused score is a function of
        ranks alone, so hybrid abstains only when its top row is, for each
        method, below its threshold or not scored by it."""
        if method == "hybrid":
            hits, abstains = self._fused(text)
            return None if abstains else hits
        hits = self.rank(text, method)
        if not hits or hits[0].score < self._config.no_match[method]:
            return None
        return hits

    def match_key(self, row: Row, level: int | None) -> str:
        """The identity a swap shows: variant and as-bought state, or the family
        alone for a leanness-family row not at the text's level."""
        if row.family in self._leanness and (level is None or row.lean_pct != level):
            return row.family
        return f"{row.variant} / {row.as_bought}"

    def _query(self, text: str) -> tuple[list[str], int | None, set[str]]:
        """The words a method compares, and the level and the text's cooking
        words, both applied through the family, for a name key: a counted diary
        name, or typed text through name_key. A cooking word stays among the
        words, as cooking fields stay in the index; every leanness family is
        ground meat, so a level adds "ground" to words that lack it."""
        words = tokens(strip_leanness(text), self._config.abbreviations)
        level = parse_leanness(text)
        if level is not None and words and "ground" not in words:
            words.append("ground")
        cooking = parse_state(text, self._rules.cooking_words, self._rules.state_fields)
        return words, level, cooking

    def tie_order(self, text: str) -> Callable[[Row], tuple[int, int]]:
        """How an exact score tie orders rows for the text: fewer first-field
        words missing from the text's words first, so potatoes lead potato
        bread for "potatoes", quinoa leads quinoa flour for "quinoa", and a
        salmon fish row, one word short, leads salmon fish oil, two short, for
        "salmon"; then the index order."""
        query = set(self._query(text)[0])
        return lambda row: (len(self._first[row.id] - query), self._position[row.id])

    def _lags(self, words: list[str]) -> NDArray[np.int_]:
        """Per index row, how many first-field words are not among the words:
        tie_order's first key, the index order being its second."""
        query = set(words)
        return np.array([len(self._first[r.id] - query) for r in self._index])

    def _cosines(self, words: list[str]) -> NDArray[np.floating]:
        """Each row's cosine with the words, a dot product of unit vectors; no
        words score zero everywhere rather than embed an empty string."""
        if not words:
            return np.zeros(len(self._vectors))
        query = self._embedder.encode([" ".join(words)])[0]
        # einsum, not @: BLAS spins its whole thread pool for one row of dot
        # products and starves the encoder, 120 ms against 12 ms per ranking on
        # 32 cores. The top five match @ on the real table except where @ breaks
        # a tie between rows sharing a vector.
        cosines: NDArray[np.floating] = np.einsum("ij,j->i", self._vectors, query)
        return cosines

    def _fused(self, text: str) -> tuple[list[Hit], bool]:
        """Hybrid's hits, and whether it abstains, as run says; its top row is
        the first by the fused score and the tie order."""
        words, level, cooking = self._query(text)
        lags = self._lags(words)
        lexical, embed = self._bm25.get_scores(words), self._cosines(words)
        fused = fuse([lexical, embed], lags, self._config.rrf_k)
        top = np.lexsort((lags, -fused))[0]
        no_match = self._config.no_match
        below = (lexical[top] <= 0 or lexical[top] < no_match["lexical"]) and (
            embed[top] <= 0 or embed[top] < no_match["embed"]
        )
        hits = self._hits(fused, lags, level, cooking)
        return hits, bool(below)

    def _hits(
        self,
        scores: NDArray[np.floating],
        lags: NDArray[np.int_],
        level: int | None,
        cooking: set[str],
    ) -> list[Hit]:
        """At most top_k distinct keys, by score and on an exact tie by
        tie_order, the lags then the index order. A leanness-family row not at
        the text's level stands for the family's row at that level, so a
        derived level is reached through its family; then, for a cooked text, a
        row in another state stands for one of its family's cooked rows at the
        level, taken plain row first and then by the tie order: the first whose
        index text holds every cooking word of the text, else the first, so
        "grilled chicken breast" reaches the grilled row, not the fried one
        ahead of it. Either stand-in is the row itself when the family has no
        such row."""
        hits: dict[str, Hit] = {}
        for i in np.lexsort((lags, -scores)):
            if scores[i] <= 0 or len(hits) == self._config.top_k:
                break
            row = self._index[i]
            if level is not None and row.lean_pct != level:
                row = self._at_level.get((row.family, level), row)
            if cooking and row.as_bought != "cooked":
                cooked = self._cooked.get((row.family, row.lean_pct), [row])
                held = (r for r in cooked if cooking.issubset(self._words[r.id]))
                row = next(held, cooked[0])
            key = self.match_key(row, level)
            hits.setdefault(key, Hit(row, float(scores[i]), key))
        return list(hits.values())


def _plain(row: Row) -> str:
    """The variant a row has with no field beyond its family and level."""
    if row.lean_pct is None:
        return row.family
    return f"{row.family}, {row.lean_pct}/{100 - row.lean_pct}"
