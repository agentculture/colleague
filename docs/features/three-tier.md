# Three-tier execution — worker acts, senses relays, cortex configures

> An **authority split**, not three sizes of the same mind.

colleague can run in a **three-tier execution mode** where three distinct roles
carry fixed, non-overlapping authority:

- **worker** — the acting seat. Drives the bounded tool loop, calls tools,
  edits files, runs commands. Resolved by role name from the lobes gateway.
- **senses** — the relay seat. Tools-off front door that reads the operator's
  input, relays worker answers with fidelity, and never acts on the repo.
- **cortex** — the configuring seat. An opt-in reviewer that proposes typed
  configuration changes between episodes. Never touches worker history.

This is the **eighth sanctioned increment** at colleague's router-exclusion
line. It is **opt-in** via `config.json` `three_tier` or `COLLEAGUE_THREE_TIER`;
absent config is **byte-identical** to legacy colleague. It is **never** an
automatic task-to-model routing policy.

## What the mode is — authority split, not three sizes

The three tiers are not three models of different capability doing the same
job. They are three seats with **fixed authority boundaries**:

- The **worker** is the only seat that acts on the repo (tools, edits, commands).
- The **senses** seat is structurally tools-off — it relays and presents, never
  acts. Its fidelity to the worker's answer is enforced by prompt clauses and
  a structural fallback.
- The **cortex** seat (the configurator) is a further opt-in that reviews
  episode facts and proposes typed configuration units. It never touches
  worker history, never acts on the repo, and is **off by default**.

The split is resolved **by role name** from the lobes gateway — `worker`,
`senses`, `cortex` — not by a heuristic that selects per-task. There is no
"worker answers cheap questions" path. The model never decides which seat
handles which input.

## Landed pieces

### Worker role resolution — `colleague/lobes.py` + `colleague/config.py`

The lobes discovery client now resolves a **`worker`** role alongside the
existing `cortex`/`senses` roles. When three-tier mode is armed, the worker's
advertised endpoint becomes the acting dial — the model that drives the tool
loop. The worker role carries its own `endpoint` field, dials independently
via `resolve_role_base_url`, and inherits the main `api_key` only when its
dial target shares the main endpoint's origin (same-origin key hygiene).

**Loud refusal:** if the worker role is advertised but three-tier mode is not
armed, the worker is read and discarded — no silent swap. If three-tier is
armed but no worker role is found, resolution degrades with one stderr notice
and falls through to the next precedence rung.

### Worker-as-actor acting-dial wiring

When three-tier mode is active, the acting dial (the model that drives the
tool loop) is the worker's endpoint, not the cortex's. The cortex remains
resolved and available for the configurator's review calls, but the loop
itself runs against the worker. This is a config-level switch, not a
runtime routing decision.

### Senses fidelity clauses — `colleague/senses.py`

The senses talk lane carries **structural fidelity clauses** in its prompt:
grounding instructions, verbatim worker-answer containment directives, and
four counters (`verbatim_presence`, `knowledge_repetition`, `fallback`,
`degraded`) recorded on each `SensesRecord`. When the model fails to contain
the worker's answer, a **raw-answer fallback** fires — the operator receives
the exact worker answer, never a rewritten version. The fallback records
`degraded=true` and is visible in the artifact.

### Seat-aware attribution — `colleague/attribution.py`

Attribution tracking is seat-aware: each action in the artifact is labeled
with the seat that produced it (`worker`, `senses`, `cortex`). This prevents
the worker's acts from being attributed to senses or vice versa.

### Lattice — `colleague/lattice.py`

The lattice provides **refuse-whole change units** and an **authority ceiling**:
configuration proposals from the configurator are validated as typed units
(worker knowledge, senses knowledge, worker prompt strategist). A proposal
that violates the authority ceiling (e.g. tries to change the worker's
tool-calling behavior) is refused. The lattice never applies partial changes —
a unit is accepted or refused as a whole.

### Config lifecycle — `colleague/configlifecycle.py`

Episode-immutable snapshots: once an episode begins, its configuration is
frozen. Changes proposed by the configurator land in **sanctioned windows**
between episodes, never mid-episode. The **T1 no-tool boundary** ensures the
configurator's review call is a tools-off completion — it cannot call tools
or modify the repo directly.

### Config events — `colleague/configevents.py`

An **append-only event stream** records every configuration change with a
digest. `digest_from_replay` can reconstruct the current config state from
the event log. **Liveness is tracked by counters, never armed** — the event
stream records what happened, not whether the system is alive.

### Configurator — `colleague/configurator.py`

The configurator is an **opt-in cortex reviewer** (default **off**). When
armed, it reviews episode facts and proposes typed configuration units
through the lattice. It is structurally pinned: it never touches worker
history, never acts on the repo, and its proposals go through lattice
validation before any change is applied. The configurator runs as a
tools-off completion against the cortex dial.

### Finish states — `colleague/finishstate.py`

Five completion states track how a work item ended: `ok`, `incomplete`,
`failed`, `truncated`, and `no-progress-zero-steps`. These states feed
the configurator's review and are recorded in the artifact.

### Oilcheck — three-tier doctor group

The `colleague doctor` verb gains a **three-tier** group that validates
the three-tier configuration: worker role presence, senses fidelity wiring,
configurator opt-in state, and lattice validation readiness.

## Configuration

Opt-in via `config.json` or environment:

```jsonc
// .colleague/config.json
{
  "three_tier": true
}
```

Or: `COLLEAGUE_THREE_TIER=1`.

When armed, the lobes gateway's `worker` role fills the acting dial. The
configurator is a **further opt-in** (default off) — three-tier mode ships
with worker + senses active, but the cortex configurator is dormant until
explicitly enabled.

Absent `three_tier` config is **byte-identical** to legacy colleague: the
cortex drives the loop, senses operates as before, no worker role is
consumed, no configurator runs.

## Experiments — three pre-registered gates

### Experiment A — senses fidelity gate

**Protocol:** `docs/experiments/2026-08-05-experiment-a-senses-fidelity.md`

Tests whether senses, with t2's structural fidelity in place, relays the
worker's answer faithfully when carrying unrelated background knowledge.

**Verdict: SUPPORTING.** 6/6 worker answers visible (5 verbatim relays + 1
raw-answer fallback), 0/6 unrelated knowledge replacements, 6/6 attribution
held. The structural fallback floor is live-proven.

### Experiment B — worker promotion gate

**Protocol:** `docs/experiments/2026-08-05-experiment-b-worker-promotion.md`

Compares the worker seat (`unsloth/Qwen3.6-35B-A3B-NVFP4`) against the
current acting cortex (`unsloth/Qwen3.6-27B-NVFP4`) on real colleague
work items.

**Verdict: PROMOTES (SUPPORTING).** Worker: 4/4 completions, quality 12/12,
0/4 protocol failures. Baseline cortex: 0/4 completions, quality 0, 4/4
protocol failures.

**Caveat:** every baseline failure is the known **zero-step markup collapse**
(issue #346) — the 27B cortex's pre-existing behavior on this surface. The
tiny minimal-context fixture is the environment #346 says amplifies the
collapse. The comparison is honest about what it measured; a broad-repo
comparison remains future evidence.

### Experiment C — strategist value gate

**Protocol:** `docs/experiments/2026-08-06-experiment-c-strategist-value.md`

Tests whether the configurator notices a genuinely misconfigured actor.

**Verdict: SUPPORTING.** 4/4 corrective detection on mismatch trials, 0/4
false interventions on control trials.

**Nuance:** every mismatch proposal was then **refused** by lattice validation
because the model-authored knowledge entry omitted its `origin` field. The
corrective content was substantively right, but the structural validation
caught the missing field. The obvious v1.1 improvement — auto-stamping
entry-level origins — is folded into the #366 follow-up. The strategist
remains opt-in and off by default.

## Honest limits

### Deviation d2 / issue #366 — the WIRED consumption lane

The change-content consumption lane is **wired end to end**. Applied
configuration changes reach the worker's next episode through the composed
prompt and tool schema. The pinning tests that prove each segment:

- **ChangeUnit.content** — strategist-targets-only validation, 4000-char cap,
  empty-narrowing refusal (`tests/test_lattice.py`)
- **Lifecycle folds** — verbatim text with REPLACE semantics
  (`tests/test_configlifecycle.py`)
- **Configurator auto-stamps** — entry origins, content key, visible degraded
  events (`tests/test_configurator.py`, `tests/test_configevents.py`)
- **Prompt seam** — `Engine.system_prompt` composes the strategist section
  (`tests/test_engine_strategist_seam.py`)
- **Tool narrowing** — schema + executor intersection with the role ceiling
  (`tests/test_tool_narrowing.py`)
- **Work front** — lifecycle + windows + folds `config_events` onto
  `TaskResult` and the persisted artifact (`tests/test_work_config_plane.py`)
- **Subagent children** — consume a frozen snapshot of the config lifecycle
  (`tests/test_subagent_config_snapshot.py`)
- **Flight run-start** — names the acting seat
  (`tests/test_flight_heartbeat.py`)

### The strategist ships opt-in and OFF

The configurator is default **off**. Three-tier mode ships the worker and
senses tiers active (when armed), but the cortex configurator is dormant
until explicitly enabled. This is deliberate: the origin-stamping refusal
nuance from experiment C shows the lattice validation is stricter than the
model's output.

### Strategist VALUE is unproven until the NEBULA benchmark arm

The content lane is wired, but whether the strategist *improves* task outcomes
remains unmeasured. The NEBULA RUN benchmark arm (issue #366: the identical
ship-game prompt re-run configurator-live against the recorded pre-#366
baseline) is the gate for a value claim. Until that arm runs, the
strategist's value is conditional on the benchmark — not proven.

### Deepthink is absent in three-tier mode

When three-tier mode is armed, the deepthink escalation surface is not
available. The worker acts, senses relays, and the cortex (if armed)
configures — but there is no dual-model judgment escalation. This is a
deliberate boundary: three-tier mode and dual-model mode are distinct
configurations, not layered features.

### Known gap: engine-failure artifact path performs no config-plane fold

When the engine fails mid-episode, the failure artifact path does not fold
in-flight window events onto the persisted artifact. The config lifecycle
snapshot is episode-immutable, so events that occur between the last
sanctioned window and the failure are not persisted. This is a known gap,
not a regression.

## Legacy vs three-tier distinction

In **legacy mode** (no `three_tier` config), colleague runs as before: the
cortex drives the tool loop, senses operates as the tools-off front door,
deepthink is available for judgment escalation. The three-tier wiring is
present but dormant — byte-identical behavior.

In **three-tier mode**, the worker role resolves as the acting dial, senses
carries the t2 fidelity clauses, and the cortex is available for the
opt-in configurator. Deepthink is absent. The authority boundary is fixed:
worker acts, senses relays, cortex configures.
