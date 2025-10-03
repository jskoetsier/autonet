#!/bin/bash
set -euo pipefail

# Function to log messages with timestamp
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >&2
}

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Ensure /usr/sbin/bird{,6} are in the path.
PATH="$PATH:/usr/sbin"

# Set default arguments
arguments=""
if [ "${1:-}" == '-d' ] || [ "${1:-}" == '--debug' ]; then
    arguments='debug'
fi

# Define routers as array for better handling
declare -a routers=(
    'dc5-1.router.nl.example.net'
    'dc5-2.router.nl.example.net'
    'eunetworks-2.router.nl.example.net'
    'eunetworks-3.router.nl.example.net'
)

. functions.sh

# Get output/staging dirs from AutoNet configuration
BUILDDIR=${BUILDDIR:-`getconfig 'builddir' '/opt/routefilters'`}
echo Building in \'${BUILDDIR}\'
STAGEDIR=${STAGEDIR:-`getconfig 'stagedir' '/opt/router-staging'`}
echo Staging files in \'${STAGEDIR}\'

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

if [ "${1}" == "push" ]; then

    # Check for required tools
    if ! command_exists bird; then
        log "ERROR: bird command not found in PATH"
        exit 1
    fi

    # Get SSH key from environment or use default
    SSH_KEY_PATH="${SSH_KEY_PATH:-$HOME/.ssh/id_rsa}"

    if [ ! -f "$SSH_KEY_PATH" ]; then
        log "ERROR: SSH key not found at $SSH_KEY_PATH"
        log "Set SSH_KEY_PATH environment variable to specify custom key location"
        exit 1
    fi

    # sync config to routers
    eval "$(ssh-agent -t 600)"
    if ! ssh-add "$SSH_KEY_PATH"; then
        log "ERROR: Failed to add SSH key"
        eval "$(ssh-agent -k)"
        exit 1
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

        if ! ssh "root@${router}" 'chown -R root: /etc/bird; /usr/sbin/birdc configure; /usr/local/bin/birdc6 configure' | sed "s/^/${router}: /"; then
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
    echo "Command '${1}' not supported" 1>&2
	exit 1
fi
