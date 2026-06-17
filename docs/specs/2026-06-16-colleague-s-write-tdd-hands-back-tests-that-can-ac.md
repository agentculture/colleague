# colleague's write/TDD hands back tests that can actually fail — a test no longer passes just because it mirrors the implementation's own bug. Fixtures match the real API shape, suspicious test/impl mirroring is flagged, and a diverse second mind can vet the test before it's trusted.

> colleague's write/TDD hands back tests that can actually fail — a test no longer passes just because it mirrors the implementation's own bug. Fixtures match the real API shape, suspicious test/impl mirroring is flagged, and a diverse second mind can vet the test before it's trusted.

## Audience

- Operators who delegate 'colleague write' and agents that call 'ask-colleague write' — anyone who trusts a green colleague-authored test suite as evidence the change is correct.

## Before → After

- Before: Today colleague ships zero test-quality guardrails: no test-first instruction exists anywhere (_DEFAULT_SYSTEM and write.md say nothing about tests), so the model derives a mock's shape from its own (possibly wrong) mental model of an external API, writes code that agrees, and both pass — a self-confirming false positive that ships the bug (#203).
- After: When colleague writes code test-first, a passing test means the behavior is actually correct against the real external API shape — a test can no longer go green merely by agreeing with the implementation's own wrong assumption.

## Why it matters

- These are exactly the bugs TDD exists to prevent; a self-confirming suite turns colleague's green check into false assurance and erodes trust in delegated field-work — the opposite of what 'hand it to colleague' is supposed to buy.

## Requirements

- Advisory mirror-detection heuristic (pure stdlib, sibling to colleague/lint.py): when a work item's changed set includes BOTH a test file and a module under test, flag any unusual identifier (attribute access or string-literal dict key) co-introduced in both yet found nowhere else in the repo — the mirror signature. Surfaced on stderr and recorded in the artifact (TaskResult), non-blocking.
  - honesty: The heuristic is pure stdlib (no new runtime dep, no new sanctioned subprocess consumer beyond the lint-gate boundary), flags the co-introduced novel symbol on BOTH #203 examples (response_error, TotalEstimate), is honestly advisory (records a finding, never blocks handoff), and its false-positive/false-negative limits are documented.
- Test-integrity GATE (deterministic, code-locked): a new colleague/testintegrity.py plus a _maybe_run_test_integrity_gate in colleague/loop.py, sibling to the lint gate, runs post-loop on the work item's changed files REGARDLESS of model behavior — the model cannot skip it. This is the harness 'tool within colleague' the operator asked for; behavior is locked in code and harness, not requested by a prompt. Best-effort wrapped so it never aborts the work item.
  - honesty: The gate runs identically for mock and vllm-openai (all-engines rule), is pure stdlib (pyproject 'dependencies = []' holds; the zero-deps guard still passes), records TaskResult.test_integrity_report omit-when-None so a no-flag run is byte-identical (tests/test_e2e_mock.py passes), and is best-effort wrapped so it never aborts a work item — exactly the lint-gate precedent.
- On a flag, the gate injects ONE bounded model re-examine turn on a clean finish with a live backend ('you and your test both introduced symbol X, found nowhere else in the repo — verify X against the real API shape and fix it if wrong'), reusing the lint-gate fix-turn pattern and saving/restoring the work item's terminal summary/status so the re-examine turn cannot clobber the real result. A strict no-op on mock / no live backend.
  - honesty: The re-examine turn is bounded (one turn, capped steps), fires only on a clean _EXIT_FINISHED with a live backend, and saves/restores the work item's terminal summary/status so its own finish cannot clobber the real result — the documented lint-fix-turn precedent; a strict no-op on mock.
- On a flag, the gate auto-spawns a DIFFERENT-model reviewer subagent (via colleague.subagents, no new worktree/merge code) tasked to independently re-derive the flagged fixture from the real API shape and report disagreement. The diverse mind is the robust guard (the same-model re-examine turn can re-confirm its own mirror). Costs a model call and needs a second model configured; degrades to record-only when unavailable; bounded by existing fan-out/depth caps.
  - honesty: The reviewer reuses colleague.subagents (make_batch_spawn/batch_spawn or the single subagent path) with NO new worktree/merge code, is bounded by the existing MAX_SUBAGENT_DEPTH/FANOUT caps, degrades to record-only when no second model is configured, and is honest that it costs a model call and adds latency on a serializing server.
- A model-callable check_test_integrity loop tool added to colleague/tools.py (offered to every backend — all-engines rule), reusing the SAME detection logic as the gate, so the model MAY self-check a test proactively mid-work. Optional and model-judged; the deterministic gate enforces regardless of whether the model calls it.
  - honesty: The loop tool is added to the runtime tool surface (colleague/tools.py) so every backend exposes it identically (all-engines rule), reuses the gate's detection so there is one detection implementation, and keeps the e2e shape test + zero-deps guard passing; it is optional/model-judged and the gate enforces regardless.

## Honesty conditions

- After the change, replaying the two #203 scenarios as fixtures shows the false positive is caught (gate flags the co-introduced novel symbol; re-examine turn and/or diverse reviewer surfaces the real key) instead of passing silently — i.e. 'a test can actually fail' is mechanically demonstrable, not aspirational.
- #203 was filed by exactly this audience: a caller (ec2-cli) who trusted a green colleague-authored test suite as evidence the change was correct — the report is the proof the audience exists and is harmed.
- The two #203 scenarios can be reproduced as fixtures and, after the change, the false positive is surfaced (heuristic finding and/or prompt-steered correct key) rather than passing silently — i.e. the success_signal is mechanically testable.
- A grep of _DEFAULT_SYSTEM (colleague/loop.py) and .claude/skills/ask-colleague/prompts/write.md finds no test-first / fixture-shape / mirror guidance — independently verified by Claude's read and colleague's own explore run.
- #203 documents two real shipped false positives (exc.response_error vs exc.response; TotalEstimate vs Total) that a green suite hid — both are the API-shape errors TDD is meant to catch, so the trust erosion is concrete, not hypothetical.
- The gate's code path never calls the handoff abort and never opens a socket/network connection — enforced by the zero-deps guard + boundary tests, exactly like the lint gate's non-blocking best-effort pattern.
- Both #203 scenarios are encodable as runnable acceptance fixtures in which the gate flags the co-introduced novel symbol (response_error / TotalEstimate) present in both the changed test and the module-under-test yet found nowhere else in the repo.

## Success signals

- Replaying the two #203 scenarios (AWS AccessDenied: impl reads exc.response_error but botocore uses exc.response; Cost Explorer: impl sums TotalEstimate but the real key is Total) — the test-integrity gate flags the co-introduced novel symbol (present in both test and impl, nowhere else), and the bounded re-examine turn and/or the diverse-model reviewer surfaces the real key, so the false positive is caught rather than shipped silently.

## Scope / boundaries

- Not a correctness oracle and not a blocking gate: the test-integrity harness flags the mirror signature, prompts a bounded re-examination, and spawns a diverse-model reviewer — but it never blocks the git handoff, never makes a network call, and cannot in v0 verify a mock against the live SDK. It reduces self-confirmation; it does not guarantee correctness.

## Non-goals

- No live SDK/network verification, no bundled third-party SDK, no blocking correctness gate, and no language coverage beyond Python in v0 (the heuristic and any lint-adjacent check are Python-only, like the existing lint gate).
- Test EXECUTION is NOT the fix: a mirrored test PASSES, so adding a run_tests tool or a pytest pre-finish gate would only re-confirm the bug. The diverse-mind explore surfaced this option; it is explicitly out of scope for #203 (the bug is test CONTENT mirroring impl, not whether tests run).

## Decisions

- Runtime-owned (all-engines rule), zero new runtime deps, no socket/daemon, advisory and non-blocking — consistent with the v1 capacity-standard and lint-gate conventions; added via this re-spec with spec + plan committed under docs/specs/ and docs/plans/.
- A single non-load-bearing nudge line in _DEFAULT_SYSTEM mentions test integrity, but it is explicitly NOT relied upon: removing or ignoring it changes nothing about enforcement because the harness gate still fires. Documented as advisory; the harness is the source of truth (the operator's 'we don't rely on prompts' principle).

## Open / follow-up

- A real correctness oracle that validates a mock against the live SDK/API shape (network call or bundled SDK introspection) — excluded in v0 by the zero-deps / no-network conventions.
