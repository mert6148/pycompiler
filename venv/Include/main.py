import time
import random
import string
from flask import Flask, jsonify, request
from flask_cors import CORS

class Config:
    """Load and access application settings stored in a YAML file.

    A file is loaded only when ``config_file`` is supplied. Loading parses the
    YAML content but does not call :meth:`validate_config` automatically.
    """

    def __init__(self, config_file: str = None):
        """Create an empty configuration, optionally loading a YAML file.

        Args:
            config_file: Optional path to the YAML configuration file.
        """
        self.config = {}
        if config_file:
            self.load_config(config_file)

    def load_config(self, config_file: str):
        """Parse a YAML file and replace the current configuration.

        Args:
            config_file: Path to the YAML file to read.

        Raises:
            OSError: If the file cannot be opened.
            yaml.YAMLError: If the file contains invalid YAML.
        """
        with open(config_file, 'r') as f:
            self.config = yaml.safe_load(f)

    def get(self, key: str, default=None):
        """Return a setting, or ``default`` when the key is absent.

        Args:
            key: Name of the setting to retrieve.
            default: Value to return when ``key`` is not present.
        """
        return self.config.get(key, default)

    """Class to handle the configuration of the application."""
    @staticmethod
    def validate_config(config: dict):
        """Check that configuration keys and top-level values are supported.

        Keys must be strings. Values must be strings, numbers, booleans,
        lists, or dictionaries. Values inside lists and dictionaries are not
        recursively checked.

        Args:
            config: Configuration mapping to validate.

        Raises:
            ValueError: If ``config`` is not a dictionary or contains a key
                or top-level value of an unsupported type.
        """
        if not isinstance(config, dict):
            raise ValueError("Configuration must be a dictionary.")
        for key, value in config.items():
            if not isinstance(key, str):
                raise ValueError(f"Configuration key '{key}' must be a string.")