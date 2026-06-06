# Colleague holds a standard for its own capacity: it sizes each job against its context budget and, at the fill line, makes one declared, opinionated move — compact (summarize its own working history to itself), split (fan the work out to child instances), or stop-with-a-handoff (finish with a continuation summary) — and warns the caller when a job is too big for one repo to hold, so a long job makes continuous, durable progress instead of silently degrading into lossy windowing or dying at the limit.

> Colleague holds a standard for its own capacity: it sizes each job against its context budget and, at the fill line, makes one declared, opinionated move — compact (summarize its own working history to itself), split (fan the work out to child instances), or stop-with-a-handoff (finish with a continuation summary) — and warns the caller when a job is too big for one repo to hold, so a long job makes continuous, durable progress instead of silently degrading into lossy windowing or dying at the limit.

## Audience

- Colleague operators and the working backend/model carrying out a long or large job, plus callers that delegate via 'colleague work' / the ask-colleague skill and want the job to make durable progress instead of silently degrading — and to be told plainly when a job is too big for one context window, one worktree, or one repo to hold.

## Before → After

- Before: Today, on a filling context the loop only WINDOWS history: it drops the oldest turns behind a '[earlier steps elided]' placeholder and explicitly does NOT summarize (context.py: 'there is no summarization'). Auto-split (#151) is REACTIVE — it fires only after the bounded overflow-retries are exhausted — and the context budget is a flat env knob, not sized to the project. There is no declared choice at the fill line and no 'too big for one repo' warning; a long job either degrades lossily or dies at the limit.
- After: When context fills mid-work, colleague makes ONE declared, opinionated move — compact (summarize its own working history to itself), split (fan out to child instances), or finish-with-handoff (stop with a continuation summary) — recorded in the run artifact and surfaced to the caller. Capacity is sized up-front against the job (token/char budget plus a coarse project-complexity signal: deps, folders, files), and when even a split can't hold the job, colleague WARNS the caller that the work must be split across repos/instances rather than dying or degrading lossily.

## Why it matters

- A summary-to-self preserves meaning where lossy windowing destroys it, and a declared opinionated move (instead of silent degradation) lets a long job make continuous, durable progress while telling the caller exactly what colleague decided and why — turning a hard context ceiling into a continuable boundary.

## Requirements

- Capacity sizing: an up-front assessment sizes the job against the context budget using a COARSE project-complexity signal (dependency count, folder/file counts, plus a token/char estimate of the instruction via the existing count_tokens seam). It is recorded as an advisory capacity estimate and NEVER blocks work — it only informs the fill-line decision and the caller warning.
  - honesty: A test shows the capacity assessment is computed from repo structure (deps/folders/files) plus instruction size and is ADVISORY — a job still runs to completion when the estimate says 'large'; the estimate is coarse/heuristic (not a precise tokenizer) and degrades to the char heuristic when /tokenize is absent.
- The fill-line decision is a single DECLARED move chosen from {compact, split, finish-with-handoff}, recorded in the run artifact as a lightweight capacity-decision record (kind + reason, like destination/announcement) and surfaced to the caller. It is advisory / backend-judged — the runtime injects a structured decision prompt naming the three options and the capacity numbers; the model picks. Never a forced runtime gate.
  - honesty: A test shows TaskResult carries exactly one recorded capacity decision per fill-line event, each with its kind {compact,split,finish-with-handoff} and a reason; with NO fill-line event the field is absent/empty and the TaskResult shape is byte-identical to today (e2e mock guard).
- Self-compaction (the NEW capability): on the compact branch, the model summarizes its own working history into a compact note that REPLACES the elided turns — a model-authored summary, not the lossy '[earlier steps elided]' placeholder drop — preserving meaning. It is bounded (one summarization turn per compaction, a capped number of compactions) and counts against the step budget; messages[:2] (system + original instruction) stay verbatim. If the summarization turn itself overflows, the loop falls back to today's lossy windowing as the floor.
  - honesty: A test proves the compacted history contains a MODEL-AUTHORED summary (distinct from the '[earlier steps elided]' placeholder) AND that messages[:2] (system + original instruction) survive verbatim; the summary turn is bounded, counts against the step budget, and on its own overflow the loop falls back to lossy windowing.
- The split branch REUSES the existing subagents / auto-split machinery unchanged (colleague.subagents.make_batch_spawn / batch_spawn, <= MAX_SUBAGENT_FANOUT-1 children, isolated per-child worktrees, sequential merge child). No new fan-out, worktree, or merge code is added; threads/subprocess stay confined to the two sanctioned modules.
  - honesty: tests/test_boundary.py still passes (threads/subprocess confined to subagents.py/worktrees.py); no new function is added to subagents.py or worktrees.py; the split branch calls the existing make_batch_spawn/batch_spawn.
- The finish-with-handoff branch preserves a readable partial result plus a continuation summary (what is done / what remains), reusing the existing preserve-partial + escalation/INCOMPLETE seam — so a stopped job hands the caller enough to resume and is never surfaced as a bare exception.
  - honesty: A test shows that on the finish-with-handoff branch TaskResult.summary carries a continuation handoff (done / remaining) and the result is PRESERVED (not raised as an exception), reusing the existing preserve-partial path.
- The 'too big for one repo' caller warning: when the capacity assessment says the job exceeds even the split capacity (children x per-child budget), colleague emits an explicit, caller-visible warning (to agent or human) that the workspace must be split across repos/instances, recorded in the artifact. Colleague does NOT itself perform a cross-repo write — warn-only.
  - honesty: A test shows an over-the-split-capacity assessment yields a caller-visible warning that names the cross-repo/instance split, recorded in the artifact; colleague performs NO cross-repo write (warn-only).
- Runtime-owned (all-engines rule): the whole feature lives in the loop/runtime, fires identically for mock and vllm-openai, adds no runtime dependency, opens no socket/daemon, and is a strict no-op when no fill-line trigger fires — zero extra model turns and byte-identical TaskResult shape.
  - honesty: tests/test_zero_deps.py and tests/test_e2e_mock.py both pass; the identical code path serves mock and vllm-openai; with no trigger there are zero extra model turns and a byte-identical TaskResult.

## Honesty conditions

- An end-to-end test on a long work item shows colleague making exactly one DECLARED fill-line move (compact | split | finish-with-handoff) recorded in TaskResult and surfaced to the caller; on the compact branch a model-authored summary replaces the elided turns (not the lossy placeholder); and the whole feature is a strict no-op (byte-identical TaskResult, zero extra turns) when no fill-line trigger fires — identical on mock and vllm-openai.
- The cross-repo 'too big to hold' warning and the declared fill-line move are both reachable by a CALLER through the documented entry points (colleague work / ask-colleague) with no new operator flag — proven by a test that a delegated long job surfaces the decision + warning to the caller's result.
- The before-state is verifiable in the current tree: context.py states 'there is no summarization', the loop only windows (drops oldest behind a placeholder), auto-split fires only at overflow-retry exhaustion, and the budget is a flat COLLEAGUE_CONTEXT_BUDGET env knob — a reviewer can confirm each against HEAD.
- A test shows the after-state holds end-to-end: a filling context yields exactly one recorded move + (when over split capacity) a caller warning, with capacity sized from repo structure + instruction size — and none of it blocks a job that fits.
- The contrast is demonstrable: a long job that today drops oldest turns lossily instead retains meaning via a model-authored summary OR splits OR hands off with a continuation summary — and the caller can read which move was taken and why.
- A boundary test proves the structural caps are unchanged (MAX_STEPS, overflow/timeout retry caps, MAX_SUBAGENT_FANOUT=4, MAX_SUBAGENT_DEPTH=2) and that no daemon/socket/cross-repo-write path is opened — only a warning is emitted for cross-repo splits.
- A runtime-owned test fires the full path (size -> declared move -> record -> optional warning) identically on mock and vllm-openai, and a no-trigger e2e mock run yields a byte-identical TaskResult with zero extra model turns.

## Success signals

- A long work item that today degrades lossily or dies at the limit instead: (a) sizes itself up-front, (b) at the fill line emits exactly ONE declared move recorded in TaskResult and surfaced to the caller, (c) on the compact branch summarizes its own working history to itself instead of dropping it, and (d) when it can't fit even a split, warns the caller it must split across repos — verified by a runtime-owned test firing identically on mock and vllm-openai, and a strict no-op (byte-identical TaskResult) when no fill-line trigger fires.

## Scope / boundaries

- A capacity-DECISION policy layered on the existing degradation + auto-split + handoff machinery — NOT a multi-backend router, NOT an execution sandbox, NOT a daemon, NOT a cross-repo write orchestrator (it WARNS about cross-repo splits; the operator performs them), and it does NOT remove the structural caps (MAX_STEPS, retry caps, MAX_SUBAGENT_FANOUT=4 / DEPTH=2). 'Work indefinitely' means bounded-degradation-plus-continuity, not a literal infinite loop.

## Non-goals

- Not a forced gate: the runtime never compacts, splits, or stops against the model's judgment; it sizes, recommends, and records — the model picks the move.
- Not a cross-repo write orchestrator: 'split to another repository' is a WARNING to the caller; colleague does not clone-and-write across repos. Neighbours stay read-only; no daemon, no cross-repo write path is added.
- Not a literal infinite loop / unbounded run: MAX_STEPS, the overflow/timeout retry caps, MAX_SUBAGENT_FANOUT=4 and MAX_SUBAGENT_DEPTH=2 are unchanged. 'Indefinitely' means continuity across the context boundary, not removal of termination.
- Not a precise tokenizer or static-analysis subsystem: the capacity/complexity estimate is coarse and advisory; no third-party tokenizer or code-analysis dependency is added (dependencies=[] holds).
- Not a replacement for graceful degradation or escalation: self-compaction is offered before/instead of lossy windowing, but lossy windowing remains the final floor and escalation remains the last fallback.

## Assumptions

- window_messages already preserves messages[:2] (system prompt + the original instruction), so a compaction / split / handoff turn always still sees the full original assignment — the same invariant the auto-split spec relies on.
- The model can author a useful self-summary of its own working history when prompted (the compaction turn), the same way it authors child briefs for a split — so a model-authored compaction is meaningfully better than a lossy drop in the common case.

## Decisions

- The fill-line move is ADVISORY / backend-judged, consistent with auto-split and subagent delegation: the runtime detects the fill line and injects ONE structured decision prompt naming the three options plus the capacity numbers; the model picks and declares the move.
- Self-compaction is a NEW model turn that REPLACES the lossy placeholder on the compact branch. This deliberately crosses the documented v0 'no LLM-generated summary in v0' line and is the headline re-spec increment — documented honestly as a convention change, not a silent breach, with lossy windowing kept as the fallback floor.
- Capacity is sized by a COARSE complexity signal (dependency count + folder/file counts + an instruction token/char estimate via the existing count_tokens seam, degrading to the char heuristic when /tokenize is absent). It is advisory input to the decision and the warning, never a hard budget override.
- Cross-repo split is WARN-ONLY in this scope: colleague surfaces the recommendation to the caller; the operator performs the cross-repo split. This keeps neighbours read-only and adds no daemon / no cross-repo write path.
- The capacity decision and the cross-repo warning are recorded LIGHTWEIGHT in the run artifact (new TaskResult fields, like destination/announcement) — not a separate per-work-item spec file.
- This increment GRADUATES colleague from v0 to v1. v0's 'no LLM-generated summary' convention is intentionally superseded by self-compaction: the v1 standard is that colleague holds an opinion about its own capacity. CLAUDE.md's v0-scope + context-budget sections and context.py's 'there is no summarization' note are updated to state the v1 behaviour, with lossy windowing retained as the documented fallback floor — an additive, declared change, never a silent breach.

## Hard questions

- risk: Advisory means the model MAY ignore the structured decision prompt and keep drowning (same caveat as auto-split); the runtime guarantees a decision is OFFERED + recorded, not that the model picks well.
- risk: Self-compaction can itself be lossy or WRONG — the model may write a confident-but-inaccurate summary, trading a silent drop for a silent distortion. Mitigation: keep messages[:2] verbatim, bound the summary, and keep lossy windowing as the floor.
- risk: A summarization turn costs tokens + time and could itself overflow on a tiny window. It must be bounded and fall back to plain windowing when the summary turn cannot fit.
- Where exactly is the cross-repo warning surfaced so a CALLER (ask-colleague skill / colleague work CLI / another agent) actually sees it — TaskResult field + stderr line + artifact — without it being swallowed on the happy path?
- Crosses the documented v0 convention 'no LLM-generated summary in v0' (CLAUDE.md context-budget section + context.py 'there is no summarization'). RESOLVED by user decision: this increment graduates colleague to v1, where self-compaction is the standard; lossy windowing is retained as the documented fallback floor. Recorded, not a silent breach (see decision c27). (blocking)

## Open / follow-up

- How to MEASURE that the model reliably picks the RIGHT fill-line move (compact vs split vs finish-with-handoff) rather than always compacting and continuing to drown — an efficacy follow-up (mirrors the open auto-split recommendation-efficacy question).
- Cross-repo split EXECUTION (colleague actually cloning + writing across multiple repos / coordinating multiple instances) is out of scope for this increment — warn-only here; a real cross-repo orchestrator needs its own spec (breaches no-daemon / read-only-neighbours conventions).
