#!/usr/bin/env python3
"""
AutoNet Peer Configuration Generator (Python Version)

Modern Python replacement for generate-peer-config.sh with enhanced features:
- Integration with new architecture v2.0
- Plugin-based vendor support
- Template-based configuration generation
- Comprehensive validation and error handling
- State tracking and performance monitoring
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Import AutoNet architecture components
from lib.config_manager import ConfigurationError, get_config_manager
from lib.plugin_system import get_plugin_manager, initialize_plugin_system, PluginType
from lib.state_manager import (
    EventType,
    GenerationRecord,
    get_state_manager,
    track_event,
)
from lib.utils import get_config_value, run_command, validate_directory

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


class PeerConfigGenerator:
    """
    Peer configuration generator with plugin support

    Features:
    - Template-based configuration generation
    - Plugin-based vendor support
    - Multi-format output (BIRD, BIRD2, etc.)
    - Validation and error checking
    - Performance monitoring
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

        # Initialize architecture components
        self.config_manager = get_config_manager()
        self.plugin_manager = initialize_plugin_system(self.config)
        self.state_manager = get_state_manager(config=self.config)

        # Configuration paths
        self.template_dir = Path(self.config.get("template_dir", "templates"))
        self.output_dir = Path(self.config.get("output_dir", "output"))

        # Ensure directories exist
        validate_directory(self.template_dir, create=False)
        validate_directory(self.output_dir, create=True, writable=True)

        logger.info("Peer Configuration Generator initialized")

    def generate_peer_config(
        self,
        asn: str,
        peer_info: Dict[str, Any],
        vendor: str = "bird",
        output_file: str = None,
    ) -> str:
        """
        Generate peer configuration for specific ASN and vendor

        Args:
            asn: Peer ASN (e.g., "AS64512")
            peer_info: Peer information dictionary
            vendor: Target vendor (bird, bird2, frr, etc.)
            output_file: Optional output file path

        Returns:
            Generated configuration content
        """
        logger.info(f"Generating peer configuration for {asn} (vendor: {vendor})")

        generation_start_time = time.time()

        try:
            # Get vendor plugin
            vendor_plugin = self.plugin_manager.get_vendor_plugin(vendor)
            if not vendor_plugin:
                raise ValueError(f"No plugin found for vendor: {vendor}")

            # Prepare template variables
            template_vars = self._prepare_template_vars(asn, peer_info)

            # Generate configuration using plugin
            config_content = vendor_plugin.generate_config(peer_info, template_vars)

            # Validate generated configuration
            if not vendor_plugin.validate_config(config_content):
                raise ValueError(f"Generated configuration failed validation for {asn}")

            # Save to file if requested
            if output_file:
                output_path = Path(output_file)
                output_path.parent.mkdir(parents=True, exist_ok=True)

                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(config_content)

                logger.info(f"Configuration saved to: {output_path}")

            # Track generation metrics
            generation_end_time = time.time()
            duration_ms = int((generation_end_time - generation_start_time) * 1000)

            track_event(
                EventType.GENERATION_SUCCESS,
                "generate_peer_config",
                f"Generated peer configuration for {asn}",
                details={
                    "asn": asn,
                    "vendor": vendor,
                    "config_size": len(config_content),
                    "output_file": output_file,
                    "duration_ms": duration_ms,
                },
                duration_ms=duration_ms,
            )

            logger.info(
                f"✓ Generated configuration for {asn} ({len(config_content)} chars)"
            )
            return config_content

        except Exception as e:
            logger.error(f"Failed to generate configuration for {asn}: {e}")

            track_event(
                EventType.GENERATION_FAILURE,
                "generate_peer_config",
                f"Failed to generate configuration for {asn}: {e}",
                details={"asn": asn, "vendor": vendor, "error": str(e)},
                success=False,
            )

            raise

    def _prepare_template_vars(
        self, asn: str, peer_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Prepare template variables for configuration generation"""
        # Base template variables
        template_vars = {
            "asn": asn,
            "timestamp": datetime.now().isoformat(),
            "generator": "AutoNet v2.0",
            **peer_info,
        }

        # Add configuration-specific variables
        template_vars.update(
            {
                "local_asn": self.config.get("local_asn", "AS64512"),
                "router_id": self.config.get("router_id", "192.0.2.1"),
                "bgp_local_pref": self.config.get("bgp_local_pref", 100),
                "irr_source": self.config.get("irr_source_host", "rr.ntt.net"),
                "irr_order": self.config.get("irr_order", "NTTCOM,INTERNAL,RADB,RIPE"),
            }
        )

        return template_vars

    def generate_multiple_peers(
        self, peer_list: List[Dict[str, Any]], vendor: str = "bird"
    ) -> Dict[str, str]:
        """
        Generate configurations for multiple peers

        Args:
            peer_list: List of peer information dictionaries
            vendor: Target vendor

        Returns:
            Dictionary mapping ASN to generated configuration
        """
        logger.info(f"Generating configurations for {len(peer_list)} peers")

        results = {}
        successful = 0
        failed = 0

        for peer_info in peer_list:
            asn = peer_info.get("asn")
            if not asn:
                logger.warning("Peer missing ASN, skipping")
                failed += 1
                continue

            try:
                config = self.generate_peer_config(asn, peer_info, vendor)
                results[asn] = config
                successful += 1

            except Exception as e:
                logger.error(f"Failed to generate config for {asn}: {e}")
                failed += 1

        logger.info(f"✓ Generated {successful} configurations, {failed} failed")
        return results

    def list_available_vendors(self) -> List[str]:
        """List available vendor plugins"""
        vendor_plugins = self.plugin_manager.get_plugins_by_type(PluginType.VENDOR)
        return [plugin.get_info().name for plugin in vendor_plugins]

    def get_vendor_features(self, vendor: str) -> List[str]:
        """Get supported features for a vendor"""
        vendor_plugin = self.plugin_manager.get_vendor_plugin(vendor)
        if vendor_plugin:
            return vendor_plugin.get_supported_features()
        return []

    def validate_peer_info(self, peer_info: Dict[str, Any]) -> List[str]:
        """
        Validate peer information

        Args:
            peer_info: Peer information dictionary

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        # Required fields
        required_fields = ["asn", "name"]
        for field in required_fields:
            if field not in peer_info:
                errors.append(f"Missing required field: {field}")

        # Validate ASN format
        asn = peer_info.get("asn", "")
        if asn and not asn.startswith("AS"):
            errors.append(f"Invalid ASN format: {asn} (should start with 'AS')")

        # Validate IP addresses if present
        from lib.utils import validate_network_address

        for ip_field in ["ipv4", "ipv6"]:
            if ip_field in peer_info:
                ip_addr = peer_info[ip_field]
                if not validate_network_address(ip_addr):
                    errors.append(f"Invalid {ip_field} address: {ip_addr}")

        return errors

    def generate_from_template_file(
        self, template_file: str, variables: Dict[str, Any], output_file: str = None
    ) -> str:
        """
        Generate configuration from template file

        Args:
            template_file: Path to template file
            variables: Template variables
            output_file: Optional output file path

        Returns:
            Generated configuration content
        """
        try:
            from jinja2 import Environment, FileSystemLoader

            # Set up Jinja2 environment
            env = Environment(
                loader=FileSystemLoader(str(self.template_dir)),
                trim_blocks=True,
                lstrip_blocks=True,
            )

            # Load template
            template = env.get_template(template_file)

            # Render configuration
            config_content = template.render(**variables)

            # Save to file if requested
            if output_file:
                output_path = Path(output_file)
                output_path.parent.mkdir(parents=True, exist_ok=True)

                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(config_content)

                logger.info(f"Configuration saved to: {output_path}")

            return config_content

        except Exception as e:
            logger.error(f"Failed to generate from template {template_file}: {e}")
            raise


def main():
    """Main CLI interface"""
    parser = argparse.ArgumentParser(
        description="AutoNet Peer Configuration Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --asn AS64512 --name "Example Peer" --vendor bird
  %(prog)s --template peer.j2 --output config.conf --asn AS64512
  %(prog)s --list-vendors
  %(prog)s --peer-file peers.json --vendor bird2 --output-dir /tmp/configs
        """,
    )

    # Peer information
    parser.add_argument("--asn", help="Peer ASN (e.g., AS64512)")
    parser.add_argument("--name", help="Peer name")
    parser.add_argument("--ipv4", help="Peer IPv4 address")
    parser.add_argument("--ipv6", help="Peer IPv6 address")
    parser.add_argument("--description", help="Peer description")

    # Generation options
    parser.add_argument(
        "--vendor", default="bird", help="Target vendor (default: bird)"
    )
    parser.add_argument("--template", help="Template file to use")
    parser.add_argument("--output", "-o", help="Output file path")
    parser.add_argument("--output-dir", help="Output directory for multiple files")

    # Input sources
    parser.add_argument("--peer-file", help="JSON file with peer information")
    parser.add_argument("--config-file", "-c", help="Configuration file path")

    # Information
    parser.add_argument(
        "--list-vendors", action="store_true", help="List available vendor plugins"
    )
    parser.add_argument("--vendor-features", help="Show features for specific vendor")

    # Options
    parser.add_argument(
        "--debug", "-d", action="store_true", help="Enable debug logging"
    )
    parser.add_argument(
        "--validate-only", action="store_true", help="Validate peer information only"
    )

    args = parser.parse_args()

    # Configure logging
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        # Load configuration
        config_manager = get_config_manager()
        config = config_manager.load_configuration(args.config_file)

        # Create generator
        generator = PeerConfigGenerator(config)

        # Handle information requests
        if args.list_vendors:
            vendors = generator.list_available_vendors()
            print("Available vendor plugins:")
            for vendor in vendors:
                features = generator.get_vendor_features(vendor)
                print(
                    f"  • {vendor}: {', '.join(features) if features else 'no features listed'}"
                )
            return

        if args.vendor_features:
            features = generator.get_vendor_features(args.vendor_features)
            print(f"Features for {args.vendor_features}:")
            for feature in features:
                print(f"  • {feature}")
            return

        # Handle peer file processing
        if args.peer_file:
            import json

            with open(args.peer_file, "r") as f:
                peer_data = json.load(f)

            if isinstance(peer_data, list):
                peer_list = peer_data
            else:
                peer_list = [peer_data]

            if args.validate_only:
                # Validate all peers
                for i, peer_info in enumerate(peer_list):
                    errors = generator.validate_peer_info(peer_info)
                    if errors:
                        print(f"Peer {i+1} validation errors:")
                        for error in errors:
                            print(f"  • {error}")
                    else:
                        print(
                            f"✓ Peer {i+1} ({peer_info.get('asn', 'unknown')}) is valid"
                        )
            else:
                # Generate configurations
                results = generator.generate_multiple_peers(peer_list, args.vendor)

                if args.output_dir:
                    output_dir = Path(args.output_dir)
                    output_dir.mkdir(parents=True, exist_ok=True)

                    for asn, config_content in results.items():
                        output_file = output_dir / f"{asn.lower()}.conf"
                        with open(output_file, "w") as f:
                            f.write(config_content)
                        print(f"✓ Generated: {output_file}")
                else:
                    for asn, config_content in results.items():
                        print(f"\n# Configuration for {asn}")
                        print(config_content)

            return

        # Handle single peer generation
        if args.asn:
            peer_info = {
                "asn": args.asn,
                "name": args.name or f"Peer {args.asn}",
                "description": args.description or f"BGP peer {args.asn}",
            }

            if args.ipv4:
                peer_info["ipv4"] = args.ipv4
            if args.ipv6:
                peer_info["ipv6"] = args.ipv6

            if args.validate_only:
                errors = generator.validate_peer_info(peer_info)
                if errors:
                    print("Validation errors:")
                    for error in errors:
                        print(f"  • {error}")
                    sys.exit(1)
                else:
                    print(f"✓ Peer information is valid")
                    return

            config_content = generator.generate_peer_config(
                args.asn, peer_info, args.vendor, args.output
            )

            if not args.output:
                print(config_content)

            return

        # Handle template-based generation
        if args.template:
            variables = {
                "asn": args.asn or "AS64512",
                "name": args.name or "Example Peer",
                "ipv4": args.ipv4,
                "ipv6": args.ipv6,
                "description": args.description,
            }

            config_content = generator.generate_from_template_file(
                args.template, variables, args.output
            )

            if not args.output:
                print(config_content)

            return

        # No action specified
        parser.print_help()

    except ConfigurationError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error: {e}")
        if args.debug:
            import traceback

            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
