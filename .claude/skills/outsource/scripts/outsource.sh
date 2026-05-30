#!/usr/bin/env bash
#
# outsource — hand a scoped repo task to convertible (a different engine/mind).
#
# Convertible's engine is not necessarily stronger than the calling agent; it is
# a *different* mind, and diversity helps — which is why `review` is the headline
# verb. Three verbs drive `convertible drive` and print the result:
#
#   outsource explore "<question or area>"   read-only investigation -> findings
#   outsource review  "<what to focus on>"   diverse second-opinion on the diff
#   outsource write   "<task>" [--pr]        implement a change
#
# explore/review run in a throwaway `git worktree` at HEAD, so they can never
# touch your working tree or branch (any stray write is discarded). write runs
# in-place and lands a drive branch (or a PR with --pr).
#
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROMPTS_DIR="$SKILL_DIR/prompts"

# ── resolve the convertible CLI (installed, then local-dev fallback) ─────────
CONVERTIBLE=()
resolve_convertible() {
    if command -v convertible >/dev/null 2>&1; then
        CONVERTIBLE=(convertible)        # installed tool — the normal case
        return 0
    fi
    # Local-dev fallback: inside the convertible checkout, run via uv.
    local dir="$PWD"
    while [[ -n "$dir" ]] && [[ "$dir" != "/" ]]; do
        if [[ -f "$dir/pyproject.toml" ]] \
            && grep -q '^name = "convertible-cli"' "$dir/pyproject.toml" 2>/dev/null; then
            if command -v uv >/dev/null 2>&1; then
                CONVERTIBLE=(uv run convertible)
                return 0
            fi
            break
        fi
        dir=$(dirname "$dir")
    done
    cat >&2 <<'EOF'
error: convertible CLI not found.
hint: install it with `uv tool install convertible-cli` (or `pipx install convertible-cli`),
      or run from inside the convertible checkout with `uv` available.
      https://github.com/agentculture/convertible
EOF
    return 1
}

usage() {
    cat <<'EOF'
outsource — hand a scoped repo task to convertible (a different engine/mind).

Usage:
  outsource explore "<question or area>"     Read-only investigation -> findings (no side effects)
  outsource review  "<what to focus on>"     Diverse second-opinion on the committed diff (no side effects)
  outsource write   "<task>" [--pr]          Implement a change (drive branch, or PR with --pr)

Options:
  --repo PATH        Target repo (default: .)
  --base BRANCH      Base for `review` diff (default: main)
  --engine NAME      Engine wheel (default: $CONVERTIBLE_ENGINE or vllm-openai)
  --model NAME       Model (default: $CONVERTIBLE_MODEL or mmangkad/Qwen3.6-27B-NVFP4)
  --base-url URL     OpenAI base URL (default: $CONVERTIBLE_BASE_URL or http://localhost:8001/v1)
  --max-steps N      Loop step budget (default: 20)
  --allow-dirty      (write) allow running on a dirty tree
  --pr               (write) push + open a PR instead of a local drive branch

explore/review run in a throwaway git worktree at HEAD — they cannot touch your
working tree or branch. review compares <base>...HEAD (committed changes only).
EOF
}

# ── parse the verb ──────────────────────────────────────────────────────────
VERB="${1:-}"
case "$VERB" in
    explore | review | write) shift ;;
    -h | --help) usage; exit 0 ;;
    "") usage >&2; exit 2 ;;
    *)
        echo "error: unknown verb '$VERB' (expected explore|review|write)" >&2
        echo "hint: run 'outsource --help'" >&2
        exit 2
        ;;
esac

# ── defaults + flag parsing ─────────────────────────────────────────────────
REPO="."
BASE="main"
ENGINE="${CONVERTIBLE_ENGINE:-vllm-openai}"
MODEL="${CONVERTIBLE_MODEL:-mmangkad/Qwen3.6-27B-NVFP4}"
BASE_URL="${CONVERTIBLE_BASE_URL:-http://localhost:8001/v1}"
MAX_STEPS=20
ALLOW_DIRTY=0
OPEN_PR=0
ARG=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo) REPO="$2"; shift 2 ;;
        --base) BASE="$2"; shift 2 ;;
        --engine) ENGINE="$2"; shift 2 ;;
        --model) MODEL="$2"; shift 2 ;;
        --base-url) BASE_URL="$2"; shift 2 ;;
        --max-steps) MAX_STEPS="$2"; shift 2 ;;
        --allow-dirty) ALLOW_DIRTY=1; shift ;;
        --pr) OPEN_PR=1; shift ;;
        -h | --help) usage; exit 0 ;;
        --) shift; while [[ $# -gt 0 ]]; do ARG="${ARG:+$ARG }$1"; shift; done ;;
        -*) echo "error: unknown option '$1'" >&2; echo "hint: run 'outsource --help'" >&2; exit 2 ;;
        *) ARG="${ARG:+$ARG }$1"; shift ;;
    esac
done

[[ -n "$ARG" ]] || { echo "error: $VERB needs a description argument" >&2; usage >&2; exit 2; }
[[ -d "$REPO" ]] || { echo "error: --repo is not a directory: $REPO" >&2; exit 2; }
REPO="$(cd "$REPO" && pwd)"

resolve_convertible || exit 2

COMMON_FLAGS=(--engine "$ENGINE" --model "$MODEL" --base-url "$BASE_URL" --max-steps "$MAX_STEPS" --json)

# ── render an instruction from a prompt template ────────────────────────────
render_prompt() {
    local file="$PROMPTS_DIR/$1.md"
    [[ -f "$file" ]] || { echo "error: missing prompt template: $file" >&2; exit 2; }
    ARG="$ARG" BASE="$BASE" python3 - "$file" <<'PY'
import os, sys
tpl = open(sys.argv[1], encoding="utf-8").read()
sys.stdout.write(tpl.replace("$ARGUMENTS", os.environ["ARG"]).replace("$BASE", os.environ["BASE"]))
PY
}

# ── print the TaskResult that convertible emitted as JSON on stdout ─────────
# Reads JSON on stdin; prints a human/agent-readable digest; exits non-zero if
# the drive failed.
print_result() {
    python3 - <<'PY'
import sys, json
raw = sys.stdin.read().strip()
if not raw:
    sys.stderr.write("error: convertible produced no result on stdout (see diagnostics above)\n")
    sys.exit(2)
try:
    d = json.loads(raw)
except Exception:
    sys.stderr.write("error: could not parse convertible --json output:\n")
    sys.stderr.write(raw[:2000] + "\n")
    sys.exit(2)
print("status:", d.get("status"))
print()
print((d.get("summary") or "").rstrip())
cf = d.get("changed_files") or []
if cf:
    print("\nchanged files:", ", ".join(cf))
if d.get("branch"):
    print("drive branch:", d["branch"])
if d.get("artifacts_path"):
    print("artifact:", d["artifacts_path"])
sys.exit(0 if d.get("status") == "ok" else 1)
PY
}

# ── read-only verbs: isolate the drive in a throwaway worktree at HEAD ──────
run_readonly() {
    local instruction="$1"
    git -C "$REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
        || { echo "error: --repo is not a git repository: $REPO" >&2; exit 2; }

    local wt drive_branch=""
    wt="$(mktemp -d)"
    cleanup() {
        git -C "$REPO" worktree remove --force "$wt" >/dev/null 2>&1 || true
        rm -rf "$wt" >/dev/null 2>&1 || true
        if [[ -n "$drive_branch" ]]; then
            git -C "$REPO" branch -D "$drive_branch" >/dev/null 2>&1 || true
        fi
    }
    trap cleanup EXIT

    git -C "$REPO" worktree add -q --detach "$wt" HEAD

    local out
    out="$("${CONVERTIBLE[@]}" drive "$instruction" --repo "$wt" --no-pr "${COMMON_FLAGS[@]}")" || true
    drive_branch="$(printf '%s' "$out" | python3 -c 'import sys,json
try: print(json.load(sys.stdin).get("branch") or "")
except Exception: print("")' 2>/dev/null || true)"
    printf '%s' "$out" | print_result
}

# ── write verb: in-place drive (drive branch, or PR with --pr) ──────────────
run_write() {
    local instruction="$1"
    if [[ "$ALLOW_DIRTY" -eq 0 ]] \
        && [[ -n "$(git -C "$REPO" status --porcelain 2>/dev/null)" ]]; then
        echo "error: working tree is dirty — commit/stash first, or pass --allow-dirty" >&2
        echo "hint: 'convertible drive --no-pr' commits uncommitted edits onto the drive branch" >&2
        exit 2
    fi
    local out
    if [[ "$OPEN_PR" -eq 1 ]]; then
        out="$("${CONVERTIBLE[@]}" drive "$instruction" --repo "$REPO" "${COMMON_FLAGS[@]}")"
    else
        out="$("${CONVERTIBLE[@]}" drive "$instruction" --repo "$REPO" --no-pr "${COMMON_FLAGS[@]}")"
    fi
    printf '%s' "$out" | print_result
}

case "$VERB" in
    explore) run_readonly "$(render_prompt explore)" ;;
    review) run_readonly "$(render_prompt review)" ;;
    write) run_write "$(render_prompt write)" ;;
esac
