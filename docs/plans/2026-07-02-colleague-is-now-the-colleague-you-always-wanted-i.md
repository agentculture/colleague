# Build Plan — Colleague is now the colleague you always wanted: it remembers and learns from every run - eidetic and daria memory inform its context before it starts - it wastes fewer steps across the whole arc from scope through plan, explore, work, review and live-test, and it takes work fully off your hands: run it detached in the background, or let it live in the culture mesh as a resident (via the agent-lifecycle harness seam) that runs its own instances.

slug: `colleague-is-now-the-colleague-you-always-wanted-i` · status: `exported` · from frame: `colleague-is-now-the-colleague-you-always-wanted-i`

> Colleague is now the colleague you always wanted: it remembers and learns from every run - eidetic and daria memory inform its context before it starts - it wastes fewer steps across the whole arc from scope through plan, explore, work, review and live-test, and it takes work fully off your hands: run it detached in the background, or let it live in the culture mesh as a resident (via the agent-lifecycle harness seam) that runs its own instances.

## Tasks

### t1 — t1 Memory adapter: colleague/memory.py shells out to the operator-installed eidetic CLI (recall + remember only, curated allow-list), repo cwd, scope colleague / visibility public - the SAME store and scope the Claude remember/recall skills use; strict no-op when the CLI is absent

- covers: c9, h7
- acceptance:
  - With no eidetic CLI on PATH a work item's TaskResult is byte-identical to today (no memory key, no error, no subprocess attempted)
  - recall/remember reach only the allow-listed eidetic verbs, with repo cwd + scope colleague/visibility public; identity injected like the culture/devague tools
  - test_boundary.py extends: memory.py joins the sanctioned subprocess consumers

### t3 — t3 Memory loop tool: model-callable memory(recall|remember) tool offered to every backend; recall available to read-only roles, remember withheld from them (a write-capable shell-out)

- depends on: t1
- covers: c9
- acceptance:
  - Tool schema offered identically to all engines; ToolExecutor enforces the verb allow-list; explorer/planner/reviewer/validator roles expose recall only

### t5 — t5 Report survival (#248): reproduce the structured-report loss on malformed finish / completion-budget exhaustion BEFORE fixing; after the fix the artifact always carries the report or an explicit degradation marker - never silence

- covers: c10, h8, c4, h4
- acceptance:
  - A regression test reproduces the observed #248 loss shape before the fix (evidence cited from a real artifact)
  - After: malformed finish and budget-exhaustion paths both preserve the structured report or record an honest degradation marker in the artifact

### t6 — t6 Findings-not-meta (#231): a finish whose summary is a meta-description of the findings (rather than the findings) triggers the existing forced-synthesis path; a real-summary finish stays byte-identical

- depends on: t5
- covers: c10, h8
- acceptance:
  - Regression test: the observed #231 meta-description finish now yields the findings themselves via forced synthesis
  - A finish with a substantive summary is byte-identical (no phantom synthesis turn)

### t7 — t7 Explore citation accuracy (#240): root-cause the ~240-line citation offset and ground read_file/tool output so cited line numbers match the real file

- covers: c10, h8, c4, h4
- acceptance:
  - Root cause documented; a regression test pins accurate line citations on the #240 evidence class
  - Tool-result grounding does not blow the output budget (max_output_chars respected)

### t8 — t8 Concurrent-run gate correctness (#239): reproduce the spurious pre-handoff gate failures with two interleaved runs deterministically, then scope every gate (lint / test-integrity / affected-tests) to the run's own worktree + changed-files

- depends on: t5
- covers: c14, h12, c4, h4
- acceptance:
  - A deterministic test reproduces #239's spurious failure before the fix
  - After: two concurrent runs on one repo with disjoint changed-files both pass their gates; composes with the rig-slot budget (#258)

### t10 — t10 Run the pending live proofs now the rig serves tool-calling again: test_vllm_live_mode.py, test_dual_live.py (dual-endpoint if servable), the edit_file ledger row; update every ledger row with commit + date + evidence ids

- covers: c15, h13, c4, h4
- acceptance:
  - Each row updated with commit+date+evidence (artifact/drive ids); a failing proof is recorded failed/partial honestly, never retro-fitted

### t11 — t11 colleague livecheck verb: one command that probes the configured endpoint and runs the applicable gated live proofs, reporting per-ledger-row pass/fail/skip

- depends on: t10
- covers: c15, h13
- acceptance:
  - livecheck composes doctor --probe + the COLLEAGUE_VLLM_E2E-gated proof selection; unreachable rig degrades to an honest skip report (exit code + stderr hint, no traceback)
  - Registered as a host command via register_into(app) with --json support and an explain entry

### t12 — t12 Background one-shot: colleague work --background detaches the run as a setsid child with zero foreground terminal; prints a machine-readable start payload {task_id, pid, artifact, flight}; auto-arms the flight control plane; colleague clean reaps a dead background run's residue

- covers: c12, h10, c8, c3, c2, h2
- acceptance:
  - work --background returns immediately; the child completes the work item end-to-end (artifact + feedback gradable) with no attached terminal
  - kill -9 mid-run leaves a partial artifact + reapable residue that colleague clean recovers; the repo is never wedged
  - No daemon/socket: the detach primitive is a one-shot child process confined to one sanctioned module

### t13 — t13 Resident harness (appserver mode): colleague implements agent-lifecycle's Harness interface behind an opt-in extra; inbound mesh work requests become background work items (rig-budget governed) under the c19 trust model: anyone may ask, only the operator has authority, the agent may refuse beyond its limits and consult peers in doubt

- depends on: t12
- covers: c13, h11, c8, h15
- acceptance:
  - colleague[resident] implements Harness (start / feed_message / replies / stop) proven end-to-end against agent-lifecycle's in-process supervisor + reference transport; real IRC/agtag transport recorded PENDING until upstream ships one (h15)
  - Base install stays byte-identical: no agent-lifecycle import, no daemon, no socket; supervision failures surface via failure(), never silently
  - Trust model enforced and tested: a non-operator request may be refused; operator identity is authoritative for confirmations

### t14 — t14 Boundary + conventions pin: extend test_boundary.py / test_zero_deps.py - no socket/daemon code in colleague, the detach primitive confined to its sanctioned module, agent-lifecycle imported only inside the resident extra; CLAUDE.md scope + conventions updated to record the deliberate no-daemon re-spec (c17)

- depends on: t12, t13
- covers: c6, h6
- acceptance:
  - Boundary tests pin: base install imports neither agent-lifecycle nor socket/daemon modules; detach lives in exactly one sanctioned module
  - CLAUDE.md v1-scope + out-of-scope sections updated honestly (background + residency in scope via this spec; supervision/transport upstream)

### t2 — t2 Runtime memory wiring in the loop: recall-before (a token-capped prior-lessons block derived from the task request, injected at task start) + remember-after (a deterministic lesson record: request, status, step/tool stats, degradations, residuals) + TaskResult.memory {query, recalled, injected_tokens} omit-when-None

- depends on: t1, t6
- covers: c9, h7, c3
- acceptance:
  - With eidetic present: recall runs once at start, the injected block is token-capped and recorded on TaskResult.memory; without eidetic the artifact is byte-identical (e2e shape test extended)
  - On any terminal finish a lesson record is upserted to the shared store (idempotent by id, never duplicates); an aborted run records nothing false
  - all-engines: mock and vllm-openai fire identically

### t4 — t4 Warm-vs-cold proof + ROI: the same task run live twice (cold store vs warmed store), WorkStats deltas + artifact ids recorded in docs/features/memory.md + a ledger row; ROI framed via the existing stats + feedback loop

- depends on: t2
- covers: c7, h14, h3, c5, h5
- acceptance:
  - Two live runs of one task recorded with artifact ids + WorkStats deltas; an honest no-saving result is recorded as-is and the warm-start claim retracted per h3
  - ROI is computed from recorded stats + a feedback grade, not asserted

### t9 — t9 Substantial writes land (#237): a too-large write task decomposes plan-first into subagent waves (reusing auto-split + plan machinery), proven on a real substantial task against the live rig

- depends on: t2
- covers: c11, h9
- acceptance:
  - The #237 evidence-class task (a substantial multi-file implementation) lands decomposed on the live rig, verified by diff + tests
  - If the served model still cannot land it decomposed, the limit is recorded honestly in the ledger/feature doc - never claimed solved

### t15 — t15 Feature docs + announcement honesty: docs/features/memory.md + background.md + resident.md, live-testing ledger rows per leg, version bump; the announcement claims only legs with landed evidence, and the caller interface is documented as artifact + flight + feedback only

- depends on: t4, t9, t11, t14
- covers: c1, h1, c2, h2, c3, c5
- acceptance:
  - Each leg has a feature doc + ledger row with live evidence or an honest PENDING
  - Announcement/README wording matches landed reality (h1); the delegation interface documented so a caller never needs colleague source (h2)

## Risks

- [unknown_nonblocking] Recall injection point + prompt shape decided at build time (v1 from the frame): system prompt vs task prompt block vs first tool result (task t2)
- [unknown_nonblocking] Resident real-transport proof depends on agent-lifecycle shipping a transport plug (IRC/agtag/Slack are upstream later increments); v1 proves against the in-process reference transport and records the real-transport row PENDING (task t13)
- [unknown_nonblocking] The #240 citation-offset root cause is unknown until investigated; the fix shape may differ from read_file grounding (task t7)
- [unknown_nonblocking] Rig stability: every live proof is contingent on the endpoint staying tool-calling-capable (it was dead 2026-07-01, live again 2026-07-02); a dead rig turns live tasks into honest PENDING rows, not failures
- [unknown_nonblocking] Warm-vs-cold may show no measurable saving on the first honest comparison; per h3 the claim is then retracted, and the memory leg ships as capability without the speed claim (task t4)
- [follow_up] loop.py is the hot file: t5 -> t6 -> t2 -> t9 must merge sequentially (the modes-build gotcha); wave widths reflect this deliberately
- [follow_up] Deeper daria coupling (colleague consulting daria investigations mid-run) is a parked follow-up until the eidetic leg proves out (c18/v2)
