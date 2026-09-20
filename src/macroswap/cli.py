"""Command-line entry point. Exit codes: 0 success, 1 no match, 2 usage or data."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog="macroswap", description="Macro-equivalent food swaps."
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    # No sub-commands exist yet, so every invocation will be a usage error
    parser.print_usage(sys.stderr)
    return 2
