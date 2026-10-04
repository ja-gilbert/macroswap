from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from macroswap.cli import main
from macroswap.pull import PullError, pull, release_dirs


def _served(tmp_path: Path, sha256: str | None = None) -> tuple[Path, Path]:
    """A one-file release archive behind a file:// URL, and its manifest."""
    archive = tmp_path / "srv" / "release_csv_2026-01.zip"
    archive.parent.mkdir()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("release_csv_2026-01/food.csv", "fdc_id\n1\n")
    digest = sha256 or hashlib.sha256(archive.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.toml"
    manifest.write_text(
        f'[sr_legacy]\nurl = "{archive.as_uri()}"\nsha256 = "{digest}"\n',
        encoding="utf-8",
    )
    return manifest, tmp_path / "raw"


def test_pull_verifies_unpacks_and_skips_only_a_verified_copy(tmp_path: Path) -> None:
    manifest, raw = _served(tmp_path)
    downloaded = ["sr_legacy: downloaded, release_csv_2026-01.zip"]
    assert pull(manifest, raw) == downloaded
    assert pull(manifest, raw) == [
        "sr_legacy: already present, release_csv_2026-01.zip"
    ]
    assert (release_dirs(manifest, raw)["sr_legacy"] / "food.csv").exists()
    (raw / "usda" / "release_csv_2026-01.zip").write_bytes(b"truncated")
    assert pull(manifest, raw) == downloaded


def test_a_source_that_is_not_an_archive_stays_a_file(tmp_path: Path) -> None:
    """A recall file is verified but never unpacked, and a second pull finds it."""
    recall = tmp_path / "srv" / "DR1IFF_L.xpt"
    recall.parent.mkdir()
    recall.write_bytes(b"HEADER RECORD")
    digest = hashlib.sha256(recall.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.toml"
    manifest.write_text(
        f'[nhanes_day1]\nurl = "{recall.as_uri()}"\nsha256 = "{digest}"\n',
        encoding="utf-8",
    )
    raw = tmp_path / "raw"
    assert pull(manifest, raw) == ["nhanes_day1: downloaded, DR1IFF_L.xpt"]
    assert release_dirs(manifest, raw)["nhanes_day1"].read_bytes() == b"HEADER RECORD"
    assert pull(manifest, raw) == ["nhanes_day1: already present, DR1IFF_L.xpt"]


def test_checksum_mismatch_is_refused_and_leaves_no_file(tmp_path: Path) -> None:
    manifest, raw = _served(tmp_path, sha256="0" * 64)
    with pytest.raises(PullError, match="is not the pinned"):
        pull(manifest, raw)
    assert list((raw / "usda").iterdir()) == []


def test_checksum_mismatch_is_exit_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest, _ = _served(tmp_path, sha256="0" * 64)
    (tmp_path / "data").mkdir()
    manifest.rename(tmp_path / "data" / "manifest.toml")
    monkeypatch.chdir(tmp_path)
    assert main(["data", "pull"]) == 2
    assert "is not the pinned" in capsys.readouterr().err
