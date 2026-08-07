# Presence default everywhere: senses is the middle manager on every front

**Colleague's middle-manager presence is now its default state on every front.**
In the interactive session, the `colleague talk` attach, a background run, the
mesh resident, and a one-shot `colleague work`, you keep conversing with **senses**
(Gemma) while **cortex** (Qwen) does the actual repo work — senses acknowledges
your request, keeps you posted on cortex's progress, relays your words to cortex,
and answers conversationally. This is the default experience, not an opt-in, and
it holds everywhere you meet colleague.

This is the **FOURTH sanctioned increment** at colleague's router-exclusion line
(after the dual-model deepthink escalation, the cortex/senses role split, and the
senses live-presence + voice arc). The fixed responsibility boundary still holds —
**cortex acts; senses perceives, presents, and now converses proactively as an
agent** — with no automatic task→model routing.
[#276](https://github.com/agentculture/colleague/issues/276) (senses-direct) stays
parked: senses never does the task itself, and never decides cortex isn't needed.
It closes [#300](https://github.com/agentculture/colleague/issues/300) (the
resident + talk parity and tts follow-ups from the talking-to-one arc) and goes
beyond it.

## The senses agentic loop — coordination-only, tools-off

Senses gets its own bounded *agentic loop* (`colleague/senses_loop.py`
`SensesLoopDriver`). It is what makes this the fourth increment rather than a
deepening — but it is sanctionable because its "tools" are a **curated,
coordination-only** move surface, never repo tools. The seven enumerated moves (`narrate` joined in the session-streaming arc, display-only)
(`colleague/senses_moves.py`):

| Move | Meaning |
|---|---|
| `dispatch_to_cortex` | hand the task to cortex, carrying the operator's verbatim words |
| `guide_cortex` | inject mid-run guidance into the running cortex work item |
| `read_flight` | read the run's flight-feed / status |
| `reply_to_operator` | say something conversational to the operator |
| `clarify` | ask the operator a clarifying question before dispatching |
| `wait` | do nothing this turn |

Cortex remains the ONLY mind that touches the repo. Repo work is always
dispatched to cortex; senses converses about the run and relays, but never
performs the task.

**Nothing tool-shaped ever goes on the wire.** Because the reference rig's senses
model has no server-side tool parser, a "move" is a small JSON object the model
writes, parsed from an ordinary **tools-off** completion
(`make_complete(senses_config, tools=[])`). `senses_moves.py` imports neither
`subprocess` nor any `ToolExecutor` and constructs no tool schema — pinned by an
AST-precise boundary test. The `SensesMoveExecutor` refuses any move name outside
the enumerated seven (a hallucinated move degrades to a recorded no-op, never
raises), so widening the surface requires a new re-spec at the router-exclusion
line.

## One pump, every front

The `colleague/presence_engine.py` `PresenceEngine` is the ONE front-agnostic pump
every surface shares. It owns the update cadence (step/phase-based, never a
clock) and rendering, and delegates all rung routing to the loop driver, driving
every beat through injected `PresenceIO` callbacks — no TTY, thread, or clock is
assumed. Each front supplies its own IO:

| Front | Renders to | Operator input | Notes |
|---|---|---|---|
| **session** (`session.py`) | the cockpit transcript (`senses:` lines) | live stdin (TTY) | live talk rides the loop; ack/updates keep the fixed-beat methods, now firing off-TTY too |
| **talk attach** (`talk.py`) | the terminal + flight chat log | live REPL stdin | ack/context on attach + proactive updates between turns |
| **background** (`_presence_sink.py`) | the flight plane (readable by an attach) | via the flight guidance channel | rides the work-path progress sink; no thread/daemon |
| **one-shot work** (`work.py`) | **stderr** (`emit_diagnostic`) | none | `--json` stdout stays machine-parseable |
| **resident** (`appserver.py`) | reply-to-origin mesh messages | inbound messages | operator-only (c19); cap-bounded |

## The degradation ladder

`loop` (the senses agentic loop, the default when armed) → `beats` (the fixed-beat
lane — intake/ack/update/talk as shipped) → `off` (cortex-only). The rung resolves
through the same precedence chain as every other knob
(`colleague/config.py` `resolve_presence_rung`): explicit `--cortex-only` >
`COLLEAGUE_PRESENCE` env > `.colleague/config.json` `"presence"` > default `loop`
when senses is armed. A loop that degrades mid-run drops to `beats` for the next
boundary and records the transition; senses unresolved is `off` (byte-identical).

## Byte-identical guarantees + the one deliberate pin-break

- **Senses unarmed** (no senses resolved) is byte-identical on every front — the
  default arms only when there is something to talk to; `resolve_presence_rung`
  returns `off`.
- **`--cortex-only`** (flag / `COLLEAGUE_PRESENCE=off` / config) fully disarms the
  lane on every front.
- **The one deliberate, recorded convention break (c19):** an off-TTY / piped /
  `--no-tui` session with senses ARMED now carries labeled `senses:` ack + update
  lines (presence is the default on every front, no longer colour-TTY-only). The
  three broken byte-identical session tests were updated in the SAME change with a
  stated reason and are ENUMERATED in
  `tests/test_presence_pin_breaks.py`, never silently changed. The `--json`
  contract is never broken: presence rides labeled lines to stderr, so a piped
  stdout parses as the same JSON schema as today (live e2e pinned).

## The artifact contract

Every beat lands on `TaskResult.senses` (`colleague/contract.py` `SensesBlock`)
in ONE shared shape regardless of front (drift-tested), so the same task run on
any front yields directly comparable artifacts: loop turns as
`SensesRecord(point="senses-loop:<move>")`, kind-ed `chat` entries (`ack` /
`update` / `clarify` / implicit `talk`), and `guide_cortex` relays as
`injections`. Per-front livecheck classifiers (`colleague/livecheck.py`
`classify_*_presence_check`, one per `PRESENCE_FRONTS`) grade the beat sequence —
ack + grounded narration (required), guidance relay (reported) — from feed +
artifact alone, never a model self-report.

## Live-proven

Live-proven 2026-07-08 on the real rig (`docs/live-testing.md`) — cortex =
Qwen3.6-27B (**tool-calling**, closing the long-standing #66 gap), senses =
Gemma-4-12B, both dialed at the gateway origin. A one-shot `colleague work`
with presence default-on: Qwen drove the tool loop end-to-end (list_dir →
read_file → edit_file → finish, committed the change), while Gemma acknowledged
and narrated real progress grounded in the feed ("Cortex has completed step 2 and
read greet.py"; "Cortex is at step 4, verifying the edits"). The `--json` stdout
stayed parseable, the chat folded onto the artifact, and
`classify_work_presence_check` graded it PASSED from evidence alone.

## Honest limits

- **Small-model move reliability.** A 12B senses model occasionally emits a
  near-miss move name at an early empty-feed boundary; the executor refuses it
  (recorded, no-op) and the loop self-corrects once real feed accumulates. The
  refusals are honest, not silent.
- **Dispatch-ack in senses' own words is best-effort.** When a dispatch move
  authors no `ack` field, the ack degrades to the fixed dispatch notice ("taking
  your request to cortex now.") — honest, never a fabricated understanding.
- **Resident clarify-first is timeout-to-dispatch (v1).** Under the async mesh
  transport a clarify question is asked but work dispatches immediately (clarify
  can never withhold work); richer round-trip threading is a follow-up.
- **tts narration SKIPped** while the rig's speech proxy 502'd
  (lobes-cli#89/#92) — the code was complete and degraded clean. **2026-07-22:
  the proxy is fixed and `run_presence_narration_check` PASSES live** (a real
  presence-beat `.wav`; `docs/live-testing.md` dated section, closes #304).
- **Cadence + latency numbers are conservative defaults**, parked pending live
  tuning (`COLLEAGUE_SENSES_UPDATE_STEPS`/`_PHASE`/`_CAP`,
  `COLLEAGUE_SENSES_LOOP_CAP`).
- **The gateway advertises a dead `:8000` endpoint** (lobes-cli#92), so a
  lobes-discovered senses may need an explicit `COLLEAGUE_SENSES_BASE_URL` until
  the rig side is fixed.

## Spec + plan

- `docs/specs/2026-07-08-colleague-s-middle-manager-presence-is-now-its-def.md`
- `docs/plans/2026-07-08-colleague-s-middle-manager-presence-is-now-its-def.md`
