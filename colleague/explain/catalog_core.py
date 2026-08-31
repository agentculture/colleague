"""Onboarding and top-level catalog entries (root, quickstart, learn, doctor, ...).

Split out of ``colleague/explain/catalog.py`` (docstring constants only, one
per ``colleague explain <path>`` topic group); see that module for ``ENTRIES``.
"""

from __future__ import annotations

_ROOT = """\
# colleague

A swappable coder-agent harness: hand it a scoped repo task and it drives a model
backend through a bounded tool-loop, then returns a JSON run report. One runtime,
many minds. Another agent works *with* it through the first-party `ask-colleague`
skill (`ask-colleague explore | review | write | feedback`) or `colleague work`
directly — `colleague learn` is the self-teaching entry point for collaborators.
Pilot a running work item with `colleague work --watch` + the `colleague flight`
noun (status/guide/stop) — cooperative, file-based, no daemon.

Run `colleague` with no verb at a terminal to open the interactive harness (the
`session` palette); piped or non-interactive, it prints this usage instead.

## Verbs

- `colleague work <goal>` — work toward a goal/instruction; work autonomously
  through a coder backend and hand off the result.
- `colleague session` — foreground interactive palette over the work path.
- `colleague backends list` — list discovered backend plugins.
- `colleague whoami` — mesh identity (`culture.yaml`) + the live work engine/model.
- `colleague learn` — structured self-teaching prompt.
- `colleague explain <path>` — markdown docs for any noun/verb.
- `colleague overview` — descriptive snapshot of the agent.
- `colleague doctor` — configuration-readiness health check.
- `colleague cli overview` — describe the CLI surface.

## Exit-code policy

- `0` success
- `1` user-input error
- `2` environment / setup error
- `3+` reserved

## See also

- `colleague explain work`
- `colleague explain backends`
- `colleague explain whoami`
"""

_WHOAMI = """\
# colleague whoami

Reports two identities in one glance, plus the package version. Read-only.

- **Mesh identity** (from `culture.yaml`): `nick` (`suffix`) and `backend` — the
  persona this agent runs as in the Culture mesh.
- **Work identity** (resolved live, the same way a real work item resolves it):
  `work_engine` — the engine a bare `colleague work` would pick
  (`--engine` > `COLLEAGUE_ENGINE` > default `vllm-openai`) — and `work_model`,
  the model it would call (`null` for the no-op `mock` engine). This is the
  trust signal an agent checks before delegating: it names the *delegate*, not
  an unrelated persona backend.

## Usage

    colleague whoami
    colleague whoami --json
"""

_QUICKSTART = """\
# colleague quickstart

A guided first-run walkthrough for new users — the "where do I start?" answer the
flat `--help` doesn't give. Read-only: it prints an ordered path, runs nothing.

The path: (1) `colleague doctor` to check setup, (2) `colleague backends list` to
see the available minds, (3) a zero-cost `colleague work … --engine mock --no-pr`
dry run of the whole loop, (4) `colleague feedback show last` to read the run
report, (5) `colleague explain work` to go deeper.

## Usage

    colleague quickstart
    colleague quickstart --json
"""

_LEARN = """\
# colleague learn

Prints a structured self-teaching prompt aimed at *another agent that wants to
work with colleague* — delegate a scoped task to it and fold the answer back. It
foregrounds the `ask-colleague` verbs (explore / review / write / feedback), the
`work` contract, the ROI loop, and **what skills to author** so colleague
works your repo well (`.colleague/skills/*.md` + the `AGENTS` cascade). It also
covers the command map, exit-code policy, `--json` support, and the `explain`
pointer.

## Usage

    colleague learn
    colleague learn --json

## See also

- `colleague explain ask-colleague`
- `colleague explain skills`
- `colleague explain work`
"""

_EXPLAIN = """\
# colleague explain <path>

Prints markdown documentation for any noun/verb path. Unlike `--help` (terse,
positional), `explain` is global and addressable by path.

## Usage

    colleague explain colleague
    colleague explain whoami
    colleague explain --json <path>
"""

_OVERVIEW = """\
# colleague overview

Read-only descriptive snapshot of the agent: identity (from `culture.yaml`), the
verb surface, and the sibling-pattern artifacts the template carries. Accepts an
ignored `target` so a stray path never hard-fails.

## Usage

    colleague overview
    colleague overview --json
"""

_DOCTOR = """\
# colleague doctor

Colleague's health check: a configuration-readiness diagnostic emitting a
rubric-shaped report across ordered check-groups: **identity**, **provider**
(config + budget), **usage** (which backend a bare work item actually picks),
**engines** (all installed plugins), **otel-readiness**, **environment**
(repo config / layering / handoff prereqs / CLI integrity), **stale-refs**
(a crashed work item's wedged `colleague/*` refs), and **organs** (the
AI-coworker organism map — presence/version/armed for lobes, eidetic,
coherence, sloth, data-refinery, agtag, devex, devague; see
`colleague explain organs`).

Exits 1 when unhealthy (when any error-severity check fails). Only
error-severity failures make the report unhealthy; warnings and info are
advisory — e.g. `usage_effective_engine` warns (but stays healthy) when a bare
run would pick the no-op `mock` backend, and a missing organ warns with a
`uv tool install <distribution>` hint rather than failing the report.

`--probe` adds opt-in network checks, all off by default: `provider_reachable`
(pings the provider server's `{base_url}/models`), a tool-calling round-trip,
and the lobes gateway's live `GET /capabilities` reachability (the organs
sibling — see `colleague explain organs`). An unreachable server/gateway is
reported as a warning, not an error.

## Usage

    colleague doctor
    colleague doctor --json
    colleague doctor --probe
"""

_LIVECHECK = """\
# colleague livecheck

Probe the configured endpoint and run gated live proofs, reporting per-row
pass/fail/skip. One verb that combines endpoint reachability with live-proof
execution.

When the endpoint is unreachable, prints an honest skip report naming the
endpoint and exits 0 without running pytest. When reachable, runs the proofs
and prints a per-row table plus a summary line; exits 1 if any proof failed,
else 0.

## Usage

    colleague livecheck
    colleague livecheck --repo PATH
    colleague livecheck --json
    colleague livecheck --repo PATH --json
"""

_CLEAN = """\
# colleague clean

Self-heal a repo a crashed `work` left wedged (#162). A crashed / interrupted
`work --apply` can leave a dangling `colleague/<id>` branch ref pointing at
half-written (0-byte) loose objects, which breaks `git fetch` / `git pull`, plus
orphaned 0-byte `.colleague/` run artifacts. `clean` reaps both — scoped
**strictly** to `colleague/*` refs and `.colleague/` artifacts — restoring the
repo with a single documented command.

What it reaps:

- **Corrupt `colleague/*` branches** (always) — a tip whose object is
  missing/unreadable is the `git fetch` breaker; deleted via `git update-ref -d`
  (which works on a corrupt tip where `git branch -D` chokes).
- **Merged `colleague/*` branches** — only with `--merged` (already an ancestor
  of `--base`, default `main`).
- **Old `colleague/*` branches** — only with `--older-than DAYS`.
- **Orphaned 0-byte `.colleague/` artifacts** + a `last_work` pointer that
  resolves to nothing. A **non-empty** (gradable) artifact is never touched.

Conservative with git internals: it **reports** any leftover 0-byte loose
objects under `.git/objects` and suggests `git prune`, but never deletes them
itself. Scoped to `colleague/*` only — it never touches an unrelated branch.

Honest limit: a SIGKILL/OOM/power-loss *during* the commit can still corrupt
objects (git/filesystem durability, not colleague's to guarantee) — which is
exactly why this recovery verb exists. `doctor` flags such a wedged repo and
points here.

## Usage

    colleague clean --repo .
    colleague clean --dry-run            # report what would be reaped; change nothing
    colleague clean --merged --older-than 14
    colleague clean --json
"""

_LEARN_FROM = """\
# colleague learn-from

Learn skills from a peer agent — colleague grows its skill set by absorbing
another mind's. The first (and currently only) source is `claude`: it reads
Claude Code's `.claude/skills/<name>/SKILL.md` and adapts each into colleague's
own flat `.colleague/skills/<name>.md`, which colleague folds into every
backend's system prompt on the same repo/root. The source is a registry, so
future minds (e.g. a codex / mesh peer) slot in without a CLI change.

Two stages:

1. **Deterministic copy** (always) — strip the SKILL.md YAML frontmatter (incl.
   `description: >` block scalars), fold the description into a leading summary
   line so `colleague skills list` shows it, stamp a `<!-- learned-from: ... -->`
   provenance marker, and keep the body verbatim. Idempotent: an unchanged skill
   reads back `skipped`. A skill's `scripts/` are left in place under
   `.claude/skills/<name>/scripts/` (same repo/root) — the marker records where;
   no binaries are copied.
2. **LLM review-and-adapt** (default; skip with `--copy-only`) — colleague itself
   drives the configured backend over each freshly written skill **in the working
   tree, with no git handoff/branch**, to fix paths/locations and replace
   Claude-isms (the Skill tool, slash commands) with colleague's tool surface,
   then flips the marker to `adapt: claude->colleague`. It **degrades to
   copy-only** with a clear notice when no backend is reachable.

Safety: an existing colleague-owned skill that differs is updated only with
`--force`; a hand-authored skill doc (no provenance marker) is `protected` unless
`--force` — colleague never silently clobbers your edits. `--dry-run` previews
every action and writes nothing.

Honest limit: colleague **loads** skills as instructional text — it does NOT
execute them. "Run them on the same repo/root" means the backend model reads the
adapted doc and acts via its own tools. A skill leaning on scripts / the Skill
tool / slash commands maps only partially — surfaced per skill as
`runnable_estimate` (full | partial | instructional-only).

## Usage

    colleague learn-from claude --repo .
    colleague learn-from claude --copy-only          # deterministic copy only
    colleague learn-from claude run-tests think      # only these skills
    colleague learn-from claude --dry-run --json     # preview, machine-readable
    colleague learn-from claude --user               # read ~/.claude/skills/
    colleague learn-from claude --force              # re-learn / overwrite

## See also

- `colleague explain skills` — inspect the resolved skill catalog
- `colleague explain learn` — the agent self-teaching prompt
"""

_CLI = """\
# colleague cli

Noun group for CLI-surface introspection. `cli overview` describes the CLI
itself (distinct from the global `overview`, which describes the agent).

## Usage

    colleague cli overview
    colleague cli overview --json
"""
