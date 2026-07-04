"""CLI entrypoints."""

from cortexops.cli import cmd_version
from argparse import Namespace


def test_cli_eval():
    """Version command is wired and returns success."""
    assert cmd_version(Namespace()) == 0


def test_cli_main_importable():
    from cortexops.cli import main

    assert callable(main)
