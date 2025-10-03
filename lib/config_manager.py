#!/usr/bin/env python3
"""
AutoNet Configuration Manager

Centralized configuration management with schema validation, environment-specific
overrides, and secure API key handling.
"""

import os
import sys
import yaml
import json
import jsonschema
from pathlib import Path
from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass
from datetime import datetime
import logging

# Import AutoNet exception classes
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from peering_filters import (
    ConfigurationError,
    ValidationError,
    get_api_key,
    encrypt_api_key,
    decrypt_api_key
)

logger = logging.getLogger(__name__)


@dataclass
class ConfigMetadata:
    """Configuration metadata for tracking and validation"""
    version: str
    schema_version: str
    loaded_at: datetime
    source_files: List[str]
    environment: str
    validation_passed: bool


class ConfigurationManager:
    """
    Centralized configuration management with schema validation

    Features:
    - Schema-based validation using JSON Schema
    - Environment-specific configuration overrides
    - Secure API key management with encryption
    - Configuration merging and inheritance
    - Validation caching for performance
    """

    def __init__(self, config_dir: str = None, environment: str = None):
        self.config_dir = Path(config_dir or "config")
        self.environment = environment or os.getenv("AUTONET_ENV", "production")
        self.schema_cache: Dict[str, Dict] = {}
        self.config_cache: Dict[str, Dict] = {}
        self.metadata: Optional[ConfigMetadata] = None

        # Load base schema
        self._load_schema()

    def _load_schema(self) -> None:
        """Load and cache the configuration schema"""
        schema_path = self.config_dir / "schema.yml"

        if not schema_path.exists():
            raise ConfigurationError(f"Schema file not found: {schema_path}")

        try:
            with open(schema_path, 'r', encoding='utf-8') as f:
                self.schema_cache['main'] = yaml.safe_load(f)

            logger.info(f"Loaded configuration schema from {schema_path}")

        except yaml.YAMLError as e:
            raise ConfigurationError(f"Invalid YAML in schema file {schema_path}: {e}")
        except Exception as e:
            raise ConfigurationError(f"Failed to load schema file {schema_path}: {e}")

    def load_configuration(self, config_path: str = None) -> Dict[str, Any]:
        """
        Load and validate configuration with environment overrides

        Args:
            config_path: Path to main configuration file (default: vars/generic.yml)

        Returns:
            Validated and merged configuration dictionary
        """
        if config_path is None:
            config_path = "vars/generic.yml"

        config_path = Path(config_path)

        if not config_path.exists():
            raise ConfigurationError(f"Configuration file not found: {config_path}")

        # Load base configuration
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                base_config = yaml.safe_load(f)

            if base_config is None:
                raise ConfigurationError(f"Configuration file is empty: {config_path}")

        except yaml.YAMLError as e:
            raise ConfigurationError(f"Invalid YAML in configuration file {config_path}: {e}")
        except Exception as e:
            raise ConfigurationError(f"Failed to load configuration file {config_path}: {e}")

        # Apply environment-specific overrides
        config = self._apply_environment_overrides(base_config)

        # Merge with schema defaults
        config = self._merge_schema_defaults(config)

        # Validate configuration against schema
        self._validate_configuration(config)

        # Process API keys securely
        config = self._process_api_keys(config)

        # Store metadata
        self.metadata = ConfigMetadata(
            version=config.get('autonet', {}).get('version', '2.0'),
            schema_version=config.get('autonet', {}).get('schema_version', '1.0'),
            loaded_at=datetime.now(),
            source_files=[str(config_path)],
            environment=self.environment,
            validation_passed=True
        )

        # Cache the configuration
        self.config_cache[str(config_path)] = config

        logger.info(f"Successfully loaded and validated configuration from {config_path}")
        return config

    def _apply_environment_overrides(self, base_config: Dict[str, Any]) -> Dict[str, Any]:
        """Apply environment-specific configuration overrides"""
        if 'environments' not in self.schema_cache['main']:
            return base_config

        env_overrides = self.schema_cache['main']['environments'].get(self.environment, {})
        if not env_overrides:
            logger.info(f"No environment overrides found for environment: {self.environment}")
            return base_config

        # Deep merge environment overrides
        config = self._deep_merge(base_config, env_overrides)
        logger.info(f"Applied environment overrides for: {self.environment}")

        return config

    def _merge_schema_defaults(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Merge schema defaults into configuration"""
        schema = self.schema_cache['main']

        if 'autonet' not in config:
            config['autonet'] = {}

        # Merge AutoNet defaults
        autonet_defaults = schema.get('autonet', {})
        config['autonet'] = self._deep_merge(autonet_defaults, config['autonet'])

        return config

    def _validate_configuration(self, config: Dict[str, Any]) -> None:
        """Validate configuration against schema"""
        try:
            # Get validation schema
            schema = self.schema_cache['main'].get('schemas', {}).get('generic_config', {})

            if not schema:
                logger.warning("No validation schema found, skipping validation")
                return

            # Validate using jsonschema
            jsonschema.validate(config, schema)

            # Custom validation rules
            self._apply_custom_validation(config)

            logger.info("Configuration validation passed")

        except jsonschema.ValidationError as e:
            error_msg = f"Configuration validation failed: {e.message}"
            if hasattr(e, 'absolute_path') and e.absolute_path:
                error_msg += f" at path: {'.'.join(str(p) for p in e.absolute_path)}"
            raise ValidationError(error_msg)
        except Exception as e:
            raise ValidationError(f"Configuration validation error: {e}")

    def _apply_custom_validation(self, config: Dict[str, Any]) -> None:
        """Apply custom validation rules"""
        validation_rules = self.schema_cache['main'].get('validation_rules', {})

        # Validate ASNs
        if 'bgp' in config:
            for router_name, router_config in config['bgp'].items():
                # Additional router-specific validation can be added here
                pass

        # Validate IXP mappings
        if 'ixp_map' in config:
            for ixp_name, ixp_config in config['ixp_map'].items():
                # Validate present_on routers exist in bgp section
                if 'present_on' in ixp_config and 'bgp' in config:
                    for router in ixp_config['present_on']:
                        router_short = router.split('.')[0]  # Extract short name
                        if router_short not in config['bgp']:
                            logger.warning(f"Router {router} in IXP {ixp_name} not found in BGP configuration")

    def _process_api_keys(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Process API keys with secure handling"""
        if 'pdb_apikey' in config:
            try:
                # Use the secure API key retrieval system
                config['pdb_apikey'] = get_api_key("PEERINGDB", "pdb_apikey")
                logger.info("Processed PeeringDB API key securely")
            except Exception as e:
                logger.warning(f"Failed to process PeeringDB API key: {e}")

        return config

    def _deep_merge(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """Deep merge two dictionaries"""
        result = base.copy()

        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value

        return result

    def get_router_config(self, router_name: str, base_config: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Load router-specific configuration with inheritance

        Args:
            router_name: Name of the router (e.g., 'router1.example.net')
            base_config: Base configuration to inherit from

        Returns:
            Complete router configuration with inheritance applied
        """
        router_config_path = Path(f"vars_example/{router_name}.yml")

        if not router_config_path.exists():
            raise ConfigurationError(f"Router configuration not found: {router_config_path}")

        try:
            with open(router_config_path, 'r', encoding='utf-8') as f:
                router_config = yaml.safe_load(f)

            if router_config is None:
                router_config = {}

        except yaml.YAMLError as e:
            raise ConfigurationError(f"Invalid YAML in router configuration {router_config_path}: {e}")
        except Exception as e:
            raise ConfigurationError(f"Failed to load router configuration {router_config_path}: {e}")

        # Validate router configuration
        self._validate_router_configuration(router_config)

        # Merge with base configuration if provided
        if base_config:
            # Extract router-specific config from base
            router_short = router_name.split('.')[0]
            if 'bgp' in base_config and router_short in base_config['bgp']:
                base_router_config = base_config['bgp'][router_short]
                router_config = self._deep_merge(base_router_config, router_config)

        logger.info(f"Loaded router configuration for {router_name}")
        return router_config

    def _validate_router_configuration(self, config: Dict[str, Any]) -> None:
        """Validate router-specific configuration"""
        try:
            schema = self.schema_cache['main'].get('schemas', {}).get('router_config', {})

            if schema:
                jsonschema.validate(config, schema)
                logger.debug("Router configuration validation passed")
            else:
                logger.warning("No router configuration schema found")

        except jsonschema.ValidationError as e:
            raise ValidationError(f"Router configuration validation failed: {e.message}")

    def get_plugin_config(self, plugin_name: str, base_config: Dict[str, Any]) -> Dict[str, Any]:
        """Get plugin-specific configuration"""
        plugins_config = base_config.get('autonet', {}).get('plugins', {})

        if plugin_name in plugins_config.get('vendors', {}):
            return plugins_config['vendors'][plugin_name]

        return {}

    def validate_environment(self) -> bool:
        """Validate current environment configuration"""
        try:
            # Check required directories
            required_dirs = ['builddir', 'stagedir']
            base_config = self.load_configuration()

            for dir_key in required_dirs:
                if dir_key in base_config:
                    dir_path = Path(base_config[dir_key])
                    if not dir_path.exists():
                        logger.warning(f"Directory does not exist: {dir_path}")
                        return False
                    if not os.access(dir_path, os.W_OK):
                        logger.error(f"Directory not writable: {dir_path}")
                        return False

            # Check API connectivity
            if 'pdb_apikey' in base_config:
                # Basic API key format validation
                api_key = base_config['pdb_apikey']
                if not api_key or len(api_key) < 10:
                    logger.error("Invalid PeeringDB API key format")
                    return False

            logger.info("Environment validation passed")
            return True

        except Exception as e:
            logger.error(f"Environment validation failed: {e}")
            return False

    def get_metadata(self) -> Optional[ConfigMetadata]:
        """Get configuration metadata"""
        return self.metadata

    def reload_configuration(self, config_path: str = None) -> Dict[str, Any]:
        """Reload configuration and clear caches"""
        self.config_cache.clear()
        self.schema_cache.clear()

        # Reload schema
        self._load_schema()

        # Reload configuration
        return self.load_configuration(config_path)


# Global configuration manager instance
_config_manager: Optional[ConfigurationManager] = None


def get_config_manager(config_dir: str = None, environment: str = None) -> ConfigurationManager:
    """Get or create global configuration manager instance"""
    global _config_manager

    if _config_manager is None:
        _config_manager = ConfigurationManager(config_dir, environment)

    return _config_manager


def load_config(config_path: str = None, environment: str = None) -> Dict[str, Any]:
    """Convenience function to load configuration"""
    manager = get_config_manager(environment=environment)
    return manager.load_configuration(config_path)


def validate_config(config_path: str = None, environment: str = None) -> bool:
    """Convenience function to validate configuration"""
    try:
        manager = get_config_manager(environment=environment)
        manager.load_configuration(config_path)
        return manager.validate_environment()
    except Exception as e:
        logger.error(f"Configuration validation failed: {e}")
        return False


if __name__ == "__main__":
    # CLI interface for configuration management
    import argparse

    parser = argparse.ArgumentParser(description="AutoNet Configuration Manager")
    parser.add_argument("--config", "-c", help="Configuration file path")
    parser.add_argument("--environment", "-e", help="Environment (development, staging, production)")
    parser.add_argument("--validate", "-v", action="store_true", help="Validate configuration only")
    parser.add_argument("--show-metadata", "-m", action="store_true", help="Show configuration metadata")

    args = parser.parse_args()

    try:
        if args.validate:
            if validate_config(args.config, args.environment):
                print("✓ Configuration validation passed")
                sys.exit(0)
            else:
                print("✗ Configuration validation failed")
                sys.exit(1)
        else:
            manager = get_config_manager(environment=args.environment)
            config = manager.load_configuration(args.config)

            if args.show_metadata:
                metadata = manager.get_metadata()
                if metadata:
                    print(f"Configuration Metadata:")
                    print(f"  Version: {metadata.version}")
                    print(f"  Schema Version: {metadata.schema_version}")
                    print(f"  Environment: {metadata.environment}")
                    print(f"  Loaded At: {metadata.loaded_at}")
                    print(f"  Source Files: {', '.join(metadata.source_files)}")
                    print(f"  Validation Passed: {metadata.validation_passed}")
            else:
                print(json.dumps(config, indent=2, default=str))

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
