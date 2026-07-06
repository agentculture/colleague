"""Markdown catalog for ``colleague explain <path>``.

Each entry is verbatim markdown. Keys are command-path tuples. The empty tuple
and ``("colleague",)`` both resolve to the root entry.

Keep bodies self-contained: an agent reading one entry should get enough
context without chaining reads.
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

_WORK = """\
# colleague work

Work toward a goal: hand colleague a request or instruction and it works
autonomously — selecting a backend plugin, running the bounded agentic tool-loop,
writing a result artifact, and handing off the change as a branch + PR. The repo
is the target (`--repo`, default cwd); the same invocation works for every
engine — only `--engine` changes.

`drive` is a **deprecated alias** of `work` (the old car-themed verb) — it still
resolves and its `--help` row is labelled deprecated, but prefer `work`.

## Usage

    colleague work "add a CONTRIBUTING.md" --repo . --engine mock --no-pr
    colleague work "fix the typo in README" --engine vllm-openai --no-pr
    colleague work "..." --engine vllm-openai --base-url http://localhost:8001/v1 --json

## Backend selection

Resolved highest-first: the `--engine` flag, then the `COLLEAGUE_ENGINE` env
var, then the built-in default `vllm-openai` (the real bundled backend). A bare
`work` never silently falls back to the no-op `mock` reference — use
`--engine mock` (or `COLLEAGUE_ENGINE=mock`) when you explicitly want it.

## Key flags

- `--repo PATH` — target repository (default: cwd).
- `--engine NAME` — backend plugin (default: `COLLEAGUE_ENGINE` env, else `vllm-openai`).
- `--no-pr` — commit locally; do not push or open a PR.
- `--allow-dirty` — run even when the working tree has uncommitted tracked
  changes (they get committed onto the work branch). Default: refuse, so a work
  item never silently sweeps your in-progress edits onto a branch (#149).
- `--base-url / --model / --api-key / --max-steps` — backend overrides.

A failed work item still writes a `status=error` artifact before exiting non-zero.
"""

_BACKENDS = """\
# colleague backends

Discover the backend plugins (the "minds") installed in this environment.
Backends register under the `colleague.engines` entry-point group; bundled and
out-of-tree plugins are discovered identically.

`wheels` is a **deprecated alias** of `backends` (the old car-themed name) — it
still resolves and its `--help` row is labelled deprecated, but prefer `backends`.

## Usage

    colleague backends list
    colleague backends list --json
    colleague backends overview
"""

_COMMANDS = """\
# colleague commands

Discover and list named command templates stored under `.colleague/commands/`
in the target repository (or user home).  Templates are Markdown files with an
optional YAML-like metadata block and a body using `$1`/`$2`/`$ARGUMENTS`
substitution.

## Usage

    colleague commands list
    colleague commands list --repo PATH
    colleague commands list --repo PATH --json
    colleague commands overview

## Template format

    ---
    description: Fix lint errors in a path
    engine: mock
    constraints: keep diffs minimal, run the formatter
    arg-hint: <path>
    ---
    Fix all lint errors under $1. Then run the formatter. $ARGUMENTS

## Running a template

    colleague work --command <name> [args...]

## See also

- `colleague explain work`
- `colleague explain hooks`
"""

_SESSION = """\
# colleague session

Open a foreground interactive palette that lists discovered command templates,
accepts free-text ad-hoc instructions, and runs every selection through the
**same work path** as `colleague work` (identical Task/loop/hooks/artifact).
The loop continues until you enter `q`, an empty line, or EOF.

## Usage

    colleague session
    colleague session --repo PATH --engine mock
    colleague session --pr            # opt back into push + PR per work item

## Interaction

At the `colleague ❯` prompt you can enter:

- A **number** (e.g. `1`) — selects that template from the numbered palette.
- A **template name** (e.g. `lint`) — runs that template directly.
- A **free-text instruction** — treated as an ad-hoc task (like `work "<text>"`).
- A **slash command** (e.g. `/help`, `/engine mock`) — the meta namespace:
  introspection of existing nouns plus live config actions. `/help` lists them all.
- `q`, `quit`, `exit`, or an **empty line** — ends the session.

## Slash autocomplete (colour TTY)

On an interactive colour TTY, typing `/` opens a **live popup** of slash
commands that **autofilters** as you type (`/co` → `commands`, `config`),
restores as you delete, and disappears when nothing matches. **Tab**/**Enter**
completes the selection, **arrows** move it, **Esc** dismisses. This is a
TTY-only nicety built on a stdlib raw-mode reader (no new dependency); off a
colour TTY — piped input, `--json`, `--no-tui`, or Windows — the prompt falls
back to plain line input, byte-identical to before, so agents and pipelines are
unaffected.

## Handoff

By default a session is a "talk + iterate" loop: each work item commits locally on a
`colleague/<task_id>` branch but does **not** push or open a PR. Pass `--pr` to
push and open a PR after every work item. (This differs from `work`, which opens a
PR by default.) Engine selection matches `work`: `--engine` > `COLLEAGUE_ENGINE`
> `vllm-openai`.

## Key flags

- `--repo PATH` — target repository (default: cwd).
- `--engine NAME` — backend plugin (default: `COLLEAGUE_ENGINE` env, else `vllm-openai`).
- `--pr` — push and open a PR after each work item (default: commit locally only, no PR).
- `--allow-dirty` — run work items even when the working tree has uncommitted
  tracked changes (they get committed onto the work branch). Default: refuse (#149).
- `--base BRANCH` — base branch for the PR (default: `main`).
- `--base-url / --model / --api-key / --max-steps` — backend overrides.

## See also

- `colleague explain work`
- `colleague explain commands`
"""

_HOOKS = """\
# colleague hooks

Inspect the lifecycle hook configuration loaded from `.colleague/hooks.json`
(repo-level, falling back to user-level at `~/.colleague/hooks.json`).

Hooks fire at four lifecycle events:
- `task_start` — before the agentic loop starts.
- `pre_tool` — before each tool call; can allow, deny, or rewrite arguments.
- `post_tool` — after each tool call.
- `finish` — after the loop ends.

## Usage

    colleague hooks list
    colleague hooks list --repo PATH
    colleague hooks list --repo PATH --json
    colleague hooks list --repo PATH --model <model> --json
    colleague hooks overview

## Per-model overlay (--model)

Pass `--model <name>` to `hooks list` to include per-model hook entries loaded
from `.colleague/<model>/hooks.json` (repo-level, falling back to
`~/.colleague/<model>/hooks.json`).

**Per-model-first precedence**: per-model entries are composed *ahead of* the
base entries for each event — so the loop's "first deny/rewrite wins" semantics
give the per-model hook priority. In the output, each entry carries a `scope`
tag (`per-model` or `base`) so you can see exactly which layer each hook comes
from. Without `--model`, output is identical to the base-only baseline (no
`scope` key is added).

The `<model>` token is sanitized the same way as in `agents list` and
`skills list` — runs of characters outside `[A-Za-z0-9._-]` collapse to a
single `-` (e.g. `Qwen/Qwen3-32B` → `Qwen-Qwen3-32B`). The overlay path is
constructed exactly, never globbed, so model X can never load model Y's overlay.

## Hook decisions

- **allow** — permit the tool call (default on exit 0 / empty stdout).
- **deny** — block the tool call (non-zero exit or `{"decision":"deny"}`).
- **rewrite** — replace tool arguments (`{"decision":"rewrite","arguments":{}}`).
- Responses may include `"additionalContext"` for the model.

## See also

- `colleague explain commands`
- `colleague explain work`
- `colleague explain agents`
- `colleague explain skills`
"""


_AGENTS = """\
# colleague agents

Inspect the layered AGENTS instruction files resolved for a model. The cascade,
read from the **repo root** with a `~/.colleague/` user-level fallback, is
composed general → specific into the system prompt every work item sends:

    AGENTS.md                       (shared base — sibling tools read this too)
    AGENTS.colleague.md           (colleague overlay)
    AGENTS.colleague.<model>.md   (model overlay)

The `<model>` token is sanitized — every run of characters outside
`[A-Za-z0-9._-]` collapses to a single `-` (e.g. `Qwen/Qwen3-32B` →
`Qwen-Qwen3-32B`). The layer name is *constructed* for the named model, never
globbed, so one model can never load another model's overlay (per-model
isolation is structural). Note the asymmetry: the repo-level layer lives at the
repo root, but the user-level fallback lives under `~/.colleague/`.

## Usage

    colleague agents list
    colleague agents list --model Qwen/Qwen3-32B --repo PATH
    colleague agents list --json
    colleague agents overview

## See also

- `colleague explain skills`
- `colleague explain work`
"""

_SKILLS = """\
# colleague skills

Inspect the layered skill docs resolved for a model. Skills live under
`.colleague/` (a colleague-internal concept):

    .colleague/skills/*.md            (base)
    .colleague/<model>/skills/*.md    (model overlay — shadows base by stem)

Repo-level `.colleague/` shadows user-level `~/.colleague/` underneath (two
orthogonal precedence axes). Resolved skills are folded into the system prompt as
a compact name + one-line-summary catalog. A skill is **instructional text
only** — there is no skill execution model in v0 (an execution sandbox is out of
scope); invokable skills are a tracked follow-up.

## Usage

    colleague skills list
    colleague skills list --model Qwen/Qwen3-32B --repo PATH
    colleague skills list --json
    colleague skills overview

## See also

- `colleague explain agents`
- `colleague explain work`
"""


_ROLES = """\
# colleague roles

Inspect the **typed subagent roles**. A *role* types a delegated subagent: it
gives the child a tailored prompt fragment, a *curated subset* of the tool
surface, and a curated skill subset. Built-in roles:

    explorer / planner / reviewer   read-only (read_file, list_dir,
                                    check_test_integrity, finish)
    validator                       read-only + a read-only `run_tests` capability
    writer                          the full tool surface (today's default)

Read-only roles withhold `write_file`, `edit_file`, AND `run_command`, so a
read-only role *provably cannot mutate the tree* — the executor refuses any
withheld tool even if the model hallucinates the call. Selecting a role on the
`subagent` / `subagents` tools is backend-judged and optional; omitting it is
byte-identical to today's full-surface delegation.

Operator prompt overlays at `.colleague/agents/<name>.md` (and the per-model
`.colleague/<model>/agents/<name>.md`, exact path, no sibling globbing) override
a built-in role's prompt. This noun is distinct from the sibling `agents` noun,
which inspects the AGENTS *instruction-file* cascade.

## Usage

    colleague roles list
    colleague roles list --model Qwen/Qwen3-32B --repo PATH
    colleague roles list --json
    colleague roles overview

## See also

- `colleague explain agents`
- `colleague explain subagents`
"""


_APPROVE = """\
# colleague approve

The ``approve`` verb is available on both the ``commands`` and ``hooks`` nouns.
It records a checksum approval for a command template file or a hook script file
into ``<repo>/.colleague/approvals.json``.

## Usage

    colleague commands approve <name> [--repo PATH] [--algo sha256|md5] [--json]
    colleague hooks approve <name>    [--repo PATH] [--algo sha256|md5] [--json]

## What it does

1. For **commands**: resolves the template file for ``<name>`` under
   ``.colleague/commands/<name>.md``; computes a checksum; writes it into
   ``approvals.json`` under the ``"commands"`` section.
2. For **hooks**: ``<name>`` is the **repo-relative path** of the hook script
   file (the same key used in the hooks approval section); the file must exist
   at ``<repo>/<name>``; its checksum is written into the ``"hooks"`` section.

Both operations **merge** into existing ``approvals.json`` without clobbering
other sections (``run_command``, ``hooks``, ``commands`` each live in their own
key). The file is created if it does not exist. Re-running with the same
unchanged file is idempotent (same checksum recorded).

## Approval policy semantics

When an ``approvals.json`` section is **present**, the approval gate is active:
only entries with matching checksums are allowed. When a section is **absent**,
the gate is a no-op (everything allowed — preserves back-compat for repos with
no approval config).

Status values shown by ``commands list`` and ``hooks list``:

- ``approved``   — entry exists and checksum matches the current file.
- ``drifted``    — entry exists but checksum mismatches (file changed after approval).
- ``unapproved`` — section present but no entry for this name.
- ``ungated``    — section absent from policy (gate not active).

Skills are never approval-gated (they are always ``accessible``).

## Checksum algorithms

- ``sha256`` (default) — ``sha256:<hex>`` format.
- ``md5`` — ``md5:<hex>`` format (weaker; use sha256 for new approvals).

## See also

- ``colleague explain commands``
- ``colleague explain hooks``
- ``colleague explain work``
"""

_FEEDBACK = """\
# colleague feedback

Grade a work item **after the fact** — the second half of the outsourcing-ROI loop.
A work item's artifact already records what it *cost* (the always-on `stats` block:
elapsed time, tokens read/generated, tools used, bytes written, reasoning-vs-answer
sizes); `feedback` records how *good* it was. Together they let a caller — human
or agent — decide whether outsourcing that task to colleague (and to which
backend) paid off.

A work item is named by its `task_id`, or the literal `last` for the most recent
work item in the repo. Feedback is a **single record per work item** (re-grading
overwrites), stored as `.colleague/<task_id>.feedback.json` beside the artifact.

`last` resolves to the most recent **consequential** work item: `ask-colleague explore`
/ `review` run read-only in a throwaway worktree and **do not move** `last` (they
preserve their artifact and are graded by their printed `task_id`). When you ask
for `last`, the resolved work item's id + request is echoed to stderr, so a
mis-resolve is never silent. Forgotten the id? `feedback list` shows every work item
by request.

## Verbs

- `feedback record <id|last> --rating N [--notes ...] [--by ...] [--repo P]` —
  write a 1-5 quality rating + notes. `--by` defaults to the resolved identity.
- `feedback show <id|last> [--repo P] [--json]` — read a work item's feedback. An
  ungraded work item reads back as `no feedback yet` (a clean state, exit 0 — not an error).
- `feedback list [--repo P] [--json]` — list every recorded work item in the repo,
  newest-first, with its request, status, and grade (`--` when ungraded). The
  durable way to find the right work item when the order is forgotten.
- `feedback overview` — describe this surface.

## Usage

    colleague feedback record last --rating 4 --notes "correct but verbose"
    colleague feedback record 9f2c1ab0 --rating 5 --repo . --json
    colleague feedback show last --repo .
    colleague feedback list --repo .

## Record shape

    {"task_id": "...", "rating": 4, "notes": "...", "by": "...", "at": "<ISO-8601>"}

`rating` must be an integer 1-5. There is no tokenizer, so the artifact's
reasoning/written sizes are exact chars/bytes, never estimated tokens — see
`colleague explain work` for the stats block.

## See also

- `colleague explain work`
- `colleague explain ask-colleague`
"""

_TELEMETRY = """\
# colleague telemetry

Telemetry for a work item: opt-in OpenTelemetry **traces + metrics** over OTLP. Telemetry
belongs to the runtime — it is instrumented once in the loop and the shared work
path, so *every* backend emits identical signals (the all-engines rule), exactly
like lifecycle hooks.

Off by default. The OpenTelemetry SDK is an **optional extra** (the base install
keeps zero runtime dependencies); enable it with the env var and install the
extra:

    pip install 'colleague[otel]'
    export COLLEAGUE_OTEL_ENABLED=1
    export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318   # OTLP/HTTP collector

When requested without the extra installed, colleague degrades to a no-op with
a one-line stderr notice — it never fails the work item.

## Signals

- spans: `colleague.work` (root) -> `colleague.tool.*` (per tool call) plus
  `colleague.handoff`.
- metrics: `colleague.steps`, `colleague.tokens` (attr `kind`),
  `colleague.generated.chars` (attr `kind`=reasoning|answer), `colleague.bytes_written`,
  `colleague.tool.latency`, `colleague.tool.calls`, `colleague.hook.denials`,
  `colleague.work.duration` (attr `status`).

## Configuration

Precedence (highest first): explicit > `COLLEAGUE_OTEL_*` > standard `OTEL_*` >
default. `OTEL_SDK_DISABLED=true` is honored as a kill-switch.

- `COLLEAGUE_OTEL_ENABLED` — turn telemetry on (default: off).
- `COLLEAGUE_OTEL_ENDPOINT` / `OTEL_EXPORTER_OTLP_ENDPOINT` — collector URL.
- `COLLEAGUE_OTEL_SERVICE_NAME` / `OTEL_SERVICE_NAME` — resource `service.name`.
- `COLLEAGUE_OTEL_METRICS_ENABLED` — toggle metric emission (default: on).

## Usage

    colleague telemetry status
    colleague telemetry status --json
    colleague telemetry overview

## See also

- `colleague explain work`
- `colleague explain hooks`
"""


_LOBES = """\
# colleague lobes

Inspect colleague's connection to a **lobes gateway** — the cortex/senses arc's
single upstream that serves multiple typed model roles behind one
`/capabilities` endpoint. Colleague resolves exactly two of those roles:

    cortex   the fast, wide-window reasoning mind that drives the tool loop
    senses   the tools-off multimodal front door (intake / normalize /
             classify_intent / prepare_context_packet / speak_back)

The gateway may serve more roles (`embedder`, `reranker`, `stt`, `tts`); this
noun reports only `cortex` + `senses` — colleague resolves nothing else today.

## Armed state + degradation rung

`lobes show` is read-only (one `GET /capabilities`, stdlib `urllib`, never
raises) and reports exactly one of three rungs:

- `not_configured` — `COLLEAGUE_LOBES_URL` is unset; a clean, honest message,
  exit 0 (not an error).
- `armed_reachable` — the gateway answered; the resolved `cortex`/`senses`
  metadata is shown (model, context window, endpoint, ready flag,
  responsibilities, forbidden_responsibilities).
- `armed_unreachable` — a URL is set but the gateway did not answer (down,
  timed out, non-200, or a malformed response); reported honestly, exit 0.

**Scope note:** this noun's ONLY armed signal is `COLLEAGUE_LOBES_URL` env. It
does not (yet) consult a `lobes` section in `.colleague/config.json` — that
fuller precedence chain (explicit flag > env > config.json > builtin) is a
separate, later config-resolution concern (the runtime's own lobes discovery
rung), not this introspection noun's job.

## Usage

    colleague lobes show
    colleague lobes show --json
    colleague lobes overview

## See also

- `colleague explain roles`
- `colleague explain config`
- `colleague explain organs`
"""


_ORGANS = """\
# colleague organs

colleague is the operator front for a small **organism** of sibling CLIs — each
an independent repo, each behind its own published contract
(issue #291, requirement R10). `organs list` shows what is wired in, and
whether it is actually here, with **zero network calls**.

## The curated table

A hand-maintained table (`colleague/oilcheck/organs.py`'s `ORGANS`) — NOT a
dynamically discovered plugin registry:

    lobes           discovery rung (colleague/lobes.py + config.py precedence)
    eidetic         memory shell-out (colleague/memory.py)
    coherence       gate — planned colleague#294 (S3); not yet built
    sloth           experiment noun (colleague/experiment.py; allow-list sloth,
                    colleague#295 S5)
    data-refinery   dataset pipeline — planned data-refinery-cli#14 (S6); not
                    yet built colleague-side
    agtag           culture tool (colleague/culture.py allow-list)
    devex           culture tool (colleague/culture.py allow-list)
    devague         destination tool (colleague/devague.py allow-list)

For each organ this reports **presence** (`shutil.which` on its binary),
**version** (`importlib.metadata.version` on a curated binary→distribution
mapping — many organs are installed as isolated CLI tools, e.g.
`uv tool install`, so a present binary very often still reads `"unknown"`; that
is the expected honest case, not a bug), and **armed** (read from colleague's
own config resolution — env vars, `.colleague/config.json`, and for the memory
organ a plain filesystem check for `.eidetic/`; never a network call).

The full per-organ writeup — what it owns, its contract artifact, and its own
respected non-goals — lives in [`docs/organs.md`](../../docs/organs.md).

## One resolver, two views

`colleague doctor`'s organs check-group and `colleague organs list` render the
SAME resolver (`resolve_organs`), so they can never disagree: `doctor` turns
each entry into a pass/fail health check (a missing/not-yet-wired organ is
always a `warning` with a `uv tool install <distribution>` remediation hint,
**never** unhealthy); `organs list` shows the full table.

`doctor --probe` additionally probes the lobes gateway's live
`GET /capabilities` reachability (reusing `colleague.lobes.resolve_roles`) —
probe-only, never part of the zero-network registered group.

## Usage

    colleague organs list
    colleague organs list --repo PATH
    colleague organs list --json
    colleague organs overview
    colleague doctor              # organs appear as organ_<name> checks
    colleague doctor --probe      # + lobes gateway reachability

## See also

- `colleague explain doctor`
- `colleague explain lobes`
- `colleague explain config`
"""


_SUBAGENT = """\
# colleague subagent

Mid-work, a backend can delegate a scoped sub-task to a nested in-process child
work item via the `subagent` loop tool. The child runs the same bounded tool-loop
with **no** git handoff; its result is returned to the parent as the tool result
and appended to `TaskResult.sub_results` (omitted when empty).

## Key properties

- **In-process** — a nested function call, no separate process, socket, or fork;
  zero new runtime dependencies. The single `subagent` runs **synchronously in
  the parent's worktree** — no per-child worktree, no thread. Worktree isolation
  and concurrency are properties of the `subagents` **batch** path only (below).
- **Backend/model switch** — the optional `engine` and `model` parameters let the
  child run on a different backend or model. Resolution goes through
  `registry.load` + `EngineConfig` inheritance (config-level switch only, no
  backend code change).
- **Bounded** — `MAX_SUBAGENT_DEPTH=2` (recursion cap, checked before any child
  work starts) and `MAX_SUBAGENT_FANOUT=4` (per-work-item fan-out cap). A child
  refused at the depth cap does zero work and returns an error immediately.
- **Backend-judged, optional** — the model decides whether to delegate per call,
  like the `devague` destination tool. There is no operator-configured automatic
  task→backend routing.
- **`subagents` batch — opt-in concurrency (shipped v0.29.0)** —
  `COLLEAGUE_SUBAGENT_CONCURRENCY` (default 1 = byte-identical sequential) runs up
  to `MIN(width, MAX_SUBAGENT_FANOUT-1)` batch children in parallel via
  `concurrent.futures`, reserving one slot for a sequential merge child.
- **`subagents` batch — per-child worktree isolation** — each *batch* child runs
  in its own throwaway git worktree on a `sub/<id>` branch
  (`colleague/worktrees.py`); the merge child integrates them, surfacing (never
  force-merging) conflicts. (The single `subagent` tool creates no worktree.)
- **No per-subagent handoff** — only the top-level work branches, commits, and
  opens a PR.
- **Runtime-owned (all-engines rule)** — the tool schema lives in
  `colleague/tools.py`; the launcher lives in `colleague/subagents.py`. No
  backend module touches either; the tool is offered to every backend identically.

## Not a router

This is **not** the out-of-scope multi-backend router: there is no
operator-configured policy that automatically routes a task to a particular
backend. Delegation is always the model's choice at call time.

## Tool parameters

- `instruction` (required) — the sub-task to hand to the child work item.
- `engine` (optional) — backend plugin name; defaults to the parent's backend.
- `model` (optional) — model override; defaults to the parent's model.

## Implementation

- `colleague/subagents.py` — `run_subagent` / `make_spawn` launcher.
- `colleague/tools.py` — tool schema + `ToolExecutor._subagent` dispatch.
- `colleague/config.py` — `MAX_SUBAGENT_DEPTH`, `MAX_SUBAGENT_FANOUT`.
- `colleague/contract.py` — `SubResult`, `TaskResult.sub_results`.

## See also

- `colleague explain work`
- `colleague explain backends`
"""

_ASK_COLLEAGUE = """\
# colleague ask-colleague (a different mind)

`ask-colleague` is a **first-party** Claude Code skill
(`.claude/skills/ask-colleague/`), not a CLI verb — the inverse of the vendored
skills (origin = colleague). It lets another agent hand a scoped task to
colleague: a *different* backend/mind, not a stronger one. Diversity is the point
— a second, independent perspective catches what the author's mind glides past,
which is why **review** is the headline verb. (Formerly named `outsource`; the
"outsource this" phrasing still triggers it and `explain outsource` still resolves
here.)

## Verbs

- `ask-colleague explore "<question or area>"` — read-only investigation; the model
  reads and reports findings.
- `ask-colleague review "<focus>" [--base main]` — a diverse second opinion on the
  committed diff (`<base>...HEAD`).
- `ask-colleague write "<task>" [--apply|--pr]` — delegate a small implementation.
  Previews by default (throwaway worktree + would-be diff, no side effects);
  `--apply` lands a `colleague/<id>` work branch, `--pr` opens a PR.
- `ask-colleague monitor|guide|stop <id>` — pilot a running flight; `--watch` on
  the dispatching `colleague work` arms the flight for piloting.

## Safety

- explore/review run in a throwaway `git worktree` at HEAD — they cannot touch
  your working tree or branch (read-only is enforced by isolation + a prompt
  constraint, not a sandbox).
- `write` previews by default (isolated worktree, safe even on a dirty tree);
  applying (`--apply` / `--pr`) refuses a dirty tree unless `--allow-dirty`
  (guards the dirty-tree hazard).

## Run

    bash .claude/skills/ask-colleague/scripts/ask-colleague.sh <verb> "<text>" [options]

Defaults to a local vLLM model; override with `--engine` / `--model` /
`--base-url` or `COLLEAGUE_*` env. See `docs/features/ask-colleague.md`.

## See also

- `colleague explain work`
"""

_CONFIG = """\
# colleague config

Inspect the resolved engine/provider configuration. ``config show`` prints the
resolved :class:`~colleague.config.EngineConfig` (base_url, model, max_steps,
temperature, timeout, context_budget_tokens) with the api_key redacted.
``config overview`` describes the noun.

Precedence (highest first): explicit flag > COLLEAGUE_*/OPENAI_* env >
.colleague/config.json > built-in default.

## Verbs

- ``config show [--repo PATH] [--json]`` — show the resolved provider config
- ``config overview`` — describe the config surface

## Usage

    colleague config show
    colleague config show --repo . --json
    colleague config overview

## See also

- ``colleague explain doctor``
- ``colleague explain work``
"""

_TUI = """\
# colleague tui

Headless, agent-facing inspection of the TUI cockpit — a state machine whose
single agent-readable mirror is the **TAUI** (a plain JSON dict). This verb runs
entirely **without a terminal** and opens no socket: it is a set of pure
`state -> mirror/frame` transforms. The live TTY view is a separate concern.

The cockpit exposes **three views** of the same `CockpitState`:

- **JSON (TAUI)** — the programmatic/script contract and the source of truth;
  emitted by `tui state`.
- **ANSI** — the visual frame for a live terminal; emitted by `tui render` (default).
- **Markdown** — the agent-facing readable view; better than raw JSON for an agent
  to read at a glance. Emitted by `tui render --format markdown`. All three are pure
  functions of one `CockpitState`, so any disagreement between them is a
  render-fidelity bug — `tui diagnose` catches it. (Before this surface was added,
  no colleague command emitted Markdown and `diagnose` inspected the ANSI frame
  only.)

## Verbs

- `tui render --state <file> [--format ansi|markdown]` — render the chosen frame
  (default: `ansi`). `--json` wraps the result as `{"ansi": "<frame>"}` or
  `{"markdown": "<frame>"}` depending on `--format`.
- `tui state [--state <file>]` — print the TAUI mirror as JSON (default: a fresh
  empty cockpit).
- `tui inspect --select <selector> [--state <file>]` — resolve a dotted selector
  to its node (JSON). A bad selector is a user error.
- `tui action --select <selector> [--state <file>]` — operate the UI by selector:
  map a popup-action selector to an event, reduce it, and print the NEW mirror.
- `tui replay <events.jsonl> [--state <file>]` — fold an event log into a mirror.
- `tui snapshot --name <n> [--state/--events/--dir]` — write the snapshot **quad**:
  `<name>.taui.json`, `<name>.ansi`, `<name>.events.jsonl`, and `<name>.md` (the
  Markdown render). Legacy triples (no `.md`) still read fine — `<name>.md` defaults
  to empty when absent.
- `tui test --scenario <file.json>` — run a JSON scenario as an assertion;
  **exit 1 on FAIL**.
- `tui diagnose (--dir <d> --name <n> | --taui <f> --ansi <f> [--events <f>])` —
  classify cross-mirror bugs (no model/network). On a quad (`<name>.md` present)
  the RENDER faithfulness check runs against **both** the ANSI frame and the
  Markdown frame — proving the JSON mirror and the Markdown render agree. Zero
  findings = faithful; a finding = render-fidelity drift between JSON and Markdown.
  (Legacy triples without a `.md` file skip the Markdown check entirely, preserving
  the exact pre-quad behavior.)
- `tui overview` — describe this surface.

## Scenario format (JSON, not YAML)

colleague keeps zero runtime dependencies, so scenarios are **JSON**, never
YAML (PyYAML is forbidden):

    {
      "name": "boost popup appears when a skill is suggested",
      "initial": { "screen": "main" },
      "events": [ {"type": "skill_suggested", "skill": "boost",
                   "reason": "task_complexity_high"} ],
      "expect": {
        "popup": { "id": "popup.skill.boost", "visible": true, "blocking": false },
        "focused": "input.prompt",
        "action_available": "popup.skill.boost.accept"
      }
    }

The runner builds `CockpitState.from_dict(initial)`, folds each event via
`event_from_dict` + `reduce`, serializes the final state, and checks each
`expect` clause: `popup` (id/visible/blocking against the serialized popups),
`focused`, and `action_available` (present among the derived selectors /
`available_actions`). The report lists which clauses passed and which failed.

## Usage

    colleague tui state --json
    colleague tui render --state cockpit.json
    colleague tui render --state cockpit.json --format markdown
    colleague tui render --state cockpit.json --format markdown --json
    colleague tui inspect --select popup.skill.boost --state cockpit.json --json
    colleague tui action --select popup.skill.boost.accept --state cockpit.json --json
    colleague tui test --scenario colleague/tui/scenarios/boost-popup.scenario.json
    colleague tui snapshot --name baseline --state cockpit.json --dir ./snapshots
    colleague tui diagnose --dir ./snapshots --name baseline

## See also

- `colleague explain session`
- `colleague explain work`
"""

_FLIGHT = """\
# colleague flight

Pilot a running work item. The flight noun lets the dispatching agent (Claude or a
colleague work-loop) pilot a running work item: watch its live feed (status),
redirect it (guide), or call it back (stop). Control is cooperative — directives
are applied at the running loop's next turn boundary.

## Verbs

- `flight status <task_id>` — read the latest feed record
- `flight guide <task_id> <message>` — send guidance to the running loop
- `flight stop <task_id>` — signal the running loop to stop
- `flight list` — list active flight task ids
- `flight overview` — describe the flight surface

## Usage

    colleague flight status tid
    colleague flight guide tid "refactor the auth module"
    colleague flight stop tid
    colleague flight list
    colleague flight overview
"""

_EXPERIMENT = """\
# colleague experiment

Detached `sloth` (unsloth-cli) training runs, driven from the operator front
(colleague#291, requirement R5 / S5). A curated allow-listed shell-out —
allow-list exactly `sloth` — following the culture-tool pattern, with the
long-run problem solved job-shaped: `experiment start` validates the dataset
first (`sloth validate --dataset … --json`, before any GPU work), then
detaches `sloth train --config <toml>` exactly the `work --background` way
(`subprocess.Popen(..., start_new_session=True)`, stdio to a log file, no
`.wait()`/`.poll()`), and returns immediately with a machine-readable start
payload.

## Verbs

- `experiment start --config <toml>` — validate then detach `sloth train`
- `experiment status <id>` — pid liveness + a log tail + best-effort
  correlation against sloth's own run registry (`sloth runs list`/`show`)
- `experiment list` — every detached experiment, newest-first
- `experiment summarize <id> [--remember]` — join `sloth summarize --json`;
  with `--remember`, upsert a compact record into eidetic memory (the same
  `--scope colleague --visibility public` convention `colleague/memory.py`
  uses — reused as-is, never re-implemented)
- `experiment overview` — this description

## Storage

- `<repo>/.colleague/experiments/<id>/start.json` — the start payload
  (`{id, pid, config, output_dir, log_dir, started}`)
- `<repo>/.colleague/experiments/<id>/train.log` — combined stdout+stderr of
  the detached `sloth train` child

## Grading

An experiment id is a valid feedback `task_id`:
`colleague feedback record <exp-id> --rating N`.

`colleague clean` reaps dead-pid experiment residue (pid gone AND the
start payload older than a day); a genuinely live pid is never touched.

## Honest limits

- Missing `sloth` (unsloth-cli) degrades to a structured error with
  remediation (`uv tool install unsloth-cli`), never a traceback.
- `experiment status`'s `sloth_run` correlation is best-effort: it degrades to
  `None` when sloth is unreachable or the registry hasn't been written yet
  (training hasn't reached that point) — never blocks the status query.
- Job-shaped, never a scheduler: one detached child per experiment, no
  daemon, no polling loop of colleague's own.

## Usage

    colleague experiment start --config run.toml --repo .
    colleague experiment status <id> --repo .
    colleague experiment list --repo .
    colleague experiment summarize <id> --remember --repo .

## See also

- `colleague explain flight`
- `colleague explain organs`
- `colleague explain feedback`
"""

_TALK = """\
# colleague talk

Attach a live REPL to a RUNNING work item over the file-based flight plane
(the senses live-presence + voice arc) and converse with senses while cortex
drives. Cooperative, file-based — no daemon, no socket.

Each typed message gets a senses answer, labeled `senses:`. An instruction can
be relayed into the running cortex loop via the flight guidance channel — it
echoes a visible `-> cortex:` line so the relay is never silent. `--audio
FILE` (at startup) or `/say FILE` (mid-REPL) transcribes a spoken message via
the configured stt model; a reply is synthesized to a `.wav` beside the flight
files when tts is configured (`config.voice.tts_model`) — additive only, never
blocking the text reply.

**Degradation:** when senses is unarmed, `talk` degrades to a **watch +
raw-guide** REPL — one notice is printed, and every subsequent typed line is
relayed directly into the running loop (the same `-> cortex:` echo, no senses
answer). Never crashes; the only hard failure is an invalid flight task id.

## Usage

    colleague talk <task_id> --repo .
    colleague talk <task_id> --audio question.wav --repo .
    colleague talk <task_id> --engine vllm-openai --model <name>

## In the REPL

- Type a message — senses answers it (`senses: ...`); an explicit `cortex:`
  prefix always forces a relay regardless of senses' own judgment.
- `/say <path>` — transcribe an audio file as the next message.
- `/quit` or `/exit` (or EOF) — end the REPL cleanly.

## See also

- `colleague explain flight`
- `colleague explain work`
"""

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

ENTRIES: dict[tuple[str, ...], str] = {
    (): _ROOT,
    ("colleague",): _ROOT,
    ("promote",): _PROMOTE,
    ("work",): _WORK,
    ("drive",): _WORK,  # deprecated alias — explain still resolves the old name
    ("session",): _SESSION,
    ("backends",): _BACKENDS,
    ("backends", "list"): _BACKENDS,
    ("backends", "overview"): _BACKENDS,
    ("wheels",): _BACKENDS,  # deprecated alias — explain still resolves the old name
    ("wheels", "list"): _BACKENDS,
    ("wheels", "overview"): _BACKENDS,
    ("whoami",): _WHOAMI,
    ("quickstart",): _QUICKSTART,
    ("learn",): _LEARN,
    ("explain",): _EXPLAIN,
    ("overview",): _OVERVIEW,
    ("doctor",): _DOCTOR,
    ("livecheck",): _LIVECHECK,
    ("clean",): _CLEAN,
    ("learn-from",): _LEARN_FROM,
    ("cli",): _CLI,
    ("cli", "overview"): _CLI,
    ("commands",): _COMMANDS,
    ("commands", "list"): _COMMANDS,
    ("commands", "overview"): _COMMANDS,
    ("commands", "approve"): _APPROVE,
    ("hooks",): _HOOKS,
    ("hooks", "list"): _HOOKS,
    ("hooks", "overview"): _HOOKS,
    ("hooks", "approve"): _APPROVE,
    ("agents",): _AGENTS,
    ("agents", "list"): _AGENTS,
    ("agents", "overview"): _AGENTS,
    ("skills",): _SKILLS,
    ("skills", "list"): _SKILLS,
    ("skills", "overview"): _SKILLS,
    ("roles",): _ROLES,
    ("roles", "list"): _ROLES,
    ("roles", "overview"): _ROLES,
    ("approve",): _APPROVE,
    ("feedback",): _FEEDBACK,
    ("feedback", "record"): _FEEDBACK,
    ("feedback", "show"): _FEEDBACK,
    ("feedback", "list"): _FEEDBACK,
    ("feedback", "overview"): _FEEDBACK,
    ("telemetry",): _TELEMETRY,
    ("telemetry", "status"): _TELEMETRY,
    ("telemetry", "overview"): _TELEMETRY,
    ("lobes",): _LOBES,
    ("lobes", "show"): _LOBES,
    ("lobes", "overview"): _LOBES,
    ("organs",): _ORGANS,
    ("organs", "list"): _ORGANS,
    ("organs", "overview"): _ORGANS,
    ("config",): _CONFIG,
    ("config", "show"): _CONFIG,
    ("config", "overview"): _CONFIG,
    ("subagent",): _SUBAGENT,
    ("subagents",): _SUBAGENT,
    ("ask-colleague",): _ASK_COLLEAGUE,
    ("outsource",): _ASK_COLLEAGUE,  # deprecated alias — explain still resolves the old name
    ("tui",): _TUI,
    ("tui", "render"): _TUI,
    ("tui", "state"): _TUI,
    ("tui", "inspect"): _TUI,
    ("tui", "action"): _TUI,
    ("tui", "replay"): _TUI,
    ("tui", "snapshot"): _TUI,
    ("tui", "test"): _TUI,
    ("tui", "diagnose"): _TUI,
    ("tui", "overview"): _TUI,
    ("flight",): _FLIGHT,
    ("flight", "status"): _FLIGHT,
    ("flight", "guide"): _FLIGHT,
    ("flight", "stop"): _FLIGHT,
    ("flight", "list"): _FLIGHT,
    ("flight", "overview"): _FLIGHT,
    ("experiment",): _EXPERIMENT,
    ("experiment", "start"): _EXPERIMENT,
    ("experiment", "status"): _EXPERIMENT,
    ("experiment", "list"): _EXPERIMENT,
    ("experiment", "summarize"): _EXPERIMENT,
    ("experiment", "overview"): _EXPERIMENT,
    ("talk",): _TALK,
    ("plan",): _PLAN,
    ("plan", "run"): _PLAN,
    ("plan", "continue"): _PLAN,
    ("plan", "status"): _PLAN,
    ("plan", "overview"): _PLAN,
    ("mcp",): _MCP,
    ("mcp", "serve"): _MCP,
    ("mcp", "overview"): _MCP,
}
