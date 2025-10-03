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

    # Validate configurations before pushing
    for router in "${routers[@]}"; do
        log "Checking configuration for $router"
        if ! /usr/sbin/bird -p -c "${STAGEDIR}/${router}/bird.conf"; then
            log "ERROR: bird.conf validation failed for $router"
            eval "$(ssh-agent -k)"
            exit 1
        fi
        if ! /usr/sbin/bird -p -c "${STAGEDIR}/${router}/bird6.conf"; then
            log "ERROR: bird6.conf validation failed for $router"
            eval "$(ssh-agent -k)"
            exit 1
        fi
    done

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
