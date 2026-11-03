"""Python runtime and YAML configuration helpers for the application."""

import os
import sysconfig
import re
import yaml

def get_python_version():
    """Return the Python version configured for the running interpreter."""
    version = sysconfig.get_python_version()
    return version

def get_python_executable():
    """Return the conventional executable path for the running Python.

    The path is assembled from the interpreter's configured binary directory
    and version. If the interpreter configuration has no binary directory,
    return ``None``.
    """
    executable = sysconfig.get_config_var("BINDIR")
    if executable:
        return os.path.join(executable, "python" + get_python_version())
    return None

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
            if not isinstance(value, (str, int, float, bool, list, dict)):
                raise ValueError(f"Configuration value for '{key}' has an invalid type: {type(value).__name__}.")