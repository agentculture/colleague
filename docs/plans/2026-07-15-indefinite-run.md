# Build Plan — indefinite-run

slug: `indefinite-run` · status: `exported` · from frame: `indefinite-run`

> colleague work items no longer die at their budgets: when the step budget exhausts mid-task, colleague automatically continues from the persisted artifact — carrying the prior episode's actual tree state — and when the context fills, it compacts with a validated summary that provably preserves the goal and the work done so far; a big task keeps going until it is done or honestly cannot progress, and the operator can stop it at any moment

## Tasks

### t1 — Fill-line re-arm + compaction cap

- instruction: Owns colleague/fillline.py + the fill-line cells/regions of colleague/loop.py (_fillline_offered/_fillline_resolved, _maybe_offer_fillline, _consume_fillline_declaration) and tests/test_fillline.py. Turn the single-element offered/resolved cells into per-crossing state (offered resets once the declaration is consumed and the run drops back under the line). Add the cap as a counted cell. Do NOT touch compaction content/validation — that is t2. Work test-first.
- covers: c3, h3
- acceptance:
  - after a resolved compact, a second threshold crossing offers the fill-line decision again (new test in tests/test_fillline.py)
  - a per-run compaction cap (default from config) bounds total compaction turns; the cap reached = no further offers, recorded on the trace
  - existing test_fillline.py + test_capacity*.py pass unmodified except where they assert the old once-per-run limit

### t2 — Deterministic compaction validation + unrepairable-note policy

- instruction: Owns colleague/fillline.py (pure validator: validate_compaction(summary, goal, changed_files) -> (text, ok)) + loop.py _compact_history to consume it + tests/test_fillline.py additions. Armed-policy flag threaded via ContextControls; unarmed behavior byte-identical to today except empty-summary rejection. Same files as t1 — build strictly after it.
- depends on: t1
- covers: c4, h4
- acceptance:
  - a validator in colleague/fillline.py cross-checks the model summary against the run's own evidence: goal/original-request text present, every changed-file path from the step trace mentioned; missing facts are appended deterministically (repair), and an empty/whitespace summary is REJECTED — it never replaces history
  - on an unrepairable note with chaining armed, the loop takes finish-with-handoff (decision c23); unarmed, it keeps today's lossy-windowing floor (both tested)
  - validation runs on the MAIN model's summary only — no second-model call is introduced (non-goal c12)

### t3 — Chain driver core: continuable exits, no-progress guard, episode cap, knobs

- instruction: Owns NEW colleague/chain.py + the two knob entries in colleague/config.py + NEW tests/test_chain.py. chain.py exposes pure decision functions (should_continue(result, episode_n, cap) -> verdict+reason) plus a ChainState record; the CLI dispatch loop that USES it is t5. Pure stdlib; no subprocess/thread/socket (test_boundary.py lists unchanged). Work test-first.
- covers: c2, h2, c5, h5, c7, h7, c24, h20, c13, h12
- acceptance:
  - new module colleague/chain.py: an explicit continuable-exit ALLOW-LIST (incompletion reason budget-exhausted; never pilot-stop / tool-protocol-broken / no-progress-zero-steps / ok) with one test per non-continuable reason
  - the no-progress guard halts when an episode lands no new commits on its branch AND adds no new artifact evidence (decision c22); ok-status episodes are never re-dispatched (ContinuationError = clean halt, not crash)
  - knobs ride resolve(): --until-done arm + --max-episodes (default 5 armed, 0 = unlimited, decision c21) via COLLEAGUE_UNTIL_DONE / COLLEAGUE_MAX_EPISODES; unset = today's single-episode behavior byte-identical
  - the loop's max_steps semantics and _EXIT_BUDGET are untouched — chain.py never imports loop internals; it consumes artifacts + resolve_continuation only

### t4 — Tree carry: base episode N+1 on episode N's branch tip

- instruction: Owns colleague/worktrees.py (isolation_worktree_add gains an optional base_ref parameter, default None = HEAD as today) + tests/test_worktrees* additions. Verify the ref exists with git rev-parse before use; degrade path returns the warning string for the caller to record. Do NOT wire the CLI here — t5 threads base_ref.
- covers: c6, h6
- acceptance:
  - a chained episode's isolation worktree is created at the prior episode's colleague/<prior-id> branch tip instead of HEAD, so a file committed by episode N's WIP sweep is present in episode N+1's tree (test)
  - a missing/reaped prior branch degrades to today's HEAD base with a recorded warning on the result — never a crash (assumption c29/h24: the #222 WIP sweep is best-effort)
  - non-chained runs still base at HEAD — byte-identical (existing worktree tests pass unmodified)

### t5 — Work dispatch chain loop: arming flags, config inheritance, handoff-once

- instruction: Owns colleague/cli/_commands/work.py (the chain loop wrapping execute_work, reusing resolve_continuation + chain.py verdicts + t4's base_ref) and colleague/handoff.py (handoff gating + intermediate reap). Follow the background-child forwardable-flags precedent (work.py ~line 1010) for inheritance. Read-only verbs stay handoff-free.
- depends on: t3, t4
- covers: c26, h21, c28, h23
- acceptance:
  - colleague work --until-done [--max-episodes N] runs the episode chain: each non-final episode suppresses push/PR, the FINAL episode hands off once with the cumulative diff (episode branches chain from each other), and intermediate colleague/<id> branches are reaped after completion (3-episode --pr test = exactly one PR)
  - every episode inherits the arming invocation's resolved options verbatim (engine, mode, --no-pr, --allow-dirty, budgets) — test: a chain armed with --engine mock --no-pr keeps both on all episodes; nothing re-resolves from a mid-chain config change
  - lineage stamps continued_from episode-to-episode; the ok-guard holds inside the chain

### t6 — Flight continuity + episode-transition observability

- instruction: Owns colleague/flight.py (a chain-transition marker record, type='episode-transition') + the chain driver's between-episode hooks in chain.py/work.py touchpoints agreed with t5 (coordinate: t6 adds the flight/sink calls, t5 owns the loop skeleton — build after t5's skeleton merges if same lines) + tests/test_flight* additions.
- depends on: t3
- covers: c8, h8, c27, h22
- acceptance:
  - the chain checks flight stop BETWEEN episodes: write_stop before the boundary prevents episode N+1 from starting (test); in-episode stop checks + heartbeat unchanged
  - each boundary records the next episode's id on the prior episode's flight feed and announces 'episode N+1 of <cap>: continuing <prior-id>' on the progress sink — a pilot following episode 1 can locate every later episode (test)

### t7 — Chain view accounting on the artifact

- instruction: Owns colleague/contract.py (ChainView dataclass + TaskResult field, from_dict/to_dict round-trip) + colleague/artifact.py rendering + NEW tests/test_chain_view.py. Additive fields only — the all-engines shape guard (test_e2e_mock.py) must keep passing.
- covers: c20, h19
- acceptance:
  - TaskResult carries an optional chain view (episode index, episode count so far, totals) whose tokens/steps are SUMS of per-episode exact usage — never estimated (tokens-are-exact rule); omit-when-absent keeps ordinary runs' artifacts byte-identical
  - WorkStats stay per-episode; the final episode's artifact renders the chain totals (test asserts additivity from real per-episode numbers)

### t8 — Chain-aware feedback grading

- instruction: Owns colleague/feedback.py + tests/test_feedback* additions. Traversal walks artifacts via find_artifact + continued_from with a visited-set; per-episode grade records keep today's schema plus a chain marker.
- covers: c30, h25
- acceptance:
  - grading the last work item traverses continued_from lineage and stamps the grade on EVERY episode of the chain (3-episode test: one record call writes three grades)
  - a lineage cycle or missing artifact terminates traversal cleanly — never loops, never crashes (both tested)

### t9 — Session parity + background forwarding

- instruction: Owns colleague/cli/_commands/session.py (arm via /mode-adjacent flag or session flag parity) + the forwardable-flags list entries in work.py (coordinate with t5 — build after it merges). Tests in tests/test_session*.
- depends on: t5
- covers: c11, h11, c15, h14
- acceptance:
  - the session front arms the same chaining with the same semantics (shared dispatch path — no session-only fork); off a colour TTY behavior is unchanged (test)
  - a --background chain forwards --until-done/--max-episodes to the detached child via the forwardable-flags list (test); all three fronts (work, session, background) reach the armed behavior in this PR

### t10 — E2E chain proofs + dormancy/boundary guards (tests only)

- instruction: Owns NEW tests/test_chain_e2e.py only (plus reading everything). Mock engine drives the chain via scripted finishes/budget exits. Verify the c16 before-state limits are actually removed (re-arm, carry, validation) by asserting against the new behavior. Record the fails-on-main proof by running each named test against main in a throwaway worktree.
- depends on: t2, t5, t6, t7, t8, t9
- covers: c1, h1, c9, h9, c10, h10, c16, h15, c17, h16, c19, h18
- acceptance:
  - chain-completes: a mock-engine task sized to need >= 3 episodes lands its deliverable with status ok, lineage chain length >= 3, zero operator interventions
  - chain-halts-honestly: a deliberately no-progress task halts within 2 episodes reporting non-ok with an incompletion reason
  - compaction-validated: an empty/uncoverable summary never silently replaces history (rejection observable on the trace)
  - dormancy: with no flag/env/config the entire existing suite passes unmodified and a bare work item's artifact is byte-identical; test_boundary.py sanctioned lists unchanged; TaskResult shape identical across mock and vllm-openai (all-engines guard extended)
  - each of the three named tests demonstrably fails on main (TDD baseline recorded in the test file docstring with the command used)

### t11 — Docs: the new line, stated honestly

- instruction: Owns docs/features/*.md + CLAUDE.md + CHANGELOG entry. Follow trim discipline: CLAUDE.md gets a few lines + Doc: pointer; detail lives in docs/features/indefinite-run.md linking the spec/plan. Cite work-lesson-54ead8272f22 (steps=46, budget exhausted) as live evidence.
- depends on: t10
- covers: c14, h13, c18
- acceptance:
  - capacity-standard.md (drops 'fires at most once'), continue-working.md, session-continue-heal.md, graceful-degradation.md, honest-incompletion.md updated + NEW docs/features/indefinite-run.md + the CLAUDE.md architecture bullet — each stating the superseding behavior AND its honest limits (best-effort WIP sweep, crawl risk under --max-episodes 0, per-episode gate cost)
  - the why-it-matters rationale cites at least one recorded work-lesson id (c18); doc-test-alignment check passes; markdownlint clean

### t12 — Live dogfood proof: chained review of this arc's own PR

- instruction: Run AFTER the PR exists: COLLEAGUE_TIMEOUT=300, cap 2 concurrent loops (GPU serializes). Use the checkout's uv run colleague (ask-colleague wrapper may resolve a stale PATH CLI). Verify the review actually finished (recorded gotcha: mid-thought narration can masquerade as a result). This is the live pass criterion for the whole arc.
- depends on: t11
- covers: h17
- acceptance:
  - an ask-colleague review of this arc's PR diff runs with chaining armed on the live rig and DELIVERS a verdict (findings or a clean pass) instead of dying at its budget — episodes > 1 observed in the lineage (decision c25)
  - the outcome is reported honestly in the delivery summary, including a negative result (e.g. the 27B loops without progress) if that is what happens (h17)

## Risks

- [unknown_nonblocking] live-model behavior under chaining is unproven until t12: the 27B may loop or stall across episodes in ways mock cannot show (recorded precedent: 27B cannot 3-way decompose under self-load)
- [unknown_nonblocking] colleague/loop.py is a 4131-line shared surface: t1 and t2 are deliberately serialized on it; every other task must keep out of loop.py or the waves' file-disjointness breaks
- [unknown_nonblocking] t5 and t6 both touch the chain-loop skeleton in work.py: t6 is sequenced after t5 via its dep on t3 only — if line-level conflicts emerge, build t6 after t5's merge (recorded coordination note in both instructions)
