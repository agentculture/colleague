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
exec python3 "$SCRIPT_DIR/check.py" "$@"
