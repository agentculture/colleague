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
#   outsource write   "<task>" [--apply]     implement a change (preview by default)
#   outsource feedback <id|last> --rating N  grade a past drive (ROI loop); no rating -> show
#
# explore/review run in a throwaway `git worktree` at HEAD, so they can never
# touch your working tree or branch (any stray write is discarded). write also
# previews in a throwaway worktree by default (reporting what it WOULD change);
# pass --apply to land a drive branch in place, or --pr to push + open a PR.
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
  outsource write   "<task>" [--apply|--pr]  Implement a change (preview by default; --apply lands it)
  outsource feedback <id|last> [--rating N]  Grade a past drive (ROI loop); with --rating records, without shows

Options:
  --repo PATH        Target repo (default: .)
  --base BRANCH      Base for `review` diff (default: main)
  --engine NAME      Engine wheel (default: $CONVERTIBLE_ENGINE or vllm-openai)
  --model NAME       Model (default: $CONVERTIBLE_MODEL or mmangkad/Qwen3.6-27B-NVFP4)
  --base-url URL     OpenAI base URL (default: $CONVERTIBLE_BASE_URL or http://localhost:8001/v1)
  --max-steps N      Loop step budget (default: 20)
  --timeout N        Per-request timeout, seconds (default: $CONVERTIBLE_TIMEOUT or 300)
  --apply            (write) apply the change in place (drive branch) instead of previewing
  --allow-dirty      (write) allow running on a dirty tree (only with --apply/--pr)
  --pr               (write) push + open a PR instead of a local drive branch (implies --apply)
  --rating N         (feedback) record a 1-5 quality rating for the drive
  --notes "..."      (feedback) free-text notes to store with the rating
  --by NAME          (feedback) who is grading (default: convertible's resolved identity)

explore/review run in a throwaway git worktree at HEAD — they cannot touch your
working tree or branch. review compares <base>...HEAD (committed changes only).
write previews in a throwaway worktree too unless --apply (or --pr) is given.
feedback grades a finished drive: stats (in the artifact) say what it cost,
feedback says how good it was — together, the ROI of outsourcing.
EOF
}

# ── parse the verb ──────────────────────────────────────────────────────────
VERB="${1:-}"
case "$VERB" in
    explore | review | write | feedback) shift ;;
    -h | --help) usage; exit 0 ;;
    "") usage >&2; exit 2 ;;
    *)
        echo "error: unknown verb '$VERB' (expected explore|review|write|feedback)" >&2
        echo "hint: run 'outsource --help'" >&2
        exit 2
        ;;
esac

# Required external tools — fail fast with a clear message, not an opaque
# mid-run error, if the environment is missing one.
require_tools() {
    local missing=() t
    for t in python3 git grep mktemp; do
        command -v "$t" >/dev/null 2>&1 || missing+=("$t")
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        echo "error: missing required tool(s): ${missing[*]}" >&2
        echo "hint: outsource needs python3, git, grep, and mktemp on PATH." >&2
        exit 2
    fi
}

# Guard a value-taking flag: a trailing flag with no value would otherwise
# dereference an unset $2 and abort under `set -u`.
need_value() {  # $1 = remaining arg count ($#), $2 = flag name
    [[ "$1" -ge 2 ]] || {
        echo "error: $2 requires a value" >&2
        echo "hint: run 'outsource --help'" >&2
        exit 2
    }
}

require_tools

# ── defaults + flag parsing ─────────────────────────────────────────────────
REPO="."
BASE="main"
ENGINE="${CONVERTIBLE_ENGINE:-vllm-openai}"
MODEL="${CONVERTIBLE_MODEL:-mmangkad/Qwen3.6-27B-NVFP4}"
BASE_URL="${CONVERTIBLE_BASE_URL:-http://localhost:8001/v1}"
MAX_STEPS=20
TIMEOUT="${CONVERTIBLE_TIMEOUT:-300}"
ALLOW_DIRTY=0
APPLY=0
OPEN_PR=0
RATING=""
NOTES=""
BY=""
ARG=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo) need_value "$#" "$1"; REPO="$2"; shift 2 ;;
        --base) need_value "$#" "$1"; BASE="$2"; shift 2 ;;
        --engine) need_value "$#" "$1"; ENGINE="$2"; shift 2 ;;
        --model) need_value "$#" "$1"; MODEL="$2"; shift 2 ;;
        --base-url) need_value "$#" "$1"; BASE_URL="$2"; shift 2 ;;
        --max-steps) need_value "$#" "$1"; MAX_STEPS="$2"; shift 2 ;;
        --timeout) need_value "$#" "$1"; TIMEOUT="$2"; shift 2 ;;
        --apply) APPLY=1; shift ;;
        --allow-dirty) ALLOW_DIRTY=1; shift ;;
        --pr) OPEN_PR=1; shift ;;
        --rating) need_value "$#" "$1"; RATING="$2"; shift 2 ;;
        --notes) need_value "$#" "$1"; NOTES="$2"; shift 2 ;;
        --by) need_value "$#" "$1"; BY="$2"; shift 2 ;;
        -h | --help) usage; exit 0 ;;
        --) shift; while [[ $# -gt 0 ]]; do ARG="${ARG:+$ARG }$1"; shift; done ;;
        -*) echo "error: unknown option '$1'" >&2; echo "hint: run 'outsource --help'" >&2; exit 2 ;;
        *) ARG="${ARG:+$ARG }$1"; shift ;;
    esac
done

[[ -n "$ARG" ]] || { echo "error: $VERB needs a description argument" >&2; usage >&2; exit 2; }
[[ -d "$REPO" ]] || { echo "error: --repo is not a directory: $REPO" >&2; exit 2; }
REPO="$(cd "$REPO" && pwd)"

# One git-repo guard for every verb: --repo is a runtime target like `git -C`, but
# it must at least be a real git work tree. Fail fast with a clear message instead
# of an opaque mid-drive error (and every verb here needs git: read-only verbs add
# a worktree, write commits a drive branch).
git -C "$REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
    || { echo "error: --repo is not a git repository: $REPO" >&2; exit 2; }

# review interpolates --base into the LLM instruction ("git diff $BASE...HEAD"),
# so reject a value that is not a real commit/ref before it is rendered into the
# prompt — fail fast rather than hand the model a bogus (or injected) ref.
if [[ "$VERB" == "review" ]]; then
    git -C "$REPO" rev-parse --verify --quiet "${BASE}^{commit}" >/dev/null 2>&1 \
        || { echo "error: --base is not a valid commit/ref in $REPO: $BASE" >&2; exit 2; }
fi

resolve_convertible || exit 2

# Per-request timeout is config (no drive flag); EngineConfig reads it from env.
# A local model can be slow on a growing context, so default generously.
export CONVERTIBLE_TIMEOUT="$TIMEOUT"
COMMON_FLAGS=(--engine "$ENGINE" --model "$MODEL" --base-url "$BASE_URL" --max-steps "$MAX_STEPS" --json)

# ── render an instruction from a prompt template ────────────────────────────
render_prompt() {
    local file="$PROMPTS_DIR/$1.md"
    [[ -f "$file" ]] || { echo "error: missing prompt template: $file" >&2; exit 2; }
    # Single-pass substitution: doing `.replace("$ARGUMENTS", ARG).replace("$BASE",
    # BASE)` in two passes lets a literal "$BASE" *inside* the user's argument get
    # clobbered by the second pass. One re.sub never re-scans already-substituted
    # text, so injected tokens survive verbatim.
    ARG="$ARG" BASE="$BASE" python3 - "$file" <<'PY'
import os, re, sys
tpl = open(sys.argv[1], encoding="utf-8").read()
repl = {"$ARGUMENTS": os.environ["ARG"], "$BASE": os.environ["BASE"]}
sys.stdout.write(re.compile(r"\$ARGUMENTS|\$BASE").sub(lambda m: repl[m.group(0)], tpl))
PY
}

# ── print the TaskResult that convertible emitted as JSON on stdout ─────────
# Reads JSON on stdin; prints a human/agent-readable digest — to stdout on
# success, to stderr on failure so a caller can script on a clean stdout — and
# exits non-zero if the drive failed.
print_result() {
    # NOTE: must be `python3 -c`, not `python3 - <<HEREDOC`: a heredoc becomes
    # python's stdin (the script source), which would shadow the piped JSON and
    # leave sys.stdin.read() empty. The script body uses no single quotes.
    #
    # $1 (optional): the real artifact directory. When the drive ran in a
    # throwaway worktree (read-only verbs), the JSON's artifacts_path points into
    # that soon-deleted worktree; pass the real repo's .convertible/ so the
    # printed path names the preserved copy instead. Empty -> print as-is.
    OUTSOURCE_REAL_ARTIFACT_DIR="${1:-}" python3 -c '
import sys, json, os
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
ok = d.get("status") == "ok"
out = sys.stdout if ok else sys.stderr
print("status:", d.get("status"), file=out)
print(file=out)
print((d.get("summary") or "").rstrip(), file=out)
cf = d.get("changed_files") or []
if cf:
    print("\nchanged files:", ", ".join(cf), file=out)
if d.get("branch"):
    print("drive branch:", d["branch"], file=out)
ap = d.get("artifacts_path")
real_dir = os.environ.get("OUTSOURCE_REAL_ARTIFACT_DIR") or ""
if ap and real_dir:
    ap = os.path.join(real_dir, os.path.basename(ap))
if ap:
    print("artifact:", ap, file=out)
sys.exit(0 if ok else 1)
'
}

# ── read-only verbs: isolate the drive in a throwaway worktree at HEAD ──────
# Worktree state is module-global, not a function local: the EXIT trap fires
# *after* run_readonly returns, so under `set -u` a local would be unbound.
_WT=""
_DRIVE_BRANCH=""

_cleanup_worktree() {
    [[ -n "$_WT" ]] || return 0
    git -C "$REPO" worktree remove --force "$_WT" >/dev/null 2>&1 || true
    rm -rf "$_WT" >/dev/null 2>&1 || true
    # Only ever delete the ephemeral drive branch convertible names
    # (convertible/<task_id>) — never an unrelated local branch, even if the
    # JSON `branch` value were unexpected.
    if [[ "$_DRIVE_BRANCH" == convertible/* ]]; then
        git -C "$REPO" branch -D "$_DRIVE_BRANCH" >/dev/null 2>&1 || true
    fi
    # Defensive: clear the handles so a re-entry is a clean no-op. The EXIT trap
    # fires once today, but this keeps cleanup idempotent against future refactors
    # (dogfood-review suggestion, #61).
    _WT=""
    _DRIVE_BRANCH=""
}

# Extract the drive branch (convertible/<id>) from a TaskResult JSON on stdin.
_extract_branch() {
    python3 -c 'import sys, json
try:
    print(json.load(sys.stdin).get("branch") or "")
except Exception:
    print("")' 2>/dev/null || true
}

# Extract the task id from a TaskResult JSON on stdin.
_extract_task_id() {
    python3 -c 'import sys, json
try:
    print(json.load(sys.stdin).get("task_id") or "")
except Exception:
    print("")' 2>/dev/null || true
}

# A task id must be a single safe path segment before it is joined into a copy
# destination (mirrors convertible/feedback.py's _validate_task_id: allow
# [A-Za-z0-9][A-Za-z0-9._-]*, reject "."/".." and any path separator). The id
# comes from convertible's own TaskResult, but validating it keeps the write
# strictly inside $REPO/.convertible/ even for a malformed/hostile result.
_valid_task_id() {
    [[ "$1" != "." && "$1" != ".." && "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]
}

# Read-only verbs drive in a throwaway worktree that _cleanup_worktree deletes, so
# the artifact written under <worktree>/.convertible/ would vanish with it. Copy it
# back to the real repo's .convertible/ (plus a last_drive pointer) so `convertible
# feedback record last` / `outsource feedback last` can grade the drive afterwards.
# Writes only the gitignored .convertible/ bookkeeping dir — never the tracked tree.
# Returns non-zero (and writes no last_drive) when the id is unsafe or the copy
# fails, so run_readonly never reports a preserved path that isn't actually there.
_preserve_artifact() {
    local task_id="$1"
    [[ -n "$task_id" && -n "$_WT" ]] || return 1
    if ! _valid_task_id "$task_id"; then
        printf 'outsource: refusing to preserve artifact for unsafe drive id %q\n' "$task_id" >&2
        return 1
    fi
    local src="$_WT/.convertible"
    local dst="$REPO/.convertible"
    [[ -f "$src/$task_id.json" ]] || return 1
    mkdir -p "$dst" || return 1
    # The JSON artifact is the record of the drive — surface a copy failure rather
    # than swallow it, so the caller can fall back to honest path reporting.
    if ! cp -f "$src/$task_id.json" "$dst/$task_id.json"; then
        printf 'outsource: could not preserve artifact %s.json\n' "$task_id" >&2
        return 1
    fi
    # The trace is optional context; a best-effort copy is fine.
    if [[ -f "$src/$task_id.trace.jsonl" ]]; then
        cp -f "$src/$task_id.trace.jsonl" "$dst/$task_id.trace.jsonl" 2>/dev/null || true
    fi
    # Write last_drive only after the artifact actually landed — never leave the
    # pointer aimed at a missing file.
    printf '%s' "$task_id" > "$dst/last_drive" || return 1
}

# Spin up a throwaway detached worktree at HEAD (the isolation both read-only
# verbs and the write preview share). `mktemp -d` is given an explicit template:
# GNU mktemp tolerates a bare `-d`, but BSD/macOS mktemp requires one.
_add_worktree() {
    _WT="$(mktemp -d "${TMPDIR:-/tmp}/outsource.XXXXXX")"
    trap _cleanup_worktree EXIT
    git -C "$REPO" worktree add -q --detach "$_WT" HEAD
}

run_readonly() {
    local instruction="$1"
    _add_worktree
    local out
    out="$("${CONVERTIBLE[@]}" drive "$instruction" --repo "$_WT" --no-pr "${COMMON_FLAGS[@]}")" || true
    _DRIVE_BRANCH="$(printf '%s' "$out" | _extract_branch)"
    # Preserve the artifact to the real repo BEFORE the EXIT trap removes the
    # worktree, so the drive can be graded (`outsource feedback last`). Only point
    # print_result at the real repo when the copy actually landed — otherwise the
    # printed `artifact:` would name a file that preservation never wrote.
    local task_id real_dir=""
    task_id="$(printf '%s' "$out" | _extract_task_id)"
    if _preserve_artifact "$task_id"; then
        real_dir="$REPO/.convertible"
    fi
    printf '%s' "$out" | print_result "$real_dir"
}

# ── write preview (default): drive in a throwaway worktree, show the would-be ──
# change, then discard. Nothing reaches the real working tree or branch — pass
# --apply (or --pr) to land it for real.
run_preview() {
    local instruction="$1"
    _add_worktree
    local out
    out="$("${CONVERTIBLE[@]}" drive "$instruction" --repo "$_WT" --no-pr "${COMMON_FLAGS[@]}")" || true
    _DRIVE_BRANCH="$(printf '%s' "$out" | _extract_branch)"

    # Capture the would-be patch before _cleanup_worktree deletes the drive branch.
    local patch=""
    if [[ "$_DRIVE_BRANCH" == convertible/* ]]; then
        patch="$(git -C "$REPO" diff "HEAD..$_DRIVE_BRANCH" 2>/dev/null || true)"
    fi

    local rc=0
    printf '%s' "$out" | print_result || rc=$?
    if [[ "$rc" -eq 0 ]]; then
        if [[ -n "$patch" ]]; then
            printf '\n--- preview diff (NOT applied — pass --apply to land it) ---\n'
            printf '%s\n' "$patch"
        else
            printf '\n(preview: no file changes reported; NOT applied)\n'
        fi
    fi
    return "$rc"
}

# ── write verb: preview by default; --apply lands a drive branch; --pr opens a ─
# PR (implies apply). The dirty-tree guard only matters when applying in place —
# a preview runs in an isolated worktree and never touches the working tree.
run_write() {
    local instruction="$1"
    if [[ "$APPLY" -eq 0 && "$OPEN_PR" -eq 0 ]]; then
        run_preview "$instruction"
        return
    fi
    if [[ "$ALLOW_DIRTY" -eq 0 ]] \
        && [[ -n "$(git -C "$REPO" status --porcelain 2>/dev/null)" ]]; then
        echo "error: working tree is dirty — commit/stash first, or pass --allow-dirty" >&2
        echo "hint: 'convertible drive --no-pr' commits uncommitted edits onto the drive branch" >&2
        exit 2
    fi
    # `|| true`: a failed drive (`convertible drive` returns 1 when status != ok,
    # printing the result JSON to stdout) must still flow into print_result so the
    # digest is emitted (to stderr) and the wrapper exits non-zero — not aborted by
    # `set -e` at the assignment, which would swallow the digest. Matches the
    # read-only / preview paths, which already guard this way.
    local out
    if [[ "$OPEN_PR" -eq 1 ]]; then
        out="$("${CONVERTIBLE[@]}" drive "$instruction" --repo "$REPO" "${COMMON_FLAGS[@]}")" || true
    else
        out="$("${CONVERTIBLE[@]}" drive "$instruction" --repo "$REPO" --no-pr "${COMMON_FLAGS[@]}")" || true
    fi
    printf '%s' "$out" | print_result
}

# ── feedback verb: grade a finished drive (the ROI loop) ────────────────────
# A thin pass-through to `convertible feedback`: with --rating it records a 1-5
# grade + notes; without, it shows the drive's existing feedback. The ref is the
# drive's task-id, or `last` for the most recent drive in --repo. No worktree,
# no engine — convertible owns the store and its own stdout/stderr/exit code.
run_feedback() {
    local ref="$1"
    # Build one command array (never empty) so we don't expand an empty array
    # under `set -u` — the optional --by is appended only when set.
    local cmd=("${CONVERTIBLE[@]}" feedback)
    if [[ -n "$RATING" ]]; then
        cmd+=(record "$ref" --rating "$RATING" --notes "$NOTES")
        [[ -n "$BY" ]] && cmd+=(--by "$BY")
    else
        cmd+=(show "$ref")
    fi
    cmd+=(--repo "$REPO")
    "${cmd[@]}"
}

case "$VERB" in
    explore) run_readonly "$(render_prompt explore)" ;;
    review) run_readonly "$(render_prompt review)" ;;
    write) run_write "$(render_prompt write)" ;;
    feedback) run_feedback "$ARG" ;;
esac
