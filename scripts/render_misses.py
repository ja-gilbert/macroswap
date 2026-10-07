"""Rewrite the README's known-misses block from the acceptance file.

Run after data/acceptance/swaps.toml changes:
    uv run python scripts/render_misses.py
CI runs it and fails on a README diff, so the README, the file and CI agree.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from macroswap.misses import render_misses

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    readme = ROOT / "README.md"
    swaps = ROOT / "data" / "acceptance" / "swaps.toml"
    entries = tomllib.loads(swaps.read_text(encoding="utf-8"))["known_misses"]
    rendered = render_misses(readme.read_text(encoding="utf-8"), entries)
    readme.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
