#!/usr/bin/env bash
set -euo pipefail

# colleague cicd workflow — thin layer over `devex pr` plus two
# extensions (`status`, `await`) for SonarCloud gating and triage flow.
#
# `devex` is the same tool as `agex` (the agentculture PR-lifecycle CLI),
# just invoked under the `devex` name. This skill standardizes on `devex`
# and never shells out to `gh` directly to open a PR.
#
# Subcommands:
#   lint                   `devex pr lint --exit-on-violation`. Same rules
#                          the skill used to vendor in portability-lint.sh
#                          (which still ships for `steward doctor`).
#   open  [pr flags]       `devex pr open --delayed-read "$@"`. Creates the
#                          PR, then polls 180s for an initial briefing.
#                          Body via --body-file PATH or stdin; --title is
#                          required.
#   read  [PR] [--wait N]  `devex pr read "$@"`. One-shot briefing; pass
#                          --wait N to poll for reviewer readiness.
#   reply <PR>             `devex pr reply <PR>` (JSONL on stdin). devex
#                          auto-signs from culture.yaml.
#   delta                  `devex pr delta`. Sibling alignment dump.
#
#   status <PR>            Steward extension: pr-status.sh — SonarCloud
#                          gate, OPEN issues, hotspots, unresolved
#                          inline-thread tally, deploy-preview URL.
#   await  <PR>            Steward extension: `read --wait` for the
#                          briefing, then `status` for the gate. Exits
#                          non-zero on SonarCloud ERROR or unresolved
#                          threads. Tunables: STEWARD_PR_AWAIT_WAIT
#                          (default 1800), STEWARD_PR_AWAIT_SECONDS (legacy).
#
#   help                   print this message

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# devex's `--agent` flag accepts only claude-code|codex|copilot|acp. The
# workspace culture.yaml convention is `backend: claude`, so we always
# pass --agent explicitly to insulate the skill from that naming gap.
# Override via STEWARD_DEVEX_AGENT (the legacy STEWARD_AGEX_AGENT is still
# read for back-compat) if you're running under codex/copilot/acp.
DEVEX_AGENT="${STEWARD_DEVEX_AGENT:-${STEWARD_AGEX_AGENT:-claude-code}}"

require_devex() {
    if ! command -v devex >/dev/null 2>&1; then
        echo "✗ devex not on PATH. Install devex (the agentculture PR CLI)." >&2
        echo "  uv tool install devex  # or pip install devex" >&2
        exit 2
    fi
}

cmd="${1:-help}"
shift || true

case "$cmd" in
    lint)
        require_devex
        exec devex pr lint --agent "$DEVEX_AGENT" --exit-on-violation "$@"
        ;;
    open)
        require_devex
        exec devex pr open --agent "$DEVEX_AGENT" --delayed-read "$@"
        ;;
    read)
        require_devex
        exec devex pr read --agent "$DEVEX_AGENT" "$@"
        ;;
    reply)
        require_devex
        PR="${1:?Usage: workflow.sh reply <PR>  (JSONL on stdin)}"
        exec devex pr reply --agent "$DEVEX_AGENT" "$PR"
        ;;
    delta)
        require_devex
        exec devex pr delta --agent "$DEVEX_AGENT" "$@"
        ;;
    status)
        PR="${1:?Usage: workflow.sh status <PR>}"
        exec bash "$SCRIPT_DIR/pr-status.sh" "$PR"
        ;;
    await)
        require_devex
        PR="${1:?Usage: workflow.sh await <PR>}"

        # Legacy fixed-sleep escape hatch.
        if [[ -n "${STEWARD_PR_AWAIT_SECONDS:-}" ]]; then
            echo "warning: STEWARD_PR_AWAIT_SECONDS is deprecated; prefer STEWARD_PR_AWAIT_WAIT." >&2
            echo "→ sleeping ${STEWARD_PR_AWAIT_SECONDS}s (legacy fixed-sleep) before devex pr read …" >&2
            sleep "$STEWARD_PR_AWAIT_SECONDS"
            WAIT_ARGS=()
        else
            WAIT="${STEWARD_PR_AWAIT_WAIT:-1800}"
            WAIT_ARGS=(--wait "$WAIT")
        fi

        # 1. devex pr read --wait — readiness loop + briefing.
        # Capture rc from the command itself (not from the negated test —
        # `if ! cmd; then rc=$?` would store the if-test status, always 0
        # in the failure branch, masking the real exit code).
        echo "── devex pr read ─────────────────────────────────────────────────────" >&2
        if devex pr read --agent "$DEVEX_AGENT" "$PR" "${WAIT_ARGS[@]}"; then
            READ_RC=0
        else
            READ_RC=$?
        fi
        if [[ "$READ_RC" -ne 0 ]]; then
            echo "✗ devex pr read failed (exit $READ_RC)" >&2
            exit "$READ_RC"
        fi

        # 2. pr-status.sh — authoritative gate (Sonar QG, unresolved threads).
        echo >&2
        echo "── pr-status ─────────────────────────────────────────────────────────" >&2
        if STATUS_OUT=$(bash "$SCRIPT_DIR/pr-status.sh" "$PR" 2>&1); then
            STATUS_RC=0
        else
            STATUS_RC=$?
        fi
        printf '%s\n' "$STATUS_OUT"
        if [[ "$STATUS_RC" -ne 0 ]]; then
            echo >&2
            echo "✗ pr-status.sh failed (exit $STATUS_RC) — cannot determine PR state" >&2
            exit "$STATUS_RC"
        fi

        # 3. Gate. Markers in pr-status.sh output:
        #     "Quality Gate ERROR"          → Sonar fail
        #     "Unresolved: N" with N>0      → unresolved threads
        SONAR_FAIL=0
        UNRESOLVED=0
        if printf '%s\n' "$STATUS_OUT" | grep -qE 'Quality Gate ERROR'; then
            SONAR_FAIL=1
        fi
        if PENDING=$(printf '%s\n' "$STATUS_OUT" | grep -oE 'Unresolved:[[:space:]]+[0-9]+' | grep -oE '[0-9]+$' | head -1); then
            [[ -n "${PENDING:-}" ]] && [[ "$PENDING" -gt 0 ]] && UNRESOLVED=1
        fi
        if [[ "$SONAR_FAIL" -eq 1 ]] || [[ "$UNRESOLVED" -eq 1 ]]; then
            echo >&2
            [[ "$SONAR_FAIL" -eq 1 ]] && echo "✗ SonarCloud quality gate ERROR" >&2
            [[ "$UNRESOLVED" -eq 1 ]] && echo "✗ ${PENDING} unresolved review thread(s)" >&2
            exit 1
        fi
        echo >&2
        echo "✓ no SonarCloud ERROR, no unresolved threads" >&2
        ;;
    help|--help|-h)
        # Print the contiguous leading comment block (from line 4), stripping
        # the "# " prefix; stop at the first non-comment line. Robust to edits
        # in the header length (no hard-coded line range).
        awk 'NR<4{next} /^#/{sub(/^# ?/,"");print;next} {exit}' "${BASH_SOURCE[0]}"
        ;;
    *)
        echo "unknown subcommand: $cmd" >&2
        echo "run '$(basename "$0") help' for usage." >&2
        exit 2
        ;;
esac
