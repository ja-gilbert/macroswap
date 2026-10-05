from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from macroswap.nhanes.xpt import read_xpt


def test_reads_the_named_columns_of_each_observation(
    tmp_path: Path, transport: Callable[[list[str], list[str]], bytes]
) -> None:
    """IBM floats typed by hand: 130378 is 0.1FD4A x 16^5, a tenth is
    0.1999... x 16^0, minus two and a half is the sign bit over 0.28 x 16^1.
    Zero is all zero bytes and a missing value is "." over zero bytes. Two
    rows of 24 bytes leave 32 blanks of padding, which are not one more
    observation."""
    rows = [
        "451FD4A000000000 4110000000000000 401999999999999A",
        "0000000000000000 2E00000000000000 C128000000000000",
    ]
    path = tmp_path / "tiny.xpt"
    path.write_bytes(transport(["SEQN", "STATUS", "GRAMS"], rows))
    assert list(read_xpt(path, ("GRAMS", "SEQN", "STATUS"))) == [
        (0.1, 130378.0, 1.0),
        (-2.5, 0.0, None),
    ]
