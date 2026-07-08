# Build Plan — Colleague's middle-manager presence is now its default state on every front: in the session, the talk attach, a background run, and the mesh resident, you keep conversing with senses while cortex works - senses acknowledges your request, keeps you posted on cortex's progress, and relays your words to cortex, everywhere you meet colleague.

slug: `colleague-s-middle-manager-presence-is-now-its-def` · status: `exported` · from frame: `colleague-s-middle-manager-presence-is-now-its-def`

> Colleague's middle-manager presence is now its default state on every front: in the session, the talk attach, a background run, and the mesh resident, you keep conversing with senses while cortex works - senses acknowledges your request, keeps you posted on cortex's progress, and relays your words to cortex, everywhere you meet colleague.

## Tasks

### t1 — Coordination move protocol + executor (new colleague/senses_moves.py): enumerate the senses loop's six coordination moves - dispatch_to_cortex, guide_cortex, read_flight, reply_to_operator, clarify, wait - as a prompted-JSON move protocol over the existing tools-off completion seam (NO tool schema ever on the wire), plus a SensesMoveExecutor that executes exactly that list

- covers: c21, h20
- acceptance:
  - The move list is enumerated in one place; the executor refuses any other move name even when the model emits one (hallucinated move degrades to a recorded no-op reply, never raises)
  - Structural boundary test: senses_moves.py imports no subprocess and no repo ToolExecutor; every senses completion still goes out via make_complete(senses_config, tools=[]) - a wire-level test pins that no senses request carries a tool schema
  - Malformed/truncated JSON move parsing degrades to reply-to-operator with the raw text, never a crash - unit-tested with garbage inputs

### t3 — Artifact + published contract: SensesBlock carries the loop-turn records and kind-ed chat identically across fronts (colleague/contract.py + docs/contract.md), omit-when-empty preserved

- covers: c13, h6
- acceptance:
  - One shared SensesBlock shape serves all fronts - a drift test asserts docs/contract.md matches TaskResult.to_dict for the senses block, and no front-specific record schema exists
  - A run with no presence lane yields a byte-identical artifact (omit-when-empty pinned)
  - Shape-equality test: the same fake task driven via two different fronts yields SensesBlocks with identical schema (fields/kinds), differing only in values

### t4 — Default-on config + off-switch wiring (colleague/config.py): the presence lane arms by default whenever senses resolves, on every front, with no extra flag; --cortex-only / env / config disarms everywhere

- covers: c3, h1
- acceptance:
  - With senses resolved (explicit config or lobes), the lane is armed on session, talk, background, resident, and one-shot work with zero additional flags - resolution test per front
  - The off switch works on every front (flag/env/config precedence test) and senses-unarmed remains byte-identical everywhere (nothing to talk to = pre-arc behaviour)
  - The selected ladder rung (loop / beats / off) is resolvable and recorded; default is loop when armed

### t5 — Senses loop core (new colleague/senses_loop.py): a bounded turn pump - each boundary event (operator input, cadence tick, feed change) yields at most a capped number of senses completions whose JSON moves are executed by the t1 executor; records every turn

- depends on: t1, t3
- covers: c22, h15, c2, h10
- acceptance:
  - Per-boundary completion cap (default 2) and senses' own context budget are enforced; a loop turn is windowed to the senses budget via the existing count_tokens seam
  - Degradation ladder test-pinned rung by rung: loop degraded mid-run -> fixed-beat lane handles the next boundary; senses unarmed -> cortex-only; each rung transition recorded on the artifact, never silent
  - The operator's request text reaches cortex verbatim on every rung (dispatch_to_cortex carries the verbatim words; relay refines, never rewrites) - pinned by test
  - Every loop turn lands as a SensesRecord + kind-ed chat entry (t3 shapes); a run where the loop never fires leaves the artifact byte-identical

### t6 — Presence engine (new colleague/presence_engine.py): ONE front-agnostic pump shared by every surface - drives ack/update/clarify/talk beats and the t5 senses loop through injected IO callbacks (input poll, renderer, guidance appender, flight handles); the session's lane logic is extracted here WITHOUT rewiring session.py (that is t7)

- depends on: t5
- covers: c4
- acceptance:
  - The engine drives all beats through injected callbacks with no TTY, thread, or clock assumption - unit-tested end-to-end with fake IO, including cadence caps and the capped-is-recorded rule
  - Both lanes live behind it: senses-loop lane (default when armed) and fixed-beat lane (the ladder's fallback rung), selected per t4 config
  - Session, talk, and resident adapters can consume it without importing each other (import-graph test)

### t7 — Session front adoption (colleague/cli/_commands/session.py): the interactive session pumps the presence engine with the senses loop default-on when armed; non-TTY/piped sessions now carry labeled 'senses:' lines too (the deliberate c19 pin-break), --cortex-only stays byte-identical pre-arc

- depends on: t5, t6
- covers: c4, c2
- acceptance:
  - TTY session: all beats fire via the engine; existing talking-to-one behaviour preserved (ack before first step, grounded updates, clarify-first, go-word dispatch)
  - Non-TTY/piped session: presence renders as plain labeled lines (no ANSI), every broken byte-identical test updated in the SAME change with a stated reason
  - --cortex-only (flag/env/config) and senses-unarmed remain strict no-ops (byte-identical pins kept)

### t8 — Talk-attach parity (colleague/cli/_commands/talk.py): 'colleague talk <task-id>' renders senses' ack/context on attach and streams cadence-gated proactive updates live between REPL turns, pumping the same presence engine

- depends on: t5, t6
- covers: c11, h4
- acceptance:
  - On attach, the REPL renders the run's ack/context (from the flight plane state) before the first prompt
  - Proactive updates render at existing poll boundaries with no new thread; a boundary where no update fired renders nothing (never a fabricated status line)
  - Senses-unarmed degrades to today's watch + raw-guide REPL, byte-identical

### t9 — Background presence (colleague/background.py + the work-path progress sink): a background run with senses armed writes ack + cadence updates onto the file-based flight plane at existing sink boundaries, so an attached talk REPL renders them live and the artifact records them

- depends on: t5, t6
- covers: c12, h5
- acceptance:
  - Beats land on the flight plane (feed/chat files) with no TTY, no new thread, no socket/daemon (boundary test); loop.py is not rewritten - the beats ride the existing progress-sink boundaries
  - An unattached run's added senses cost is cap-bounded and recorded on the artifact whether or not anyone ever reads it
  - Integration test with a fake senses: background run -> attach via the flight plane -> ack + one update are readable live

### t10 — One-shot foreground work beats (colleague/cli/_commands/work.py): 'colleague work' with senses armed renders ack + updates as labeled stderr lines by default; --json stdout stays parseable by existing consumers

- depends on: t9
- covers: c23, h16
- acceptance:
  - Default run with senses armed: ack + updates appear as labeled lines on stderr, results stay on stdout (never mixed)
  - A --json invocation's stdout parses as the same JSON schema as today (test pipes and json.loads it); an ask-colleague-style caller still gets a parseable result contract
  - --cortex-only / senses-unarmed one-shot work is byte-identical to today

### t11 — Resident parity (colleague/resident/appserver.py): the mesh resident's operator lane gains the full beats - ack replied-to-origin before cortex's first step, cadence-gated updates pushed reply-to-origin (cap-bounded), clarify-first via message round-trip; c19 trust model structurally intact

- depends on: t5, t6
- covers: c10, h3, c5, h17
- acceptance:
  - Operator request -> ack message goes back where the request arrived (channel or DM) before cortex's first step; proactive updates follow to the same origin, cap-bounded so senses can never flood a channel
  - Clarify-first: a low-confidence+omissions intake may ask ONE question back at origin; a go-word, any answer, or a timeout dispatches - clarification can never withhold work (test-pinned)
  - c19 pinned structurally: a non-operator can never reach append_guidance nor the operator-lane beats (the one call site stays inside the operator branch; test); update pushes carry no repo content beyond what existing replies already may

### t12 — tts narration of presence beats (engine render hook + colleague/voice.py): with voice armed, each rendered ack/update is synthesized additively - a wav beside the run (session/talk/work) or a file-link line (resident); implements decision c17, degrade-clean

- depends on: t6
- acceptance:
  - Narration is strictly additive: a failed/absent synthesis (rig 502) changes nothing in the text output (byte-identical text, one notice); no [voice] dependency at base install (lazy imports pinned)
  - The hook lives in the presence engine so every front inherits it without per-front voice code
  - The voice live proof SKIPs honestly while the rig's speech proxy 502s (never a fabricated pass)

### t13 — Deliberate pin-break sweep + per-front degrade pins: enumerate every off-TTY/piped byte-identical test this arc breaks and update each in the same change with a stated reason; add the per-front degrade pins

- depends on: t7, t8, t9, t10, t11
- covers: c24, h14, c3, h1
- acceptance:
  - An enumerated pin-break list exists in the feature doc/PR body; every broken test names its reason in the diff - zero silently-changed expectations (reviewable one by one)
  - Per-front pins added: senses-unarmed byte-identical, degraded senses call bounded + recorded, --cortex-only a strict no-op of the whole lane
  - JSON parseability tests cover work/session/talk --json surfaces after the pin-breaks

### t14 — livecheck per-front middle-manager classifiers + live proofs: extend colleague/livecheck.py so each front's full beat sequence (ack, grounded update, guidance relay, conversational answer) is machine-checked from feed + artifact alone; record rig evidence in docs/live-testing.md

- depends on: t7, t8, t9, t10, t11, t12
- covers: c15, h8, h2, c7, h19, c4
- acceptance:
  - Classifiers exist for session(loop), talk-attach, background, resident, and one-shot work fronts; each grades from evidence (feed + artifact), never from model self-report
  - A front the rig cannot exercise records an honest SKIP with the reason (voice narration; resident if transport unavailable) - never a fabricated pass
  - The same-beats-per-front consistency is what the classifiers grade: a front missing a beat FAILS its check; live rows added to docs/live-testing.md with wall-clock latencies

### t15 — Docs + fourth-increment recording: feature doc for presence-default-everywhere, CLAUDE.md scope section records the FOURTH sanctioned router-exclusion increment and the stdout convention break, #300 closure notes, before-state verified at base commit

- depends on: t13, t14
- covers: c1, h9, c6, h18
- acceptance:
  - Feature doc documents per-front behaviour, the degradation ladder, the enumerated move list, the enumerated pin-breaks, and honest limits (Gemma JSON-move reliability, rig 502, latency numbers parked)
  - CLAUDE.md's out-of-scope section names this the fourth sanctioned increment with its fixed boundary (coordination-only moves, cortex sole repo actor, #276 still parked) - the router-exclusion line moves deliberately, never silently
  - The before-state is cited against the arc's base commit (talk.py/appserver.py reactive-only) and #300 is referenced for closure; doc-test alignment passes

## Risks

- [unknown_nonblocking] Senses-loop live viability on the rig: Gemma4 emits no structured tool calls today, which is exactly why the move surface is prompted-JSON over the tools-off completion; if Gemma cannot sustain reliable JSON moves under load, the ladder's fixed-beat rung carries the front - reliability numbers land with live tuning.
- [unknown_nonblocking] Senses-loop latency under cortex GPU load: a boundary may now cost up to 2 senses completions (single-call p50 measured 2.33s under load); the per-boundary cap + cadence caps bound it, but the shipped numbers are conservative defaults pending live tuning.
- [unknown_nonblocking] Resident clarify-first round-trip semantics ride the agent-lifecycle transport (async answer arrival): v1 uses a timeout-to-dispatch default so clarify can never withhold work; richer conversational threading is follow-up territory.
- [unknown_nonblocking] Rig stt/tts still 502 (lobes-cli#89/#92) and the advertised-endpoint regression (lobes-cli#92) persists - voice narration live proof SKIPs and lobes-discovered senses may need the explicit COLLEAGUE_SENSES_BASE_URL workaround until fixed rig-side.
- [follow_up] Retiring the fixed-beat lane once the senses loop proves out on every front (the two lanes coexist deliberately as the degradation ladder's rungs).
- [out_of_scope] #276 senses-direct-for-cheap-tasks and the #277 embedder/reranker retrieval lane stay parked - unchanged by this arc.
