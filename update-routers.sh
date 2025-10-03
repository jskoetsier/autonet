#!/bin/bash
set -euo pipefail

# Exit codes for consistency
readonly EXIT_SUCCESS=0
readonly EXIT_CONFIG_ERROR=1  
readonly EXIT_TOOL_ERROR=2
readonly EXIT_SSH_ERROR=3
readonly EXIT_VALIDATION_ERROR=4
readonly EXIT_UPLOAD_ERROR=5

# Function to log messages with timestamp
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >&2
}

# Function to log error and exit
error_exit() {
    log "ERROR: $1"
    exit "${2:-$EXIT_CONFIG_ERROR}"
}

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to validate SSH key
validate_ssh_key() {
    local key_path="$1"
    
    if [[ ! -f "$key_path" ]]; then
        error_exit "SSH key not found at $key_path" $EXIT_SSH_ERROR
    fi
    
    if [[ ! -r "$key_path" ]]; then
        error_exit "SSH key at $key_path is not readable" $EXIT_SSH_ERROR  
    fi
    
    # Check key permissions (should be 600 or 400)
    local perms
    perms=$(stat -f "%Lp" "$key_path" 2>/dev/null || stat -c "%a" "$key_path" 2>/dev/null || echo "000")
    if [[ "$perms" != "600" ]] && [[ "$perms" != "400" ]]; then
        log "WARNING: SSH key permissions are $perms, should be 600 or 400"
    fi
    
    # Try to load the key to validate format
    if ! ssh-keygen -l -f "$key_path" >/dev/null 2>&1; then
        error_exit "SSH key at $key_path appears to be invalid or corrupted" $EXIT_SSH_ERROR
    fi
    
    log "SSH key validated: $key_path"
}

# Function to sanitize input for shell safety  
sanitize_input() {
    local input="$1"
    # Remove potentially dangerous characters
    echo "$input" | sed 's/[;&|`$(){}[\]<>]//g'
}

# Function to validate router name format
validate_router() {
    local router="$1"
    if [[ ! "$router" =~ ^[a-zA-Z0-9.-]+$ ]]; then
        error_exit "Invalid router name format: $router" $EXIT_CONFIG_ERROR
    fi
}

# Function to validate BIRD configuration syntax
validate_bird_config() {
    local config_file="$1"
    local config_type="$2"  # bird or bird6
    local router="$3"
    
    if [[ ! -f "$config_file" ]]; then
        error_exit "Configuration file not found: $config_file" $EXIT_VALIDATION_ERROR
    fi
    
    log "Validating $config_type configuration: $config_file"
    
    # Use appropriate BIRD binary for validation
    local bird_binary
    if [[ "$config_type" == "bird6" ]]; then
        bird_binary="$BIRD6_BIN"
    else
        bird_binary="$BIRD_BIN"
    fi
    
    # Perform syntax check
    if ! "$bird_binary" -p -c "$config_file" >/dev/null 2>&1; then
        log "ERROR: $config_type configuration validation failed for $router"
        
        # Show detailed error for debugging
        log "Detailed validation output:"
        "$bird_binary" -p -c "$config_file" 2>&1 | sed "s/^/  ERROR: /"
        
        return $EXIT_VALIDATION_ERROR
    fi
    
    log "✓ $config_type configuration validated successfully: $config_file"
    return 0
}

# Function to perform comprehensive configuration validation
comprehensive_config_validation() {
    local router="$1"
    local config_dir="${STAGEDIR}/${router}"
    
    log "Performing comprehensive validation for $router"
    
    # Check if configuration directory exists
    if [[ ! -d "$config_dir" ]]; then
        error_exit "Configuration directory not found: $config_dir" $EXIT_CONFIG_ERROR
    fi
    
    # Validate main BIRD configurations
    local bird_configs=("bird.conf" "bird6.conf")
    for config in "${bird_configs[@]}"; do
        local config_path="${config_dir}/${config}"
        if [[ -f "$config_path" ]]; then
            if [[ "$config" == "bird6.conf" ]]; then
                validate_bird_config "$config_path" "bird6" "$router"
            else
                validate_bird_config "$config_path" "bird" "$router"
            fi
            
            if [[ $? -ne 0 ]]; then
                return $EXIT_VALIDATION_ERROR
            fi
        else
            log "WARNING: Configuration file not found: $config_path"
        fi
    done
    
    # Validate that essential configuration sections exist
    validate_config_sections "$config_dir" "$router"
    
    # Validate prefix sets exist and are not empty
    validate_prefix_sets "$config_dir" "$router"
    
    # Validate router-specific settings
    validate_router_settings "$config_dir" "$router"
    
    log "✓ Comprehensive validation completed successfully for $router"
    return 0
}

# Function to validate essential configuration sections
validate_config_sections() {
    local config_dir="$1"
    local router="$2"
    
    log "Validating configuration sections for $router"
    
    # Essential configuration files that should exist
    local essential_files=(
        "header-ipv4.conf"
        "header-ipv6.conf"  
        "interfaces-ipv4.conf"
        "interfaces-ipv6.conf"
        "peerings/peers.ipv4.conf"
        "peerings/peers.ipv6.conf"
    )
    
    for file in "${essential_files[@]}"; do
        local file_path="${config_dir}/${file}"
        if [[ ! -f "$file_path" ]]; then
            log "ERROR: Essential configuration file missing: $file_path"
            return $EXIT_VALIDATION_ERROR
        fi
        
        # Check if file is not empty
        if [[ ! -s "$file_path" ]]; then
            log "WARNING: Configuration file is empty: $file_path"
        fi
    done
    
    log "✓ Configuration sections validated for $router"
    return 0
}

# Function to validate prefix sets
validate_prefix_sets() {
    local config_dir="$1"
    local router="$2"
    
    log "Validating prefix sets for $router"
    
    local prefix_dir="${config_dir}/peerings"
    if [[ ! -d "$prefix_dir" ]]; then
        log "ERROR: Peerings directory not found: $prefix_dir"
        return $EXIT_VALIDATION_ERROR
    fi
    
    # Count prefix sets
    local ipv4_prefixes=0
    local ipv6_prefixes=0
    
    if [[ -f "${prefix_dir}/peers.ipv4.conf" ]]; then
        ipv4_prefixes=$(grep -c "define " "${prefix_dir}/peers.ipv4.conf" 2>/dev/null || echo "0")
    fi
    
    if [[ -f "${prefix_dir}/peers.ipv6.conf" ]]; then
        ipv6_prefixes=$(grep -c "define " "${prefix_dir}/peers.ipv6.conf" 2>/dev/null || echo "0")
    fi
    
    log "Found $ipv4_prefixes IPv4 prefix sets and $ipv6_prefixes IPv6 prefix sets"
    
    if [[ $ipv4_prefixes -eq 0 ]] && [[ $ipv6_prefixes -eq 0 ]]; then
        log "WARNING: No prefix sets found for $router"
    fi
    
    log "✓ Prefix sets validated for $router"
    return 0
}

# Function to validate router-specific settings
validate_router_settings() {
    local config_dir="$1"
    local router="$2"
    
    log "Validating router-specific settings for $router"
    
    # Validate router ID is set
    if [[ -f "${config_dir}/header-ipv4.conf" ]]; then
        if ! grep -q "router id" "${config_dir}/header-ipv4.conf"; then
            log "ERROR: Router ID not found in header-ipv4.conf for $router"
            return $EXIT_VALIDATION_ERROR
        fi
    fi
    
    # Validate that interfaces are configured
    local interface_files=("interfaces-ipv4.conf" "interfaces-ipv6.conf")
    for file in "${interface_files[@]}"; do
        local file_path="${config_dir}/${file}"
        if [[ -f "$file_path" ]]; then
            if ! grep -q "protocol device" "$file_path"; then
                log "WARNING: No device protocol found in $file for $router"
            fi
        fi
    done
    
    log "✓ Router-specific settings validated for $router"
    return 0
}

# Function to validate YAML configuration schema
validate_yaml_schema() {
    local yaml_file="$1"
    
    if [[ ! -f "$yaml_file" ]]; then
        log "ERROR: YAML file not found: $yaml_file"
        return $EXIT_VALIDATION_ERROR
    fi
    
    log "Validating YAML schema: $yaml_file"
    
    # Use Python to validate YAML syntax and structure
    python3 -c "
import yaml
import sys

required_sections = ['builddir', 'stagedir', 'peerings_url', 'ixp_map', 'bgp']

try:
    with open('$yaml_file', 'r') as f:
        config = yaml.safe_load(f)
    
    if config is None:
        print('ERROR: YAML file is empty or invalid')
        sys.exit(1)
    
    # Check for required sections
    missing_sections = []
    for section in required_sections:
        if section not in config:
            missing_sections.append(section)
    
    if missing_sections:
        print(f'ERROR: Missing required sections: {missing_sections}')
        sys.exit(1)
    
    # Validate ixp_map structure
    if 'ixp_map' in config:
        for ixp, ixp_config in config['ixp_map'].items():
            required_ixp_fields = ['ipv4_range', 'ipv6_range', 'present_on']
            for field in required_ixp_fields:
                if field not in ixp_config:
                    print(f'ERROR: Missing {field} in ixp_map.{ixp}')
                    sys.exit(1)
    
    # Validate bgp structure
    if 'bgp' in config:
        for router, router_config in config['bgp'].items():
            required_router_fields = ['fqdn', 'ipv4', 'ipv6', 'vendor']
            for field in required_router_fields:
                if field not in router_config:
                    print(f'ERROR: Missing {field} in bgp.{router}')
                    sys.exit(1)
    
    print('✓ YAML schema validation passed')
    
except yaml.YAMLError as e:
    print(f'ERROR: YAML syntax error: {e}')
    sys.exit(1)
except Exception as e:
    print(f'ERROR: Validation error: {e}')
    sys.exit(1)
" 2>&1

    local validation_result=$?
    if [[ $validation_result -ne 0 ]]; then
        log "ERROR: YAML schema validation failed for $yaml_file"
        return $EXIT_VALIDATION_ERROR
    fi
    
    log "✓ YAML schema validated successfully: $yaml_file"
    return 0
}

# Ensure /usr/sbin/bird{,6} are in the path.
PATH="$PATH:/usr/sbin"

# Set default arguments
arguments=""
if [ "${1:-}" == '-d' ] || [ "${1:-}" == '--debug' ]; then
    arguments='debug'
fi

# Source functions for configuration management
if [[ ! -f "functions.sh" ]]; then
    error_exit "functions.sh not found in current directory" $EXIT_CONFIG_ERROR
fi
. functions.sh

# Get configurable paths from AutoNet configuration
BUILDDIR=${BUILDDIR:-$(getconfig 'builddir' '/opt/routefilters')}
if [[ -z "$BUILDDIR" ]]; then
    error_exit "BUILDDIR not configured" $EXIT_CONFIG_ERROR  
fi
log "Building in: $BUILDDIR"

STAGEDIR=${STAGEDIR:-$(getconfig 'stagedir' '/opt/router-staging')}  
if [[ -z "$STAGEDIR" ]]; then
    error_exit "STAGEDIR not configured" $EXIT_CONFIG_ERROR
fi
log "Staging files in: $STAGEDIR"

# Get configurable paths for tools
BIRD_BIN=${BIRD_BIN:-$(getconfig 'bird_bin' '/usr/sbin/bird')}
BIRD6_BIN=${BIRD6_BIN:-$(getconfig 'bird6_bin' '/usr/sbin/bird')}
BIRDC_BIN=${BIRDC_BIN:-$(getconfig 'birdc_bin' '/usr/sbin/birdc')}
BIRDC6_BIN=${BIRDC6_BIN:-$(getconfig 'birdc6_bin' '/usr/local/bin/birdc6')}

# SSH configuration
SSH_KEY_PATH=${SSH_KEY_PATH:-$(getconfig 'ssh_key_path' "$HOME/.ssh/id_rsa")}
SSH_USER=${SSH_USER:-$(getconfig 'ssh_user' 'root')}
SSH_TIMEOUT=${SSH_TIMEOUT:-$(getconfig 'ssh_timeout' '30')}

# Get routers from configuration instead of hardcoding
declare -a routers=()
while IFS= read -r router; do
    router=$(sanitize_input "$router")
    validate_router "$router"
    routers+=("$router")
done < <(getconfig 'routers' | tr ',' '\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | grep -v '^$')

# Fallback to hardcoded routers if none configured
if [[ ${#routers[@]} -eq 0 ]]; then
    log "WARNING: No routers configured, using defaults"
    routers=(
        'dc5-1.router.nl.example.net'
        'dc5-2.router.nl.example.net' 
        'eunetworks-2.router.nl.example.net'
        'eunetworks-3.router.nl.example.net'
    )
fi

log "Configured routers: ${routers[*]}"

# Validate directories exist and are writable
for dir in "$BUILDDIR" "$STAGEDIR"; do
    if [[ ! -d "$dir" ]]; then
        log "Creating directory: $dir"
        mkdir -p "$dir" || error_exit "Failed to create directory: $dir" $EXIT_CONFIG_ERROR
    fi
    if [[ ! -w "$dir" ]]; then
        error_exit "Directory not writable: $dir" $EXIT_CONFIG_ERROR
    fi
done

# Validate required binaries
for bin in "$BIRD_BIN" "$BIRD6_BIN"; do
    if [[ ! -x "$bin" ]]; then
        error_exit "Binary not found or not executable: $bin" $EXIT_TOOL_ERROR
    fi
done

# generate peer configs
./peering_filters configs "${arguments}"

for router in "${routers[@]}"; do
    rm -rf ${STAGEDIR}/${router}
    mkdir -p ${STAGEDIR}/${router}

    ./gentool -y vars/generic.yml -t templates/envvars.j2 -o ${STAGEDIR}/${router}/envvars
    ./gentool -y vars/generic.yml vars/${router}.yml -t templates/ebgp_state.j2 -o ${STAGEDIR}/${router}/ebgp_state.conf

    ./gentool -4 -y vars/generic.yml vars/${router}.yml -t templates/header.j2 -o ${STAGEDIR}/${router}/header-ipv4.conf
    ./gentool -6 -y vars/generic.yml vars/${router}.yml -t templates/header.j2 -o ${STAGEDIR}/${router}/header-ipv6.conf
    ./gentool -4 -y vars/generic.yml vars/${router}.yml -t templates/bfd.j2 -o ${STAGEDIR}/${router}/bfd-ipv4.conf
    ./gentool -6 -y vars/generic.yml vars/${router}.yml -t templates/bfd.j2 -o ${STAGEDIR}/${router}/bfd-ipv6.conf
    ./gentool -4 -y vars/generic.yml vars/${router}.yml -t templates/ospf.j2 -o ${STAGEDIR}/${router}/ospf-ipv4.conf
    ./gentool -6 -y vars/generic.yml vars/${router}.yml -t templates/ospf.j2 -o ${STAGEDIR}/${router}/ospf-ipv6.conf

    ./gentool -4 -y vars/generic.yml vars/${router}.yml -t templates/ibgp.j2 -o ${STAGEDIR}/${router}/ibgp-ipv4.conf
    ./gentool -6 -y vars/generic.yml vars/${router}.yml -t templates/ibgp.j2 -o ${STAGEDIR}/${router}/ibgp-ipv6.conf

    ./gentool -4 -y vars/generic.yml vars/${router}.yml -t templates/interfaces.j2 -o ${STAGEDIR}/${router}/interfaces-ipv4.conf
    ./gentool -6 -y vars/generic.yml vars/${router}.yml -t templates/interfaces.j2 -o ${STAGEDIR}/${router}/interfaces-ipv6.conf

    ./gentool -y vars/generic.yml vars/${router}.yml -t templates/generic_filters.j2 -o ${STAGEDIR}/${router}/generic_filters.conf

    ./gentool -4 -y vars/generic.yml vars/${router}.yml -t templates/afi_specific_filters.j2 -o ${STAGEDIR}/${router}/ipv4_filters.conf
    ./gentool -6 -y vars/generic.yml vars/${router}.yml -t templates/afi_specific_filters.j2 -o ${STAGEDIR}/${router}/ipv6_filters.conf

    ./gentool -4 -y vars/generic.yml vars/${router}.yml vars/members_bgp.yml -t templates/members_bgp.j2 -o ${STAGEDIR}/${router}/members_bgp-ipv4.conf
    ./gentool -6 -y vars/generic.yml vars/${router}.yml vars/members_bgp.yml -t templates/members_bgp.j2 -o ${STAGEDIR}/${router}/members_bgp-ipv6.conf

    ./gentool -4 -y vars/generic.yml vars/${router}.yml vars/transit.yml -t templates/transit.j2 -o ${STAGEDIR}/${router}/transit-ipv4.conf
    ./gentool -6 -y vars/generic.yml vars/${router}.yml vars/transit.yml -t templates/transit.j2 -o ${STAGEDIR}/${router}/transit-ipv6.conf

    ./gentool -4 -y vars/generic.yml vars/${router}.yml vars/scrubbers.yml -t templates/scrubbers.j2 -o ${STAGEDIR}/${router}/scrubber-ipv4.conf
    ./gentool -6 -y vars/generic.yml vars/${router}.yml vars/scrubbers.yml -t templates/scrubbers.j2 -o ${STAGEDIR}/${router}/scrubber-ipv6.conf
    ./gentool -4 -y vars/generic.yml vars/${router}.yml vars/scrubbers.yml -t templates/via_scrubbers_afi.j2 -o ${STAGEDIR}/${router}/via_scrubbers_ipv4.conf
    ./gentool -6 -y vars/generic.yml vars/${router}.yml vars/scrubbers.yml -t templates/via_scrubbers_afi.j2 -o ${STAGEDIR}/${router}/via_scrubbers_ipv6.conf

    # DC5 specific stuff
    if [ "${router}" == "dc5-1.router.nl.example.net" ] || [ "${router}" == "dc5-2.router.nl.example.net" ]; then
        ./gentool -4 -t templates/static_routes.j2 -y vars/statics-dc5.yml -o ${STAGEDIR}/${router}/static_routes-ipv4.conf
        ./gentool -6 -t templates/static_routes.j2 -y vars/statics-dc5.yml -o ${STAGEDIR}/${router}/static_routes-ipv6.conf
    # EUNetworks specific stuff
    elif [ "${router}" == "eunetworks-2.router.nl.example.net" ] || [ "${router}" == "eunetworks-3.router.nl.example.net" ]; then
        ./gentool -4 -t templates/static_routes.j2 -y vars/statics-eunetworks.yml -o ${STAGEDIR}/${router}/static_routes-ipv4.conf
        ./gentool -6 -t templates/static_routes.j2 -y vars/statics-eunetworks.yml -o ${STAGEDIR}/${router}/static_routes-ipv6.conf
    fi

    rsync -av blobs/${router}/ ${STAGEDIR}/${router}/
    rsync -av ${BUILDDIR}/rpki/ ${STAGEDIR}/${router}/rpki/

    rsync -av --delete ${BUILDDIR}/*bird* ${STAGEDIR}/${router}/peerings/
    rsync -av --delete ${BUILDDIR}/${router}.ipv4.config ${STAGEDIR}/${router}/peerings/peers.ipv4.conf
    rsync -av --delete ${BUILDDIR}/${router}.ipv6.config ${STAGEDIR}/${router}/peerings/peers.ipv6.conf

    TZ=Etc/UTC date '+# Created: %a, %d %b %Y %T %z' >>  ${STAGEDIR}/${router}/bird.conf
    TZ=Etc/UTC date '+# Created: %a, %d %b %Y %T %z' >>  ${STAGEDIR}/${router}/bird6.conf

done

if [ "${1:-}" == "push" ]; then

    # Check for required tools
    if ! command_exists bird; then
        error_exit "bird command not found in PATH" $EXIT_TOOL_ERROR
    fi

    # Validate SSH key
    validate_ssh_key "$SSH_KEY_PATH"

    # sync config to routers
    eval "$(ssh-agent -t 600)"
    if ! ssh-add "$SSH_KEY_PATH"; then
        error_exit "Failed to add SSH key" $EXIT_SSH_ERROR
    fi

    # Perform comprehensive validation before pushing
    log "Performing comprehensive validation before deployment..."
    
    # Validate YAML configuration schema first
    if ! validate_yaml_schema "vars/generic.yml"; then
        error_exit "YAML schema validation failed" $EXIT_VALIDATION_ERROR
    fi
    
    # Validate each router configuration comprehensively
    validation_errors=0
    for router in "${routers[@]}"; do
        log "Performing comprehensive validation for $router"
        
        if ! comprehensive_config_validation "$router"; then
            log "ERROR: Comprehensive validation failed for $router"
            ((validation_errors++))
        fi
    done
    
    if [[ $validation_errors -gt 0 ]]; then
        log "ERROR: $validation_errors router(s) failed validation"
        eval "$(ssh-agent -k)"
        error_exit "Configuration validation failed before deployment" $EXIT_VALIDATION_ERROR
    fi
    
    log "✓ All configurations validated successfully, proceeding with deployment"

    # Push configurations to routers
    for router in "${routers[@]}"; do
        log "Uploading configuration for $router"
        if ! rsync -avH --delete "${STAGEDIR}/${router}/" "root@${router}:/etc/bird/"; then
            log "ERROR: Failed to upload configuration to $router"
            continue
        fi

        # Use configured SSH parameters with proper sanitization and timeout
        sanitized_router=$(sanitize_input "$router")
        if ! ssh -o ConnectTimeout="$SSH_TIMEOUT" -o StrictHostKeyChecking=yes "${SSH_USER}@${sanitized_router}" 'chown -R root: /etc/bird; /usr/sbin/birdc configure; /usr/local/bin/birdc6 configure' | sed "s/^/${router}: /"; then
            log "ERROR: Failed to reload configuration on $router"
        fi
    done

    # Clean up SSH agent
    eval "$(ssh-agent -k)"

    # update RIPE if new peers are added
    if command_exists php; then
        php /opt/organization/update-ripe.php
        php /opt/organization/update-asset-ripe.php
    else
        log "WARNING: php not found, skipping RIPE updates"
    fi

elif [ "${1}" == "check" ]; then

    # Check for required tools
    if ! command_exists bird; then
        log "ERROR: bird command not found in PATH"
        exit 1
    fi

    for router in "${routers[@]}"; do
        log "Checking configuration for $router"
        if ! /usr/sbin/bird -p -c "${STAGEDIR}/${router}/bird.conf"; then
            log "ERROR: bird.conf validation failed for $router"
            exit 1
        fi
        if ! /usr/sbin/bird -p -c "${STAGEDIR}/${router}/bird6.conf"; then
            log "ERROR: bird6.conf validation failed for $router"
            exit 1
        fi
    done
else
    echo "Command '${1}' not supported" >&2
    echo "Usage: $0 [push|check] [-d|--debug]" >&2
    exit $EXIT_CONFIG_ERROR
fi
