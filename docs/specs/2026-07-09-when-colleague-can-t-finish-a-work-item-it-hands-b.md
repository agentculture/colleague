# When colleague can't finish a work item, it hands back an honest not-ok status and a short explanation — the reason, the evidence, and a recommended next move (take over, re-scope, split, or escalate) — instead of reporting ok with an empty diff.

> When colleague can't finish a work item, it hands back an honest not-ok status and a short explanation — the reason, the evidence, and a recommended next move (take over, re-scope, split, or escalate) — instead of reporting ok with an empty diff.

## Audience

- The delegating caller — Claude via the ask-colleague skill, or any programmatic caller of 'colleague work' — plus the human operator; they need a trustworthy status signal to decide whether to take over, re-scope, split, or escalate.

## Before → After

- Before: Today a clean finish() on a write task that produced 0 changed files (a 'meta-finish' whose own summary admits it isn't done — the live #313 evidence from the PR #312 t4 build) reports status: ok; likewise an empty or meta-description finish (#231/#248) hands back a near-empty deliverable as ok. The caller can only discover the non-completion by diffing the branch.
- After: A work item that did not produce its expected deliverable comes back non-ok (status: incomplete) carrying a structured, omit-when-None TaskResult.incompletion {reason, evidence, recommendation}; ask-colleague surfaces it to the caller. A genuinely complete run (write with changes, or read-only with findings) is byte-identical — no incompletion key, status unchanged.

## Why it matters

- Delegation only works if the caller can trust the status. A silent incomplete both wastes the caller's trust and hides the exact moment they most need to intervene; an honest reason + recommended next move is what lets the caller act instead of re-deriving the failure by hand.

## Requirements

- TaskResult gains an omit-when-None 'incompletion' field {reason: str, evidence: str, recommendation: str} (a dataclass mirroring the finish_recovered/acceptance_outcomes omit-when-None convention in colleague/contract.py), serialized only when set.
  - honesty: TaskResult.incompletion round-trips through to_dict/from_dict, is omit-when-None, and a run without it serializes byte-identically to a pre-feature artifact (drift-tested).
- The loop's terminal-status logic (colleague/loop.py _set_terminal_status) is extended so a clean finish (_EXIT_FINISHED) that produced NO expected deliverable downgrades to INCOMPLETE and attaches the incompletion record — extending, never duplicating, the existing finish_recovered / forced-synthesis / NO_RESULT_PRODUCED machinery.
  - honesty: The 'no expected deliverable' test is role/intent-aware: for a write-intent run the deliverable is >=1 changed file; for a read-intent run it is a non-empty, non-meta findings summary. The downgrade never fires on a run that produced its role-appropriate deliverable.
  - honesty: incompletion composes with finish_recovered: when forced-synthesis recovered a real (non-empty) deliverable, the run is complete and no incompletion fires; incompletion fires only when NO deliverable survives after the existing recovery paths run.
  - honesty: The status downgrade for the previously-ok write-0-changes case is a DELIBERATE, documented behavior change (recorded in CLAUDE.md like the other convention changes), not a silent breach; callers keying on status=='ok' will correctly now see 'incomplete' for these runs.
- The incompletion detector is runtime-owned and fires identically for mock and vllm-openai (all-engines rule); a genuinely complete run leaves TaskResult byte-identical (no incompletion key), guarded by the e2e mock shape test.
  - honesty: The feature fires identically for mock and vllm-openai; tests/test_e2e_mock.py still passes because a complete mock run carries no incompletion key.
- The ask-colleague skill surfaces the incompletion {reason, recommendation} to the delegating caller (a stderr line and/or the --json payload), so the caller sees the honest non-completion without diffing the branch.
  - honesty: ask-colleague prints the incompletion reason+recommendation on a non-ok result and suppresses the success-shaped 'grade:' footer for an incomplete run, consistent with the existing #192 ask-colleague.sh incomplete handling.

## Honesty conditions

- A legitimately read-only run (explorer/reviewer role, or explore/review mode) that changes 0 files is NOT flagged incomplete — it is complete when it delivered a non-empty findings summary. The detector distinguishes write-intent from read-intent so it never mislabels a correct read-only run.
- The primary consumer is a programmatic caller (ask-colleague / colleague work --json), so the signal must be machine-readable — a status value plus a structured field — not human prose alone.
- The #313 before-state is real and reproducible: the PR #312 t4 run (task 48a9e3db1b3f) finished clean with 0 changed files yet reported status ok — verifiable from the issue body.
- The incompletion field is additive and omit-when-None: its presence never alters a complete run's artifact, and its absence is itself the signal 'this run is complete'.
- The value is measurable: a caller can branch on status/incompletion WITHOUT diffing the branch — the 'diff-to-discover' step that #313 describes is eliminated.
- The boundary holds under test: a run that produces a WRONG-but-present deliverable (changed files that are incorrect) is NOT flagged — the gate detects ABSENCE of a deliverable, never incorrectness (that stays with review/feedback).
- The success signal is a concrete testable pair on mock: a write task with 0 changes yields status=incomplete + incompletion.reason='write-no-changes'; a write task with >=1 change yields status=ok and no incompletion key.
- The recommendation is produced by a fixed reason->advice map with no model call, so the same terminal condition yields the same recommendation on mock and on a live backend — testable without a live model.

## Success signals

- A delegated write task that meta-finishes with 0 changed files returns status: incomplete with incompletion.reason == 'write-no-changes' and a recommendation; ask-colleague prints it; a normal write (>=1 changed file) and a normal explore (findings summary, 0 changes) are byte-identical (no incompletion, status unchanged).

## Scope / boundaries

- Not about making colleague COMPLETE more work (the reach half — #289 tool-call-parsing, #237 cross-drive continuation — is explicitly out of scope, per the user's frame decision); not a multi-model router; not a correctness oracle (it detects 'no deliverable', never 'wrong deliverable'); the recommendation is a deterministic reason->advice map, not a model deciding to escalate.

## Non-goals

- Does not fix the #289 tool-calls-emitted-as-text parsing or the #237 cross-drive continuation/reach; for the #289 zero-step symptom it ADDS an explanation (reason='no-progress-zero-steps') but leaves the parsing unchanged.

## Decisions

- Reuse the existing INCOMPLETE status constant — do NOT add a new status value; the write-no-changes / no-deliverable cases join the outcomes already mapped to INCOMPLETE.
- Detection and explanation are fully deterministic (no new model call, no prompt-dependent behavior): reason is derived from the detected terminal condition, recommendation from a fixed reason->advice map — consistent with colleague's 'behavior locked in code and harness, not prompts' principle.
- The incompletion explanation attaches to EVERY non-ok outcome: the newly-flagged write-no-changes and empty/meta-finish cases (which also downgrade a clean finish from ok->incomplete) AND the runs already marked incomplete today (budget/stop exhaustion, zero-step no-progress #289), which gain a reason+recommendation. Every non-ok run carries {reason, evidence, recommendation}.
- Detection, the status downgrade, and the TaskResult.incompletion field are runtime-owned in colleague/loop.py and fire on ALL paths (work/drive/session) identically for mock and vllm-openai; the ask-colleague skill adds caller-facing surfacing (stderr line / --json) on top.
