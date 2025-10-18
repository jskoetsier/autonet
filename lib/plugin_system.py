#!/usr/bin/env python3
"""
AutoNet Plugin System

Extensible plugin architecture for vendor-specific implementations and custom features.
"""

import os
import sys
import importlib
import inspect
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, List, Optional, Type, Union
from dataclasses import dataclass
from enum import Enum
import logging

# Import AutoNet exception classes
from lib.exceptions import ConfigurationError, PluginError

logger = logging.getLogger(__name__)


class PluginType(Enum):
    """Plugin types supported by AutoNet"""
    VENDOR = "vendor"
    FILTER = "filter"
    VALIDATOR = "validator"
    EXPORTER = "exporter"
    MONITOR = "monitor"


@dataclass
class PluginInfo:
    """Plugin metadata and information"""
    name: str
    version: str
    description: str
    author: str
    plugin_type: PluginType
    enabled: bool
    config: Dict[str, Any]
    module_path: str
    class_name: str
    dependencies: List[str]

    def __post_init__(self):
        if isinstance(self.plugin_type, str):
            self.plugin_type = PluginType(self.plugin_type)


class PluginInterface(ABC):
    """Base interface for all AutoNet plugins"""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.enabled = True
        self.logger = logging.getLogger(f"{self.__class__.__module__}.{self.__class__.__name__}")

    @abstractmethod
    def get_info(self) -> PluginInfo:
        """Return plugin information"""
        pass

    @abstractmethod
    def initialize(self) -> bool:
        """Initialize the plugin"""
        pass

    @abstractmethod
    def cleanup(self) -> bool:
        """Cleanup plugin resources"""
        pass

    def is_enabled(self) -> bool:
        """Check if plugin is enabled"""
        return self.enabled

    def enable(self) -> None:
        """Enable the plugin"""
        self.enabled = True
        self.logger.info(f"Plugin {self.__class__.__name__} enabled")

    def disable(self) -> None:
        """Disable the plugin"""
        self.enabled = False
        self.logger.info(f"Plugin {self.__class__.__name__} disabled")


class VendorPlugin(PluginInterface):
    """Base class for vendor-specific plugins"""

    @abstractmethod
    def generate_config(self, peer_info: Dict[str, Any], template_vars: Dict[str, Any]) -> str:
        """Generate vendor-specific configuration"""
        pass

    @abstractmethod
    def validate_config(self, config_content: str) -> bool:
        """Validate vendor-specific configuration"""
        pass

    @abstractmethod
    def get_supported_features(self) -> List[str]:
        """Return list of supported features"""
        pass


class FilterPlugin(PluginInterface):
    """Base class for filter plugins"""

    @abstractmethod
    def generate_filters(self, asn: str, as_set: List[str], **kwargs) -> List[str]:
        """Generate prefix filters"""
        pass

    @abstractmethod
    def validate_filters(self, filters: List[str]) -> bool:
        """Validate generated filters"""
        pass


class ValidatorPlugin(PluginInterface):
    """Base class for validation plugins"""

    @abstractmethod
    def validate(self, data: Any, context: Dict[str, Any] = None) -> List[str]:
        """Validate data and return list of errors (empty if valid)"""
        pass


class PluginManager:
    """
    Plugin manager for loading, managing, and executing plugins

    Features:
    - Auto-discovery of plugins from configured directories
    - Plugin dependency resolution
    - Configuration-based plugin enabling/disabling
    - Plugin lifecycle management
    - Type-safe plugin interfaces
    """

    def __init__(self, plugin_dirs: List[str] = None, config: Dict[str, Any] = None):
        self.plugin_dirs = plugin_dirs or ["plugins"]
        self.config = config or {}
        self.plugins: Dict[str, PluginInterface] = {}
        self.plugin_info: Dict[str, PluginInfo] = {}
        self.plugin_types: Dict[PluginType, List[str]] = {pt: [] for pt in PluginType}

        # Add plugin directories to Python path
        for plugin_dir in self.plugin_dirs:
            plugin_path = Path(plugin_dir).absolute()
            if plugin_path.exists() and str(plugin_path) not in sys.path:
                sys.path.insert(0, str(plugin_path))

    def discover_plugins(self) -> None:
        """Discover and register all available plugins"""
        logger.info("Discovering plugins...")

        for plugin_dir in self.plugin_dirs:
            plugin_path = Path(plugin_dir)

            if not plugin_path.exists():
                logger.warning(f"Plugin directory does not exist: {plugin_path}")
                continue

            # Scan for Python files
            for py_file in plugin_path.rglob("*.py"):
                if py_file.name.startswith("__"):
                    continue

                try:
                    self._load_plugin_from_file(py_file)
                except Exception as e:
                    logger.error(f"Failed to load plugin from {py_file}: {e}")

        logger.info(f"Discovered {len(self.plugins)} plugins")

    def _load_plugin_from_file(self, plugin_file: Path) -> None:
        """Load plugin from a Python file"""
        # Calculate module name from file path
        relative_path = plugin_file.relative_to(Path(self.plugin_dirs[0]))
        module_name = str(relative_path.with_suffix("")).replace(os.sep, ".")

        try:
            # Import the module
            module = importlib.import_module(module_name)

            # Find plugin classes
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if (issubclass(obj, PluginInterface) and
                    obj != PluginInterface and
                    not inspect.isabstract(obj)):

                    # Get plugin config
                    plugin_config = self._get_plugin_config(name)

                    if plugin_config.get('enabled', True):
                        # Instantiate plugin
                        plugin = obj(plugin_config.get('config', {}))

                        # Get plugin info
                        info = plugin.get_info()

                        # Register plugin
                        self.plugins[info.name] = plugin
                        self.plugin_info[info.name] = info
                        self.plugin_types[info.plugin_type].append(info.name)

                        logger.info(f"Loaded plugin: {info.name} ({info.plugin_type.value})")
                    else:
                        logger.info(f"Plugin {name} is disabled in configuration")

        except ImportError as e:
            logger.error(f"Failed to import plugin module {module_name}: {e}")
        except Exception as e:
            logger.error(f"Failed to load plugin from {plugin_file}: {e}")

    def _get_plugin_config(self, plugin_name: str) -> Dict[str, Any]:
        """Get configuration for a specific plugin"""
        plugins_config = self.config.get('plugins', {})

        # Check in vendors section
        if 'vendors' in plugins_config:
            for vendor_name, vendor_config in plugins_config['vendors'].items():
                if vendor_config.get('class') == plugin_name:
                    return vendor_config

        # Check in general plugins section
        return plugins_config.get(plugin_name, {})

    def initialize_plugins(self) -> None:
        """Initialize all enabled plugins"""
        logger.info("Initializing plugins...")

        failed_plugins = []

        for name, plugin in self.plugins.items():
            try:
                if plugin.initialize():
                    logger.info(f"Initialized plugin: {name}")
                else:
                    logger.error(f"Failed to initialize plugin: {name}")
                    failed_plugins.append(name)
            except Exception as e:
                logger.error(f"Error initializing plugin {name}: {e}")
                failed_plugins.append(name)

        # Remove failed plugins
        for name in failed_plugins:
            self.plugins.pop(name, None)
            self.plugin_info.pop(name, None)

        logger.info(f"Successfully initialized {len(self.plugins)} plugins")

    def cleanup_plugins(self) -> None:
        """Cleanup all plugins"""
        logger.info("Cleaning up plugins...")

        for name, plugin in self.plugins.items():
            try:
                plugin.cleanup()
                logger.debug(f"Cleaned up plugin: {name}")
            except Exception as e:
                logger.error(f"Error cleaning up plugin {name}: {e}")

    def get_plugin(self, name: str) -> Optional[PluginInterface]:
        """Get plugin by name"""
        return self.plugins.get(name)

    def get_plugins_by_type(self, plugin_type: PluginType) -> List[PluginInterface]:
        """Get all plugins of a specific type"""
        plugin_names = self.plugin_types.get(plugin_type, [])
        return [self.plugins[name] for name in plugin_names if name in self.plugins]

    def get_vendor_plugin(self, vendor: str) -> Optional[VendorPlugin]:
        """Get vendor plugin by vendor name"""
        vendor_plugins = self.get_plugins_by_type(PluginType.VENDOR)

        for plugin in vendor_plugins:
            if isinstance(plugin, VendorPlugin):
                info = plugin.get_info()
                if info.name.lower() == vendor.lower() or vendor.lower() in info.name.lower():
                    return plugin

        return None

    def list_plugins(self) -> List[PluginInfo]:
        """List all registered plugins"""
        return list(self.plugin_info.values())

    def reload_plugin(self, name: str) -> bool:
        """Reload a specific plugin"""
        if name not in self.plugins:
            logger.error(f"Plugin not found: {name}")
            return False

        try:
            # Cleanup existing plugin
            self.plugins[name].cleanup()

            # Remove from registries
            info = self.plugin_info[name]
            self.plugin_types[info.plugin_type].remove(name)
            del self.plugins[name]
            del self.plugin_info[name]

            # Rediscover and load
            self.discover_plugins()

            if name in self.plugins:
                self.plugins[name].initialize()
                logger.info(f"Successfully reloaded plugin: {name}")
                return True
            else:
                logger.error(f"Failed to reload plugin: {name}")
                return False

        except Exception as e:
            logger.error(f"Error reloading plugin {name}: {e}")
            return False

    def validate_dependencies(self) -> List[str]:
        """Validate plugin dependencies and return missing dependencies"""
        missing_deps = []

        for name, info in self.plugin_info.items():
            for dep in info.dependencies:
                if dep not in self.plugins:
                    missing_deps.append(f"{name} requires {dep}")

        return missing_deps


# Global plugin manager instance
_plugin_manager: Optional[PluginManager] = None


def get_plugin_manager(plugin_dirs: List[str] = None, config: Dict[str, Any] = None) -> PluginManager:
    """Get or create global plugin manager instance"""
    global _plugin_manager

    if _plugin_manager is None:
        _plugin_manager = PluginManager(plugin_dirs, config)

    return _plugin_manager


def initialize_plugin_system(config: Dict[str, Any]) -> PluginManager:
    """Initialize the plugin system with configuration"""
    plugin_config = config.get('autonet', {}).get('plugins', {})

    if not plugin_config.get('enabled', True):
        logger.info("Plugin system is disabled")
        return PluginManager([], {})

    plugin_dirs = plugin_config.get('directories', ['plugins'])

    manager = get_plugin_manager(plugin_dirs, config)

    if plugin_config.get('auto_discovery', True):
        manager.discover_plugins()
        manager.initialize_plugins()

        # Validate dependencies
        missing_deps = manager.validate_dependencies()
        if missing_deps:
            logger.warning("Missing plugin dependencies:")
            for dep in missing_deps:
                logger.warning(f"  {dep}")

    return manager


if __name__ == "__main__":
    # CLI interface for plugin management
    import argparse
    import json

    parser = argparse.ArgumentParser(description="AutoNet Plugin Manager")
    parser.add_argument("--list", "-l", action="store_true", help="List all plugins")
    parser.add_argument("--info", "-i", help="Show info for specific plugin")
    parser.add_argument("--reload", "-r", help="Reload specific plugin")
    parser.add_argument("--validate-deps", "-v", action="store_true", help="Validate plugin dependencies")
    parser.add_argument("--plugin-dirs", nargs="+", default=["plugins"], help="Plugin directories")

    args = parser.parse_args()

    try:
        manager = get_plugin_manager(args.plugin_dirs)
        manager.discover_plugins()

        if args.list:
            plugins = manager.list_plugins()
            print(f"Found {len(plugins)} plugins:")
            for plugin in plugins:
                status = "✓" if plugin.enabled else "✗"
                print(f"  {status} {plugin.name} ({plugin.plugin_type.value}) - {plugin.description}")

        elif args.info:
            plugin = manager.get_plugin(args.info)
            if plugin:
                info = plugin.get_info()
                print(json.dumps({
                    "name": info.name,
                    "version": info.version,
                    "description": info.description,
                    "author": info.author,
                    "type": info.plugin_type.value,
                    "enabled": info.enabled,
                    "dependencies": info.dependencies
                }, indent=2))
            else:
                print(f"Plugin not found: {args.info}")
                sys.exit(1)

        elif args.reload:
            if manager.reload_plugin(args.reload):
                print(f"✓ Successfully reloaded plugin: {args.reload}")
            else:
                print(f"✗ Failed to reload plugin: {args.reload}")
                sys.exit(1)

        elif args.validate_deps:
            missing_deps = manager.validate_dependencies()
            if missing_deps:
                print("Missing dependencies:")
                for dep in missing_deps:
                    print(f"  ✗ {dep}")
                sys.exit(1)
            else:
                print("✓ All plugin dependencies satisfied")

        else:
            manager.initialize_plugins()
            print(f"✓ Initialized {len(manager.plugins)} plugins")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
