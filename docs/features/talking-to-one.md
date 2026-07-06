# Talking to one: senses is the middle manager

**Talking to colleague now feels like talking to one person.** In the
interactive session, senses (the tools-off front door) becomes a middle
manager: it acknowledges the operator's request in its own words, hands the
work to cortex, keeps the operator posted with proactive progress updates
while cortex drives, asks a clarifying question first when the request is
genuinely unclear, and delivers cortex's answer back conversationally. Cortex
still does the entire task — senses fronts it, never substitutes for it.

This is a **deepening** of the third sanctioned increment at colleague's
router-exclusion line (senses live presence + voice), not a new surface: the
same fixed responsibility boundary holds — cortex acts, senses
perceives/presents/converses — with no new model consumers and no automatic
task→model routing. [#276](https://github.com/agentculture/colleague/issues/276)
(senses-direct) stays parked: senses never answers the task itself and never
decides cortex isn't needed.

## Before this arc

At the arc's base commit (`fb1bf2c`), `colleague/senses.py` already shipped
intake (`run_senses_intake`), speak-back (`run_senses_speakback`), and the
concurrent talk lane (`run_senses_talk`) — but only *reactively*:

- **No ack turn existed.** Intake returned only a `ContextPacket`; nothing
  spoke before cortex's first step, so a work line started in silence.
- **No unprompted-update path existed.** The operator watched the raw cockpit
  feed; senses never narrated progress unless directly asked via the talk lane.
- **`run_senses_talk` threaded no chat history.** Every talk exchange was
  stateless — a message and a reply, with no memory of the prior exchange in
  the same session.

Each of these is directly verifiable by reading `colleague/senses.py` at that
commit: no `ack` field on `ContextPacket`, no `run_senses_update` function,
and `run_senses_talk`'s signature carrying no history parameter.

## The beats

One continuous conversation, in order: acknowledge, dispatch, narrate
proactively, clarify first when warranted, relay guidance, answer
conversationally. The task itself is always done by cortex.

### Acknowledgment — rides the intake completion

The acknowledgment is **not a separate model call**. `run_senses_intake`
(`colleague/senses.py`) asks the senses model for one more JSON field, `ack`,
alongside `interpretation`/`confidence`/`task_type`/`omissions` — the SAME
completion, zero extra calls, zero extra latency (the spec's ack-shape
decision). `_coerce_ack` strips and hard-caps the reply (500 characters); a
missing, empty, or non-string `ack` degrades to `None`, never fabricated.

The session renders the ack before cortex's first step
(`colleague/cli/_commands/session.py` `_render_ack`): a present `packet.ack`
renders verbatim, and a missing/degraded ack renders the FIXED dispatch notice
`"taking your request to cortex now."` — a plain fact, never invented
understanding. Every spoken ack is recorded as a `kind="ack"` chat entry.

### Proactive updates — cadence-gated narration

While cortex works, senses narrates progress **unprompted** at existing
progress-sink boundaries — no new thread, no clock. The cadence decision is a
pure, clock-free policy module, `colleague/presence.py`:

- fires on a **phase change** (`COLLEAGUE_SENSES_UPDATE_PHASE`, default on;
  set to `0` to disable) and/or **every N steps**
  (`COLLEAGUE_SENSES_UPDATE_STEPS`, default 8),
- bounded by a **per-run cap** (`COLLEAGUE_SENSES_UPDATE_CAP`, default 4) so a
  chatty senses can never dominate the feed or the senses budget,
- hitting the cap is **recorded, never silent** — one log line plus one
  `{"kind": "update", "capped": true}` chat entry the first time the cap
  binds.

Each fired update calls `run_senses_update(feed_tail, packet, ...)`
(`colleague/senses.py`), the structural sibling of `run_senses_talk`: tools-off
(`make_complete(senses_config, tools=[])`), windowed to senses' own context
budget, and grounded STRICTLY in the live flight-feed tail — the system prompt
instructs senses to quote or paraphrase real feed lines, say plainly when
nothing new has happened, and never invent progress, files, or results not
present in the feed. A fabricated-status reply is a test failure, mirroring
`run_senses_talk`'s grounding contract. An update never advances
`step_count` or adds a phantom step (the #206 invariant) — narration is
presentation, not work.

A degraded update call still counts toward the cap and still records — an
attempt that consumed senses budget is accounted for honestly whether or not
it produced text.

### Clarify-first

On a low-confidence intake WITH omissions, senses MAY ask a clarifying
question **before** dispatching to cortex — more than one is allowed, judged
by senses itself from the packet it authored (`colleague/presence.py`
`should_clarify`, wired in `colleague/cli/_commands/session.py`
`_maybe_clarify`):

- `COLLEAGUE_SENSES_CLARIFY_CONFIDENCE` (default `0.45`) — intake confidence
  below this floor, together with a non-empty `omissions` list, MAY trigger a
  clarify question,
- `COLLEAGUE_SENSES_CLARIFY_MAX` (default `3`) — a generous, env-tunable
  ceiling on consecutive questions (loop-proofing, not a UX cap; `0` disables
  clarify entirely).

Clarification can **never withhold work**: an explicit operator go-word
(`"go"`, `"go ahead"`, `"proceed"`, `"dispatch"`, `"just go"`, `"run it"`,
`"ship it"`, `"do it"` — case/punctuation-insensitive) dispatches
unconditionally, and so does an empty answer, EOF, or a missing input source.
Each answer re-runs intake over the instruction plus the operator's verbatim
clarification, so clarify **refines** the packet — the final dispatched
instruction always still contains the operator's original verbatim words, plus
their own follow-up answers, never a rewrite. Every clarify exchange is
recorded on the per-line chat (`kind="clarify"`) and the rolling history.

### Conversation continuity — rolling history

`colleague/cli/_commands/session.py` threads a session-lifetime rolling
history (`_history_append`) into every senses call — intake, updates, clarify,
talk, and speak-back all fold in prior exchanges (`colleague/senses.py`'s
`_fold_history`, windowed to senses' OWN context budget, oldest entries
dropped first when it doesn't fit). The operator's original request always
stays verbatim on the packet regardless of this windowing. History is capped
at the last 50 entries as a memory bound (windowing to budget happens
senses-side, at call time). It survives across work lines within one session
(only the per-work-line ack/update/clarify chat resets between lines,
`_reset_presence_lane`) and is gated on the presence lane being enabled at all
— an unarmed session (off-TTY / `--no-tui` / piped / `--cortex-only` / no
senses) never accumulates history, so every senses call it makes stays
byte-identical to before this arc.

## The artifact contract

The whole operator-senses exchange is reconstructable from
`TaskResult.senses` alone (a `SensesBlock`, `colleague/contract.py`):

- `packet.ack` — the senses-authored acknowledgment line, or `None` when
  degraded.
- `records` — the ordered list of `SensesRecord` entries, including
  `senses-update` points (one per fired proactive update, degraded or not).
- `chat` — the folded exchange list, each entry optionally carrying a `kind`
  of `"ack"`, `"update"`, `"clarify"`, or `"talk"` (absent `kind` implies
  `"talk"`, the pre-existing live-presence shape) — so ack, updates, clarify
  exchanges, and talk-lane messages all land in ONE ordered list.

A run with no senses front door leaves `TaskResult.senses` at `None`
(omit-when-None); a run with senses armed but the middle-manager lane never
triggering (e.g. `--cortex-only`) leaves the block at its pre-arc shape, no
`chat`/`injections` keys — both byte-identical to the arc before this one.

## Degrade paths

Every beat degrades honestly instead of failing the run:

- **Degraded intake** → the ack renders the FIXED dispatch notice
  (`"taking your request to cortex now."`), never a fabricated understanding;
  the raw instruction still reaches cortex untouched.
- **Degraded update** → still counts toward the cadence cap and still records
  (a `SensesRecord` with `degraded=True`); nothing renders in the transcript
  for that attempt.
- **Senses unarmed / off-TTY / piped / `--no-tui` / `--cortex-only`** → the
  whole middle-manager lane is a strict no-op: no ack, no updates, no
  clarify, no history accumulation — byte-identical to a session that
  predates this arc.

## Live-testing

Recorded live on the real rig, 2026-07-06 (`docs/live-testing.md` rows 24-25):

- **All beats passed** — `test_vllm_live_talking_to_one.py` drove the real
  session path: Gemma (senses) acknowledged in its own words before Qwen
  (cortex)'s first step, one proactive update rendered grounded mid-run, and a
  conversational speak-back answer closed the run. Three `senses:` transcript
  lines, the chat folded, the whole exchange machine-checked from the artifact
  plus the transcript by `colleague/livecheck.py`'s
  `classify_middle_manager_check` — no human judgment required. Full run:
  15.69s.
- **Front latency measured** — median senses turn **0.83s** over 3 turns, max
  3.52s (target: median < 3s), wall-clock from `SensesRecord.latency`, never
  estimated.

## Honest limits

- **The v1 surface is the interactive colour-TTY session only.** Mesh-resident
  and `colleague talk` parity for the ack + proactive-update beats is a
  **named follow-up**, not shipped here (see below).
- **Cadence numbers are conservative defaults, parked pending live tuning** —
  `COLLEAGUE_SENSES_UPDATE_STEPS`/`_PHASE`/`_CAP` and
  `COLLEAGUE_SENSES_CLARIFY_CONFIDENCE`/`_MAX` are env-tunable precisely
  because the shipped defaults are a starting point, not a tuned constant.
- **Update calls are synchronous at sink boundaries** — the session is
  thread-free, so each fired update adds roughly 1-2s of senses latency at
  that boundary; the per-run cap bounds the total added wall-clock.
- **tts narration of proactive updates is a follow-up** on the existing
  `[voice]` extra, not built here — updates are text-only in v1.
- **The rig's advertised role-endpoint regression** (`docs/live-testing.md`
  row 26) means a lobes-discovered senses may need an explicit
  `COLLEAGUE_SENSES_BASE_URL` set until the rig/lobes-cli side is fixed — see
  the named follow-up below for the precise shape.

## Named follow-ups

Recorded here so they are named, not implied shipped. Filed: items 1-2 as
[colleague#300](https://github.com/agentculture/colleague/issues/300), item 3
as [lobes-cli#92](https://github.com/agentculture/lobes-cli/issues/92).

1. **Mesh-resident + `colleague talk` surface parity for ack + proactive
   updates.** The v1 middle-manager lane (ack before dispatch, cadence-gated
   proactive updates, clarify-first) is built into the interactive
   `colleague session` only. The mesh-resident appserver
   (`colleague/resident/appserver.py`) and the `colleague talk <task-id>`
   attach verb (`colleague/cli/_commands/talk.py`) still only carry the
   live-presence arc's reactive talk lane — no ack, no unprompted updates, no
   clarify. Bringing the same beats to those two surfaces is session-first by
   design (the spec's v1 decision) and is a named parity follow-up.
2. **tts voice narration of proactive updates.** Proactive updates render as
   text (`senses:` transcript lines) only. Speaking them aloud over the
   existing `[voice]` extra (`colleague/voice.py` `synthesize`, the same `tts`
   role the live-presence arc already wires) is a follow-up, not v1.
3. **Lobes advertised-endpoint regression (file on lobes-cli).** The gateway's
   `/capabilities` currently advertises `endpoint: http://<host>:8000` with
   `ready: true` for every role, but `:8000` 404s from a client — only the
   gateway origin (`:8001/v1` on the reference rig) actually serves requests.
   Colleague's per-role dialing (task t19, closing lobes-cli#87) trusts that
   advertisement, so a lobes-discovered senses degrades **instantly**
   (roughly 0.002s per call — the request never leaves the process, it just
   fails to connect) rather than answering. The reference-rig workaround is
   to set `COLLEAGUE_SENSES_BASE_URL` explicitly to the gateway origin (the
   operator-declared config rung outranks lobes discovery), until the rig or
   lobes-cli fixes the advertised `endpoint` value. This is a regression of
   the shape lobes-cli#87 already tracked once.

## Spec + plan

- `docs/specs/2026-07-05-talking-to-colleague-now-feels-like-talking-to-one.md`
- `docs/plans/2026-07-06-talking-to-colleague-now-feels-like-talking-to-one.md`
