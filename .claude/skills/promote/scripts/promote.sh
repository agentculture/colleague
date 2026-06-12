#!/usr/bin/env bash
#
# promote.sh — graduate colleague from a task runner into a Culture resident.
#
# Resolves the colleague CLI portably and forwards all arguments verbatim to
# `colleague promote`. See `colleague explain promote` for the full flag set.
#
# Usage:
#   bash .claude/skills/promote/scripts/promote.sh [promote args...]
#
# Exit codes mirror the colleague CLI contract:
#   0  success
#   1  user-input error (bad flag, missing [culture] extra, etc.)
#   2  environment/setup error (colleague CLI not found)
#
set -euo pipefail

# ── resolve the colleague CLI (installed, then local-dev fallback) ─────────
COLLEAGUE=()
resolve_colleague() {
    if command -v colleague >/dev/null 2>&1; then
        COLLEAGUE=(colleague)        # installed tool — the normal case
        return 0
    fi
    # Local-dev fallback: inside the colleague checkout, run via uv.
    local dir="$PWD"
    while [[ -n "$dir" ]] && [[ "$dir" != "/" ]]; do
        if [[ -f "$dir/pyproject.toml" ]] \
            && grep -q '^name = "colleague"' "$dir/pyproject.toml" 2>/dev/null; then
            if command -v uv >/dev/null 2>&1; then
                COLLEAGUE=(uv run colleague)
                return 0
            fi
            break
        fi
        dir=$(dirname "$dir")
    done
    cat >&2 <<'EOF'
error: colleague CLI not found.
hint: install it with `uv tool install colleague` (or `pipx install colleague`),
      or run from inside the colleague checkout with `uv` available.
      https://github.com/agentculture/colleague
EOF
    return 1
}

resolve_colleague || exit 2

# Forward all arguments verbatim; exit with the CLI's exit code.
exec "${COLLEAGUE[@]}" promote "$@"
