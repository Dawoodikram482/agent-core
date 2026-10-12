"""The package exposes its installed version."""

import re

import agent_core


def test_version_is_semantic() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", agent_core.__version__)
