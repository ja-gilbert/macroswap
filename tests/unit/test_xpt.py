from __future__ import annotations

import struct
from pathlib import Path

from macroswap.nhanes.xpt import read_xpt


def _record(text: str) -> bytes:
    return text.ljust(80).encode("ascii")


def _padded(data: bytes) -> bytes:
    return data + b" " * (-len(data) % 80)


def _transport(columns: list[str], rows: list[str]) -> bytes:
    """A transport file of 8-byte numeric columns; a row is its values' bytes
    in hex."""
    namestrs = b"".join(
        struct.pack(">hhhh8s68xl52x", 1, 0, 8, k + 1, name.ljust(8).encode(), 8 * k)
        for k, name in enumerate(columns)
    )
    return (
        _record(f"HEADER RECORD*******NAMESTR HEADER RECORD!!!!!!!{len(columns):010d}")
        + _padded(namestrs)
        + _record("HEADER RECORD*******OBS     HEADER RECORD!!!!!!!")
        + _padded(bytes.fromhex("".join(rows)))
    )


def test_reads_the_named_columns_of_each_observation(tmp_path: Path) -> None:
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
    path.write_bytes(_transport(["SEQN", "STATUS", "GRAMS"], rows))
    assert list(read_xpt(path, ("GRAMS", "SEQN", "STATUS"))) == [
        (0.1, 130378.0, 1.0),
        (-2.5, 0.0, None),
    ]
