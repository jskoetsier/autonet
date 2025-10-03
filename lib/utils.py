#!/usr/bin/env python3
"""
AutoNet Utility Functions

Python replacement for functions.sh with enhanced functionality and integration
with the new architecture.
"""

import os
import sys
import yaml
import subprocess
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Union, List
import ipaddress
import shlex

logger = logging.getLogger(__name__)


def get_config_value(key: str, default: Any = None, config_file: str = "vars/generic.yml") -> Any:
    """
    Get configuration value from YAML file with robust error handling
    
    Python replacement for the bash getconfig function
    
    Args:
        key: Configuration key (supports nested keys with dot notation like 'rpki.validation')
        default: Default value if key not found
        config_file: Path to configuration file
        
    Returns:
        Configuration value or default
    """
    try:
        config_path = Path(config_file)
        
        if not config_path.exists():
            logger.warning(f"Configuration file not found: {config_file}")
            return default
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        if config is None:
            logger.warning(f"Configuration file is empty: {config_file}")
            return default
        
        # Navigate nested keys (e.g., 'rpki.validation')
        keys = key.split('.')
        current = config
        
        for k in keys:
            if isinstance(current, dict) and k in current:
                current = current[k]
            else:
                logger.debug(f"Configuration key not found: {key}")
                return default
        
        # Validate return type
        if isinstance(current, (str, int, float, bool)):
            return current
        elif isinstance(current, list):
            # Convert list to string for compatibility
            return ','.join(str(item) for item in current)
        elif isinstance(current, dict):
            logger.warning(f"Configuration key {key} is a dict, returning default")
            return default
        else:
            return current
            
    except yaml.YAMLError as e:
        logger.error(f"YAML error in {config_file}: {e}")
        return default
    except Exception as e:
        logger.error(f"Error reading configuration {config_file}: {e}")
        return default


def validate_directory(path: Union[str, Path], create: bool = False, writable: bool = False) -> bool:
    """
    Validate directory exists and has required permissions
    
    Args:
        path: Directory path to validate
        create: Create directory if it doesn't exist
        writable: Check if directory is writable
        
    Returns:
        True if directory is valid, False otherwise
    """
    try:
        dir_path = Path(path)
        
        if not dir_path.exists():
            if create:
                dir_path.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created directory: {dir_path}")
            else:
                logger.error(f"Directory does not exist: {dir_path}")
                return False
        
        if not dir_path.is_dir():
            logger.error(f"Path is not a directory: {dir_path}")
            return False
        
        if writable and not os.access(dir_path, os.W_OK):
            logger.error(f"Directory is not writable: {dir_path}")
            return False
        
        return True
        
    except Exception as e:
        logger.error(f"Error validating directory {path}: {e}")
        return False


def run_command(command: List[str], timeout: int = 30, capture_output: bool = True, 
               check: bool = False, cwd: Optional[str] = None) -> subprocess.CompletedProcess:
    """
    Run shell command with proper error handling and logging
    
    Args:
        command: Command and arguments as list
        timeout: Command timeout in seconds
        capture_output: Capture stdout/stderr
        check: Raise exception on non-zero exit
        cwd: Working directory for command
        
    Returns:
        CompletedProcess result
    """
    try:
        logger.debug(f"Running command: {' '.join(command)}")
        
        result = subprocess.run(
            command,
            timeout=timeout,
            capture_output=capture_output,
            text=True,
            check=check,
            cwd=cwd
        )
        
        if result.returncode != 0:
            logger.warning(f"Command failed with exit code {result.returncode}: {' '.join(command)}")
            if capture_output and result.stderr:
                logger.warning(f"Command stderr: {result.stderr}")
        
        return result
        
    except subprocess.TimeoutExpired as e:
        logger.error(f"Command timed out after {timeout}s: {' '.join(command)}")
        raise
    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed: {' '.join(command)}")
        logger.error(f"Exit code: {e.returncode}")
        if e.stderr:
            logger.error(f"Stderr: {e.stderr}")
        raise
    except Exception as e:
        logger.error(f"Error running command {' '.join(command)}: {e}")
        raise


def safe_shell_command(command: str, **kwargs) -> subprocess.CompletedProcess:
    """
    Run shell command string with proper escaping
    
    Args:
        command: Shell command string
        **kwargs: Additional arguments for run_command
        
    Returns:
        CompletedProcess result
    """
    # Parse command string safely
    try:
        command_list = shlex.split(command)
        return run_command(command_list, **kwargs)
    except ValueError as e:
        logger.error(f"Invalid shell command: {command}")
        raise


def check_binary_exists(binary_path: str, executable_check: bool = True) -> bool:
    """
    Check if binary exists and is executable
    
    Args:
        binary_path: Path to binary
        executable_check: Check if binary is executable
        
    Returns:
        True if binary is valid, False otherwise
    """
    try:
        binary = Path(binary_path)
        
        if not binary.exists():
            logger.error(f"Binary not found: {binary_path}")
            return False
        
        if not binary.is_file():
            logger.error(f"Path is not a file: {binary_path}")
            return False
        
        if executable_check and not os.access(binary, os.X_OK):
            logger.error(f"Binary is not executable: {binary_path}")
            return False
        
        return True
        
    except Exception as e:
        logger.error(f"Error checking binary {binary_path}: {e}")
        return False


def get_system_info() -> Dict[str, str]:
    """
    Get system information for debugging and logging
    
    Returns:
        Dictionary with system information
    """
    try:
        import platform
        import socket
        
        return {
            'hostname': socket.gethostname(),
            'platform': platform.platform(),
            'python_version': platform.python_version(),
            'architecture': platform.architecture()[0],
            'processor': platform.processor(),
            'user': os.getenv('USER', 'unknown'),
            'working_directory': str(Path.cwd())
        }
    except Exception as e:
        logger.error(f"Error getting system info: {e}")
        return {'error': str(e)}


def format_bytes(bytes_value: int) -> str:
    """
    Format bytes value in human-readable format
    
    Args:
        bytes_value: Number of bytes
        
    Returns:
        Formatted string (e.g., "1.5 MB")
    """
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_value < 1024.0:
            return f"{bytes_value:.1f} {unit}"
        bytes_value /= 1024.0
    return f"{bytes_value:.1f} PB"


def format_duration(seconds: float) -> str:
    """
    Format duration in human-readable format
    
    Args:
        seconds: Duration in seconds
        
    Returns:
        Formatted string (e.g., "1m 30s")
    """
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        remaining_seconds = seconds % 60
        return f"{minutes}m {remaining_seconds:.1f}s"
    else:
        hours = int(seconds // 3600)
        remaining_minutes = int((seconds % 3600) // 60)
        return f"{hours}h {remaining_minutes}m"


def validate_network_address(address: str, address_type: str = "auto") -> bool:
    """
    Validate network address (IPv4, IPv6, or CIDR)
    
    Args:
        address: Network address to validate
        address_type: Type of address ("ipv4", "ipv6", "cidr", "auto")
        
    Returns:
        True if address is valid, False otherwise
    """
    try:
        if address_type == "auto":
            # Try to determine type automatically
            if '/' in address:
                # CIDR notation
                ipaddress.ip_network(address, strict=False)
                return True
            else:
                # Single IP address
                ipaddress.ip_address(address)
                return True
        elif address_type == "ipv4":
            ipaddress.IPv4Address(address)
            return True
        elif address_type == "ipv6":
            ipaddress.IPv6Address(address)
            return True
        elif address_type == "cidr":
            ipaddress.ip_network(address, strict=False)
            return True
        else:
            logger.error(f"Unknown address type: {address_type}")
            return False
            
    except Exception as e:
        logger.debug(f"Invalid network address {address}: {e}")
        return False


def ensure_file_permissions(file_path: Union[str, Path], mode: int) -> bool:
    """
    Ensure file has correct permissions
    
    Args:
        file_path: Path to file
        mode: Octal permission mode (e.g., 0o600)
        
    Returns:
        True if permissions set successfully, False otherwise
    """
    try:
        path = Path(file_path)
        
        if not path.exists():
            logger.error(f"File does not exist: {file_path}")
            return False
        
        current_mode = path.stat().st_mode & 0o777
        if current_mode != mode:
            path.chmod(mode)
            logger.debug(f"Changed permissions of {file_path} to {oct(mode)}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error setting permissions for {file_path}: {e}")
        return False


def create_backup_file(source_path: Union[str, Path], backup_suffix: str = None) -> Optional[Path]:
    """
    Create backup of file with timestamp
    
    Args:
        source_path: Path to source file
        backup_suffix: Custom backup suffix (default: timestamp)
        
    Returns:
        Path to backup file if successful, None otherwise
    """
    try:
        source = Path(source_path)
        
        if not source.exists():
            logger.error(f"Source file does not exist: {source_path}")
            return None
        
        if backup_suffix is None:
            from datetime import datetime
            backup_suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        backup_path = source.with_suffix(f"{source.suffix}.backup.{backup_suffix}")
        
        import shutil
        shutil.copy2(source, backup_path)
        
        logger.info(f"Created backup: {backup_path}")
        return backup_path
        
    except Exception as e:
        logger.error(f"Error creating backup of {source_path}: {e}")
        return None


def cleanup_old_files(directory: Union[str, Path], pattern: str, max_age_days: int) -> int:
    """
    Clean up old files matching pattern
    
    Args:
        directory: Directory to clean
        pattern: File pattern to match
        max_age_days: Maximum age in days
        
    Returns:
        Number of files deleted
    """
    try:
        import time
        from datetime import datetime, timedelta
        
        dir_path = Path(directory)
        cutoff_time = time.time() - (max_age_days * 24 * 3600)
        deleted_count = 0
        
        for file_path in dir_path.glob(pattern):
            if file_path.is_file() and file_path.stat().st_mtime < cutoff_time:
                try:
                    file_path.unlink()
                    deleted_count += 1
                    logger.debug(f"Deleted old file: {file_path}")
                except Exception as e:
                    logger.warning(f"Failed to delete {file_path}: {e}")
        
        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old files from {directory}")
        
        return deleted_count
        
    except Exception as e:
        logger.error(f"Error cleaning up files in {directory}: {e}")
        return 0


def get_file_hash(file_path: Union[str, Path], algorithm: str = "sha256") -> Optional[str]:
    """
    Calculate hash of file
    
    Args:
        file_path: Path to file
        algorithm: Hash algorithm ("md5", "sha1", "sha256", "sha512")
        
    Returns:
        Hex digest of file hash, None if error
    """
    try:
        import hashlib
        
        hash_obj = getattr(hashlib, algorithm.lower())()
        
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hash_obj.update(chunk)
        
        return hash_obj.hexdigest()
        
    except Exception as e:
        logger.error(f"Error calculating hash of {file_path}: {e}")
        return None


def retry_operation(func, max_retries: int = 3, delay: float = 1.0, backoff_factor: float = 2.0, 
                   exceptions: tuple = (Exception,)):
    """
    Retry decorator for operations that might fail temporarily
    
    Args:
        func: Function to retry
        max_retries: Maximum number of retry attempts
        delay: Initial delay between retries
        backoff_factor: Multiplier for delay on each retry
        exceptions: Tuple of exceptions that trigger retry
        
    Returns:
        Decorated function result
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            current_delay = delay
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_retries:
                        logger.error(f"Operation failed after {max_retries} retries: {e}")
                        raise
                    
                    logger.warning(f"Attempt {attempt + 1} failed, retrying in {current_delay}s: {e}")
                    time.sleep(current_delay)
                    current_delay *= backoff_factor
            
        return wrapper
    return decorator


# Convenience functions for common operations
def get_builddir(default: str = "/opt/routefilters") -> str:
    """Get build directory from configuration"""
    return get_config_value("builddir", default)


def get_stagedir(default: str = "/opt/router-staging") -> str:
    """Get staging directory from configuration"""  
    return get_config_value("stagedir", default)


def get_bird_binary(default: str = "/usr/sbin/bird") -> str:
    """Get BIRD binary path from configuration"""
    return get_config_value("bird_bin", default)


def get_birdc_binary(default: str = "/usr/sbin/birdc") -> str:
    """Get BIRDC binary path from configuration"""
    return get_config_value("birdc_bin", default)


if __name__ == "__main__":
    # CLI interface for utility functions
    import argparse
    
    parser = argparse.ArgumentParser(description="AutoNet Utilities")
    parser.add_argument("--get-config", help="Get configuration value")
    parser.add_argument("--config-file", default="vars/generic.yml", help="Configuration file")
    parser.add_argument("--default", help="Default value for configuration")
    parser.add_argument("--validate-dir", help="Validate directory")
    parser.add_argument("--create-dir", action="store_true", help="Create directory if missing")
    parser.add_argument("--check-binary", help="Check if binary exists")
    parser.add_argument("--system-info", action="store_true", help="Show system information")
    
    args = parser.parse_args()
    
    try:
        if args.get_config:
            value = get_config_value(args.get_config, args.default, args.config_file)
            print(value)
        
        elif args.validate_dir:
            if validate_directory(args.validate_dir, create=args.create_dir, writable=True):
                print(f"✓ Directory is valid: {args.validate_dir}")
                sys.exit(0)
            else:
                print(f"✗ Directory validation failed: {args.validate_dir}")
                sys.exit(1)
        
        elif args.check_binary:
            if check_binary_exists(args.check_binary):
                print(f"✓ Binary is valid: {args.check_binary}")
                sys.exit(0)
            else:
                print(f"✗ Binary check failed: {args.check_binary}")
                sys.exit(1)
        
        elif args.system_info:
            import json
            info = get_system_info()
            print(json.dumps(info, indent=2))
        
        else:
            parser.print_help()
            
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)