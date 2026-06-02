#!/usr/bin/env bash
# doc-test-alignment skill — entry point.
#
# Thin portable wrapper: resolves the script's own directory and delegates
# to check.py. All arguments are forwarded verbatim.
#
# Exit codes mirror check.py:
#   0  aligned
#   1  drift found (error-severity check failed)
#   2  usage / operational error
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Guard the one external tool this wrapper needs so a missing interpreter fails
# with a clear message + the usage/operational exit code (2), not a bare
# "python3: command not found".
if ! command -v python3 >/dev/null 2>&1; then
    echo "doc-test-alignment: python3 not found on PATH (required to run check.py)" >&2
    exit 2
fi

exec python3 "$SCRIPT_DIR/check.py" "$@"
