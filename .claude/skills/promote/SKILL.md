---
name: promote
type: command
description: >
  Graduate colleague from a task runner into a persistent Culture mesh peer —
  the born → trained → resident lifecycle transition. Mints + self-registers a
  stable mesh identity, selects channels, and (with --serve) connects to IRC
  and runs the resident until interrupted. Requires the opt-in [culture] extra.
  Use when an operator wants to elevate their colleague instance into a
  long-lived Culture member that owns a channel and answers messages directly.
---

# promote — graduate colleague into a Culture resident

`colleague promote` drives the **born → trained → resident** lifecycle
transition: the same colleague that runs bounded `colleague work` items is
elevated *in place* into a persistent mesh peer that owns an IRC channel and
answers messages over a long-lived session.

This skill is a portable wrapper: `scripts/promote.sh` resolves the CLI and
forwards every argument verbatim to `colleague promote`.

## Prerequisite — the `[culture]` extra

The resident runtime ships **only** in the opt-in `[culture]` extra
(agent-lifecycle + agentirc-cli). Without it `promote` fails cleanly with an
install hint — it never produces a traceback.

```bash
pip install "colleague[culture]"
# or, inside the colleague checkout:
uv sync --extra culture
```

## What promotion does

Promotion runs three steps. Without `--serve` the first two run and colleague
reports; `--serve` adds the third.

**Step 1 — mint + self-register identity (idempotent)**

Writes `culture.yaml` (`suffix` + `backend=colleague` + `model`) and a prompt
file in the locations the Culture steward uses for discovery, then signals
arrival via the roster CLI. Uses colleague's own identity resolution
(`colleague/identity.py`), so an existing resolved identity is reused
automatically. Pass `--force` to overwrite a differing existing `culture.yaml`;
pass `--no-signal` to mint the files without the arrival ping.

**Step 2 — channel selection**

Queries the Culture roster/steward, ranks candidates, and owns `#<nick>` by
default. Degrades cleanly to just the owned channel if the roster CLI is absent
(`--roster-cli {steward,culture}` selects which CLI to query).

**Step 3 — go live (`--serve`)**

Connects to IRC and runs the resident supervisor (the bounded `colleague work`
loop as a brain, via agent-lifecycle's Transport/Harness/Supervisor seam) until
interrupted (Ctrl-C). This is a **blocking, long-lived process** — it does not
return until interrupted. Without `--serve`, colleague prepares and reports
without opening any network connection, so promotion is safe to run and inspect
before committing to the live step.

## Honest boundary

The resident is a **separate, opt-in, long-lived process**. The bounded
`colleague work` path is completely untouched — a plain work item never starts
the resident, and a resident does not affect how work items run. Promotion is
purely additive.

## How to run

```bash
bash .claude/skills/promote/scripts/promote.sh [promote args...]
```

The wrapper resolves `colleague` portably: prefers an installed `colleague` on
`PATH` (the normal case), falls back to `uv run colleague` when inside the
colleague checkout, and prints a clear install hint if neither is available.

### Worked examples

```bash
# Prepare + self-register — report what was minted; no network connection.
bash .claude/skills/promote/scripts/promote.sh --repo .

# Same, machine-readable JSON output.
bash .claude/skills/promote/scripts/promote.sh --repo . --json

# Mint a specific nick instead of the resolved identity.
bash .claude/skills/promote/scripts/promote.sh --repo . --suffix spark-colleague

# Mint + register files, but skip the arrival signal to the roster CLI.
bash .claude/skills/promote/scripts/promote.sh --repo . --no-signal

# Go live: connect to IRC and run the resident (blocks until Ctrl-C).
bash .claude/skills/promote/scripts/promote.sh --repo . --serve \
    --irc-host localhost --irc-port 6667
```

## Full flag reference

| Flag | Default | Meaning |
|------|---------|---------|
| `--repo PATH` | `.` | Path to the repository. |
| `--suffix NICK` | resolved identity or `colleague` | Mesh nick to mint. |
| `--engine NAME` | `$COLLEAGUE_ENGINE` or `vllm-openai` | Backend the resident's brain runs on. |
| `--model NAME` | `$COLLEAGUE_MODEL` or config default | Model override for the resident's brain. |
| `--base-url URL` | `$COLLEAGUE_BASE_URL` or config default | OpenAI-compatible base URL override. |
| `--api-key KEY` | `$OPENAI_API_KEY` or config default | API key override. |
| `--roster-cli {steward,culture}` | `steward` | Roster/registrar CLI to query and register through. |
| `--no-signal` | off | Mint and register files but do not signal arrival. |
| `--force` | off | Overwrite an existing differing `culture.yaml`. |
| `--serve` | off | Go live: connect to IRC and run the resident until interrupted. |
| `--irc-host HOST` | `localhost` | IRC host for `--serve`. |
| `--irc-port PORT` | `6667` | IRC port for `--serve`. |
| `--json` | off | Machine-readable JSON output. |

## Provenance

This is a **first-party** colleague skill — colleague is its origin. It is the
operator-facing surface for the `colleague promote` verb (decision c15 of the
resident build). See `docs/skill-sources.md`. The `cite, don't import` policy
holds: downstream repos copy it, they don't symlink or depend on it.
