"""Numeric columns of a SAS transport (XPT) file, read with the standard
library: NHANES publishes its recall files in this format.

A transport file is 80-byte records: headers, one 140-byte NAMESTR per
variable giving its name, length and position in an observation, then the
observations back to back, blank-padded to a whole record.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

_RECORD = 80
_NAMESTR = 140
_NAMESTR_HEADER = b"HEADER RECORD*******NAMESTR HEADER RECORD!!!!!!!"
_OBS_HEADER = b"HEADER RECORD*******OBS     HEADER RECORD!!!!!!!"


def read_xpt(path: Path, columns: Sequence[str]) -> Iterator[tuple[float | None, ...]]:
    """Each observation's values for the named columns, in the order asked;
    a missing value is None."""
    raw = path.read_bytes()
    header = raw.index(_NAMESTR_HEADER)
    count = int(raw[header + 54 : header + 58])
    names = header + _RECORD
    fields: dict[str, tuple[int, int]] = {}
    width = 0
    for at in range(names, names + _NAMESTR * count, _NAMESTR):
        namestr = raw[at : at + _NAMESTR]
        length = int.from_bytes(namestr[4:6], "big")
        position = int.from_bytes(namestr[84:88], "big")
        fields[namestr[8:16].decode("ascii").strip()] = (position, length)
        width += length
    wanted = [fields[name] for name in columns]
    data = raw.index(_OBS_HEADER) + _RECORD
    for at in range(data, len(raw), width):
        row = raw[at : at + width]
        if not row.strip(b" "):
            break  # the blanks that pad the last record
        yield tuple(_ibm(row[p : p + n]) for p, n in wanted)


def _ibm(field: bytes) -> float | None:
    """An IBM hexadecimal float: a sign bit and a base-16 exponent in excess
    64, then a fraction of 14 hex digits. Zero is all zero bytes; any other
    first byte over a zero fraction is read as missing, which SAS writes as
    ".", "_" or a letter."""
    first, fraction = field[0], int.from_bytes(field[1:], "big")
    if fraction == 0:
        return None if first else 0.0
    sign = -1.0 if first & 0x80 else 1.0
    return sign * fraction * 16.0 ** ((first & 0x7F) - 64 - 14)
