# Build Plan — When colleague can't finish a work item, it hands back an honest not-ok status and a short explanation — the reason, the evidence, and a recommended next move (take over, re-scope, split, or escalate) — instead of reporting ok with an empty diff.

slug: `when-colleague-can-t-finish-a-work-item-it-hands-b` · status: `exported` · from frame: `when-colleague-can-t-finish-a-work-item-it-hands-b`

> When colleague can't finish a work item, it hands back an honest not-ok status and a short explanation — the reason, the evidence, and a recommended next move (take over, re-scope, split, or escalate) — instead of reporting ok with an empty diff.

## Tasks

### t1 — contract.py: add IncompletionRecord{reason,evidence,recommendation} dataclass + omit-when-None TaskResult.incompletion field

- covers: c8, h5, h11, c4
- acceptance:
  - IncompletionRecord round-trips through to_dict/from_dict; TaskResult.incompletion is omit-when-None (key absent when None); a TaskResult without it serializes byte-identically to the pre-feature shape (drift-tested in tests/test_contract_incompletion.py)

### t2 — colleague/incompletion.py: pure deterministic classify_incompletion() + fixed reason->advice map

- depends on: t1
- covers: c6, h13, h2, h3
- acceptance:
  - classify_incompletion(outcome, write_intent, changed_files, summary, step_count, finish_recovered) returns None when the run delivered its role-appropriate deliverable (write_intent+>=1 change, OR read+non-empty non-meta summary) and an IncompletionRecord otherwise; reason in {write-no-changes,empty-deliverable,budget-exhausted,no-progress-zero-steps}; recommendation from a fixed map with NO model call; a WRONG-but-present deliverable (>=1 change) returns None (detects absence, not incorrectness)

### t3 — ask-colleague surfacing: print incompletion {reason,recommendation} on a non-ok result and suppress the success grade footer

- depends on: t1
- covers: c11, h8, c2, h9
- acceptance:
  - on a work --json payload with status!=ok and an incompletion field, ask-colleague.sh prints 'incomplete: <reason> - <recommendation>' to stderr and omits the success-shaped grade: footer; an ok result with no incompletion is byte-identical to today; tested against a synthetic --json fixture

### t4 — loop.py wiring: call classify_incompletion at terminal-status, downgrade a no-deliverable clean finish to INCOMPLETE, attach the record (all paths, all engines)

- depends on: t1, t2
- covers: c9, c10, h4, h6, c1, c5, c7, h14, h1, h12, c3, h10
- acceptance:
  - mock write task finishing with 0 changed files -> status=incomplete + incompletion.reason='write-no-changes'; mock write task with >=1 change -> status=ok, no incompletion key; read-only explorer run with 0 changes + real findings summary -> stays complete, no incompletion (h1); a finish_recovered synthesis that produced content -> no incompletion (h3); tests/test_e2e_mock.py still passes; wired via ContextControls so mock and vllm-openai fire identically

### t5 — docs + livecheck: feature doc, CLAUDE.md arc bullet recording the deliberate ok->incomplete downgrade, livecheck classifier, version bump

- depends on: t4, t3
- covers: h4
- acceptance:
  - docs/features/honest-incompletion.md documents the contract + honest limits; CLAUDE.md records the write-0-changes ok->incomplete downgrade as a DELIBERATE documented behavior change (h4); colleague/livecheck.py gains classify_honest_incompletion_check; pyproject/CHANGELOG version bumped
