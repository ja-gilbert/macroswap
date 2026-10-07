from __future__ import annotations

import pytest

from macroswap.misses import render_misses

ENTRIES = [
    {
        "why": "cheese for a meat target: the fit is real",
        "pairs": [
            "salmon: cheese, cheddar",
            "tilapia: cheese, swiss",
            "salmon: cheese, swiss",
        ],
    },
    {"why": "soy foods where the plate does not fit", "pairs": ["salmon: soymilk"]},
]


def test_the_readme_block_is_one_paragraph_per_entry_grouped_by_source() -> None:
    """Each entry is its reason and then its pairs, grouped by source in the
    order the pairs first name them, however the pairs interleave; rendering
    again changes nothing, and a README without the block is refused."""
    readme = "# macroswap\n\n<!-- misses:begin -->\nold\n<!-- misses:end -->\n\nMore.\n"
    rendered = render_misses(readme, ENTRIES)
    assert rendered == (
        "# macroswap\n\n<!-- misses:begin -->\n"
        "- cheese for a meat target: the fit is real. Offered today for salmon: "
        "`cheese, cheddar`, `cheese, swiss`; for tilapia: `cheese, swiss`.\n"
        "- soy foods where the plate does not fit. Offered today for salmon: "
        "`soymilk`.\n"
        "<!-- misses:end -->\n\nMore.\n"
    )
    assert render_misses(rendered, ENTRIES) == rendered
    with pytest.raises(ValueError, match="misses:begin"):
        render_misses("# macroswap\n", ENTRIES)
