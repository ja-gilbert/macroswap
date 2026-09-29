"""Rewrite the README's eval block from the committed expected table.

Run after `macroswap match eval --write-expected`:
    uv run python scripts/render_eval.py
CI runs it and fails on a README diff, so the README, the table and CI agree.
"""

from __future__ import annotations

from pathlib import Path

from macroswap.config import load_config
from macroswap.match.evaluate import read_expected, render_readme

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    readme = ROOT / "README.md"
    cells = read_expected(ROOT / load_config().paths.eval_expected)
    rendered = render_readme(readme.read_text(encoding="utf-8"), cells)
    readme.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
