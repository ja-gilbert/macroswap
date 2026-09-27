"""The frozen embedder behind the `embed` extra: the pinned sentence-transformers
model on CPU, and the index's vectors cached beside the database.

Nothing here imports sentence-transformers until an Embedder is made, so the
package runs without the extra.
"""

from __future__ import annotations

import hashlib
import sys
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

# The model, tokenizer and pooling files; not the onnx/ and openvino/ exports.
_FILES = ["*.json", "*.txt", "model.safetensors"]


class EmbedUnavailable(RuntimeError):
    """The extra is not installed, or the pinned model is neither cached nor
    downloadable."""


class Embedder:
    """The pinned model, fetched on first use."""

    def __init__(self, model: str, revision: str, cache_dir: Path) -> None:
        try:
            import sentence_transformers
            import torch
            import transformers
            from huggingface_hub import snapshot_download
            from huggingface_hub.errors import LocalEntryNotFoundError
        except ImportError as exc:
            raise EmbedUnavailable(
                "embed extra not installed (uv sync --extra embed)"
            ) from exc
        pinned = f"{model}@{revision[:7]}"
        try:
            path = snapshot_download(
                model, revision=revision, allow_patterns=_FILES, local_files_only=True
            )
        except LocalEntryNotFoundError:
            print(f"downloading {pinned} (first use)", file=sys.stderr)
            try:
                path = snapshot_download(
                    model, revision=revision, allow_patterns=_FILES
                )
            except Exception as exc:
                # Offline, the Hub down, a revision gone: all leave no model.
                raise EmbedUnavailable(
                    f"{pinned} is not cached and did not download ({exc})"
                ) from exc
        # After the download, so a first use still shows its progress.
        transformers.utils.logging.disable_progress_bar()
        self._model = sentence_transformers.SentenceTransformer(path, device="cpu")
        self._cache_dir = cache_dir
        # Beside the texts, the key holds the model and these two versions; a
        # bump of transformers or tokenizers alone keeps the cached vectors.
        self._key = "\n".join(
            (model, revision, sentence_transformers.__version__, torch.__version__)
        )

    def encode(self, texts: Sequence[str]) -> NDArray[np.float32]:
        """One unit vector per text, so a dot product is the cosine."""
        vectors = self._model.encode(list(texts), normalize_embeddings=True)
        return np.asarray(vectors, dtype=np.float32)

    def index_vectors(self, texts: Sequence[str]) -> NDArray[np.float32]:
        """The texts' vectors, read from the cache while the texts and the key
        are unchanged; a new file replaces the old one."""
        key = "\n".join((self._key, *texts))
        digest = hashlib.sha256(key.encode()).hexdigest()
        path = self._cache_dir / f"embeddings-{digest}.npy"
        if not path.exists():
            vectors = self.encode(texts)
            for stale in self._cache_dir.glob("embeddings-*"):
                stale.unlink()
            # Renamed into place, so a cut-short write never leaves a bad cache.
            partial = path.with_name(path.name + ".part")
            with partial.open("wb") as out:
                np.save(out, vectors)
            partial.replace(path)
        cached: NDArray[np.float32] = np.load(path)
        return cached
