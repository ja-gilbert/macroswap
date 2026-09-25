"""Download the pinned USDA releases and refuse any whose checksum differs."""

from __future__ import annotations

import hashlib
import shutil
import tomllib
import urllib.request
import zipfile
from pathlib import Path


class PullError(ValueError):
    """A download does not match the manifest, or the manifest is unusable."""


def read_manifest(path: Path) -> dict[str, tuple[str, str]]:
    """Source name -> (url, sha256), from data/manifest.toml."""
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        return {name: (entry["url"], entry["sha256"]) for name, entry in raw.items()}
    except FileNotFoundError as exc:
        raise PullError(f"manifest not found: {path}") from exc
    except (tomllib.TOMLDecodeError, KeyError, TypeError) as exc:
        raise PullError(f"{path}: every source needs a url and a sha256") from exc


def release_dirs(manifest: Path, raw: Path) -> dict[str, Path]:
    """Where each source unpacks: a folder named after its archive."""
    return {
        name: raw / "usda" / Path(url.rsplit("/", 1)[-1]).stem
        for name, (url, _) in read_manifest(manifest).items()
    }


def pull(manifest: Path, raw: Path) -> list[str]:
    """Fetch each archive unless a verified copy is present, then unpack it."""
    target = raw / "usda"
    target.mkdir(parents=True, exist_ok=True)
    lines = []
    for name, (url, sha256) in read_manifest(manifest).items():
        archive = target / url.rsplit("/", 1)[-1]
        if archive.exists() and _sha256(archive) == sha256:
            state = "already present"
        else:
            partial = archive.with_name(archive.name + ".part")
            with (
                urllib.request.urlopen(url, timeout=120) as response,
                partial.open("wb") as out,
            ):
                shutil.copyfileobj(response, out)
            actual = _sha256(partial)
            if actual != sha256:
                partial.unlink()
                raise PullError(
                    f"{name}: downloaded sha256 {actual} is not the pinned {sha256}"
                )
            partial.replace(archive)
            state = "downloaded"
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(target)
        lines.append(f"{name}: {state}, {archive.name}")
    return lines


def _sha256(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()
