"""Rank USDA rows for a diary name or a typed food, or abstain (NO_MATCH).

The index is every non-derived row, exclusion_reason ignored, so NO_MATCH means
no USDA food is right, never that the right one was filtered out.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray
from rank_bm25 import BM25Okapi

from macroswap.config import MatchConfig
from macroswap.diary.normalize import parse_leanness, strip_leanness, tokens
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
        # On an equal score a candidate leads an excluded row, an analytical
        # duplicate comes last, then the lower id: an SR row beats the Foundation
        # row repeating it.
        ordered = sorted(
            rows,
            key=lambda r: (
                r.exclusion_reason is not None,
                r.exclusion_reason == "analytical-duplicate",
                r.id,
            ),
        )
        self._index = [r for r in ordered if r.source != "derived"]
        # A leanness family's row at a level is its plain "<family>, NN/MM" row.
        self._at_level: dict[tuple[str, int], Row] = {}
        for r in ordered:
            if (
                r.lean_pct is not None
                and r.variant == f"{r.family}, {r.lean_pct}/{100 - r.lean_pct}"
            ):
                self._at_level.setdefault((r.family, r.lean_pct), r)
        self._leanness = {family for family, _ in self._at_level}
        documents = [
            tokens(
                index_text(r.description, rules, r.family in self._leanness),
                config.abbreviations,
            )
            for r in self._index
        ]
        self._bm25 = BM25Okapi(documents)
        self._rankers: dict[str, Callable[[str], list[Hit]]] = {"lexical": self.lexical}
        if embedder is not None:
            self._embedder = embedder
            # Each distinct text is encoded once, so rows sharing a text share a
            # vector and tie exactly, and the index order decides as in BM25.
            texts = [" ".join(d) for d in documents]
            distinct, inverse = np.unique(texts, return_inverse=True)
            self._vectors = embedder.index_vectors(distinct.tolist())[inverse]
            self._rankers["embed"] = self.embed
        self.methods = tuple(self._rankers)

    def lexical(self, text: str) -> list[Hit]:
        """BM25 over the index text; a row scoring zero is never a hit."""
        words, level = self._query(text)
        return self._hits(self._bm25.get_scores(words), level)

    def embed(self, text: str) -> list[Hit]:
        """Cosine similarity between the text and each row's index text, both
        normalized the same way; a text with no words scores nothing."""
        words, level = self._query(text)
        if not words:
            return []
        query = self._embedder.encode([" ".join(words)])[0]
        # einsum, not @: BLAS spins its whole thread pool for one row of dot
        # products and starves the encoder, 120 ms against 12 ms per ranking on
        # 32 cores. The top five match @ on the real table except where @ breaks
        # a tie between rows sharing a vector.
        return self._hits(np.einsum("ij,j->i", self._vectors, query), level)

    def run(self, text: str, method: str) -> list[Hit] | None:
        """The method's hits, or None for NO_MATCH: nothing scored, or the top
        score is below the method's threshold."""
        hits = self._rankers[method](text)
        if not hits or hits[0].score < self._config.no_match[method]:
            return None
        return hits

    def match_key(self, row: Row, level: int | None) -> str:
        """The identity a swap shows: variant and as-bought state, or the family
        alone for a leanness-family row not at the text's level."""
        if row.family in self._leanness and (level is None or row.lean_pct != level):
            return row.family
        return f"{row.variant} / {row.as_bought}"

    def _query(self, text: str) -> tuple[list[str], int | None]:
        """The words a method compares and the level applied through the family,
        for a name key: a counted diary name, or typed text through name_key."""
        words = tokens(strip_leanness(text), self._config.abbreviations)
        return words, parse_leanness(text)

    def _hits(self, scores: NDArray[np.floating], level: int | None) -> list[Hit]:
        """At most top_k distinct keys. A leanness-family row not at the text's
        level stands for the family's row at that level, so a derived level is
        reached through its family and a cooked row at the level keeps its own
        identity."""
        hits: dict[str, Hit] = {}
        # A stable sort keeps the index order on an equal score.
        for i in np.argsort(-scores, kind="stable"):
            if scores[i] <= 0 or len(hits) == self._config.top_k:
                break
            row = self._index[i]
            if level is not None and row.lean_pct != level:
                row = self._at_level.get((row.family, level), row)
            key = self.match_key(row, level)
            hits.setdefault(key, Hit(row, float(scores[i]), key))
        return list(hits.values())
