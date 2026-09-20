from __future__ import annotations

import pytest

from macroswap.cli import main


def test_no_command_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    """Running with no command exits 2 and prints usage, not a traceback."""
    assert main([]) == 2
    assert "usage" in capsys.readouterr().err.lower()


def test_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
