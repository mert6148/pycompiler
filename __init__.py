"""Tests for configuration loading in the bundled Flask tutorial example."""

from __future__ import annotations

import argparse
import ast
import keyword
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

def test_config():
    """Verify that the example app uses its default configuration."""
    from n.flask.examples.tutorial.flaskr import create_app

    assert not create_app().testing
    assert create_app({"TESTING": True}).testing

def test_config_override():
    """Verify that an explicit test configuration enables testing mode."""
    from n.flask.examples.tutorial.flaskr import create_app

    assert create_app({"TESTING": True}).testing
    assert not create_app().testing

def test_config_from_file(tmp_path: Path):
    """Verify configuration-file loading and its precedence over defaults.

    Args:
        tmp_path: Temporary directory fixture used for the configuration file.
    """
    from n.flask.examples.tutorial.flaskr import create_app

    config_file = tmp_path / "config.py"
    config_file.write_text("TESTING = True")
    assert create_app({"TESTING": False}).testing
    assert not create_app().testing
    assert create_app(config_file).testing