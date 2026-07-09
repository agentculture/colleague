# Build Plan — Every colleague run is pilotable, alive, and steerable — you can talk to it, watch it, and redirect it from a second terminal on work, drive, session, plan, and background runs, because the flight plane is armed by default in the operator's repo (not a throwaway worktree), shows a live heartbeat even during a long completion, accepts steering at each mode's natural checkpoint including plan, and records every senses turn (dispatched or direct) as an auditable artifact

slug: `every-colleague-run-is-pilotable-alive-and-steerab` · status: `exported` · from frame: `every-colleague-run-is-pilotable-alive-and-steerab`

> Every colleague run is pilotable, alive, and steerable — you can talk to it, watch it, and redirect it from a second terminal on work, drive, session, plan, and background runs, because the flight plane is armed by default in the operator's repo (not a throwaway worktree), shows a live heartbeat even during a long completion, accepts steering at each mode's natural checkpoint including plan, and records every senses turn (dispatched or direct) as an auditable artifact

## Tasks

### t1 — Extend the contract: add Task.flight_repo_path (operator-repo path for the flight plane, distinct from repo_path=work CWD, omit-when-None) and a SensesDirectRecord dataclass {route, text, answer, latency, tokens, degraded, at} in the SensesRecord shape family

- covers: c9, c13, h3
- acceptance:
  - a Task with no flight_repo_path serializes byte-identically to today (key absent); a Task with it set round-trips through to_dict/from_dict
  - SensesDirectRecord.to_dict/from_dict round-trips including verbatim text, with best-effort numeric coercion of latency/tokens (mirrors SensesRecord.from_dict)
  - tests/test_e2e_mock.py (TaskResult shape) stays green

### t2 — [#310] Arm the flight plane at the operator repo path, not the isolation worktree: loop.py _arm_flight and _fold_flight_chat resolve task.flight_repo_path or task.repo_path; work.py _setup_isolation sets flight_repo_path=str(repo) on the isolated task (in-place path leaves it None)

- depends on: t1
- covers: c4, h1, h2, h14, h15
- acceptance:
  - a mock 'colleague work --watch' (write run -> isolates) leaves .colleague/flight/<id>.feed.jsonl in the OPERATOR repo and it survives worktree removal (issue #310 repro #5 flips green)
  - guidance written to the operator-repo control.json drains into the running loop at a boundary (issue #310 repro #4 flips to guidance-applied)
  - the in-place session path (flight_repo_path=None) is byte-identical to today; .colleague/flight writes do not trip the #149 dirty-tree guard and two concurrent runs keyed by distinct <id> do not collide (verify, not assume)

### t3 — [#308] Give the flight feed liveness: flight.py gains a distinct heartbeat/run-start feed record type; loop.py writes a run-start marker at task start and folds the #206 phase notice (thinking/synthesizing/compacting, elapsed + step N/max) into the flight-feed sink as a heartbeat record — WITHOUT advancing step_count

- depends on: t2
- covers: c11, c7, h5, h6, h17
- acceptance:
  - a run-start feed record exists before the first WorkStep; a heartbeat record appears during a long completion carrying phase+elapsed+step N/max, and 'colleague talk'/senses grounding surface a real status instead of 'I don't know'
  - the heartbeat/run-start record does NOT advance step_count and does NOT appear in 'tui replay'/'snapshot' (the #206 step-only invariant test passes)
  - fires identically for mock and vllm-openai (all-engines) and is a strict no-op when no plane is armed

### t4 — [#309] Steer plan mode: give plan runs a flight plane armed at the operator repo path (reusing t2's decoupling) and cooperative injection checkpoints at the orchestrator's natural boundaries (spec/plan/workforce stage transitions, per claim-proposal batch, per plan-item batch) — read control, apply guidance, honor stop at each boundary; steering uniform across work/drive/explore/review/plan

- depends on: t2
- covers: c12, h7, h8
- acceptance:
  - 'colleague plan run --watch' arms a plane in the OPERATOR repo; 'colleague flight guide <id>' injected mid-plan is applied at the next stage/batch boundary and drains control.json; a 'stop' halts the plan cooperatively
  - guidance is applied only at a boundary, never mid-completion; a plan run with nobody steering is byte-identical
  - the same operator command (flight guide / talk 'cortex:') steers uniformly across every mode

### t5 — [#307] Arm the flight plane by DEFAULT for work/drive/session: EngineConfig.watch (default True) resolved flag>env(COLLEAGUE_WATCH)>config.json{watch}>default; --no-watch opt-out with --watch kept as explicit alias; session also arms the file plane by default while keeping its stdin talk lane (decision c18)

- depends on: t2
- covers: c3, c10, h4
- acceptance:
  - a plain 'colleague work'/'drive'/'session' arms the plane; --no-watch, COLLEAGUE_WATCH=0, and .colleague/config.json {watch:false} each disarm; precedence flag>env>config>default proven by unit test
  - a no-pilot run is byte-identical on stdout and TaskResult/artifact shape (e2e mock shape green); the feed is a pure side file
  - colleague clean still reaps the always-armed flight residue and a second terminal can 'colleague talk' into an interactive session

### t6 — [#311] Persist the senses-direct record: on a SENSES_DIRECT route (answered OR degraded-fallback), write a standalone .colleague/senses-direct/<id>.json SensesDirectRecord (verbatim text, answer, route, latency, tokens, degraded, at); centralize the write so both the session and the resident get it (decision c19: standalone file, not a session ledger)

- depends on: t1, t5
- covers: c13, h9, h10
- acceptance:
  - a senses-direct turn writes exactly one .colleague/senses-direct/<id>.json with verbatim operator text (never derived from model output) + answer + route; a degraded/misroute senses-direct turn also records (auditable)
  - strict no-op when the front door does not fire / senses is unarmed / --cortex-only (no file written) — pinned by a test
  - routing is unchanged: a dispatched (cortex) front-door turn still records senses-frontdoor:<route> on TaskResult.senses.records exactly as before

### t7 — Measure success and document: encode each of the four issue repros as a check red-before/green-after (colleague/livecheck.py classifier and/or unit/integration tests); update docs (senses-live-presence + flight feature docs, a 'pilotable everywhere' feature doc) with honest limits (cooperative granularity, cadence knob, plan workforce-child steering follow-up); confirm test_boundary.py + test_zero_deps.py stay green

- depends on: t2, t3, t4, t5, t6
- covers: c1, c2, c5, c6, c8, h11, h12, h13, h16, h18
- acceptance:
  - each of the four success repros has a check that FAILS on pre-fix code and PASSES post-fix (measured, not asserted); a repro whose rig dependency is unavailable SKIPs honestly
  - test_boundary.py and test_zero_deps.py pass: no new subprocess/socket/daemon/thread and no new base dependency introduced anywhere in the arc
  - the feature docs are updated and drift-checked against the shipped behavior (doc-test-alignment), naming the cooperative-granularity limit and the parked cadence/workforce-child follow-ups

## Risks

- [unknown_nonblocking] heartbeat cadence — the elapsed-threshold / minimum interval between phase-heartbeat feed records plus its env knob and conservative default; tunable, does not block the design (task t3)
- [unknown_nonblocking] plan-mode steering depth — v1 exposes only the top-level orchestrator stage/batch boundaries; per-child steering (each workforce child in its own subagent worktree) is a follow-up (task t4)
- [unknown_nonblocking] verify (not assume) that .colleague/flight writes into the operator repo during an isolated run do not trip the #149 dirty-tree guard and that two concurrent runs keyed by distinct <id> never collide — .colleague/* is code-confirmed gitignored (task t2)
- [unknown_nonblocking] live proof depends on the reference rig serving a tool-calling cortex (#66); repros whose rig dependency is unavailable SKIP honestly and the livecheck grades from evidence (task t7)
- [unknown_nonblocking] large-file editing constraint — loop.py/work.py/session.py are large existing files the local model tends to time out on (memory lesson); the loop/work/session edits in t2/t5/t6 are Claude-implemented or split, leaving the new/small pieces (contract, flight.py heartbeat, plan/ checkpoints, frontdoor.py writer, docs, tests) as colleague-friendly briefs
- [follow_up] unifying the senses-direct standalone record with the flight-feed/TaskResult observability surfaces (one query path for every senses turn) is a consolidation follow-up, not needed for v1 auditability
