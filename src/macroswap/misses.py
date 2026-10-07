"""The known misses of the acceptance file, rendered into the README so the
limits it states are the ones the suite holds."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

_BLOCK = re.compile(r"(<!-- misses:begin -->\n).*?(<!-- misses:end -->)", re.DOTALL)


def render_misses(readme: str, entries: Iterable[Mapping[str, Any]]) -> str:
    """The README with the text between its misses markers replaced: one
    paragraph per entry, its reason and then its pairs grouped by source."""
    paragraphs = []
    for entry in entries:
        by_source: dict[str, list[str]] = defaultdict(list)
        for pair in entry["pairs"]:
            source, family = pair.split(": ", 1)
            by_source[source].append(family)
        offered = "; ".join(
            f"for {source}: " + ", ".join(f"`{family}`" for family in families)
            for source, families in by_source.items()
        )
        paragraphs.append(f"- {entry['why']}. Offered today {offered}.")
    body = "\n".join(paragraphs)
    rendered, found = _BLOCK.subn(lambda block: f"{block[1]}{body}\n{block[2]}", readme)
    if not found:
        raise ValueError("no <!-- misses:begin --> ... <!-- misses:end --> block")
    return rendered
