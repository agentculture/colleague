# Build Plan — Colleague auto-splits a too-large assignment into up to ~4 hand-over child assignments before it degrades lossily or fails — reaching ~1M-token effective capacity by reusing the subagent fan-out machinery, advisory and backend-judged, never a forced gate.

slug: `colleague-auto-splits-a-too-large-assignment-into` · status: `exported` · from frame: `colleague-auto-splits-a-too-large-assignment-into`

> Colleague auto-splits a too-large assignment into up to ~4 hand-over child assignments before it degrades lossily or fails — reaching ~1M-token effective capacity by reusing the subagent fan-out machinery, advisory and backend-judged, never a forced gate.

## Tasks

### t1 — Add a tunable split-capacity knob to EngineConfig

- covers: c19, h4
- acceptance:
  - EngineConfig exposes a split-capacity field resolved via EngineConfig.resolve, preferring COLLEAGUE_AUTOSPLIT_* over CONVERTIBLE_AUTOSPLIT_*, defaulting to ~4 children x the per-child context budget (~1M).
  - A configured child count exceeding MAX_SUBAGENT_FANOUT-1 is clamped down to MAX_SUBAGENT_FANOUT-1, proven by a config unit test.
  - Default-config behavior (knob unset) is unchanged; the field has a sane default and no env required.

### t2 — Build a pure colleague/autosplit.py: up-front estimator + recommendation builder

- depends on: t1
- covers: c17, h2
- acceptance:
  - A pure builder renders exactly ONE recommendation message naming the concrete per-child token budget and the child cap (<= MAX_SUBAGENT_FANOUT-1) and pointing the model at the existing 'subagents' tool; asserted by a unit test on the message text.
  - A coarse up-front estimator returns a token estimate of the task instruction text using the existing count_tokens seam / char heuristic (stdlib only, no new dependency).
  - All helpers are pure (no subprocess/threading/network import); tests/test_boundary.py stays green.

### t3 — Wire the reactive split trigger into loop.py, sequenced before escalation

- depends on: t2
- covers: c16, h1, c18, h3, c3, c5, c7, h6, h8
- acceptance:
  - When degradation's overflow retries (_MAX_OVERFLOW_RETRIES) are exhausted, the loop injects the recommendation and grants >=1 bounded extra turn STRICTLY BEFORE _escalation.escalate() runs on the aborted/not-finished path — asserted by a test that orders the two calls.
  - The model's resulting 'subagents' call is served by the EXISTING make_batch_spawn/batch_spawn with NO new function added to subagents.py or worktrees.py (boundary test green).
  - An end-to-end mock test drives trigger -> recommendation -> subagents -> merge producing <= MAX_SUBAGENT_FANOUT child hand-over assignments that are fanned out and merged.
  - A test shows an assignment exceeding the per-child budget triggers the recommendation while a within-budget one does not.

### t4 — Add cross-cutting guard tests: no-op, all-engines parity, caps, windowing invariant

- depends on: t3
- covers: c8, h13, c20, h5, h12, c6, h11, h9, h10
- acceptance:
  - With NO trigger fired, tests/test_e2e_mock.py shows a byte-identical TaskResult shape and ZERO extra model turns; tests/test_zero_deps.py passes (dependencies=[] holds, no socket/daemon).
  - A runtime-owned test asserts the trigger -> recommendation path is offered IDENTICALLY for mock and vllm-openai (all-engines rule).
  - A toggleable-contrast test: with detection disabled, the same oversize assignment degrades lossily or escalates with NO split offered.
  - A test asserts window_messages never drops messages[0]/messages[1] under the most aggressive windowing, so the split-authoring turn always sees the original assignment; and asserts effective capacity ~= children x per-child budget > one window.
  - MAX_SUBAGENT_FANOUT (4) and MAX_SUBAGENT_DEPTH (2) are unchanged (boundary/constant test).

### t5 — Document the feature: docs/features/auto-split.md + CLAUDE.md runtime bullet

- depends on: t3
- covers: c1, c2, c4, h7
- acceptance:
  - docs/features/auto-split.md documents the advisory reactive split: the degradation-exhaustion trigger point, the recommendation, reuse of the subagents fan-out/merge machinery, the tunable FANOUT-clamped capacity knob, and the honest limits (advisory-may-be-ignored, concurrency-bound speedup, up-front-estimate blindness).
  - CLAUDE.md gains an auto-split runtime-component bullet consistent with the existing component list (audience: operators + the working model; before/after contrast captured).
  - The feature arms with NO new operator flag (detection is automatic, response advisory) — stated in the docs and confirmed by doc-test-alignment.
  - doc-test-alignment passes: the committed docs match the built behavior.

### t6 — Bump version (minor) + CHANGELOG entry

- depends on: t3, t4, t5
- acceptance:
  - Version bumped (minor) in pyproject.toml and colleague/__init__.py; CHANGELOG.md gets a Keep-a-Changelog entry referencing issue #151; the version-check CI job passes.
  - Lint + gates green: black --check, isort --check-only, flake8, bandit, and teken cli doctor . --strict.

## Risks

- [follow_up] Advisory means the model MAY ignore the recommendation and keep drowning — efficacy of the nudge is not guaranteed by the build; measuring it (and a possible escalate-after-decline) is a follow-up. (task t3)
- [unknown_nonblocking] The coarse up-front estimate sees only the instruction text, not the repo surface the work will touch, so it can over/under-trigger; the reactive trigger is the reliable path. (task t2)
