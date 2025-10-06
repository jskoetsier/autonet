#!/usr/bin/env python3
"""
AutoNet - Unified Command Line Interface

Modern Python-based network automation toolchain with unified CLI interface.
Replaces all bash scripts with integrated Python tools.
"""

import os
import sys
import argparse
import logging
from pathlib import Path

# Import AutoNet modules
from lib.config_manager import get_config_manager, ConfigurationError
from lib.plugin_system import initialize_plugin_system
from lib.state_manager import get_state_manager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def setup_common_args(parser):
    """Add common arguments to parser"""
    parser.add_argument('--config', '-c', help='Configuration file path')
    parser.add_argument('--debug', '-d', action='store_true', help='Enable debug logging')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose output')


def cmd_generate(args):
    """Generate router configurations"""
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Import and run peering_filters functionality
    import subprocess
    cmd = [sys.executable, 'peering_filters']

    if 'all' in args.targets:
        cmd.append('all')
    else:
        if 'configs' in args.targets:
            cmd.append('configs')
        if 'prefixsets' in args.targets:
            cmd.append('prefixsets')

    if args.no_checks:
        cmd.append('--no-checks')

    if args.debug:
        cmd.append('debug')

    result = subprocess.run(cmd, cwd=Path.cwd())
    return result.returncode


def cmd_deploy(args):
    """Deploy configurations to routers"""
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Import and run update_routers functionality
    from update_routers import AutoNetDeployer

    try:
        # Load configuration
        config_manager = get_config_manager()
        config = config_manager.load_configuration(args.config)

        # Create deployer
        deployer = AutoNetDeployer(config)

        # Filter routers if specified
        if args.router:
            deployer.routers = [r for r in deployer.routers if args.router in r.name]
            if not deployer.routers:
                logger.error(f"Router not found: {args.router}")
                return 1

        # Perform action
        if args.action == 'check':
            if not deployer.validate_environment():
                return 1
            if not deployer.comprehensive_validation():
                return 4
            logger.info("✓ All validations passed")
            return 0

        elif args.action == 'status':
            status_results = deployer.check_router_status()
            print(f"\nRouter Status Report:")
            print("=" * 50)
            for router_name, status in status_results.items():
                reachable = status.get('reachable', False)
                status_icon = "✓" if reachable else "✗"
                print(f"{status_icon} {router_name}: {'OK' if reachable else 'UNREACHABLE'}")
                if 'error' in status:
                    print(f"    Error: {status['error']}")
            return 0

        elif args.action == 'push':
            if not deployer.validate_environment():
                return 1
            if not deployer.comprehensive_validation():
                return 4
            if not deployer.deploy_all():
                return 5
            logger.info("✓ Deployment completed successfully")
            return 0

    except Exception as e:
        logger.error(f"Deployment error: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        return 2


def cmd_peer_config(args):
    """Generate peer configurations"""
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    from generate_peer_config import PeerConfigGenerator

    try:
        # Load configuration
        config_manager = get_config_manager()
        config = config_manager.load_configuration(args.config)

        # Create generator
        generator = PeerConfigGenerator(config)

        # Handle list vendors
        if args.list_vendors:
            vendors = generator.list_available_vendors()
            print("Available vendor plugins:")
            for vendor in vendors:
                features = generator.get_vendor_features(vendor)
                print(f"  • {vendor}: {', '.join(features) if features else 'no features listed'}")
            return 0

        # Handle single peer generation
        if args.asn:
            peer_info = {
                'asn': args.asn,
                'name': args.name or f"Peer {args.asn}",
                'description': args.description or f"BGP peer {args.asn}"
            }

            if args.ipv4:
                peer_info['ipv4'] = args.ipv4
            if args.ipv6:
                peer_info['ipv6'] = args.ipv6

            config_content = generator.generate_peer_config(
                args.asn, peer_info, args.vendor, args.output
            )

            if not args.output:
                print(config_content)

            return 0

        # Handle peer file
        if args.peer_file:
            import json
            with open(args.peer_file, 'r') as f:
                peer_data = json.load(f)

            if isinstance(peer_data, list):
                peer_list = peer_data
            else:
                peer_list = [peer_data]

            results = generator.generate_multiple_peers(peer_list, args.vendor)

            if args.output_dir:
                output_dir = Path(args.output_dir)
                output_dir.mkdir(parents=True, exist_ok=True)

                for asn, config_content in results.items():
                    output_file = output_dir / f"{asn.lower()}.conf"
                    with open(output_file, 'w') as f:
                        f.write(config_content)
                    print(f"✓ Generated: {output_file}")
            else:
                for asn, config_content in results.items():
                    print(f"\n# Configuration for {asn}")
                    print(config_content)

            return 0

        logger.error("No peer information provided")
        return 1

    except Exception as e:
        logger.error(f"Peer config generation error: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        return 2


def cmd_state(args):
    """State management operations"""
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    from lib.state_manager import StateManager

    try:
        # Load configuration
        config_manager = get_config_manager()
        config = config_manager.load_configuration(args.config)

        # Create state manager
        state_manager = get_state_manager(config=config)

        if args.action == 'events':
            events = state_manager.get_recent_events(args.limit or 50)
            print(f"Recent {len(events)} events:")
            for event in events:
                status = "✓" if event.success else "✗"
                print(f"  {status} {event.timestamp.strftime('%Y-%m-%d %H:%M:%S')} "
                     f"[{event.component}] {event.event_type.value}: {event.message}")

        elif args.action == 'generations':
            generations = state_manager.get_recent_generations(args.limit or 20)
            print(f"Recent {len(generations)} generations:")
            for gen in generations:
                status = "✓" if gen.success else "✗"
                duration = f"{gen.duration_ms/1000:.1f}s" if gen.duration_ms else "N/A"
                memory = f"{gen.memory_peak_mb:.1f}MB" if gen.memory_peak_mb else "N/A"
                print(f"  {status} {gen.timestamp.strftime('%Y-%m-%d %H:%M:%S')} "
                     f"Peers: {gen.peer_count}, Duration: {duration}, Memory: {memory}")

        elif args.action == 'deployments':
            deployments = state_manager.get_deployment_history(args.router, args.limit or 20)
            print(f"Recent {len(deployments)} deployments:")
            for dep in deployments:
                status = "✓" if dep.success else "✗"
                duration = f"{dep.duration_ms/1000:.1f}s" if dep.duration_ms else "N/A"
                print(f"  {status} {dep.timestamp.strftime('%Y-%m-%d %H:%M:%S')} "
                     f"{dep.router} Duration: {duration}")

        elif args.action == 'stats':
            stats = state_manager.get_performance_stats(args.days or 7)
            import json
            print(json.dumps(stats, indent=2))

        elif args.action == 'cleanup':
            stats = state_manager.cleanup_old_data()
            print(f"Cleanup completed: {stats}")

        elif args.action == 'export':
            if state_manager.export_data(args.output or 'autonet_state.json'):
                print(f"✓ Data exported to {args.output or 'autonet_state.json'}")
            else:
                print("✗ Export failed")
                return 1

        return 0

    except Exception as e:
        logger.error(f"State management error: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        return 2


def cmd_config(args):
    """Configuration management operations"""
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    from lib.config_manager import get_config_manager

    try:
        config_manager = get_config_manager()

        if args.action == 'validate':
            config = config_manager.load_configuration(args.config_file)
            if config_manager.validate_environment():
                print("✓ Configuration validation passed")
                return 0
            else:
                print("✗ Configuration validation failed")
                return 1

        elif args.action == 'show':
            config = config_manager.load_configuration(args.config_file)
            import json

            if args.key:
                # Show specific key
                keys = args.key.split('.')
                value = config
                for key in keys:
                    if isinstance(value, dict) and key in value:
                        value = value[key]
                    else:
                        print(f"Key not found: {args.key}")
                        return 1
                print(json.dumps(value, indent=2, default=str))
            else:
                # Show entire config
                print(json.dumps(config, indent=2, default=str))

        elif args.action == 'metadata':
            config = config_manager.load_configuration(args.config_file)
            metadata = config_manager.get_metadata()
            if metadata:
                print(f"Configuration Metadata:")
                print(f"  Version: {metadata.version}")
                print(f"  Schema Version: {metadata.schema_version}")
                print(f"  Environment: {metadata.environment}")
                print(f"  Loaded At: {metadata.loaded_at}")
                print(f"  Source Files: {', '.join(metadata.source_files)}")
                print(f"  Validation Passed: {metadata.validation_passed}")

        return 0

    except Exception as e:
        logger.error(f"Configuration error: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        return 2


def main():
    """Main CLI interface"""
    parser = argparse.ArgumentParser(
        description="AutoNet - Network Automation Toolchain v2.1",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
AutoNet Commands:
  generate    Generate router configurations (replaces peering_filters)
  deploy      Deploy configurations to routers (replaces update-routers.sh)
  peer-config Generate peer-specific configurations
  state       State management and monitoring
  config      Configuration management

Examples:
  autonet generate all                    # Generate all configurations
  autonet deploy push                     # Deploy to all routers
  autonet deploy check                    # Validate without deploying
  autonet peer-config --asn AS64512 --vendor bird2
  autonet state events --limit 100       # Show recent events
  autonet config validate                 # Validate configuration
        """
    )

    # Global options
    setup_common_args(parser)

    # Subcommands
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Generate command
    gen_parser = subparsers.add_parser('generate', help='Generate router configurations')
    gen_parser.add_argument('targets', nargs='*', default=['all'],
                           choices=['all', 'configs', 'prefixsets'],
                           help='What to generate')
    gen_parser.add_argument('--no-checks', action='store_true',
                           help='Skip existence checks for prefix sets')
    setup_common_args(gen_parser)

    # Deploy command
    deploy_parser = subparsers.add_parser('deploy', help='Deploy configurations to routers')
    deploy_parser.add_argument('action', choices=['push', 'check', 'status'],
                              help='Deployment action')
    deploy_parser.add_argument('--router', '-r', help='Deploy to specific router only')
    deploy_parser.add_argument('--parallel', '-p', type=int, default=3,
                              help='Maximum parallel deployments')
    deploy_parser.add_argument('--timeout', '-t', type=int, default=300,
                              help='Deployment timeout in seconds')
    setup_common_args(deploy_parser)

    # Peer config command
    peer_parser = subparsers.add_parser('peer-config', help='Generate peer configurations')
    peer_parser.add_argument('--asn', help='Peer ASN (e.g., AS64512)')
    peer_parser.add_argument('--name', help='Peer name')
    peer_parser.add_argument('--ipv4', help='Peer IPv4 address')
    peer_parser.add_argument('--ipv6', help='Peer IPv6 address')
    peer_parser.add_argument('--description', help='Peer description')
    peer_parser.add_argument('--vendor', default='bird', help='Target vendor')
    peer_parser.add_argument('--output', '-o', help='Output file path')
    peer_parser.add_argument('--output-dir', help='Output directory for multiple files')
    peer_parser.add_argument('--peer-file', help='JSON file with peer information')
    peer_parser.add_argument('--list-vendors', action='store_true',
                            help='List available vendor plugins')
    setup_common_args(peer_parser)

    # State command
    state_parser = subparsers.add_parser('state', help='State management and monitoring')
    state_parser.add_argument('action',
                             choices=['events', 'generations', 'deployments', 'stats', 'cleanup', 'export'],
                             help='State management action')
    state_parser.add_argument('--limit', type=int, help='Limit number of results')
    state_parser.add_argument('--router', help='Filter by router name')
    state_parser.add_argument('--days', type=int, help='Number of days for stats')
    state_parser.add_argument('--output', help='Output file for export')
    setup_common_args(state_parser)

    # Config command
    config_parser = subparsers.add_parser('config', help='Configuration management')
    config_parser.add_argument('action', choices=['validate', 'show', 'metadata'],
                              help='Configuration action')
    config_parser.add_argument('--config-file', help='Configuration file to process')
    config_parser.add_argument('--key', help='Specific configuration key to show')
    setup_common_args(config_parser)

    # Parse arguments
    args = parser.parse_args()

    # Configure logging
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    elif args.verbose:
        logging.getLogger().setLevel(logging.INFO)

    # Execute command
    try:
        if args.command == 'generate':
            return cmd_generate(args)
        elif args.command == 'deploy':
            return cmd_deploy(args)
        elif args.command == 'peer-config':
            return cmd_peer_config(args)
        elif args.command == 'state':
            return cmd_state(args)
        elif args.command == 'config':
            return cmd_config(args)
        else:
            parser.print_help()
            return 1

    except KeyboardInterrupt:
        logger.info("Operation cancelled by user")
        return 0
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())
