"""Download the pinned sources and refuse any whose checksum differs."""

from __future__ import annotations

import hashlib
import shutil
import tomllib
import urllib.request
import zipfile
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path


class PullError(ValueError):
    """A download does not match the manifest, or the manifest is unusable."""


def packaged_manifest() -> Traversable:
    """The manifest shipped inside the package, beside the config, so the pull
    and the build run from an installed wheel in any directory."""
    return files("macroswap") / "manifest.toml"


def read_manifest(path: Traversable) -> dict[str, tuple[str, str]]:
    """Source name -> (url, sha256), from a manifest.toml."""
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        return {name: (entry["url"], entry["sha256"]) for name, entry in raw.items()}
    except FileNotFoundError as exc:
        raise PullError(f"manifest not found: {path}") from exc
    except (tomllib.TOMLDecodeError, KeyError, TypeError) as exc:
        raise PullError(f"{path}: every source needs a url and a sha256") from exc


def release_dirs(manifest: Traversable, raw: Path) -> dict[str, Path]:
    """Where each source lands: a folder named after its .zip, or the file itself."""
    return {
        name: raw / "usda" / url.rsplit("/", 1)[-1].removesuffix(".zip")
        for name, (url, _) in read_manifest(manifest).items()
    }


def pull(manifest: Traversable, raw: Path) -> list[str]:
    """Fetch each source unless a verified copy is present, and unpack each .zip."""
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
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(target)
        lines.append(f"{name}: {state}, {archive.name}")
    return lines


def _sha256(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()
