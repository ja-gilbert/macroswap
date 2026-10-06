"""Rewrite the numbers of docs/popularity.md from the committed popularity table.

Run after `macroswap data build --write-popularity`:
    uv run python scripts/render_popularity.py
CI runs it and fails on a diff, so the page, the table and CI agree.
"""

from __future__ import annotations

import json
from pathlib import Path

from macroswap.config import load_config
from macroswap.nhanes.page import render_page

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    config = load_config()
    page = ROOT / "docs" / "popularity.md"
    table = json.loads((ROOT / config.paths.popularity).read_text(encoding="utf-8"))
    rendered = render_page(page.read_text(encoding="utf-8"), table, config)
    page.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
