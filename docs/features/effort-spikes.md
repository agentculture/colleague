# Effort spikes — the amended thinking-effort invariant's opt-in surface

> Spec:
> [`docs/specs/2026-09-01-small-fixes-then-effort-balance.md`](../specs/2026-09-01-small-fixes-then-effort-balance.md)
> (c18/c8/h5/h7) — the arc that lands four small validity/observability fixes
> (#480-#483) before this surface (#484).

[`thinking-effort.md`](thinking-effort.md) states the invariant: a seat's
reasoning rung is resolved **where the seat is built**, never per turn. #484
**amends** that wording (recorded as convention change (7) in CLAUDE.md's
"v0 → v1 graduation" list): the invariant now reads **"never per turn FROM
CONTENT — per enumerated point from a fixed table."** The distinction
matters — the old wording alone would not rule out a table keyed on turn
*content* (a summary of what the model just did, a report's findings, the
model's own text). Effort spikes key a rung by **POINT NAME only**: a fixed,
enumerated string like `"barrier.pre_mutation"`, never anything read from the
turn. This doc covers that surface; `thinking-effort.md` line 11 and CLAUDE.md
carry the amended wording as pointers back here.

**Default ON since the effort-floor-and-decay arc (row 77, operator
decision recorded as deviation d1 on that plan).** `COLLEAGUE_EFFORT_SPIKES`
unset means armed; `=0` (or `off`/`false`/`no`) disarms it, and then every
function in `colleague/effortspikes.py` is a strict no-op and the run is
byte-identical to v1.74.0: no `effort_spikes` key on the artifact, no seat
built, no config attribute set. The same applies to `COLLEAGUE_EFFORT_DECAY`
(default ON, `=0` disarms) and to the cortex floor, which moved `low` → `off`
in `effort.SEAT_TABLE` at the same time (`COLLEAGUE_REASONING_EFFORT=low`
restores it). **The test suite pins the OLD wire as its baseline** (both
knobs `=0` in `tests/conftest.py`) so the hundreds of byte-identity tests
about other features stay meaningful; the default-ON contract is asserted
explicitly in `tests/test_effortspikes_boundary.py` /
`tests/test_effortdecay_boundary.py`. The rigour debt behind this default —
n=1 — is issue #490.

## The five enumerated points (`colleague/effortspikes.py`)

Exactly five, no more — `SPIKE_POINTS`, a tuple both the table and the drift
test (`tests/test_effortspikes_boundary.py`) key off. Three landed with #484;
the effort-floor-and-decay arc added the two position/count-keyed ones after
rows 74-75 showed an `off`-floor run never reaches the pre-mutation barrier:

| Point | Rung | Keyed by | Fires in |
|-------|------|----------|----------|
| `barrier.pre_mutation` | `"medium"` | first `write_file`/`edit_file` request (name) | `colleague/loop_barrier.py` |
| `gate.repeat_failure` | `"medium"` | a gate's 2nd repair attempt (count) | `colleague/loop_gateescalation.py` |
| `fillline.decision` | delegated (see below) | the fill-line declaring turn | `colleague/loop_gateescalation.py` |
| `stall.no_write` | `"medium"` | `STALL_TURNS` (10) acting turns with no file-writing call since start / last spike / last write (count over names); at most `STALL_MAX_FIRES` (3) per run | `colleague/loop_barrier.py` (`intercept_stall`, the barrier's tools-off turn with a stall prompt) |
| `start.first_turn` | `"medium"` | model turn 1 (position), tools on | `colleague/loop_gateescalation.py` (`acting_turn`) |

Both new points are resets for the effort decay below and stall marks for
each other: a start spike restarts the stall count at turn 1; a stall or
barrier firing restarts it again. Neither reads turn content.

`SPIKE_TABLE` maps each point to its rung. Every non-delegated row is a member
of the closed ladder (`colleague.effort.LADDER`) — `resolve_spike` re-validates
through `colleague.effort.validate_effort`, so there is no path by which an
out-of-ladder string reaches the wire. An explicit per-point override,
`COLLEAGUE_EFFORT_SPIKE_<POINT>` (point name upper-cased, `.` → `_`), wins over
the table row and is validated the same way.

### `fillline.decision` is delegated, not duplicated

`SPIKE_TABLE["fillline.decision"]` holds the sentinel `FILLLINE_DELEGATED`, not
a rung — `resolve_spike` refuses to resolve it directly and always returns
`None` for that point. The fill-line's decision point already had a rung:
`colleague.effort.DESIGN_SITE_TABLE["fillline.split"]` = `"xhigh"` (`effort.py`
line ~110), landed with the #416 design-site table but with **no live
consumer** until this arc. Giving it a second, independent row in
`SPIKE_TABLE` would let the two tables drift; the module instead documents
"ask `DESIGN_SITE_TABLE['fillline.split']` instead," and
`colleague/loop_gateescalation.py` (below) is the consumer that actually reads
it, via the existing builder `colleague.fillline.design_seat_config` — so the
operator override / `default` kill-switch precedence (c32) is honoured in the
one place it was already honoured, never re-derived.

### No model-reachable parameter

`resolve_spike(point: str) -> Optional[str]` takes only a point name. No
function in the module accepts an `effort`/`rung`/`reasoning_effort` keyword
(swept by `tests/test_effortspikes_boundary.py`), and `colleague/tool_schemas.py`
names no `spike` surface at all — there is no tool-parameter path by which a
model could reach a rung.

## Consumer 1 — the pre-mutation decision barrier (`colleague/loop_barrier.py`)

The FIRST time a turn's requested tool calls include a **mutating** tool (tool
NAME lookup only, via `colleague.roles.is_read_only_tool` — never argument or
content inspection), after a run phase where every prior step named only
read-only tools, the loop interposes one bounded, **tools-off** completion at
the `barrier.pre_mutation` rung: same history, no tools offered, plus a system
nudge (`BARRIER_PROMPT`) asking the model to name the files, invariants and
seams it is about to touch before touching them.

**The intercepted turn is replaced, not deferred.** Its tool calls are never
executed and its assistant message is never appended — a deferred-then-replayed
call would act on a plan the model had not yet written, and an appended
assistant tool-call message with no matching `tool` results is not a valid
OpenAI history. The model re-issues whatever it still wants to do on its next
turn, now with the plan in context.

**Accounting is honest (decision c23).** The barrier turn is a NORMAL step:
its usage/reasoning/answer sizes fold into `WorkStats` via
`loop_accounting._account_turn` and `model_turns` advances — it costs a turn
like any other against `max_steps`. It appends one `Step` named
`barrier.pre_mutation`, so `stats.step_count` advances by exactly one.

**Bounds:** output capped to `max_output_chars // 8` (`PLAN_CHARS_DIVISOR`,
8500 chars on the 68000 default) with the same discoverable
`[truncated: original N chars]` marker `colleague/tasktext.py` uses; timeout is
the STANDARD (un-escalated) turn timeout, never an escalated one.

**The trigger, after #487.** v0's precondition was "every prior step named a
read-only tool", and `run_command` is mutating BY NAME (`roles._WRITE_TOOLS`)
— so a survey that opened with `git status` or `wc -l` latched the barrier
shut for the whole run; 3 of 5 measured dispatches did exactly that
(`docs/live-testing.md` rows 72-73). Since the effort-decay arc the
precondition is "no prior step named a **file-writing** tool"
(`FILE_WRITE_TOOLS` = `write_file`/`edit_file`) and the trigger is "this turn
requests one" — still a tool-NAME lookup, never content. `run_command` stays
a mutating tool for roles and policy; a `sed -i` inside it slips past the
barrier, and that is documented here rather than inspected.

**Firing:** at most once per run (v0). The barrier's own `TaskResult
.effort_spikes` entry for `barrier.pre_mutation` IS the already-fired marker —
no separate state cell. Unarmed, `make_barrier_complete` returns `None` before
it builds anything and `intercept` returns `False` before it looks at a tool
name — a strict no-op, including on the `mock` backend (which has no one-shot
completion seam; the caller warns once and proceeds without a barrier, never
crashes — the all-engines rule holds because an armed `mock` run records why
it skipped, rather than diverging in shape).

## Consumer 2 — repeated-gate-failure + fill-line (`colleague/loop_gateescalation.py`)

Both points here escalate a turn that must **keep the run's own tool
surface** (a gate repair turn calls `edit_file`/`run_tests`; the fill-line
declaring turn declares SPLIT by calling `subagents` or
finish-with-handoff by calling `finish`) — the role-curated `offered_tools` the
engine already captured when it built the acting completion. Building a new
one-shot seat, the way the barrier and every other effort consumer
(deepthink, associate, hire) does, would mean re-deriving that role/tool_set
narrowing — the one thing the allow-list seam exists to keep single.

**So the mechanism deviates on purpose, and the deviation is documented, not
hidden:** `SeatEscalator` push/pops the acting config's optional
`reasoning_effort_seat` attribute — the same plain attribute
`vllm_payload._effort_for` reads and `loop_barrier.barrier_seat_config` sets —
on the **LIVE config object** the acting completion closed over, for the
duration of the escalated point, restoring its exact prior state (present-
with-value vs absent) afterwards. It is a stack, so nested pushes are safe.

### `gate.repeat_failure` — the REPEATED repair turn

`escalated_gate_turn(ctx, gate, attempt)` is a context manager wrapping a
gate's bounded fix-turn. The FIRST repair (`attempt` below
`FIRST_REPEATED_ATTEMPT` = 2) keeps the seat's ordinary rung — unchanged,
byte for byte. A REPEATED repair (the second and later iterations of the
gate's `while report … and retries > 0` loop) escalates to
`resolve_spike("gate.repeat_failure")`'s `"medium"`. The deterministic signal
is the loop's own **iteration count** — nothing here inspects the failing
report, the failing tests, or any model text. At most once per gate per run.

**The unit of escalation is the repair ATTEMPT, not a single completion.** A
gate's fix-turn is itself a bounded mini-loop (`_TESTINTEGRITY_FIX_STEPS` = 6
/ `_AFFECTEDTESTS_FIX_STEPS` = 8 extra model turns in
`colleague/loop_constants.py`), so the ONE escalated replan covers up to that
many completions — the model may edit, run tests, and iterate inside its
single escalated attempt. The artifact records one `gate.repeat_failure`
`SpikeRecord` for that attempt (the point fired once); it does not count the
attempt's individual completions. Exactly one attempt per gate per run ever
escalates — `_fired` gates the rung itself, so third and later repair
attempts run back at the ordinary rung.

### `fillline.decision` — the DECLARING turn

`arm_fillline_decision(ctx)` escalates the turn that will DECLARE the
fill-line move (compact | split | finish-with-handoff), called where the
decision prompt is injected (`loop_context._offer_fillline`) — the fill-line
has no completion of its own to build a seat for (the honest limit
`fillline.design_seat_config` has documented since #416 t6). Its rung comes
from `SeatEscalator.fillline_rung()`, which calls
`colleague.fillline.design_seat_config` to read the design-site table's
`"xhigh"` — **this is the live consumer** the design-site table lacked before
this arc. `disarm_fillline_decision(ctx)` releases the escalation the moment
the declaration is recorded, so exactly the declaring turn — never the
compaction turn that may follow it — carries the rung. At most once per run,
even though the fill line re-arms per crossing (see
[capacity-standard.md](capacity-standard.md)).

**Unarmed** (`COLLEAGUE_EFFORT_SPIKES` unset): `make_escalator` returns `None`,
every function is a strict no-op, no attribute on the acting config is ever
touched.

## Effort decay after a spike (`colleague/effortdecay.py`, opt-in)

The shape the #484 discussion argued for — *decide → medium, then low, then
none … until the next reset* — built as a FIXED table keyed by an acting
turn's **offset from the last spike**, not by anything in the turn:

| offset since the last spike | rung |
|---|---|
| 1 | `low` |
| 2 and later | `off` (`DECAY_FLOOR`), until the next spike resets the clock |

**Resets are exactly the enumerated spike points** (`RESET_POINTS` IS
`SPIKE_POINTS`): the barrier, a repeated-gate escalation, the fill-line
declaring turn, the stall decision turn, and the start spike (stamped at
turn 1). Each spike record site calls
`loop_gateescalation.note_reset`, which stamps the run's current model-turn
count; `loop_gateescalation.decayed_turn` wraps each acting completion in
`loop.py`, computes `(this turn) − (last reset)`, and pushes the table's rung
through the SAME `SeatEscalator` the spike points use, popping it the moment
the completion returns. `loop.py` itself assigns no effort (the AST guard in
`tests/test_thinking_effort_boundary.py` still holds; `effortdecay.py` never
touches the attribute either).

**Opt-in:** `COLLEAGUE_EFFORT_DECAY=1` **and** `COLLEAGUE_EFFORT_SPIKES=1` —
decay without a reset trigger is meaningless, so either unset leaves the
surface inert and the run byte-identical. **Record:**
`TaskResult.effort_decay` = `{resets: [model-turn indices], turns: {rung: n}}`,
omit-when-empty. **This is convention change (8)** — the invariant now reads
"per enumerated point, or per fixed OFFSET from such a point, from a fixed
table"; it is recorded in CLAUDE.md and `thinking-effort.md` line 11, never
silently. **Honest limits:** the decay covers the main loop's acting
completions only (a gate's bounded fix-turn mini-loop runs at its own
escalated rung); v0 has one table with one named offset; measured in
`docs/live-testing.md` rows 74-77 (the off-floor and decay arms).

## The artifact field — `TaskResult.effort_spikes`

A list of `{"point": ..., "rung": ..., "seat": ...}` dicts
(`colleague.effortspikes.SpikeRecord.to_dict()`), one entry per point that
actually fired this run. **Omit-when-empty** serialization (mirroring the
`hires` field's convention): the key is absent from the JSON artifact when the
list is empty — including every unarmed run — so a pre-#484 artifact and an
armed-but-never-fired run are byte-identical to each other and to the
pre-#484 shape. **Absence of an entry for a given point on a finished run
reads as "did-not-fire"** — there is no separate off/false record.

## Opt-in + per-point overrides

- `COLLEAGUE_EFFORT_SPIKES=1` — the one arming switch for the whole surface
  (checked by `spikes_enabled()`); anything else (unset, `"0"`, empty, any
  other string) leaves it OFF.
- `COLLEAGUE_EFFORT_SPIKE_<POINT>` (point upper-cased, `.` → `_`, e.g.
  `COLLEAGUE_EFFORT_SPIKE_BARRIER_PRE_MUTATION`) — an explicit per-point rung
  override, re-validated through the closed ladder like the table row it
  replaces. An out-of-ladder override raises rather than silently falling
  back.

## Honest limits

- **At most once per point per run (v0).** The barrier fires once; each gate
  escalates once; the fill-line decision escalates once even across multiple
  crossings. Repeated firing within a run is explicitly out of scope for this
  arc.
- **The measurement contract is the reason this ships opt-in.** Per the spec,
  #484 is GATED on the four small fixes (#480-#483): the pre-registered
  null-hypothesis arm (low effort + the #482 importability check + the #480
  surfaced gate warning + one bounded fix turn) is compared against a flat
  `low` baseline and the barrier/rung arms. **Arming any spike by default
  requires the spike arm (C) to beat the cheap-feedback arm (B) on the same
  measurement** — this doc records the surface as built and opt-in; it does
  not itself constitute that evidence. **MEASURED (`docs/live-testing.md` rows
  70-73, spec `2026-09-01-measure-effort-spikes-484`): the barrier fires live
  (row 70 smoke; row 73 at step 21 after a 20-step survey, a 5,661-char plan
  naming the seams) and the run lands correct — but so did the flat-`low`
  feedback arm, twice, at 44% of the reasoning and 69% of the wall (rows
  71-72), so C did not beat A. Two pre-registered rules apply separately: #482's
  three-reading rule (feedback arm vs the planning-turn arm — A vs C, which
  DID run) reads "same correctness at lower spend → #480+#482 are the
  fix"; the spec's default-arming rule (C must beat B) could NOT run because
  arm B was VOID twice — so it licenses nothing and the default stays OFF.
  The C-vs-A figures are #482's comparison, not a substitute for C-vs-B.** The v0 trigger is the reason B could not run: with
  `run_command` a mutating tool BY NAME, a model that opens its survey with a
  shell command (3 of 5 dispatches on that brief) can never reach the barrier
  — a trigger follow-up is filed from the #484 disposition (#487, fixed in
  the effort-floor-and-decay arc). **Round 2, rows 74-77 (the off floor and
  the decay):** an `off` floor alone never crosses from survey to action (row
  74: 91 turns of reading, zero files; row 75: the same with the barrier armed
  — a spike that waits for the first write request cannot reach a run that
  never makes one). `low` + decay (row 76) lands correct but spends the most
  of any arm, because the spend sits in the pre-spike survey the decay cannot
  touch. **The full stack on the off floor (row 77: `start.first_turn`, two
  `stall.no_write` decision turns, the barrier, then the decayed tail) lands
  a correct branch at 24,279 reasoning chars in 1,286 s — 16% of the
  flat-`low` arm's reasoning and 41% of its wall — meeting the pre-stated
  win condition at n=1.** The lever was the count-keyed stall turn forcing
  the crossing, after which `off` executed the plan. Still opt-in; a G arm
  (off + stall only) would separate the start spike's share.
- **`gate.repeat_failure` and `fillline.decision` share one mechanism
  (`SeatEscalator`) that mutates a live config object rather than building a
  seat** — a deliberate deviation from every other effort consumer's pattern,
  documented here and in the module docstring rather than hidden; the
  push/pop discipline is what keeps it safe to nest.
- **No tools-off seat for the gate/fillline points** — both need the run's
  real tool surface, so unlike the barrier (which builds a genuinely tools-off
  completion) these two points still offer the acting completion's ordinary
  tools; only the reasoning rung changes.

## See also

- [`docs/features/thinking-effort.md`](thinking-effort.md) — the invariant
  this surface amends (the amendment note at line 11).
- [`docs/features/deepthink.md`](deepthink.md) — the enumerated escalation
  precedent (`test_deepthink_boundary.py`'s descriptor-list style, mirrored by
  `tests/test_effortspikes_boundary.py`).
- [`docs/features/capacity-standard.md`](capacity-standard.md) — the fill-line
  decision the third spike point escalates.
- [`docs/features/work-and-loop.md`](work-and-loop.md) — the loop the barrier
  and gate-escalation modules hook into.
