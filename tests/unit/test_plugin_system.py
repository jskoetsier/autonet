#!/usr/bin/env python3
"""
Unit tests for AutoNet Plugin System
"""

import unittest
import tempfile
import os
import sys
from pathlib import Path

# Add lib directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from lib.plugin_system import PluginManager, PluginInterface, VendorPlugin, PluginInfo, PluginType


class TestPlugin(PluginInterface):
    """Test plugin for unit testing"""
    
    def get_info(self):
        return PluginInfo(
            name="test_plugin",
            version="1.0.0",
            description="Test plugin",
            author="Test Author",
            plugin_type=PluginType.VENDOR,
            enabled=True,
            config={},
            module_path="test",
            class_name="TestPlugin",
            dependencies=[]
        )
    
    def initialize(self):
        return True
    
    def cleanup(self):
        return True


class TestVendorPlugin(VendorPlugin):
    """Test vendor plugin"""
    
    def get_info(self):
        return PluginInfo(
            name="test_vendor",
            version="1.0.0", 
            description="Test vendor plugin",
            author="Test Author",
            plugin_type=PluginType.VENDOR,
            enabled=True,
            config={},
            module_path="test",
            class_name="TestVendorPlugin",
            dependencies=[]
        )
    
    def initialize(self):
        return True
    
    def cleanup(self):
        return True
    
    def generate_config(self, peer_info, template_vars):
        return f"# Test config for {peer_info.get('asn', 'unknown')}"
    
    def validate_config(self, config_content):
        return True
    
    def get_supported_features(self):
        return ["test_feature"]


class TestPluginSystem(unittest.TestCase):
    """Test cases for Plugin System"""
    
    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.plugin_dirs = [str(Path(self.temp_dir) / "plugins")]
        
        # Create plugin directory
        Path(self.plugin_dirs[0]).mkdir(parents=True)
    
    def tearDown(self):
        """Clean up test environment"""
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_plugin_manager_creation(self):
        """Test plugin manager creation"""
        manager = PluginManager(self.plugin_dirs)
        self.assertEqual(manager.plugin_dirs, self.plugin_dirs)
        self.assertEqual(len(manager.plugins), 0)
    
    def test_plugin_registration(self):
        """Test manual plugin registration"""
        manager = PluginManager(self.plugin_dirs)
        
        # Manually register a plugin
        plugin = TestPlugin()
        info = plugin.get_info()
        
        manager.plugins[info.name] = plugin
        manager.plugin_info[info.name] = info
        manager.plugin_types[info.plugin_type].append(info.name)
        
        self.assertEqual(len(manager.plugins), 1)
        self.assertIn("test_plugin", manager.plugins)
    
    def test_get_plugin_by_type(self):
        """Test getting plugins by type"""
        manager = PluginManager(self.plugin_dirs)
        
        # Register test plugins
        vendor_plugin = TestVendorPlugin()
        vendor_info = vendor_plugin.get_info()
        manager.plugins[vendor_info.name] = vendor_plugin
        manager.plugin_info[vendor_info.name] = vendor_info
        manager.plugin_types[vendor_info.plugin_type].append(vendor_info.name)
        
        vendor_plugins = manager.get_plugins_by_type(PluginType.VENDOR)
        self.assertEqual(len(vendor_plugins), 1)
        self.assertIsInstance(vendor_plugins[0], VendorPlugin)
    
    def test_vendor_plugin_functionality(self):
        """Test vendor plugin specific functionality"""
        plugin = TestVendorPlugin()
        
        # Test config generation
        peer_info = {"asn": "AS64512"}
        config = plugin.generate_config(peer_info, {})
        self.assertIn("AS64512", config)
        
        # Test config validation
        self.assertTrue(plugin.validate_config("test config"))
        
        # Test supported features
        features = plugin.get_supported_features()
        self.assertIn("test_feature", features)


if __name__ == "__main__":
    unittest.main()