# Build Plan — Colleague holds a standard for its own capacity: it sizes each job against its context budget and, at the fill line, makes one declared, opinionated move — compact (summarize its own working history to itself), split (fan the work out to child instances), or stop-with-a-handoff (finish with a continuation summary) — and warns the caller when a job is too big for one repo to hold, so a long job makes continuous, durable progress instead of silently degrading into lossy windowing or dying at the limit.

slug: `colleague-holds-a-standard-for-its-own-capacity-it` · status: `exported` · from frame: `colleague-holds-a-standard-for-its-own-capacity-it`

> Colleague holds a standard for its own capacity: it sizes each job against its context budget and, at the fill line, makes one declared, opinionated move — compact (summarize its own working history to itself), split (fan the work out to child instances), or stop-with-a-handoff (finish with a continuation summary) — and warns the caller when a job is too big for one repo to hold, so a long job makes continuous, durable progress instead of silently degrading into lossy windowing or dying at the limit.

## Tasks

### t1 — Add colleague/capacity.py — a coarse, advisory capacity assessment sizing a job against the context budget

- covers: c8, h1
- acceptance:
  - assess_capacity(repo_path, instruction, budget) returns an advisory verdict from dependency count + folder count + file count + an instruction token estimate via the existing count_tokens seam (char-heuristic fallback when /tokenize is absent)
  - The verdict is ADVISORY and NEVER blocks: a unit test shows a job whose estimate says large still runs to completion
  - Pure stdlib, zero new dependency; tests/test_zero_deps.py still passes

### t2 — Add lightweight TaskResult.capacity_decision + capacity_warning fields to colleague/contract.py (modelled on destination/announcement)

- covers: c9, c13
- acceptance:
  - TaskResult gains a capacity_decision record {kind in compact|split|finish-with-handoff, reason} and a capacity_warning field; both default to empty/None and are omitted from the artifact when unset (lightweight, no separate spec file)
  - tests/test_e2e_mock.py asserts the default (no-fill-line) TaskResult shape is byte-identical to today

### t3 — Add the proactive fill-line trigger + structured decision prompt to colleague/loop.py

- depends on: t1, t2
- covers: c4, h2, h11
- acceptance:
  - Each turn, when used/budget >= a tunable threshold knob (COLLEAGUE_* env, resolved via EngineConfig precedence), the runtime injects EXACTLY ONE structured decision prompt naming the three moves {compact,split,finish-with-handoff} plus the capacity numbers; advisory, never a forced gate
  - The model's declared move is recorded exactly once per fill-line event in TaskResult.capacity_decision with kind + reason
  - With no fill-line event nothing is injected, zero extra model turns occur, and TaskResult is byte-identical (e2e mock guard)

### t4 — Implement self-compaction (compact branch): a bounded model-authored summary that replaces elided turns, with lossy windowing as the fallback floor

- depends on: t3
- covers: c10, h3
- acceptance:
  - On a declared compact move, a bounded summarization turn produces a MODEL-AUTHORED summary that replaces the elided turns (distinct from the [earlier steps elided] placeholder); messages[:2] (system + original instruction) survive verbatim
  - Compaction is bounded: one summary turn per compaction, a capped number of compactions, counted against the step budget
  - If the summarization turn itself overflows, the loop falls back to window_messages (lossy windowing retained as the documented floor) — degradation is extended, not replaced

### t5 — Route a declared split move to the existing subagents/auto-split machinery (no new fan-out/worktree/merge code)

- depends on: t3
- covers: c11, h4
- acceptance:
  - A declared split move calls existing colleague.subagents.make_batch_spawn/batch_spawn (<= MAX_SUBAGENT_FANOUT-1 children, isolated per-child worktrees, sequential merge child)
  - No new function is added to subagents.py or worktrees.py; tests/test_boundary.py still passes (threads/subprocess confined to the two sanctioned modules)

### t6 — Implement the finish-with-handoff branch reusing the existing preserve-partial / INCOMPLETE seam

- depends on: t3
- covers: c12, h5
- acceptance:
  - A declared finish-with-handoff move writes a continuation handoff (what is done / what remains) into TaskResult.summary, reusing the existing preserve-partial path
  - The result is PRESERVED (returned, never raised as a bare exception); a test asserts the handoff content + preservation

### t7 — Surface the warn-only 'too big for one repo' caller warning (TaskResult field + stderr + artifact), reachable via colleague work / ask-colleague

- depends on: t1, t2
- covers: c13, h6, h9, c2
- acceptance:
  - When the capacity assessment exceeds the split capacity (children x per-child budget), a caller-visible warning naming the cross-repo/instance split is set on TaskResult.capacity_warning, recorded in the artifact, AND emitted to stderr — not swallowed on the happy path
  - The warning + the declared move are reachable through the documented entry points (colleague work / ask-colleague) with NO new operator flag; a test delegates a long job and asserts the caller's result carries them
  - Colleague performs NO cross-repo write (warn-only); neighbours stay read-only and no daemon/socket is opened

### t8 — Add runtime-owned guard tests: full path identical on mock + vllm-openai, strict no-op when no trigger, structural caps unchanged

- depends on: t3, t4, t5, t6, t7
- covers: c1, c7, h8, h14, h13, h12, c14, h7
- acceptance:
  - A runtime-owned test fires the full path (size -> declared move -> record -> optional warning) and asserts it is identical for mock and vllm-openai (all-engines rule)
  - A no-trigger e2e mock run yields a byte-identical TaskResult shape with zero extra model turns (strict no-op)
  - A boundary test asserts the structural caps are unchanged (MAX_STEPS, overflow/timeout retry caps, MAX_SUBAGENT_FANOUT=4, MAX_SUBAGENT_DEPTH=2) and no daemon/socket/cross-repo-write path is opened
  - The contrast is demonstrated: a long job that today drops oldest turns lossily instead retains meaning via compact OR splits OR hands off, and the caller can read which move + why

### t9 — Document the v0->v1 graduation: update CLAUDE.md (v0-scope + context-budget sections), context.py docstring, README, and bump to v1.x

- depends on: t8
- covers: c3, h10, c5, c6
- acceptance:
  - CLAUDE.md v0-scope + context-budget sections and context.py's 'there is no summarization' note are updated to state the v1 self-compaction behaviour, with lossy windowing retained as the documented fallback floor (additive, declared change)
  - The before-state claims remain verifiable: the docs/commit reference the pre-change tree state (windowing-only, reactive auto-split, flat budget knob) so a reviewer can confirm the contrast against history
  - The version is bumped to v1.x (version-bump skill) and CHANGELOG records the capacity standard; the doc-test-alignment check passes

## Risks

- [unknown_nonblocking] Exact project-complexity formula — which signals (deps vs folders vs files vs instruction tokens) and what weights map to a capacity verdict. Start coarse and tune; the verdict is advisory either way. (task t1)
- [follow_up] How to MEASURE that the model reliably picks the RIGHT fill-line move (compact vs split vs finish-with-handoff) rather than always compacting and continuing to drown — an efficacy follow-up (mirrors the open auto-split recommendation-efficacy question). (task t3)
- [out_of_scope] Cross-repo split EXECUTION (colleague cloning + writing across repos / coordinating instances) is out of scope here — warn-only. A real cross-repo orchestrator needs its own spec (would breach the no-daemon / read-only-neighbours conventions). (task t7)
- [unknown_nonblocking] OPERATIONAL: t3-t7 all touch colleague/loop.py, so although the dependency graph permits parallel waves, same-wave loop.py tasks merge-serialize. The operator should build the loop.py branch tasks sequentially (or behind explicit deps) to avoid merge collisions; capacity.py/contract.py/compaction.py/tests are the file-disjoint pieces. (task t3)
