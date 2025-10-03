#!/usr/bin/env python3
"""
AutoNet Router Update Tool (Python Version)

Modern Python replacement for update-routers.sh with enhanced features:
- Integration with new architecture v2.0
- Comprehensive validation and error handling
- State tracking and deployment monitoring
- Plugin-based vendor support
- Secure SSH operations with proper validation
"""

import os
import sys
import argparse
import logging
import subprocess
import tempfile
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
import concurrent.futures
from dataclasses import dataclass

# Import AutoNet architecture components
from lib.config_manager import get_config_manager, ConfigurationError
from lib.plugin_system import get_plugin_manager, initialize_plugin_system
from lib.state_manager import (
    get_state_manager, track_event, EventType, 
    DeploymentRecord, StateEvent
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


# Exit codes for consistency
EXIT_SUCCESS = 0
EXIT_CONFIG_ERROR = 1  
EXIT_TOOL_ERROR = 2
EXIT_SSH_ERROR = 3
EXIT_VALIDATION_ERROR = 4
EXIT_UPLOAD_ERROR = 5


@dataclass
class RouterInfo:
    """Router information and configuration"""
    name: str
    fqdn: str
    short_name: str
    ipv4: str
    ipv6: str
    vendor: str
    config_dir: Path
    graceful_shutdown: bool = False
    maintenance_mode: bool = False


class AutoNetDeployer:
    """
    AutoNet configuration deployment system
    
    Features:
    - Multi-router parallel deployment
    - Comprehensive pre-deployment validation
    - Plugin-based vendor support
    - State tracking and monitoring
    - Rollback capabilities
    - SSH security and key management
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        
        # Initialize architecture components
        self.config_manager = get_config_manager()
        self.plugin_manager = initialize_plugin_system(self.config)
        self.state_manager = get_state_manager(config=self.config)
        
        # Configuration paths
        self.builddir = Path(self.config.get('builddir', '/opt/routefilters'))
        self.stagedir = Path(self.config.get('stagedir', '/opt/router-staging'))
        
        # SSH configuration
        self.ssh_key_path = Path(os.getenv('SSH_KEY_PATH', 
                                          self.config.get('ssh_key_path', 
                                                         f"{os.path.expanduser('~')}/.ssh/id_rsa")))
        self.ssh_user = os.getenv('SSH_USER', self.config.get('ssh_user', 'root'))
        self.ssh_timeout = int(os.getenv('SSH_TIMEOUT', self.config.get('ssh_timeout', 30)))
        
        # Tool paths
        self.bird_bin = self.config.get('bird_bin', '/usr/sbin/bird')
        self.bird6_bin = self.config.get('bird6_bin', '/usr/sbin/bird')
        self.birdc_bin = self.config.get('birdc_bin', '/usr/sbin/birdc')
        self.birdc6_bin = self.config.get('birdc6_bin', '/usr/local/bin/birdc6')
        
        # Deployment settings
        self.max_parallel_deployments = self.config.get('max_parallel_deployments', 3)
        self.deployment_timeout = self.config.get('deployment_timeout', 300)  # 5 minutes
        
        # Load router list
        self.routers = self._load_routers()
        
        logger.info(f"AutoNet Deployer initialized with {len(self.routers)} routers")
    
    def _load_routers(self) -> List[RouterInfo]:
        """Load router configuration from various sources"""
        routers = []
        
        # Try to get routers from configuration
        if 'bgp' in self.config:
            for router_short, router_config in self.config['bgp'].items():
                router_info = RouterInfo(
                    name=router_config['fqdn'],
                    fqdn=router_config['fqdn'],
                    short_name=router_short,
                    ipv4=router_config['ipv4'],
                    ipv6=router_config['ipv6'],
                    vendor=router_config.get('vendor', 'bird'),
                    config_dir=self.stagedir / router_config['fqdn'],
                    graceful_shutdown=router_config.get('graceful_shutdown', False),
                    maintenance_mode=router_config.get('maintenance_mode', False)
                )
                routers.append(router_info)
        
        # Fallback to environment variable or hardcoded list
        if not routers:
            router_names = os.getenv('AUTONET_ROUTERS', '').split(',')
            if not router_names or router_names == ['']:
                router_names = [
                    'dc5-1.router.nl.example.net',
                    'dc5-2.router.nl.example.net', 
                    'eunetworks-2.router.nl.example.net',
                    'eunetworks-3.router.nl.example.net'
                ]
            
            for router_name in router_names:
                router_name = router_name.strip()
                if router_name:
                    router_info = RouterInfo(
                        name=router_name,
                        fqdn=router_name,
                        short_name=router_name.split('.')[0],
                        ipv4="unknown",
                        ipv6="unknown",
                        vendor="bird",
                        config_dir=self.stagedir / router_name
                    )
                    routers.append(router_info)
        
        return routers
    
    def validate_environment(self) -> bool:
        """Validate deployment environment"""
        logger.info("Validating deployment environment...")
        
        try:
            # Validate directories
            for directory in [self.builddir, self.stagedir]:
                if not directory.exists():
                    logger.error(f"Directory does not exist: {directory}")
                    return False
                if not os.access(directory, os.W_OK):
                    logger.error(f"Directory not writable: {directory}")
                    return False
            
            # Validate SSH key
            if not self._validate_ssh_key():
                return False
            
            # Validate required binaries
            for binary in [self.bird_bin, self.birdc_bin]:
                if not Path(binary).exists():
                    logger.error(f"Required binary not found: {binary}")
                    return False
                if not os.access(binary, os.X_OK):
                    logger.error(f"Binary not executable: {binary}")
                    return False
            
            # Validate router configurations exist
            missing_configs = []
            for router in self.routers:
                if not router.config_dir.exists():
                    missing_configs.append(router.name)
            
            if missing_configs:
                logger.error(f"Missing configuration directories: {missing_configs}")
                return False
            
            logger.info("✓ Environment validation passed")
            return True
            
        except Exception as e:
            logger.error(f"Environment validation failed: {e}")
            return False
    
    def _validate_ssh_key(self) -> bool:
        """Validate SSH key"""
        if not self.ssh_key_path.exists():
            logger.error(f"SSH key not found: {self.ssh_key_path}")
            return False
        
        if not os.access(self.ssh_key_path, os.R_OK):
            logger.error(f"SSH key not readable: {self.ssh_key_path}")
            return False
        
        # Check key permissions
        key_perms = oct(self.ssh_key_path.stat().st_mode)[-3:]
        if key_perms not in ['600', '400']:
            logger.warning(f"SSH key permissions are {key_perms}, should be 600 or 400")
        
        # Validate key format
        try:
            result = subprocess.run(
                ['ssh-keygen', '-l', '-f', str(self.ssh_key_path)],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                logger.error(f"SSH key validation failed: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"Failed to validate SSH key: {e}")
            return False
        
        logger.debug(f"✓ SSH key validated: {self.ssh_key_path}")
        return True
    
    def comprehensive_validation(self) -> bool:
        """Perform comprehensive pre-deployment validation"""
        logger.info("Performing comprehensive configuration validation...")
        
        validation_errors = 0
        
        for router in self.routers:
            logger.info(f"Validating configuration for {router.name}")
            
            try:
                # Get vendor plugin
                vendor_plugin = self.plugin_manager.get_vendor_plugin(router.vendor)
                if not vendor_plugin:
                    logger.error(f"No plugin found for vendor: {router.vendor}")
                    validation_errors += 1
                    continue
                
                # Validate BIRD configurations
                bird_configs = ['bird.conf', 'bird6.conf']
                for config_file in bird_configs:
                    config_path = router.config_dir / config_file
                    
                    if config_path.exists():
                        if not self._validate_bird_config(config_path, router.vendor):
                            validation_errors += 1
                    else:
                        logger.warning(f"Configuration file not found: {config_path}")
                
                # Validate essential configuration sections
                if not self._validate_config_sections(router):
                    validation_errors += 1
                
            except Exception as e:
                logger.error(f"Validation failed for {router.name}: {e}")
                validation_errors += 1
        
        if validation_errors > 0:
            logger.error(f"Configuration validation failed with {validation_errors} errors")
            return False
        
        logger.info("✓ Comprehensive validation passed")
        return True
    
    def _validate_bird_config(self, config_path: Path, vendor: str) -> bool:
        """Validate BIRD configuration file"""
        try:
            # Get vendor plugin for validation
            vendor_plugin = self.plugin_manager.get_vendor_plugin(vendor)
            if vendor_plugin:
                with open(config_path, 'r') as f:
                    config_content = f.read()
                return vendor_plugin.validate_config(config_content)
            else:
                # Fallback to direct BIRD validation
                if 'bird6' in config_path.name:
                    binary = self.bird6_bin
                else:
                    binary = self.bird_bin
                
                result = subprocess.run(
                    [binary, '-p', '-c', str(config_path)],
                    capture_output=True, text=True, timeout=30
                )
                
                if result.returncode == 0:
                    logger.debug(f"✓ Configuration validated: {config_path}")
                    return True
                else:
                    logger.error(f"Configuration validation failed for {config_path}:")
                    logger.error(result.stderr)
                    return False
                    
        except Exception as e:
            logger.error(f"Error validating configuration {config_path}: {e}")
            return False
    
    def _validate_config_sections(self, router: RouterInfo) -> bool:
        """Validate essential configuration sections exist"""
        essential_files = [
            'header-ipv4.conf',
            'header-ipv6.conf',
            'interfaces-ipv4.conf', 
            'interfaces-ipv6.conf',
            'peerings/peers.ipv4.conf',
            'peerings/peers.ipv6.conf'
        ]
        
        for file_path in essential_files:
            full_path = router.config_dir / file_path
            if not full_path.exists():
                logger.error(f"Essential configuration file missing: {full_path}")
                return False
            
            if full_path.stat().st_size == 0:
                logger.warning(f"Configuration file is empty: {full_path}")
        
        return True
    
    def deploy_all(self) -> bool:
        """Deploy configurations to all routers"""
        logger.info(f"Starting deployment to {len(self.routers)} routers...")
        
        # Track deployment start
        track_event(
            EventType.DEPLOYMENT_START,
            "update_routers",
            f"Starting deployment to {len(self.routers)} routers",
            details={
                "router_count": len(self.routers),
                "routers": [r.name for r in self.routers],
                "parallel_deployments": self.max_parallel_deployments
            }
        )
        
        deployment_start_time = time.time()
        successful_deployments = 0
        failed_deployments = 0
        
        # Use thread pool for parallel deployments
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_parallel_deployments) as executor:
            # Submit deployment tasks
            future_to_router = {
                executor.submit(self._deploy_single_router, router): router 
                for router in self.routers
            }
            
            # Collect results
            for future in concurrent.futures.as_completed(future_to_router, timeout=self.deployment_timeout):
                router = future_to_router[future]
                
                try:
                    success = future.result()
                    if success:
                        successful_deployments += 1
                        logger.info(f"✓ Successfully deployed to {router.name}")
                    else:
                        failed_deployments += 1
                        logger.error(f"✗ Failed to deploy to {router.name}")
                        
                except Exception as e:
                    failed_deployments += 1
                    logger.error(f"✗ Deployment to {router.name} raised exception: {e}")
        
        # Calculate metrics
        deployment_end_time = time.time()
        total_duration_ms = int((deployment_end_time - deployment_start_time) * 1000)
        
        # Track deployment completion
        success = failed_deployments == 0
        
        track_event(
            EventType.DEPLOYMENT_SUCCESS if success else EventType.DEPLOYMENT_FAILURE,
            "update_routers",
            f"Deployment completed: {successful_deployments} successful, {failed_deployments} failed",
            details={
                "successful_deployments": successful_deployments,
                "failed_deployments": failed_deployments,
                "total_routers": len(self.routers),
                "success_rate": (successful_deployments / len(self.routers)) * 100,
                "total_duration_ms": total_duration_ms
            },
            duration_ms=total_duration_ms,
            success=success
        )
        
        if success:
            logger.info(f"✓ All deployments completed successfully in {total_duration_ms/1000:.1f}s")
        else:
            logger.error(f"✗ Deployment completed with {failed_deployments} failures")
        
        return success
    
    def _deploy_single_router(self, router: RouterInfo) -> bool:
        """Deploy configuration to a single router"""
        logger.info(f"Deploying configuration to {router.name}")
        
        deployment_start_time = time.time()
        
        try:
            # Skip if in maintenance mode
            if router.maintenance_mode:
                logger.info(f"Skipping {router.name} - in maintenance mode")
                return True
            
            # Generate configuration hash for tracking
            config_hash = self._calculate_config_hash(router)
            
            # Copy configuration files
            if not self._upload_configs(router):
                return False
            
            # Reload BIRD configuration
            if not self._reload_bird_config(router):
                return False
            
            # Calculate deployment metrics
            deployment_end_time = time.time()
            duration_ms = int((deployment_end_time - deployment_start_time) * 1000)
            
            # Track successful deployment
            deployment_record = DeploymentRecord(
                router=router.name,
                config_hash=config_hash,
                deployment_method="ssh",
                duration_ms=duration_ms,
                success=True,
                validation_passed=True
            )
            
            self.state_manager.track_deployment(deployment_record)
            
            return True
            
        except Exception as e:
            # Calculate deployment metrics for failed deployment
            deployment_end_time = time.time()
            duration_ms = int((deployment_end_time - deployment_start_time) * 1000)
            
            logger.error(f"Deployment to {router.name} failed: {e}")
            
            # Track failed deployment
            deployment_record = DeploymentRecord(
                router=router.name,
                config_hash="unknown",
                deployment_method="ssh",
                duration_ms=duration_ms,
                success=False,
                error_message=str(e),
                validation_passed=False
            )
            
            self.state_manager.track_deployment(deployment_record)
            
            return False
    
    def _calculate_config_hash(self, router: RouterInfo) -> str:
        """Calculate hash of router configuration"""
        import hashlib
        
        hash_obj = hashlib.sha256()
        
        # Hash all configuration files
        for config_file in router.config_dir.rglob('*.conf'):
            try:
                with open(config_file, 'rb') as f:
                    hash_obj.update(f.read())
            except Exception:
                pass  # Skip files that can't be read
        
        return hash_obj.hexdigest()[:16]
    
    def _upload_configs(self, router: RouterInfo) -> bool:
        """Upload configuration files to router"""
        try:
            # Use rsync for efficient file transfer
            rsync_cmd = [
                'rsync', '-avz', '--delete',
                '-e', f'ssh -i {self.ssh_key_path} -o ConnectTimeout={self.ssh_timeout} -o StrictHostKeyChecking=yes',
                f'{router.config_dir}/',
                f'{self.ssh_user}@{router.fqdn}:/etc/bird/'
            ]
            
            result = subprocess.run(
                rsync_cmd,
                capture_output=True, text=True, timeout=120
            )
            
            if result.returncode == 0:
                logger.debug(f"✓ Configuration uploaded to {router.name}")
                return True
            else:
                logger.error(f"rsync failed for {router.name}: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error(f"Upload to {router.name} timed out")
            return False
        except Exception as e:
            logger.error(f"Failed to upload configs to {router.name}: {e}")
            return False
    
    def _reload_bird_config(self, router: RouterInfo) -> bool:
        """Reload BIRD configuration on router"""
        try:
            # SSH command to reload BIRD
            ssh_cmd = [
                'ssh',
                '-i', str(self.ssh_key_path),
                '-o', f'ConnectTimeout={self.ssh_timeout}',
                '-o', 'StrictHostKeyChecking=yes',
                f'{self.ssh_user}@{router.fqdn}',
                'chown -R root: /etc/bird && /usr/sbin/birdc configure && /usr/local/bin/birdc6 configure'
            ]
            
            result = subprocess.run(
                ssh_cmd,
                capture_output=True, text=True, timeout=60
            )
            
            if result.returncode == 0:
                logger.debug(f"✓ BIRD configuration reloaded on {router.name}")
                return True
            else:
                logger.error(f"BIRD reload failed on {router.name}: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error(f"BIRD reload on {router.name} timed out")
            return False
        except Exception as e:
            logger.error(f"Failed to reload BIRD on {router.name}: {e}")
            return False
    
    def check_router_status(self) -> Dict[str, Any]:
        """Check status of all routers"""
        logger.info("Checking router status...")
        
        status_results = {}
        
        for router in self.routers:
            try:
                # Get vendor plugin
                vendor_plugin = self.plugin_manager.get_vendor_plugin(router.vendor)
                
                if vendor_plugin and hasattr(vendor_plugin, 'get_config_status'):
                    # Use plugin to get status
                    status = vendor_plugin.get_config_status()
                else:
                    # Fallback to basic SSH check
                    status = self._check_router_ssh(router)
                
                status_results[router.name] = status
                
            except Exception as e:
                logger.error(f"Failed to check status of {router.name}: {e}")
                status_results[router.name] = {
                    'error': str(e),
                    'reachable': False
                }
        
        return status_results
    
    def _check_router_ssh(self, router: RouterInfo) -> Dict[str, Any]:
        """Basic SSH connectivity check"""
        try:
            ssh_cmd = [
                'ssh',
                '-i', str(self.ssh_key_path),
                '-o', f'ConnectTimeout={self.ssh_timeout}',
                '-o', 'StrictHostKeyChecking=yes',
                f'{self.ssh_user}@{router.fqdn}',
                'echo "Connection OK"'
            ]
            
            result = subprocess.run(
                ssh_cmd,
                capture_output=True, text=True, timeout=30
            )
            
            return {
                'reachable': result.returncode == 0,
                'response_time': 'unknown',
                'last_check': datetime.now().isoformat()
            }
            
        except Exception as e:
            return {
                'reachable': False,
                'error': str(e),
                'last_check': datetime.now().isoformat()
            }


def main():
    """Main CLI interface"""
    parser = argparse.ArgumentParser(
        description="AutoNet Router Configuration Deployment Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s push                    Deploy configurations to all routers
  %(prog)s check                   Validate configurations without deploying
  %(prog)s status                  Check router connectivity and status
  %(prog)s --debug push            Deploy with debug logging
        """
    )
    
    parser.add_argument('action', 
                       choices=['push', 'check', 'status'],
                       help='Action to perform')
    
    parser.add_argument('--debug', '-d', 
                       action='store_true',
                       help='Enable debug logging')
    
    parser.add_argument('--config', '-c',
                       help='Configuration file path')
    
    parser.add_argument('--router', '-r',
                       help='Deploy to specific router only')
    
    parser.add_argument('--parallel', '-p',
                       type=int, default=3,
                       help='Maximum parallel deployments')
    
    parser.add_argument('--timeout', '-t',
                       type=int, default=300,
                       help='Deployment timeout in seconds')
    
    args = parser.parse_args()
    
    # Configure logging level
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")
    
    try:
        # Load configuration
        config_manager = get_config_manager()
        config = config_manager.load_configuration(args.config)
        
        # Override config with command line arguments
        if args.parallel:
            config['max_parallel_deployments'] = args.parallel
        if args.timeout:
            config['deployment_timeout'] = args.timeout
        
        # Create deployer
        deployer = AutoNetDeployer(config)
        
        # Filter routers if specific router requested
        if args.router:
            deployer.routers = [r for r in deployer.routers if args.router in r.name]
            if not deployer.routers:
                logger.error(f"Router not found: {args.router}")
                sys.exit(EXIT_CONFIG_ERROR)
        
        # Perform requested action
        if args.action == 'check':
            # Validation only
            if not deployer.validate_environment():
                sys.exit(EXIT_CONFIG_ERROR)
            
            if not deployer.comprehensive_validation():
                sys.exit(EXIT_VALIDATION_ERROR)
            
            logger.info("✓ All validations passed")
            
        elif args.action == 'status':
            # Status check
            status_results = deployer.check_router_status()
            
            print(f"\nRouter Status Report:")
            print("=" * 50)
            
            for router_name, status in status_results.items():
                reachable = status.get('reachable', False)
                status_icon = "✓" if reachable else "✗"
                print(f"{status_icon} {router_name}: {'OK' if reachable else 'UNREACHABLE'}")
                
                if 'error' in status:
                    print(f"    Error: {status['error']}")
            
        elif args.action == 'push':
            # Full deployment
            if not deployer.validate_environment():
                sys.exit(EXIT_CONFIG_ERROR)
            
            if not deployer.comprehensive_validation():
                sys.exit(EXIT_VALIDATION_ERROR)
            
            if not deployer.deploy_all():
                sys.exit(EXIT_UPLOAD_ERROR)
            
            logger.info("✓ Deployment completed successfully")
        
        sys.exit(EXIT_SUCCESS)
        
    except ConfigurationError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(EXIT_CONFIG_ERROR)
    except KeyboardInterrupt:
        logger.info("Deployment cancelled by user")
        sys.exit(EXIT_SUCCESS)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        sys.exit(EXIT_TOOL_ERROR)


if __name__ == "__main__":
    main()