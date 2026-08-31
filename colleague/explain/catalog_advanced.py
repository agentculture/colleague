"""Advanced surfaces catalog entries (promote, plan, mcp).

Split out of ``colleague/explain/catalog.py`` (docstring constants only, one
per ``colleague explain <path>`` topic group); see that module for ``ENTRIES``.
"""

from __future__ import annotations

_PROMOTE = """\
# colleague promote

Graduate colleague from a born-and-trained task runner into a **resident** member
of the Culture mesh — the lifecycle transition born → trained → resident. The
*same* colleague that drives bounded `colleague work` items is elevated in place
into a persistent peer that owns a channel and answers messages over a long-lived
session. (Spec: `docs/specs/2026-06-10-colleague-graduates-from-a-born-and-trained-task-r.md`.)

The resident runtime ships only in the opt-in `[culture]` extra (agent-lifecycle +
agentirc-cli), which requires Python >=3.12. Without it, `promote` fails cleanly
with an install hint. Install with `uv tool install --python 3.12 'colleague[culture]'`
(pip: `pip install "colleague[culture]"`; in a checkout: `uv sync --extra culture`).
The `--python 3.12` is load-bearing: `uv tool install` otherwise defaults to a
Python it has on hand, which may be <3.12 and fail to resolve.

Promoting inside a repo that already declares a *different* `culture.yaml` (e.g.
colleague's own checkout) is a recoverable conflict, not a bug: re-run with
`--force` to overwrite, or pass `--suffix`/`--repo` to mint a separate identity.

What it does:

1. **Mint + self-register** a stable mesh identity — writes `culture.yaml`
   (`suffix` + `backend=colleague` + `model`) and a prompt file where the Culture
   steward discovers them, reusing colleague's own identity resolution
   (`colleague/identity.py`), then signals arrival via the roster CLI. Idempotent.
2. **Select channels** — queries the Culture roster/steward, ranks candidates, and
   owns `#<nick>` by default; degrades cleanly to just the owned channel if the
   roster CLI is absent.
3. **Go live (`--serve`)** — connects to IRC and runs the resident supervisor (the
   bounded loop as its driving engine, via agent-lifecycle's Transport/Harness/Supervisor
   seam) until interrupted. Without `--serve` it *prepares and reports* — the
   consequential network step is explicit.

The bounded `colleague work` path is untouched: the resident is a SEPARATE, opt-in
process; a bare work item never starts it.

## Examples

    colleague promote --repo .                          # prepare + register, report
    colleague promote --repo . --json                   # machine-readable report
    colleague promote --repo . --suffix spark-colleague # mint a specific nick
    colleague promote --repo . --no-signal              # mint/register, skip arrival ping
    colleague promote --repo . --serve --irc-host localhost --irc-port 6667  # go live
"""

_PLAN = """\
# colleague plan

Colleague plans a complex task — the same arc as the `/think` -> `/spec-to-plan`
-> `/assign-to-workforce` skills, but with COLLEAGUE as the planning mind (a
different mind from the requester; the diversity is the point). It proposes spec
claims, you gate each one, it proposes a split plan (items + dependency waves),
then it fans the waves out to a subagent-colleague workforce, reusing the
existing `subagents` machinery. Plan mode needs a live backend (the `mock` engine
has no model).

## Verbs

- `plan "<request>"` — plan a task end to end (spec -> plan -> workforce)
- `plan continue` — resume an interrupted plan run from its checkpoint (#t17)
- `plan status` — read the last plan checkpoint
- `plan overview` — describe the plan surface

## Gating

You gate each proposed item — colleague proposes, you confirm/reject:

- default: gate each item on stdin (an interactive terminal)
- `--yes`: auto-confirm every gate (non-interactive / agent use)
- `--review`: run the same-model critic before each gate (advisory)

Colleague never self-confirms; planning/implementation never runs before the spec
converges.

## Resuming: `plan continue`

If a `plan run` is interrupted (killed, crashed, closed terminal), `plan
continue` resumes it from the checkpoint written under `.colleague/plan/<frame>.json`
(`<frame>` defaults to `plan`; `--frame <slug>` targets a different one) —
**without re-asking the gates it already resolved.** It is a thin wrapper over
the same orchestrator entry as `run`: it reads the checkpoint's stored request
and resolved-gate count, reports `resuming '<frame>': N gate(s) already
resolved` to stderr, then resumes in the already-shipped `quick=True` mode
(which never calls `decide` for spec claims/honesty), so those resolved gates
are structurally never re-asked. It **refuses cleanly** (a `CliError` with a
remediation hint, never a traceback) when there is no checkpoint to resume
from, or when the checkpoint predates this feature and has no stored request —
that refusal is exactly what distinguishes `continue` from `run`. Accepts the
same `--repo`/`--engine`/`--model`/`--yes`/`--review`/`--no-workforce`/`--json`
flags as `run` (no `--quick` — resuming is always the quick/skip-spec-stage
path, so the flag would be a silent no-op).

## Usage

    colleague plan "add a rate limiter to the API" --repo .
    colleague plan "refactor the auth module" --yes --json
    colleague plan continue --repo .                  # resume after an interruption
    colleague plan continue --frame my-plan --yes --repo .
    colleague plan status --repo .
    colleague plan overview
"""

_MCP = """\
# colleague mcp

Serve colleague's operations as an **MCP server** — the bonus surface that falls
out of the same imported agentfront `App` that renders the CLI. The MCP surface is
**single-dispatch**: ONE `run` tool whose description embeds the command catalog
(the same registry operations the CLI verbs and `learn` enumerate — catalog-level
parity). A platform (e.g. Cowork) drives colleague by calling `run` with a command
path + named args, e.g. `{"command": ["feedback", "record"], "args": {...}}`.

Needs the optional `[mcp]` extra (`pip install 'colleague[mcp]'` /
`uv sync --extra mcp`); without it, `mcp serve` fails with a clean error naming the
install. No socket/daemon code lives in colleague — the blocking stdio loop is
agentfront's `serve_stdio`; colleague only assembles the App and hands it over.
The host-command launchers (`work` / `plan` / `session` / `tui` / `flight` /
`clean` / `learn-from` / `promote` / `mcp`) carry CLI-only semantics and are NOT in
the single `run` tool's catalog (the rendered tool verbs are).

## Verbs

- `mcp serve` — serve colleague over stdio (blocking; Ctrl-C to stop)
- `mcp overview` — describe the MCP surface

## Usage

    colleague mcp serve            # blocks, speaking MCP over stdio
    colleague mcp overview
"""
