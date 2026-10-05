from __future__ import annotations

from pathlib import Path

from macroswap.nhanes.xpt import read_xpt


def test_the_day_one_recall_file_reads_whole(releases: dict[str, Path]) -> None:
    """Counted once beside pandas: 100,116 food rows, their food codes summing
    to 6,295,591,051,419."""
    rows = list(read_xpt(releases["nhanes_day1"], ("DR1IFDCD",)))
    assert len(rows) == 100116
    assert sum(code or 0.0 for (code,) in rows) == 6295591051419
