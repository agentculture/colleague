# Build Plan — Talking to colleague now feels like talking to one person: senses. You speak with senses (Gemma) directly — it acknowledges your request in its own words, hands the work to cortex (Qwen), keeps you posted with proactive progress updates while cortex drives, relays your mid-run guidance, and delivers cortex's answer back conversationally. A middle manager with senses' emotional intelligence fronting cortex's logical intelligence — and the task itself is always done by cortex.

slug: `talking-to-colleague-now-feels-like-talking-to-one` · status: `exported` · from frame: `talking-to-colleague-now-feels-like-talking-to-one`

> Talking to colleague now feels like talking to one person: senses. You speak with senses (Gemma) directly — it acknowledges your request in its own words, hands the work to cortex (Qwen), keeps you posted with proactive progress updates while cortex drives, relays your mid-run guidance, and delivers cortex's answer back conversationally. A middle manager with senses' emotional intelligence fronting cortex's logical intelligence — and the task itself is always done by cortex.

## Tasks

### t2 — NEW pure cadence policy module (colleague/presence.py): clock-free, thread-free decision helper for proactive updates — fire on phase change and/or every N steps (env-tunable), with a per-run cap; hitting the cap is a recordable signal, never silent

- covers: h4
- acceptance:
  - pure unit tests: fires on phase-change and every-N boundaries, respects the per-run cap, cap-hit yields a recordable signal; the module imports no threading/clock (boundary-test pinned)
  - cadence knobs resolve via env (COLLEAGUE_SENSES_UPDATE_* naming) with conservative defaults; the concrete numbers are recorded as parked-pending-live-tuning

### t5 — Artifact contract (colleague/contract.py + the session fold path): TaskResult.senses records the ack and each proactive update (point-labeled SensesRecords plus chat entries with a role/kind), omit-when-None so a run without the lane serializes byte-identically; the whole operator-senses exchange is reconstructable from the artifact alone

- covers: c8, h14
- acceptance:
  - a proof-shaped fixture asserts TaskResult.senses contains the ack record, at least one proactive-update record, and the folded chat — machine-checkable with no human judgment
  - runs without the lane serialize byte-identically (e2e shape test unchanged)

### t1 — Ack rides intake (colleague/senses.py): run_senses_intake returns a senses-authored acknowledgment line alongside the ContextPacket in the SAME completion (zero extra calls — the spec's ack-shape decision); a degraded intake degrades the ack to a fixed dispatch notice, never fabricated understanding

- depends on: t5
- covers: c9, h2
- acceptance:
  - one wire call returns both packet and ack (unit-pinned: exactly one make_complete invocation); the ack derives only from packet fields — a test pins that no ack claims an understanding absent from the packet
  - degraded intake yields the fixed dispatch-notice ack; senses unarmed yields no ack and stays byte-identical

### t3 — Proactive update lane (colleague/senses.py): run_senses_update(feed_tail, packet, history) — tools-off narration grounded STRICTLY in the live feed tail, structural sibling of run_senses_talk (make_complete(senses_config, tools=[]), windowed to senses' OWN budget, degrade-never-raise), returning an advisory {update, latency, tokens, degraded} record

- depends on: t1
- covers: c10, h3
- acceptance:
  - the completion carries no tool schema and the feed window respects senses' context_budget (unit-pinned); a grounding test feeds a fabricated-status reply and asserts it is rejected/flagged, mirroring run_senses_talk's grounding contract
  - an update never advances step_count or adds a phantom step (the #206 invariant, test-pinned); senses unarmed returns None cleanly

### t4 — Conversation continuity (colleague/senses.py): intake/talk/update/speak-back accept an optional rolling chat history threaded into the completion, windowed to senses' OWN budget with the operator's original request verbatim; absent history is byte-identical

- depends on: t3
- covers: c11, h5
- acceptance:
  - history is windowed to senses' context_budget and the verbatim-original invariant holds (ContextPacket.original untouched by windowing, test-pinned)
  - calls without history are byte-identical (existing senses tests unchanged); a session with senses absent writes NO chat history

### t6 — Session middle-manager wiring (colleague/cli/_commands/session.py): render the senses ack BEFORE cortex's first step, fire cadence-gated proactive updates at the EXISTING progress-sink boundaries via the t2 policy + t3 lane (labeled senses lines joining the conversation surface; the raw cockpit feed stays available — senses augments, never hides), keeping off-TTY / piped / --no-tui / --cortex-only / senses-unarmed byte-identical

- depends on: t1, t2, t3, t5
- covers: c2, c4, c5, h9
- acceptance:
  - on a running work line the transcript shows the ack before the first cortex step and at least one labeled proactive update at a sink boundary (integration test on mock with a scripted sink)
  - off-TTY / piped / --no-tui / --cortex-only / unarmed paths are byte-identical to today (test-pinned); updates fire only from existing sink boundaries — no new threads, no clock

### t7 — Clarify-first + session-side continuity (colleague/cli/_commands/session.py): on low-confidence intake senses MAY ask clarifying questions before dispatching (senses judges, more than one allowed, bounded by a generous env-tunable ceiling); an explicit operator go-word dispatches unconditionally; the session threads the rolling history into every senses call and every exchange folds into TaskResult.senses.chat; the dispatched instruction always carries the operator's verbatim words — clarify refines the packet, never rewrites the request

- depends on: t4, t6
- covers: c19, h8
- acceptance:
  - a low-confidence intake asks; an explicit go-word dispatches immediately regardless (test); consecutive questions are bounded by the env-tunable ceiling (loop-proofing pinned)
  - every clarify exchange lands on TaskResult.senses.chat and the final dispatched instruction contains the operator's verbatim request (test-pinned)

### t8 — Structural proofs + byte-identical pins (tests only): the task instruction always reaches cortex un-shortcut; no senses output is ever used as the TaskResult.summary source (the relay path is the ONLY senses influence on the run); the SAME work line run cortex-only and split yields the same TaskResult core (summary/status/steps); no new threading/clock imports outside the sanctioned list; a session with senses unresolved is byte-identical to today

- depends on: t6, t7
- covers: c6, c7, h1, h6, h13
- acceptance:
  - a structural test pins that senses modules never produce TaskResult.summary and that the instruction reaching the engine is the operator's verbatim request (clarify refinements recorded alongside, never rewriting it)
  - boundary tests pin threads/clock/subprocess allow-lists unchanged; cortex-only vs split TaskResult-core equality is test-pinned on mock; #276 senses-direct stays structurally impossible (no code path answers the task from senses)

### t9 — Livecheck proof + latency (colleague/livecheck.py lane + docs/live-testing.md rows): ONE recorded real run showing every announcement beat — ack, dispatch, at least one grounded proactive update, relay, conversational answer — with senses front latency measured against the conversational target (low-single-digit seconds; ~2.3s p50-under-load baseline) and a long-run transcript where progress is legible from senses lines alone while the raw feed stays available; every failing lane records FAIL/SKIP with the reason, never a synthesized pass

- depends on: t6, t7
- covers: c1, c8, c16, h7, h11, h12
- acceptance:
  - livecheck grades each beat from recorded evidence: the session transcript shows the lines AND TaskResult.senses records ack/update/chat; latencies are wall-clock measurements vs the target, never estimates
  - the smoothness proof is a recorded long-run transcript legible from senses lines alone; rows land in docs/live-testing.md with honest FAIL/SKIP on any unproven lane

### t10 — Docs + scope line + named follow-ups: CLAUDE.md architecture part recording this as a DEEPENING of the third sanctioned router-exclusion increment (same fixed boundary — cortex acts, senses perceives/presents/converses; no new model consumers, #276 stays parked); a docs/features feature doc incl. degrade paths + the parked cadence numbers; the before-state cited to today's code (intake/speak-back/talk exist in colleague/senses.py, no ack turn, no unprompted-update path, run_senses_talk threads no chat history); mesh-resident + 'colleague talk' parity and tts narration recorded as NAMED follow-ups, never implied shipped

- depends on: t8, t9
- covers: c3, h10
- acceptance:
  - the CLAUDE.md scope section records the deepening with the fixed-boundary language and the drift-guard doc tests pass
  - the feature doc records degrade paths + parked cadence numbers; the parity and tts follow-ups are filed/NAMED with issue references

## Risks

- [unknown_nonblocking] Update cadence concrete numbers (every-N steps, per-run cap) stay parked pending live tuning — conservative env-tunable defaults ship v1 (the spec's operator decision) (task t2)
- [unknown_nonblocking] Proactive update calls are synchronous at sink boundaries (the session is thread-free): each fired update adds ~1-2s senses latency at that boundary; the cadence cap bounds total added wall-clock, and live tuning may lower the default cadence (task t6)
- [unknown_nonblocking] Clarify-judgment quality on Gemma (over- or under-asking on low-confidence intake) — the explicit go-word is the guaranteed dispatch path and the env-tunable ceiling bounds loops; a misjudged clarify is visible in TaskResult.senses.chat, never silent (task t7)
- [follow_up] Mesh-resident + 'colleague talk' surface parity for ack + proactive updates (session-first in v1)
- [follow_up] tts voice narration of proactive updates over the existing [voice] extra
