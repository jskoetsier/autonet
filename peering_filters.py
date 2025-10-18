#!/usr/bin/env python3

"""
    AutoNet

    Network Automation Toolchain

    (c) 2014-2017 Job Snijders <job@instituut.net>
    (c) 2017-2023 Network Operators <routers@example.net>

"""
#!/usr/bin/env python3

import ipaddress
import json
import os
import re
import sys
import time
import fcntl
import shlex
import gc
import gzip
import psutil
from concurrent.futures import as_completed, ProcessPoolExecutor
from hashlib import sha256
from subprocess import PIPE, Popen
from typing import List, Dict, Optional, Union, Iterator, Generator
from pathlib import Path
from io import StringIO
from datetime import datetime

import requests
import yaml
from jinja2 import Environment, FileSystemLoader
from numpy import base_repr
from cryptography.fernet import Fernet
import base64

# Import new architecture components
from lib.config_manager import get_config_manager, ConfigurationManager
from lib.plugin_system import get_plugin_manager, initialize_plugin_system, PluginType
from lib.state_manager import (
    get_state_manager, StateManager, StateEvent, GenerationRecord,
    EventType, track_event
                          )



# Custom exception classes for better error handling
class AutoNetError(Exception):
    """Base exception for AutoNet errors"""

    pass


class PeeringDBError(AutoNetError):
    """PeeringDB API related errors"""

    pass


class ConfigurationError(AutoNetError):
    """Configuration file related errors"""

    pass


class FileOperationError(AutoNetError):
    """File operation related errors"""
    pass


class ValidationError(AutoNetError):
    """Input validation related errors"""
    pass


# Security and validation functions
def validate_asn(asn: str) -> bool:
    """Validate ASN format supporting 32-bit ASNs (ASxxxxx)"""
    if not isinstance(asn, str):
        return False
    
    if not re.match(r'^AS\d+$', asn, re.IGNORECASE):
        return False
    
    # Extract ASN number and validate 32-bit range
    try:
        asn_num = int(asn[2:])
        # Valid 32-bit ASN range: 1-4294967294 (excluding reserved values)
        if asn_num == 0 or asn_num == 23456 or asn_num == 4294967295:
            return False
        return 1 <= asn_num <= 4294967294
    except ValueError:
        return False


def validate_ip_address(ip: str) -> bool:
    """Validate IP address format"""
    try:
        ipaddress.ip_address(ip)
        return True
    except (ValueError, TypeError):
        return False


def validate_as_set(as_set: str) -> bool:
    """Validate AS-SET format"""
    if not isinstance(as_set, str):
        return False
    # AS-SET format: AS-SETNAME or ASN:AS-SETNAME
    return re.match(r'^(AS\d+:)?AS-[A-Z0-9\-]+$', as_set, re.IGNORECASE) is not None


def sanitize_shell_input(input_str: str) -> str:
    """Sanitize string for safe shell usage"""
    if not isinstance(input_str, str):
        raise ValidationError("Input must be a string")

    # Remove any potentially dangerous characters
    sanitized = re.sub(r'[;&|`$(){}[\]<>]', '', input_str)
    return shlex.quote(sanitized)


def get_api_key(key_name: str, config_key: str = None) -> str:
    """Securely retrieve API key from environment or config"""
    # First try environment variable (most secure)
    env_key = os.environ.get(f'AUTONET_{key_name.upper()}_KEY')
    if env_key:
        return env_key

    # Fall back to encrypted config if available
    if config_key and config_key in generic:
        encrypted_key = generic[config_key]
        # Check if it's encrypted (starts with our encryption prefix)
        if isinstance(encrypted_key, str) and encrypted_key.startswith('ENCRYPTED:'):
            try:
                return decrypt_api_key(encrypted_key[10:])  # Remove ENCRYPTED: prefix
            except Exception as e:
                print(f"WARNING: Failed to decrypt API key {key_name}: {e}", file=sys.stderr)
                return encrypted_key[10:]  # Return as-is if decryption fails
        else:
            print(f"WARNING: API key {key_name} is stored in plaintext. Consider using encryption or environment variables", file=sys.stderr)
            return encrypted_key

    raise ConfigurationError(f"API key {key_name} not found in environment or config")


def encrypt_api_key(key: str, encryption_key: str = None) -> str:
    """Encrypt API key for storage"""
    if not encryption_key:
        encryption_key = os.environ.get('AUTONET_ENCRYPTION_KEY')
        if not encryption_key:
            # Generate a key if none provided (should be saved securely)
            encryption_key = Fernet.generate_key().decode()
            print(f"Generated encryption key: {encryption_key}", file=sys.stderr)
            print("Save this key securely and set AUTONET_ENCRYPTION_KEY environment variable", file=sys.stderr)

    try:
        if isinstance(encryption_key, str):
            encryption_key = encryption_key.encode()
        fernet = Fernet(encryption_key)
        encrypted = fernet.encrypt(key.encode())
        return base64.b64encode(encrypted).decode()
    except Exception as e:
        raise ConfigurationError(f"Failed to encrypt API key: {e}")


def decrypt_api_key(encrypted_key: str, encryption_key: str = None) -> str:
    """Decrypt API key from storage"""
    if not encryption_key:
        encryption_key = os.environ.get('AUTONET_ENCRYPTION_KEY')
        if not encryption_key:
            raise ConfigurationError("AUTONET_ENCRYPTION_KEY environment variable not set")

    try:
        if isinstance(encryption_key, str):
            encryption_key = encryption_key.encode()
        fernet = Fernet(encryption_key)
        encrypted_bytes = base64.b64decode(encrypted_key.encode())
        decrypted = fernet.decrypt(encrypted_bytes)
        return decrypted.decode()
    except Exception as e:
        raise ConfigurationError(f"Failed to decrypt API key: {e}")


def safe_file_write(filename: str, content: str, mode: str = 'w') -> None:
    """Thread-safe file writing with file locking"""
    try:
        # Ensure directory exists
        Path(filename).parent.mkdir(parents=True, exist_ok=True)

        with open(filename, mode, encoding='utf-8') as f:
            # Apply exclusive lock
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(content)
                f.flush()  # Ensure data is written
                os.fsync(f.fileno())  # Force write to disk
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception as e:
        raise FileOperationError(f"Failed to write file {filename}: {e}")


def safe_file_check_and_update(filename: str, content: str, max_age_seconds: int = 3600) -> bool:
    """Thread-safe file checking and updating with proper locking"""
    try:
        # Create file if it doesn't exist
        if not os.path.exists(filename):
            safe_file_write(filename, content)
            return True

        # Check if file needs updating (age-based)
        if time.time() - os.path.getmtime(filename) > max_age_seconds:
            safe_file_write(filename, content)
            return True

        return False
    except Exception as e:
        raise FileOperationError(f"Failed to check/update file {filename}: {e}")


# Memory-efficient streaming and pagination functions
def stream_json_download(url: str, headers: Dict = None, timeout: int = 30,
                        max_retries: int = 3, chunk_size: int = 8192) -> Iterator[bytes]:
    """Stream download JSON data in chunks to reduce memory usage"""
    if headers is None:
        headers = {}
    headers["user-agent"] = "autonet"

    for attempt in range(max_retries):
        try:
            with requests.get(url, headers=headers, timeout=timeout, stream=True) as r:
                r.raise_for_status()
                for chunk in r.iter_content(chunk_size=chunk_size):
                    if chunk:
                        yield chunk
                return
        except requests.exceptions.Timeout:
            print(f"Timeout streaming {url} (attempt {attempt + 1}/{max_retries})", file=sys.stderr)
            if attempt == max_retries - 1:
                raise PeeringDBError(f"Timeout streaming {url} after {max_retries} attempts")
        except requests.exceptions.ConnectionError as e:
            print(f"Connection error streaming {url} (attempt {attempt + 1}/{max_retries}): {e}", file=sys.stderr)
            if attempt == max_retries - 1:
                raise PeeringDBError(f"Connection error streaming {url}: {e}")
        except requests.exceptions.HTTPError as e:
            print(f"HTTP error streaming {url}: {e}", file=sys.stderr)
            raise PeeringDBError(f"HTTP error streaming {url}: {e}")
        except requests.exceptions.RequestException as e:
            print(f"Request error streaming {url} (attempt {attempt + 1}/{max_retries}): {e}", file=sys.stderr)
            if attempt == max_retries - 1:
                raise PeeringDBError(f"Request error streaming {url}: {e}")

        # Wait before retrying (exponential backoff)
        if attempt < max_retries - 1:
            wait_time = 2 ** attempt
            print(f"Waiting {wait_time} seconds before retry...", file=sys.stderr)
            time.sleep(wait_time)


def paginated_peeringdb_request(base_url: str, headers: Dict = None,
                               page_size: int = 1000, max_pages: int = None) -> Generator[Dict, None, None]:
    """Paginate PeeringDB API requests to reduce memory usage"""
    if headers is None:
        headers = {}

    page = 0
    total_processed = 0

    while True:
        if max_pages and page >= max_pages:
            break

        # Construct paginated URL
        paginated_url = f"{base_url}?limit={page_size}&skip={page * page_size}"

        try:
            print(f"Fetching page {page + 1} from PeeringDB API (processed {total_processed} records)", file=sys.stderr)

            # Use streaming download for memory efficiency
            chunks = []
            for chunk in stream_json_download(paginated_url, headers):
                chunks.append(chunk)

            data_str = b''.join(chunks).decode('utf-8')
            page_data = json.loads(data_str)

            # Free up memory immediately
            del chunks, data_str
            gc.collect()

            if "data" not in page_data:
                print(f"WARNING: No 'data' field in response from {paginated_url}", file=sys.stderr)
                break

            data_items = page_data["data"]
            if not data_items:
                print(f"No more data available, processed {total_processed} total records", file=sys.stderr)
                break

            # Yield each item individually for memory efficiency
            for item in data_items:
                yield item
                total_processed += 1

            # Free memory after processing each page
            del page_data, data_items
            gc.collect()

            # Check if we got fewer items than requested (last page)
            if len(data_items) < page_size:
                print(f"Reached last page, processed {total_processed} total records", file=sys.stderr)
                break

            page += 1

        except Exception as e:
            print(f"Error fetching page {page + 1}: {e}", file=sys.stderr)
            raise PeeringDBError(f"Failed to fetch paginated data from {base_url}: {e}")


def memory_efficient_pdb_processing(pdb_auth: Dict) -> Dict[int, List[str]]:
    """Process PeeringDB data with memory-efficient streaming"""
    print("Processing PeeringDB netixlan data with memory-efficient streaming...", file=sys.stderr)

    pdb = {}
    processed_count = 0

    try:
        # Use pagination for netixlan data
        for connection in paginated_peeringdb_request(
            "https://www.peeringdb.com/api/netixlan",
            pdb_auth,
            page_size=2000  # Larger page size for efficiency
        ):
            asn = connection.get("asn")
            v4 = connection.get("ipaddr4")
            v6 = connection.get("ipaddr6")

            if asn is None:
                continue

            if asn not in pdb:
                pdb[asn] = []

            if v4:
                pdb[asn].append(v4)
            if v6:
                pdb[asn].append(v6)

            processed_count += 1

            # Periodic garbage collection to keep memory usage low
            if processed_count % 10000 == 0:
                print(f"Processed {processed_count} PeeringDB connections, current memory usage for {len(pdb)} ASNs", file=sys.stderr)
                gc.collect()

    except Exception as e:
        print(f"Error processing PeeringDB netixlan data: {e}", file=sys.stderr)
        raise PeeringDBError(f"Failed to process PeeringDB netixlan data: {e}")

    print(f"Completed processing {processed_count} PeeringDB connections for {len(pdb)} ASNs", file=sys.stderr)
    return pdb


def memory_efficient_max_prefixes_processing(pdb_auth: Dict) -> Dict[str, Dict[str, int]]:
    """Process PeeringDB network data with memory-efficient streaming"""
    print("Processing PeeringDB network data with memory-efficient streaming...", file=sys.stderr)

    max_prefixes = {}
    processed_count = 0

    try:
        # Use pagination for network data
        for netdata in paginated_peeringdb_request(
            "https://www.peeringdb.com/api/net",
            pdb_auth,
            page_size=1000  # Network data is typically smaller than netixlan
        ):
            asn_num = netdata.get("asn")
            if asn_num is None:
                continue

            asn = f"AS{asn_num}"
            if asn not in max_prefixes:
                max_prefixes[asn] = {}

            # Process IPv4 prefix limits
            maxprefixes_v4 = netdata.get("info_prefixes4")
            if maxprefixes_v4 is None or maxprefixes_v4 < 100:
                max_prefixes[asn]["v4"] = 100
            else:
                max_prefixes[asn]["v4"] = int(maxprefixes_v4 * 1.1)

            # Process IPv6 prefix limits
            maxprefixes_v6 = netdata.get("info_prefixes6")
            if maxprefixes_v6 is None or maxprefixes_v6 < 100:
                max_prefixes[asn]["v6"] = 100
            else:
                max_prefixes[asn]["v6"] = int(maxprefixes_v6 * 1.1)

            processed_count += 1

            # Periodic garbage collection
            if processed_count % 5000 == 0:
                print(f"Processed {processed_count} networks, tracking prefix limits for {len(max_prefixes)} ASNs", file=sys.stderr)
                gc.collect()

    except Exception as e:
        print(f"Error processing PeeringDB network data: {e}", file=sys.stderr)
        raise PeeringDBError(f"Failed to process PeeringDB network data: {e}")

    print(f"Completed processing {processed_count} networks with prefix limits for {len(max_prefixes)} ASNs", file=sys.stderr)
    return max_prefixes


# PeeringDB API fallback mechanisms for reliability
PEERINGDB_MIRRORS = [
    "https://www.peeringdb.com/api",
    "https://peeringdb.org/api",  # Alternative mirror
    # Add more mirrors as they become available
]

def resilient_peeringdb_request(endpoint: str, headers: Dict, fallback_cache_file: str = None) -> Dict:
    """Make PeeringDB API request with fallback mechanisms"""
    last_error = None

    for mirror_base in PEERINGDB_MIRRORS:
        mirror_url = f"{mirror_base}/{endpoint.lstrip('/')}"

        try:
            print(f"Attempting to fetch from {mirror_url}", file=sys.stderr)

            # Try the mirror
            data_str = download(mirror_url, headers)
            data = json.loads(data_str)

            # Cache successful response if cache file specified
            if fallback_cache_file:
                try:
                    # Compress cache to save disk space
                    with gzip.open(f"{fallback_cache_file}.gz", 'wt', encoding='utf-8') as f:
                        json.dump(data, f, separators=(',', ':'))
                    print(f"Cached response to {fallback_cache_file}.gz", file=sys.stderr)
                except Exception as cache_error:
                    print(f"WARNING: Failed to cache response: {cache_error}", file=sys.stderr)

            return data

        except Exception as e:
            print(f"Mirror {mirror_url} failed: {e}", file=sys.stderr)
            last_error = e
            continue

    # All mirrors failed, try fallback cache
    if fallback_cache_file:
        cache_files = [f"{fallback_cache_file}.gz", fallback_cache_file]

        for cache_file in cache_files:
            if os.path.exists(cache_file):
                try:
                    print(f"All PeeringDB mirrors failed, using cached data from {cache_file}", file=sys.stderr)

                    if cache_file.endswith('.gz'):
                        with gzip.open(cache_file, 'rt', encoding='utf-8') as f:
                            data = json.load(f)
                    else:
                        with open(cache_file, 'r', encoding='utf-8') as f:
                            data = json.load(f)

                    # Check cache age and warn if old
                    cache_age = time.time() - os.path.getmtime(cache_file)
                    if cache_age > 24 * 3600:  # Older than 24 hours
                        print(f"WARNING: Using cached data that is {cache_age/3600:.1f} hours old", file=sys.stderr)

                    return data

                except Exception as cache_error:
                    print(f"Failed to read cache file {cache_file}: {cache_error}", file=sys.stderr)
                    continue

    # All options exhausted
    raise PeeringDBError(f"All PeeringDB mirrors failed and no valid cache available. Last error: {last_error}")


# Load generic configuration with proper error handling
try:
    with open("vars/generic.yml", "r", encoding="utf-8") as genfile:
        generic = yaml.safe_load(genfile)
        if generic is None:
            raise ConfigurationError("vars/generic.yml is empty or invalid")
except FileNotFoundError:
    print("ERROR: Configuration file vars/generic.yml not found", file=sys.stderr)
    raise ConfigurationError("Configuration file vars/generic.yml not found")
except yaml.YAMLError as e:
    print(f"ERROR: Invalid YAML in vars/generic.yml: {e}", file=sys.stderr)
    raise ConfigurationError(f"Invalid YAML in vars/generic.yml: {e}")
except PermissionError:
    print("ERROR: Permission denied reading vars/generic.yml", file=sys.stderr)
    raise ConfigurationError("Permission denied reading vars/generic.yml")
except UnicodeDecodeError as e:
    print(f"ERROR: Unicode decode error in vars/generic.yml: {e}", file=sys.stderr)
    raise ConfigurationError(f"Unicode decode error in vars/generic.yml: {e}")


def download(url, headers={}, timeout=30, max_retries=3):
    """Download content from URL with proper error handling and retries"""
    headers["user-agent"] = "autonet"

    for attempt in range(max_retries):
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            r.raise_for_status()  # Raises HTTPError for bad responses
            return r.text
        except requests.exceptions.Timeout:
            print(
                f"Timeout downloading {url} (attempt {attempt + 1}/{max_retries})",
                file=sys.stderr,
            )
            if attempt == max_retries - 1:
                raise PeeringDBError(
                    f"Timeout downloading {url} after {max_retries} attempts"
                )
        except requests.exceptions.ConnectionError as e:
            print(
                f"Connection error downloading {url} (attempt {attempt + 1}/{max_retries}): {e}",
                file=sys.stderr,
            )
            if attempt == max_retries - 1:
                raise PeeringDBError(f"Connection error downloading {url}: {e}")
        except requests.exceptions.HTTPError as e:
            print(f"HTTP error downloading {url}: {e}", file=sys.stderr)
            raise PeeringDBError(f"HTTP error downloading {url}: {e}")
        except requests.exceptions.RequestException as e:
            print(
                f"Request error downloading {url} (attempt {attempt + 1}/{max_retries}): {e}",
                file=sys.stderr,
            )
            if attempt == max_retries - 1:
                raise PeeringDBError(f"Request error downloading {url}: {e}")

        # Wait before retrying (exponential backoff)
        if attempt < max_retries - 1:
            wait_time = 2**attempt
            print(f"Waiting {wait_time} seconds before retry...", file=sys.stderr)
            time.sleep(wait_time)


def readfile(filename):
    """Read file content with proper error handling"""
    try:
        with open(filename, "r", encoding="utf-8") as reader:
            filecontent = reader.read()
    except FileNotFoundError:
        print(f"File not found: {filename}", file=sys.stderr)
        raise FileOperationError(f"File not found: {filename}")
    except PermissionError:
        print(f"Permission denied reading file: {filename}", file=sys.stderr)
        raise FileOperationError(f"Permission denied reading file: {filename}")
    except UnicodeDecodeError as e:
        print(f"Unicode decode error reading file {filename}: {e}", file=sys.stderr)
        raise FileOperationError(f"Unicode decode error reading file {filename}: {e}")
    except IOError as e:
        print(f"IO error reading file {filename}: {e}", file=sys.stderr)
        raise FileOperationError(f"IO error reading file {filename}: {e}")
    except Exception as e:
        print(f"Unexpected error reading file {filename}: {e}", file=sys.stderr)
        raise FileOperationError(f"Unexpected error reading file {filename}: {e}")

    return filecontent


# Secure API key handling with validation
try:
    pdb_api_key = get_api_key("PEERINGDB", "pdb_apikey")
    if not pdb_api_key:
        raise ConfigurationError("PeeringDB API key is empty")
    pdb_auth = {"Authorization": f"Api-Key {pdb_api_key}"}
except (KeyError, ConfigurationError) as e:
    print(f"ERROR: {e}", file=sys.stderr)
    print("Set AUTONET_PEERINGDB_KEY environment variable or configure pdb_apikey in generic.yml", file=sys.stderr)
    sys.exit(1)
# Use memory-efficient processing with fallback caching
print("Using memory-efficient PeeringDB processing...", file=sys.stderr)

try:
    # Process PeeringDB data with memory-efficient streaming
    pdb = memory_efficient_pdb_processing(pdb_auth)
    max_prefixes = memory_efficient_max_prefixes_processing(pdb_auth)
except PeeringDBError as e:
    print(f"ERROR: {e}", file=sys.stderr)
    sys.exit(1)

# Defaults
generate_configs = False
generate_prefixsets = False
debugmode = False
do_checks = True

if "all" in sys.argv:
    generate_configs = True
    generate_prefixsets = True
if "prefixsets" in sys.argv:
    generate_prefixsets = True
if "configs" in sys.argv:
    generate_configs = True
if "--no-checks" in sys.argv:
    do_checks = False
    print(
        "Saw '--no-checks': skipping existence checks for prefix sets when generating config."
    )
if "debug" in sys.argv:
    debugmode = True

# Initialize new architecture
try:
    # Load configuration with new architecture
    config_manager = get_config_manager()
    config = config_manager.load_configuration()

    # Initialize plugin system
    plugin_manager = initialize_plugin_system(config)

    # Initialize state manager
    state_manager = get_state_manager(config=config)

    # Track generation start
    generation_start_time = time.time()
    start_memory = psutil.Process().memory_info().rss / 1024 / 1024  # MB

    track_event(
        EventType.GENERATION_START,
        "peering_filters",
        f"Starting configuration generation with new architecture",
        details={
            "total_peers": len(peerings) if 'peerings' in locals() else 0,
            "generate_configs": generate_configs,
            "generate_prefixsets": generate_prefixsets,
            "memory_start_mb": start_memory
        }
    )

    print(f"✓ Initialized new architecture - Config Manager, Plugin System, State Manager", file=sys.stderr)

except Exception as e:
    print(f"WARNING: Failed to initialize new architecture: {e}", file=sys.stderr)
    print("Falling back to legacy mode", file=sys.stderr)
    config_manager = None
    plugin_manager = None
    state_manager = None
    generation_start_time = time.time()
    start_memory = 0.0


# For testing purposes, allow a local file as peering manifest
if "PEERINGS_FILE" in os.environ:
    peerings_flat = readfile(os.environ.get("PEERINGS_FILE"))
else:
    peerings_flat = download(generic["peerings_url"])

# Parse peerings configuration with error handling
try:
    peerings = yaml.safe_load(peerings_flat)
    if peerings is None:
        raise ConfigurationError("Peerings configuration is empty or invalid")
except yaml.YAMLError as e:
    print(f"ERROR: Invalid YAML in peerings configuration: {e}", file=sys.stderr)
    raise ConfigurationError(f"Invalid YAML in peerings configuration: {e}")

# ip addresses should not be needed to define ourselves
#   this could be retrieved from https://www.peeringdb.com/api/ixlan
ixp_map = {}
router_map = {}
for ixp in generic["ixp_map"]:
    ixp_map[ixp] = {}
    ixp_map[ixp]["subnets"] = [
        ipaddress.ip_network(generic["ixp_map"][ixp]["ipv4_range"]),
        ipaddress.ip_network(generic["ixp_map"][ixp]["ipv6_range"]),
    ]

    # Set a default bgp_local_pref of 100, allow for IXP based override
    ixp_map[ixp]["bgp_local_pref"] = 100
    if "bgp_local_pref" in generic["ixp_map"][ixp]:
        ixp_map[ixp]["bgp_local_pref"] = generic["ixp_map"][ixp]["bgp_local_pref"]

    router_map[ixp] = []
    for router in generic["ixp_map"][ixp]["present_on"]:
        router_map[ixp].append(router)

multihop_source_map = {}
vendor_map = {}
for routername in generic["bgp"]:
    fqdn = generic["bgp"][routername]["fqdn"]
    multihop_source_map[fqdn] = {}
    multihop_source_map[fqdn]["ipv4"] = generic["bgp"][routername]["ipv4"]
    multihop_source_map[fqdn]["ipv6"] = generic["bgp"][routername]["ipv6"]
    vendor_map[fqdn] = generic["bgp"][routername]["vendor"]

allow_upto = {4: "24", 6: "48"}

# store the directory in which the script was started
# this is used to find template files
launchdir = os.getcwd()

# get output dir from environment, configuration or hard-coded default.
try:
    outputdir = os.environ["BUILDDIR"]
except KeyError:
    outputdir = (
        generic["builddir"] if "builddir" in generic.keys() else "/opt/routefilters"
    )

try:
    os.chdir(outputdir)
except IOError:
    print("%s does not exist?" % outputdir)
    sys.exit(2)

if "irr_source_host" in generic:
    irr_source_host = generic["irr_source_host"]
else:
    irr_source_host = "rr.ntt.net"


def render(tpl_path, context):
    path, filename = os.path.split(launchdir + "/" + tpl_path)
    env = Environment(loader=FileSystemLoader(path or "./"))
    env.trim_blocks = True
    env.lstrip_blocks = True
    env.rstrip_blocks = True

    return env.get_template(filename).render(context)


def generate_filters(asn, as_set, irr_order, irr_source_host, loose=False):
    # Default filter settings
    filtername_prefix = "AUTOFILTER"
    filename_prefix = "prefixset"
    max_prefix_length = allow_upto

    # Loose filtering settings
    if loose:
        filtername_prefix = "LOOSEFILTER"
        filename_prefix = "looseprefixset"
        max_prefix_length = {4: "32", 6: "128"}

    # inner function for actual bgpq3 execution
    def run_bgpq3(
        filename, v, as_set, vendor, flags, subterm, asn, irr_order, irr_source_host
    ):

        stanza_name = "%s_%s_IPv%s%s" % (filtername_prefix, asn, v, subterm)

        with open(filename, "w") as bgpq3_result:
            if flags:
                p = Popen(
                    [
                        "bgpq3",
                        "-h",
                        irr_source_host,
                        "-S",
                        irr_order,
                        "-R",
                        max_prefix_length[v],
                        "-%s" % v,
                        vendor,
                    ]
                    + flags
                    + ["-l", stanza_name, "-A", asn]
                    + as_set,
                    stdout=bgpq3_result,
                )
            else:
                p = Popen(
                    [
                        "bgpq3",
                        "-h",
                        irr_source_host,
                        "-S",
                        irr_order,
                        "-R",
                        max_prefix_length[v],
                        "-%s" % v,
                        vendor,
                        "-l",
                        stanza_name,
                        "-A",
                        asn,
                    ]
                    + as_set,
                    stdout=bgpq3_result,
                )
        if debugmode:
            print("DEBUG: bgpq3 args: {}".format(p.args))
        now = time.perf_counter()  # record current performance counter
        p.wait()
        bgpq_duration = time.perf_counter() - now
        if debugmode:
            print("DEBUG: bgpq3 elapsed time: {}".format(bgpq_duration))
        return p.returncode

    # BIRD IPv4
    for v in [4, 6]:
        if as_set == "ANY":
            continue

        filename = "%s.%s.bird.ipv%s" % (asn, filename_prefix, v)
        if os.path.exists(filename):
            if time.time() - os.path.getmtime(filename) > 3600:
                errno = run_bgpq3(
                    filename, v, as_set, "-b", None, "", asn, irr_order, irr_source_host
                )
                if errno != 0:
                    print(
                        "ERROR: bgpq3 returned non-zero for existing filename {}: {}".format(
                            filename, errno
                        )
                    )
                print("bird ipv%s refreshed: %s" % (v, filename))
            else:
                print("bird ipv%s cached: %s" % (v, filename))
        else:
            errno = run_bgpq3(
                filename, v, as_set, "-b", None, "", asn, irr_order, irr_source_host
            )
            if errno != 0:
                print(
                    "ERROR: bgpq3 returned non-zero for existing filename {}: {}".format(
                        filename, errno
                    )
                )
            print("bird ipv%s created: %s" % (v, filename))


seen_router_policy = []
seen_bird_peers = {}


def config_snippet(
    asn,
    peer,
    description,
    ixp,
    router,
    no_filter,
    export_full_table,
    limits,
    gtsm,
    peer_type,
    multihop,
    disable_multihop_source_map,
    multihop_source_map,
    generic,
    admin_down_state,
    block_importexport,
    bgp_local_pref,
    graceful_shutdown,
    blackhole_accept,
    blackhole_community,
):
    if peer_type not in ["upstream", "peer", "downstream"]:
        print("ERROR: invalid peertype: %s for %s" % (peer_type, asn))
        sys.exit(2)
    global seen_router_policy
    vendor = vendor_map[router]
    v = ipaddress.ip_address(peer).version
    policy_name = "AUTOFILTER:%s:IPv%s" % (asn, v)

    if vendor == "bird":
        global seen_bird_peers
        if asn not in seen_bird_peers:
            seen_bird_peers[asn] = 0
        else:
            seen_bird_peers[asn] = seen_bird_peers[asn] + 1

        if no_filter:
            filter_name = "ebgp_unfiltered_peering_import"
        else:
            filter_name = "peer_in_%s_ipv%s" % (asn, v)

        password = None
        if asn in generic["bgp_passwords"]:
            password = generic["bgp_passwords"][asn]

        ixp_community = None
        if "ixp_community" in generic["ixp_map"][ixp]:
            ixp_community = generic["ixp_map"][ixp]["ixp_community"]

        limit = limits[v]
        neighbor_name = base_repr(
            int(sha256(str(peer).encode("utf-8")).hexdigest(), 16), 36
        )[:6]

        peer_info = {
            "asn": asn.replace("AS", ""),
            "afi": v,
            "prefix_set": policy_name.replace(":", "_"),
            "neigh_ip": peer,
            "neigh_name": "peer_%s_%s_%s" % (asn, ixp.replace("-", ""), neighbor_name),
            "description": description,
            "filter_name": filter_name,
            "limit": limit,
            "gtsm": gtsm,
            "multihop": multihop,
            "disable_multihop_source_map": disable_multihop_source_map,
            "password": password,
            "peer_type": peer_type,
            "source": multihop_source_map[router]["ipv%s" % v],
            "export_full_table": export_full_table,
            "ixp": ixp,
            "ixp_community": ixp_community,
            "rpki": generic["rpki"],
            "admin_down_state": admin_down_state,
            "block_importexport": block_importexport,
            "bgp_local_pref": bgp_local_pref,
            "graceful_shutdown": graceful_shutdown,
            "blackhole_accept": blackhole_accept,
            "blackhole_community": blackhole_community,
            "loose_prefix_set": policy_name.replace(
                "AUTOFILTER", "LOOSEFILTER"
            ).replace(":", "_"),
        }

        peer_config_blob = render("templates/peer.j2", peer_info)
        f = open("%s.ipv%s.config" % (router, v), "a")
        if not (router, asn, v) in seen_router_policy:
            seen_router_policy.append((router, asn, v))
            filter_config_blob = render("templates/filter.j2", peer_info)
            f.write(filter_config_blob)
        f.write(peer_config_blob)
        f.close()


def ebgp_peer_type(asn):
    if "type" in peerings[asn]:
        return peerings[asn]["type"]
    else:
        return "peer"


def ebgp_setting(setting, default_value, asn, ixp, session_ip):
    ip = str(session_ip)
    bgp_settings = {}
    if "bgp_settings" in generic:
        bgp_settings = generic["bgp_settings"]

    if asn in bgp_settings:
        if (
            ("session" in bgp_settings[asn])
            and (ip in bgp_settings[asn]["session"])
            and (setting in bgp_settings[asn]["session"][ip])
        ):
            return bgp_settings[asn]["session"][ip][setting]
        if (
            ("ixp" in bgp_settings[asn])
            and (ixp in bgp_settings[asn]["ixp"])
            and (setting in bgp_settings[asn]["ixp"][ixp])
        ):
            return bgp_settings[asn]["ixp"][ixp][setting]
        if ("common" in bgp_settings[asn]) and (setting in bgp_settings[asn]["common"]):
            return bgp_settings[asn]["common"][setting]
    if setting in ixp_map[ixp]:
        return ixp_map[ixp][setting]

    # last resort
    return default_value


def ebgp_local_pref(asn, ixp, session_ip):
    setting = "bgp_local_pref"
    default_value = ebgp_local_pref_default(ebgp_peer_type(asn), 100)

    return ebgp_setting(setting, default_value, asn, ixp, session_ip)


def ebgp_local_pref_default(peer_type, default_value=100):
    if peer_type == "downstream":
        return 500
    if peer_type == "upstream":
        return 60

    return default_value


def process_asn(
    asn, peerings, generic, generate_prefixsets, irr_source_host, do_checks
):
    results = []
    if generate_prefixsets:
        irr_order = (
            peerings[asn].get("irr_order")
            or generic.get("irr_order")
            or "NTTCOM,INTERNAL,RADB,RIPE,ALTDB,BELL,LEVEL3,RGNET,APNIC,JPIRR,ARIN,BBOI,TC,AFRINIC,RPKI,"
            "ARIN-WHOIS,REGISTROBR"
        )

        # Generate standard filters
        generate_filters(
            asn, peerings[asn]["import"].split(), irr_order, irr_source_host
        )
        results.append(f"Generated filters for {asn}")

        # Generate loose filters for blackhole communities if applicable
        if peerings[asn].get("blackhole_accept"):
            generate_filters(
                asn,
                peerings[asn]["import"].split(),
                irr_order,
                irr_source_host,
                loose=True,
            )
            results.append(f"Generated loose filters for {asn}")

    elif (
        not os.path.isfile(f"{asn}.prefixset.bird.ipv4")
        and not os.path.isfile(f"{asn}.prefixset.bird.ipv6")
        and do_checks
    ):
        results.append(f"Skipped {asn} due to missing files")

    return results


for router in vendor_map:
    if not generate_configs:
        break

    if vendor_map[router] == "bird":
        try:
            os.remove("%s.ipv4.config" % router)
            os.remove("%s.ipv6.config" % router)
        except OSError:
            print("INFO: Config for %s wasn't present, no need to delete" % router)

with ProcessPoolExecutor(max_workers=10) as executor:
    futures = [
        executor.submit(
            process_asn,
            asn,
            peerings,
            generic,
            generate_prefixsets,
            irr_source_host,
            do_checks,
        )
        for asn in peerings
    ]

    for future in as_completed(futures):
        try:
            result = future.result()
            for res in result:
                print(res)
        except Exception as e:
            print(f"Error processing ASN: {e}")


# Initialize new architecture
try:
    # Load configuration with new architecture
    config_manager = get_config_manager()
    config = config_manager.load_configuration()

    # Initialize plugin system
    plugin_manager = initialize_plugin_system(config)

    # Initialize state manager
    state_manager = get_state_manager(config=config)

    # Track generation start
    generation_start_time = time.time()
    start_memory = psutil.Process().memory_info().rss / 1024 / 1024  # MB

    track_event(
        EventType.GENERATION_START,
        "peering_filters",
        f"Starting configuration generation with new architecture",
        details={
            "total_peers": len(peerings),
            "generate_configs": generate_configs,
            "generate_prefixsets": generate_prefixsets,
            "memory_start_mb": start_memory
        }
    )

    print(f"Initialized new architecture - Config Manager, Plugin System, State Manager", file=sys.stderr)

except Exception as e:
    print(f"WARNING: Failed to initialize new architecture: {e}", file=sys.stderr)
    print("Falling back to legacy mode", file=sys.stderr)
    config_manager = None
    plugin_manager = None
    state_manager = None

for asn in peerings:
    # Validate ASN format
    if not validate_asn(asn):
        print(f"ERROR: Invalid ASN format: {asn}", file=sys.stderr)
        continue

    # Validate AS-SET in import field
    if "import" in peerings[asn] and peerings[asn]["import"] != "ANY":
        for as_set in peerings[asn]["import"].split():
            if not validate_as_set(as_set) and not validate_asn(as_set):
                print(f"ERROR: Invalid AS-SET or ASN format in import for {asn}: {as_set}", file=sys.stderr)
                continue

    sessions = []
    if "only_with" in peerings[asn]:
        sessions = peerings[asn]["only_with"]
    elif "private_peerings" in peerings[asn]:
        sessions = peerings[asn]["private_peerings"]
    elif int(asn[2:]) in pdb:
        sessions = pdb[int(asn[2:])]
        if "not_with" in peerings[asn]:
            for remove_ip in peerings[asn]["not_with"]:
                # Validate IP before removing
                if not validate_ip_address(remove_ip):
                    print(f"ERROR: Invalid IP address in not_with for {asn}: {remove_ip}", file=sys.stderr)
                    continue
                sessions.remove(remove_ip)
    else:
        continue

    for session in sessions:
        # Validate session IP address
        if not validate_ip_address(session):
            print(f"ERROR: Invalid session IP address for {asn}: {session}", file=sys.stderr)
            continue

        try:
            session_ip = ipaddress.ip_address(session)
        except (ValueError, TypeError) as e:
            print(f"ERROR: Failed to parse IP address {session}: {e}", file=sys.stderr)
            continue
        for ixp in ixp_map:
            for subnet in ixp_map[ixp]["subnets"]:
                bgp_local_pref = ebgp_local_pref(asn, ixp, session_ip)
                if session_ip in subnet:
                    print(
                        "found peer %s in IXP %s with localpref %d"
                        % (session_ip, ixp, bgp_local_pref)
                    )
                    print("must deploy on %s" % " ".join(router_map[ixp]))
                    description = peerings[asn]["description"]
                    for router in router_map[ixp]:
                        routershort = router.split(".")[0]
                        routershortnodash = routershort.replace("-", "")

                        if (
                            "only_on" in peerings[asn]
                            and router not in peerings[asn]["only_on"]
                        ):
                            continue

                        if "not_on" in peerings[asn] and ixp in peerings[asn]["not_on"]:
                            continue

                        peer_type = ebgp_peer_type(asn)

                        if peerings[asn]["import"] == "ANY":
                            no_filter = True
                        else:
                            no_filter = False
                        if peerings[asn]["export"] == "ANY":
                            export_full_table = True
                        else:
                            export_full_table = False

                        # set max prefix settings (if available)
                        limits = {}
                        if "ipv4_limit" in peerings[asn]:
                            limits[4] = peerings[asn]["ipv4_limit"]
                        elif asn in max_prefixes and "v4" in max_prefixes[asn]:
                            limits[4] = max_prefixes[asn]["v4"]
                        else:
                            limits[4] = 10000
                        if "ipv6_limit" in peerings[asn]:
                            limits[6] = peerings[asn]["ipv6_limit"]
                        elif asn in max_prefixes and "v6" in max_prefixes[asn]:
                            limits[6] = max_prefixes[asn]["v6"]
                        else:
                            limits[6] = 1000

                        gtsm = False
                        if "gtsm" in peerings[asn]:
                            if peerings[asn]["gtsm"]:
                                gtsm = True

                        multihop = False
                        if "multihop" in peerings[asn]:
                            if peerings[asn]["multihop"]:
                                multihop = True

                        disable_multihop_source_map = False
                        if "disable_multihop_source_map" in peerings[asn]:
                            if peerings[asn]["disable_multihop_source_map"]:
                                disable_multihop_source_map = True

                        blackhole_accept = False
                        if "blackhole_accept" in peerings[asn]:
                            blackhole_accept = peerings[asn]["blackhole_accept"]

                        blackhole_community = ["65535:666"]
                        if "blackhole_community" in peerings[asn]:
                            blackhole_community = peerings[asn]["blackhole_community"]

                        ixprouter = ixp + "-" + routershort
                        admin_down_state = False
                        # Is the IXP defined in the bgp_groups settings
                        if ixp in generic["bgp_groups"]:
                            # If it has an admin_down_state setting
                            if "admin_down_state" in generic["bgp_groups"][ixp]:
                                # Configure it to whatever it is set to in the config
                                admin_down_state = generic["bgp_groups"][ixp][
                                    "admin_down_state"
                                ]
                        # If a specific router of an IXP connection is configured
                        if ixprouter in generic["bgp_groups"]:
                            # If it has a admin_down_state setting, and it hasn't been configured above yet
                            if (
                                "admin_down_state" in generic["bgp_groups"][ixprouter]
                                and admin_down_state is False
                            ):
                                # Set it to whatever it is set to in the config
                                admin_down_state = generic["bgp_groups"][ixprouter][
                                    "admin_down_state"
                                ]

                        graceful_shutdown = False
                        if ixp in generic["bgp_groups"]:
                            if "graceful_shutdown" in generic["bgp_groups"][ixp]:
                                graceful_shutdown = generic["bgp_groups"][ixp][
                                    "graceful_shutdown"
                                ]
                        if ixprouter in generic["bgp_groups"]:
                            if (
                                "graceful_shutdown" in generic["bgp_groups"][ixprouter]
                                and graceful_shutdown is False
                            ):
                                graceful_shutdown = generic["bgp_groups"][ixprouter][
                                    "graceful_shutdown"
                                ]
                        if (
                            "graceful_shutdown" in generic["bgp"][routershortnodash]
                            and graceful_shutdown is False
                        ):
                            graceful_shutdown = generic["bgp"][routershortnodash][
                                "graceful_shutdown"
                            ]

                        block_importexport = False
                        if (
                            ixp in generic["bgp_groups"]
                            or ixprouter in generic["bgp_groups"]
                        ):
                            if (
                                "block_importexport" in generic["bgp_groups"][ixp]
                                or "block_importexport"
                                in generic["bgp_groups"][ixprouter]
                            ):
                                block_importexport = generic["bgp_groups"][ixp][
                                    "block_importexport"
                                ]
                        if ixprouter in generic["bgp_groups"]:
                            if (
                                "block_importexport" in generic["bgp_groups"][ixprouter]
                                and block_importexport is False
                            ):
                                block_importexport = generic["bgp_groups"][ixprouter][
                                    "block_importexport"
                                ]

                        if not generate_configs:
                            continue

                        config_snippet(
                            asn,
                            str(session_ip),
                            description,
                            ixp,
                            router,
                            no_filter,
                            export_full_table,
                            limits,
                            gtsm,
                            peer_type,
                            multihop,
                            disable_multihop_source_map,
                            multihop_source_map,
                            generic,
                            admin_down_state,
                            block_importexport,
                            bgp_local_pref,
                            graceful_shutdown,
                            blackhole_accept,
                            blackhole_community,
                        )

# Complete generation tracking with new architecture
if state_manager:
    try:
        # Calculate final metrics
        generation_end_time = time.time()
        end_memory = psutil.Process().memory_info().rss / 1024 / 1024  # MB
        peak_memory = max(start_memory, end_memory)
        generation_duration_ms = int((generation_end_time - generation_start_time) * 1000)

        # Count total filters and peers processed
        peer_count = len(peerings)
        filter_count = len(seen_router_policy) if 'seen_router_policy' in locals() else 0

        # Create generation record
        generation_record = GenerationRecord(
            config_hash=sha256(str(peerings).encode()).hexdigest()[:16],
            peer_count=peer_count,
            filter_count=filter_count,
            duration_ms=generation_duration_ms,
            memory_peak_mb=peak_memory,
            success=True,
            metadata={
                "generate_configs": generate_configs,
                "generate_prefixsets": generate_prefixsets,
                "architecture_version": "2.0",
                "memory_start_mb": start_memory,
                "memory_end_mb": end_memory,
                "processed_asns": peer_count,
                "total_sessions": sum(len(sessions) for sessions in [
                    peerings[asn].get("only_with", []) or
                    peerings[asn].get("private_peerings", []) or
                    pdb.get(int(asn[2:]), []) for asn in peerings
                ] if sessions),
                "plugins_loaded": len(plugin_manager.plugins) if plugin_manager else 0
            }
        )

        # Track the generation
        generation_id = state_manager.track_generation(generation_record)

        # Track completion event
        track_event(
            EventType.GENERATION_SUCCESS,
            "peering_filters",
            f"Configuration generation completed successfully",
            details={
                "generation_id": generation_id,
                "peer_count": peer_count,
                "filter_count": filter_count,
                "duration_ms": generation_duration_ms,
                "memory_peak_mb": peak_memory,
                "memory_efficiency": f"{((start_memory - end_memory) / start_memory * 100):.1f}% reduction" if start_memory > end_memory else "memory stable",
                "architecture_version": "2.0"
            },
            duration_ms=generation_duration_ms
        )

        print(f"✓ Generation completed - ID: {generation_id}, Duration: {generation_duration_ms/1000:.1f}s, Peak Memory: {peak_memory:.1f}MB", file=sys.stderr)

    except Exception as e:
        print(f"ERROR: Failed to track generation completion: {e}", file=sys.stderr)
        if 'track_event' in locals():
            track_event(
                EventType.GENERATION_FAILURE,
                "peering_filters",
                f"Failed to track generation: {e}",
                success=False
            )
