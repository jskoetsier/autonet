#!/usr/bin/env python3
"""
BIRD 2 Vendor Plugin for AutoNet

Provides BIRD 2.x-specific configuration generation and validation.
"""

import os
import sys
from pathlib import Path
from typing import Dict, Any, List
from subprocess import run, PIPE, DEVNULL

# Import plugin system
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from lib.plugin_system import VendorPlugin, PluginInfo, PluginType
from jinja2 import Environment, FileSystemLoader


class Bird2VendorPlugin(VendorPlugin):
    """
    BIRD 2.x vendor plugin implementation
    
    Features:
    - BIRD 2.x unified IPv4/IPv6 configuration generation
    - Template-based configuration with Jinja2
    - Syntax validation using bird binary
    - Feature detection and capability reporting
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        
        # Configuration with defaults
        self.bird_bin = self.config.get('bird_bin', '/usr/sbin/bird')
        self.birdc_bin = self.config.get('birdc_bin', '/usr/sbin/birdc')
        self.template_dir = self.config.get('template_dir', 'templates/bird2')
        
        # Initialize Jinja2 environment
        if Path(self.template_dir).exists():
            self.jinja_env = Environment(
                loader=FileSystemLoader(self.template_dir),
                trim_blocks=True,
                lstrip_blocks=True
            )
        else:
            self.logger.warning(f"Template directory not found: {self.template_dir}")
            self.jinja_env = None
        
        # BIRD 2 capabilities
        self.capabilities = [
            "unified_ipv4_ipv6",
            "roa_tables", 
            "rpki_validation",
            "bfd_support",
            "bgp_large_communities",
            "flowspec",
            "mrt_dumps",
            "multiple_tables"
        ]
    
    def get_info(self) -> PluginInfo:
        """Return plugin information"""
        return PluginInfo(
            name="bird2",
            version="2.0.0",
            description="BIRD 2.x routing daemon support",
            author="AutoNet Team",
            plugin_type=PluginType.VENDOR,
            enabled=True,
            config=self.config,
            module_path="plugins.vendors.bird2",
            class_name="Bird2VendorPlugin",
            dependencies=[]
        )
    
    def initialize(self) -> bool:
        """Initialize the BIRD 2 plugin"""
        try:
            # Check if BIRD binary exists and is executable
            if not os.path.exists(self.bird_bin):
                self.logger.error(f"BIRD binary not found: {self.bird_bin}")
                return False
            
            if not os.access(self.bird_bin, os.X_OK):
                self.logger.error(f"BIRD binary not executable: {self.bird_bin}")
                return False
            
            # Check BIRD version
            version_info = self._get_bird_version()
            if not version_info or not version_info.startswith('2.'):
                self.logger.error(f"BIRD 2.x required, found: {version_info}")
                return False
            
            self.logger.info(f"BIRD 2 plugin initialized with version: {version_info}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize BIRD 2 plugin: {e}")
            return False
    
    def cleanup(self) -> bool:
        """Cleanup plugin resources"""
        # No cleanup needed for BIRD 2 plugin
        return True
    
    def _get_bird_version(self) -> str:
        """Get BIRD version information"""
        try:
            result = run([self.bird_bin, '--version'], 
                        capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                # Parse version from output like "BIRD 2.0.8"
                version_line = result.stdout.strip().split('\n')[0]
                if 'BIRD' in version_line:
                    return version_line.split()[-1]
            return ""
        except Exception as e:
            self.logger.error(f"Failed to get BIRD version: {e}")
            return ""
    
    def generate_config(self, peer_info: Dict[str, Any], template_vars: Dict[str, Any]) -> str:
        """
        Generate BIRD 2.x configuration
        
        Args:
            peer_info: Peer information dictionary
            template_vars: Template variables for rendering
            
        Returns:
            Generated BIRD 2.x configuration string
        """
        if not self.jinja_env:
            raise RuntimeError("Jinja2 environment not initialized")
        
        try:
            # Determine template based on peer type
            template_name = self._get_template_name(peer_info)
            
            # Load template
            template = self.jinja_env.get_template(template_name)
            
            # Merge peer info into template vars
            render_vars = {**template_vars, 'peer': peer_info}
            
            # Add BIRD 2 specific variables
            render_vars.update({
                'bird_version': '2',
                'supports_unified_config': True,
                'supports_roa_tables': True,
                'supports_large_communities': True
            })
            
            # Render configuration
            config = template.render(**render_vars)
            
            self.logger.debug(f"Generated BIRD 2 config for peer: {peer_info.get('asn', 'unknown')}")
            return config
            
        except Exception as e:
            self.logger.error(f"Failed to generate BIRD 2 config: {e}")
            raise
    
    def _get_template_name(self, peer_info: Dict[str, Any]) -> str:
        """Determine appropriate template based on peer information"""
        # Default template
        template_name = "peer.j2"
        
        # Check for specific peer types
        if peer_info.get('is_route_server'):
            template_name = "route_server.j2"
        elif peer_info.get('is_transit'):
            template_name = "transit.j2"
        elif peer_info.get('is_customer'):
            template_name = "customer.j2"
        
        # Fallback to peer.j2 if specific template doesn't exist
        if not (Path(self.template_dir) / template_name).exists():
            template_name = "peer.j2"
        
        return template_name
    
    def validate_config(self, config_content: str) -> bool:
        """
        Validate BIRD 2.x configuration syntax
        
        Args:
            config_content: Configuration content to validate
            
        Returns:
            True if configuration is valid, False otherwise
        """
        try:
            # Write config to temporary file
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.conf', delete=False) as f:
                f.write(config_content)
                temp_config = f.name
            
            try:
                # Run BIRD syntax check
                result = run([self.bird_bin, '-p', '-c', temp_config],
                           capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    self.logger.debug("BIRD 2 configuration validation passed")
                    return True
                else:
                    self.logger.error(f"BIRD 2 configuration validation failed:")
                    self.logger.error(result.stderr)
                    return False
                    
            finally:
                # Clean up temporary file
                os.unlink(temp_config)
                
        except Exception as e:
            self.logger.error(f"Error validating BIRD 2 configuration: {e}")
            return False
    
    def get_supported_features(self) -> List[str]:
        """Return list of supported BIRD 2 features"""
        return self.capabilities.copy()
    
    def supports_feature(self, feature: str) -> bool:
        """Check if a specific feature is supported"""
        return feature in self.capabilities
    
    def get_default_template_vars(self) -> Dict[str, Any]:
        """Get default template variables for BIRD 2"""
        return {
            'bird_version': '2',
            'config_format': 'unified',
            'ipv4_table': 'master4',
            'ipv6_table': 'master6',
            'supports_roa': True,
            'supports_large_communities': True,
            'supports_bfd': True,
            'default_local_pref': 100,
            'default_med': 0
        }
    
    def generate_protocol_config(self, protocol_type: str, protocol_config: Dict[str, Any]) -> str:
        """
        Generate specific protocol configuration
        
        Args:
            protocol_type: Type of protocol (bgp, ospf, static, etc.)
            protocol_config: Protocol-specific configuration
            
        Returns:
            Generated protocol configuration
        """
        if not self.jinja_env:
            raise RuntimeError("Jinja2 environment not initialized")
        
        try:
            template_name = f"protocols/{protocol_type}.j2"
            
            # Check if protocol template exists
            if not (Path(self.template_dir) / template_name).exists():
                raise ValueError(f"Protocol template not found: {template_name}")
            
            template = self.jinja_env.get_template(template_name)
            
            # Add default template vars
            render_vars = self.get_default_template_vars()
            render_vars.update(protocol_config)
            
            config = template.render(**render_vars)
            
            self.logger.debug(f"Generated {protocol_type} protocol config")
            return config
            
        except Exception as e:
            self.logger.error(f"Failed to generate {protocol_type} config: {e}")
            raise
    
    def get_config_status(self) -> Dict[str, Any]:
        """Get current BIRD configuration status"""
        try:
            result = run([self.birdc_bin, 'show', 'status'], 
                        capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                status_info = self._parse_status_output(result.stdout)
                return {
                    'running': True,
                    'version': status_info.get('version', 'unknown'),
                    'uptime': status_info.get('uptime', 'unknown'),
                    'protocols': status_info.get('protocols', 0)
                }
            else:
                return {'running': False, 'error': result.stderr}
                
        except Exception as e:
            self.logger.error(f"Failed to get BIRD status: {e}")
            return {'running': False, 'error': str(e)}
    
    def _parse_status_output(self, output: str) -> Dict[str, Any]:
        """Parse BIRD status output"""
        status = {}
        
        for line in output.split('\n'):
            line = line.strip()
            if 'BIRD' in line and 'version' in line:
                # Extract version
                parts = line.split()
                for i, part in enumerate(parts):
                    if part == 'version' and i + 1 < len(parts):
                        status['version'] = parts[i + 1]
                        break
            elif 'Router ID' in line:
                # Extract router ID
                parts = line.split()
                if len(parts) >= 3:
                    status['router_id'] = parts[-1]
            elif 'Current server time' in line:
                # Extract uptime info
                status['current_time'] = line.split('Current server time is')[1].strip()
        
        return status
    
    def reload_config(self) -> bool:
        """Reload BIRD configuration"""
        try:
            result = run([self.birdc_bin, 'configure'], 
                        capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                self.logger.info("BIRD 2 configuration reloaded successfully")
                return True
            else:
                self.logger.error(f"Failed to reload BIRD 2 configuration: {result.stderr}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error reloading BIRD 2 configuration: {e}")
            return False


# Plugin factory function for easier instantiation
def create_bird2_plugin(config: Dict[str, Any] = None) -> Bird2VendorPlugin:
    """Create and return a BIRD 2 vendor plugin instance"""
    return Bird2VendorPlugin(config)