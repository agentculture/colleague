# Build Plan — effort-v4-rung-observability-rerank

slug: `effort-v4-rung-observability-rerank` · status: `exported` · from frame: `effort-v4-rung-observability-rerank`

> colleague drops its acting/associate/purpose effort defaults to the v4 low set, records the resolved effort rung per seat on the run artifact so effort experiments are verifiable from the run's own record, and its eidetic recall lane is rerank-aware

## Tasks

### t1 — v4 effort tables: `SEAT_TABLE` cortex/worker/evaluator/associate + `ROLE_TABLE` writer/planner -> low; `ASSOCIATE_SEAT_TABLE` + `PURPOSE_TABLE` all low; `FALLBACK_EFFORT` -> off

- instruction: Touch colleague/effort.py (`SEAT_TABLE` lines 60-70, `ROLE_TABLE` writer/planner), colleague/efforttables.py (both tables), colleague/`associate_seats.py` (`FALLBACK_EFFORT` line 82 + the rung string in the warning text near line 139). Update the pin tuples in tests/`test_effort.py` (lines 26-44, 223-226) and any sibling effort test that pins a v3 value. Do NOT touch docs here (t7 owns them).
- covers: c2, h2, c3, h3, c4, h4
- acceptance:
  - `test_effort.py` row-for-row pins assert the v4 values for every table
  - `FALLBACK_EFFORT` == 'off' and `SEAT_TABLE`\['associate'\] == 'low' are asserted together with the two-models-one-seat rationale in the test body
  - the changed scout-rows-agree test names this arc in a comment; effort precedence tests pass unchanged

### t2 — FinishRecord gains `reasoning_effort` (contract only)

- instruction: colleague/`contract_records.py` only (FinishRecord dataclass, lines 52-101). Pick the sentinel for never-resolved (e.g. '') and document it in the docstring. No loop wiring here (t5 owns it).
- covers: c6
- acceptance:
  - FinishRecord has `reasoning_effort` with a stable sentinel default; `to_dict` emits it; `from_dict` tolerates old artifacts without the key
  - round-trip test: `to_dict` -> `from_dict` identical, with and without the field

### t3 — reasoning sidecar module: writer with size cap, off-knob, tagged child naming, request timestamp + index

- instruction: New file colleague/reasoninglog.py + tests/`test_reasoninglog.py` — stdlib only, no imports from loop modules (loop imports it, never the reverse, mirroring artifact.py). Reuse `artifact_dir`() for path resolution so children land beside the parent artifact.
- covers: c30, h17
- acceptance:
  - new module writes <`task_id`>.reasoning.jsonl records {seat, turn, `request_ts`, `request_index`, text}
  - `COLLEAGUE_REASONING_LOG`=0 -> no file, byte-identical run; size cap truncates with a marker record
  - child id in the filename (<`task_id`>.<`child_id`>.reasoning.jsonl) resolves to the OPERATOR repo .colleague/ dir

### t4 — eidetic --rerank opt-in behind a version probe

- instruction: colleague/memory.py (recall argv, version probe cached per process) + colleague/`memory_lessons.py` (comment only on the score-field choice). The probe is one subprocess call, allow-listed already via memory.py. Do not add a `rerank_score` threshold.
- covers: c27, h9, c28, h16
- acceptance:
  - memory.recall passes --rerank iff one 'eidetic --version' probe parses >= 0.14.0; probe failure or older CLI -> flag withheld, argv byte-identical to today
  - fake-eidetic-on-PATH test: a 0.13.0 stub gets no --rerank and recall returns its items; a stub rejecting unknown flags can never yield recalled=0
  - `filter_recall_records` keeps thresholding on the hybrid 'score' field; a comment cites #467's near-binary measurement

### t5 — wire the resolved rung into the loop: populate FinishRecord.`reasoning_effort` + top-level artifact effort block {seat: rung}

- instruction: colleague/`loop_outcomes.py` (the seat='main' record at line 200 + senses record), colleague/artifact.py (effort block on write), reading the same resolved value `vllm_openai`.`_effort_for` computes (line 462 `sent_effort`) — pass it through TaskResult, do not recompute per consumer. The ladder-400 retry warning already on the artifact stays the marker for a dropped key (c29): assert the pair coexists in one test.
- depends on: t1, t2
- covers: c6, c14, h5, h6
- acceptance:
  - every finish record on a mock e2e run carries `reasoning_effort`; mock and vllm-openai record identical shape (`test_e2e_mock.py` extended)
  - a run with work --effort xhigh records xhigh (effective rung, not table default) — override-and-read-back test
  - artifact top-level effort block lists every seat built during the run, including no-finish-record seats (scout child, distill)

### t6 — wire the sidecar into the loop with request timestamp/index; children tagged to the operator repo

- instruction: Hook at colleague/`loop_accounting.py` (where resp.reasoning is already in hand) — one call into reasoninglog per turn; thread the operator-repo dir + child id through the existing subagent snapshot plumbing. Tool-call records for the batch case ride the same `request_index` the turn assigns in `toolbatch_loop` bookkeeping.
- depends on: t3
- covers: c16, h7, c34, h20
- acceptance:
  - a run with reasoning present yields per-turn sidecar records; git status stays clean; model context messages byte-identical with and without the sidecar
  - a parallel read-only batch renders N records sharing ONE `request_ts`/`request_index`; a sequential pair gets two distinct indices (mock-run test)
  - a subagent child's sidecar lands tagged in the operator repo .colleague/ and survives child-worktree removal

### t7 — docs to v4 + narrative fidelity sweep

- instruction: docs/features/thinking-effort.md (+ memory.md for the sidecar pointer, qwen-direct.md /effort listing if it names defaults). Also CHANGELOG via the version-bump skill at PR time, not here.
- depends on: t1
- covers: c5, h10, c17, h12, c18, h13, c19, h14, c20, h15
- acceptance:
  - docs/features/thinking-effort.md renders the v4 table once; `test_thinking_effort_docs.py` passes
  - grep for 'medium' across effort modules/tests/doc returns only ladder vocabulary or history, no live default (h10 sweep recorded in the PR body)
  - before/after/why sections of the spec render facts quoted from the preserved 6daa8d083e7b artifact and cite h24 as recorded on #475, not stronger

### t8 — work --continue re-applies the recorded rung, loudly on mismatch

- instruction: colleague/continuation.py + the continue path in colleague/cli/`_commands`/`_work_`\*.py; reuse `_listing`.`apply_effort` for the re-apply so precedence stays single-sourced.
- depends on: t5
- covers: c32, h19
- acceptance:
  - continuation reads the artifact's recorded acting-seat rung and re-applies it; an explicit --effort on the continue invocation wins
  - recorded != current resolution -> TaskResult.warnings entry naming both values and the source artifact; equal -> no warning (pinned both ways)

### t9 — sidecar stays out of every sharing surface

- instruction: Mostly assertion work: tests over colleague/feedback.py export and handoff.py; add an explicit exclusion only where a glob would otherwise sweep the file.
- depends on: t6
- covers: c31, h18
- acceptance:
  - feedback export output for a run WITH a sidecar contains no reasoning text (test)
  - handoff/PR content and mesh surfaces read nothing from \*.reasoning.jsonl (grep audit recorded in the test or PR body)

### t10 — byte-identical audit: overrides unchanged, adapter diff minimal, full suite

- instruction: The integration gate before validation: run lint (black/isort/flake8/bandit) + the teken rubric too. No new code except missing-test fills.
- depends on: t5, t6, t8, t9
- covers: c1, h1, c12, h11
- acceptance:
  - full suite green (uv run pytest -n auto) with effort-precedence tests passing unchanged
  - git diff over colleague/engines/ shows no request-building change beyond reading `sent_effort` (audit noted in PR body)
  - a run with explicit effort overrides resolves exactly as pre-v4 (pinned)

### t11 — live validation: rerun 6daa8d083e7b at low; close #475/#476/#467

- instruction: Run AFTER the rung recording is merged into the branch (c13 ordering). Use the preserved brief; compare against both recorded arms (2851s incomplete medium / 506s Claude control). If low alone misses the bound, record honestly and revisit parked v1 (sampling) — never tune blind in this task.
- depends on: t10, t7, t4
- covers: c21, h8
- acceptance:
  - the rerun completes inside the 1800s stream-lifetime bound with the six pins intact and suite green, and its artifact names the rung per seat with no source archaeology
  - the artifact is quoted in #475 as closure evidence; docs/live-testing.md gains the row; #476 and #467 get closing comments (rerank noted as dark on the 0.13.0 rig)

## Risks

- [unknown_nonblocking] chain-episode sidecar semantics (append vs per-episode, cap per-run vs per-chain) — decide at t6 implementation time (task t6)
- [unknown_nonblocking] the rerank lane cannot be live-proven on this rig (eidetic 0.13.0) — t4 validates via fake-CLI stubs only; live proof waits for a rig upgrade (task t4)
- [unknown_nonblocking] low alone may not land the rerun inside the bound (sampling compensation parked as v1) — t11 records the miss honestly rather than tuning (task t11)
