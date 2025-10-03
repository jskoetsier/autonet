#!/usr/bin/env python3
"""
Unit tests for AutoNet Configuration Manager
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add lib directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from lib.config_manager import ConfigurationError, ConfigurationManager, ValidationError


class TestConfigurationManager(unittest.TestCase):
    """Test cases for ConfigurationManager"""

    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.config_dir = Path(self.temp_dir) / "config"
        self.config_dir.mkdir()

        # Create minimal schema
        schema_content = """
autonet:
  version: "2.0"
  schema_version: "1.0"

schemas:
  generic_config:
    type: "object"
    required: ["builddir", "stagedir"]
    properties:
      builddir:
        type: "string"
      stagedir:
        type: "string"
"""

        with open(self.config_dir / "schema.yml", "w") as f:
            f.write(schema_content)

    def tearDown(self):
        """Clean up test environment"""
        import shutil

        shutil.rmtree(self.temp_dir)

    def test_schema_loading(self):
        """Test schema loading"""
        manager = ConfigurationManager(str(self.config_dir))
        self.assertIn("main", manager.schema_cache)
        self.assertEqual(manager.schema_cache["main"]["autonet"]["version"], "2.0")

    def test_config_validation_success(self):
        """Test successful configuration validation"""
        manager = ConfigurationManager(str(self.config_dir))

        # Create valid config
        config = {"builddir": "/tmp/build", "stagedir": "/tmp/stage"}

        # Should not raise exception
        manager._validate_configuration(config)

    def test_config_validation_failure(self):
        """Test configuration validation failure"""
        manager = ConfigurationManager(str(self.config_dir))

        # Create invalid config (missing required fields)
        config = {
            "builddir": "/tmp/build"
            # Missing stagedir
        }

        with self.assertRaises(ValidationError):
            manager._validate_configuration(config)

    def test_environment_overrides(self):
        """Test environment-specific overrides"""
        # Add environment overrides to schema
        schema_content = """
autonet:
  version: "2.0"

environments:
  test:
    logging:
      level: "DEBUG"
    test_override: true
"""
        with open(self.config_dir / "schema.yml", "w") as f:
            f.write(schema_content)

        manager = ConfigurationManager(str(self.config_dir), environment="test")
        base_config = {"logging": {"level": "INFO"}}

        result = manager._apply_environment_overrides(base_config)

        self.assertEqual(result["logging"]["level"], "DEBUG")
        self.assertTrue(result["test_override"])


if __name__ == "__main__":
    unittest.main()
