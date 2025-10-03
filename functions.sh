#!/bin/bash
# Support functions for AutoNet scripts

function getconfig () {
    varname=$1
    default=$2

    # Robust YAML parsing with proper error handling
    if [ ! -f "vars/generic.yml" ]; then
        echo "ERROR: Configuration file vars/generic.yml not found" >&2
        echo "${default}"
        return 1
    fi

    # Use a more robust Python script for YAML parsing
    value=$(python3 -c "
import yaml
import sys
import json

try:
    with open('vars/generic.yml', 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    if config is None:
        print('', end='')
        sys.exit(1)

    # Navigate nested keys (e.g., 'rpki.validation')
    keys = '$varname'.split('.')
    current = config

    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            print('', end='')
            sys.exit(1)

    # Handle different data types properly
    if isinstance(current, (str, int, float)):
        print(current, end='')
    elif isinstance(current, bool):
        print('True' if current else 'False', end='')
    elif isinstance(current, (list, dict)):
        # For complex types, return empty and let caller use default
        print('', end='')
        sys.exit(1)
    else:
        print('', end='')
        sys.exit(1)

except (yaml.YAMLError, FileNotFoundError, PermissionError, UnicodeDecodeError, KeyError, TypeError) as e:
    print('', end='')
    sys.exit(1)
except Exception as e:
    print('', end='')
    sys.exit(1)
" 2>/dev/null)
    rc=$?

    if [ ${rc} -eq 0 ] && [ -n "${value}" ]; then
        echo "${value}"
        return 0
    else
        echo "${default}"
        return 0
    fi
}
