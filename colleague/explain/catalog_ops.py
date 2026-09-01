"""Delegation and operations catalog entries (subagent, ask-colleague, config, tui, flight, ...).

Split out of ``colleague/explain/catalog.py`` (docstring constants only, one
per ``colleague explain <path>`` topic group); see that module for ``ENTRIES``.
"""

from __future__ import annotations

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

## Temperature knob deprecation (#479)

``temperature`` is a flat scalar being superseded by the per-half sampling
table (``colleague.sampling`` + the tracked ``.colleague/models.json``):

- ``CONVERTIBLE_TEMPERATURE`` is REMOVED — its value is ignored, and setting
  it prints a warning and lands one on ``TaskResult.warnings``.
- ``COLLEAGUE_TEMPERATURE`` is DEPRECATED for one release — it still applies
  exactly as it does today, but warns that a single value collapses BOTH the
  thinking and non-thinking sampling halves to itself, and names
  ``.colleague/models.json`` as the per-half replacement.
- A run with neither variable set is silent — no warning, byte-identical
  behaviour.

``config show`` states the resolved sampling match POSITIVELY, right beside
the effort lines — the row + model it matched, or an explicit
no-row-matched line — never a silent miss on a checkpoint colleague has no
card for.

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

_STRIVE = """\
# colleague strive

The necessity loop (self-learning arc, plan t13/t14): bounded, operator-invoked
attempts toward a goal with an EXECUTABLE ground-truth measure. Per attempt the
harness enforces four phases — recall, delta declaration (recorded BEFORE
execution; an attempt that cannot name a delta or new hypothesis is recorded as
exactly that), execute + measure, lesson-grade remember. The per-goal hypothesis
ledger (schema-enforced records, refuse-whole on unknown keys) is the novelty
detector; K consecutive refuted-recombinations = a recorded novelty stall, never
fabricated progress. The measure command routes through the approval gate exactly
like run_command (a policy gate, not a sandbox) and runs in the episode worktree.
chain.CONTINUABLE_REASONS stays exactly {budget-exhausted}: strive's retry policy
lives in colleague/strive.py, never in the work/drive chain.

Usage: `colleague strive run "<goal>" --attempts N --measure "<cmd>" [--json]`,
`colleague strive overview`.
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
