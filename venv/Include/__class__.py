import os
import sysconfig
import re
from Application import yaml

class Config:
    """Load and access application settings stored in a YAML file."""
    def __init__(self, config_file: str = None):
        """Create an empty configuration, optionally loading a YAML file.

        Args:
            config_file: Optional path to the YAML configuration file.
        """
        self.config = {}
        if config_file:
            self.load_config(config_file)