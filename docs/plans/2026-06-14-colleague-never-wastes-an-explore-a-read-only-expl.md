# Build Plan — colleague never wastes an explore: a read-only explore/drive that exhausts its step budget forces one final no-tools synthesis turn and returns a usable partial answer; a run that truly produces nothing reports a distinct non-ok status instead of a misleading status:ok so callers like ask-colleague can detect-and-retry without sentinel string-matching; explore gets a step budget tuned for codebase-mapping; and the ask-colleague wrapper resolves the colleague CLI with zero external-tool dependencies.

slug: `colleague-never-wastes-an-explore-a-read-only-expl` · status: `exported` · from frame: `colleague-never-wastes-an-explore-a-read-only-expl`

> colleague never wastes an explore: a read-only explore/drive that exhausts its step budget forces one final no-tools synthesis turn and returns a usable partial answer; a run that truly produces nothing reports a distinct non-ok status instead of a misleading status:ok so callers like ask-colleague can detect-and-retry without sentinel string-matching; explore gets a step budget tuned for codebase-mapping; and the ask-colleague wrapper resolves the colleague CLI with zero external-tool dependencies.

## Tasks

### t1 — R2 contract: add an INCOMPLETE run status and a non-zero exit for any non-clean-finish run

- covers: c9, h3
- acceptance:
  - colleague/contract.py defines an INCOMPLETE status distinct from OK and ERROR; the loop sets it for any _work_loop exit other than _EXIT_FINISHED, and status:ok is reached only via a clean finish.
  - tests/test_e2e_mock.py asserts a clean finish is status:ok with exit 0 while an unfinished (budget or stopped) run is status:incomplete with a non-zero exit, identically for mock and the vllm shape (all-engines).
  - a genuine successful finish is unchanged (status:ok, exit 0); the exact non-zero code composes with the existing tri-state 0/1/2 convention ask-colleague.sh already propagates.

### t2 — R5 grep-free ask-colleague.sh resolver via pure-bash _pyproject_is_colleague

- covers: c12, h6
- acceptance:
  - ask-colleague.sh _colleague_via_uv uses a pure-bash _pyproject_is_colleague check; no grep invocation remains anywhere in the script, asserted by a test scanning the script source.
  - a regression test stubs colleague off a grep-less PATH, points --repo at a checkout, and asserts resolution via uv run --project (mirrors the existing no-python3 and no-mktemp tests).
  - the stale comment claiming grep is only used by the uv-fallback resolver is corrected; black, isort, flake8, bandit and teken cli doctor --strict stay clean.

### t3 — R1 forced no-tools synthesis turn on budget/stopped exhaustion

- depends on: t1
- covers: c8, h2, c3, h8
- acceptance:
  - when _work_loop exits via _EXIT_BUDGET or _EXIT_STOPPED with non-trivial context read and no finish, the loop runs exactly one no-tools completion (out of steps; answer now from what you have read) and uses its text as summary; mirrors _finalize_after_cap, runtime-owned so it fires for every backend.
  - tests/test_loop.py: a scripted run that consumes the whole max_steps budget on tool calls yields the forced-synthesis text as summary, not NO_RESULT_PRODUCED, on mock.
  - NO_RESULT_PRODUCED is returned only when the forced turn also yields empty (immediate stop, zero context read); existing genuinely-empty-case assertions in test_loop and test_clone_lifecycle still pass.

### t4 — R3 advisory subagent fan-out for read-only mapping runs

- depends on: t3
- covers: c10, h4, c4, h9, c6, h11
- acceptance:
  - during a read-only mapping run, when files-read crosses the threshold N or context crosses the fill-line threshold, the loop injects exactly one structured fan-out recommendation naming a concrete per-folder or N-file partition and the subagents tool.
  - the recommendation is advisory: when the model declines, TaskResult is byte-identical to today (strict no-op), asserted by a not-triggered test; it fires identically for mock and the vllm shape.
  - read-only fan-out reuses make_batch_spawn/batch_spawn with no new worktree or merge code, spawns no merge child, opens no PR, and respects MAX_SUBAGENT_FANOUT and MAX_SUBAGENT_DEPTH; the zero-deps guard stays green.

### t5 — R4 ask-colleague re-run hint, modest budget, status/exit branching, subagent steer

- depends on: t1, t2
- covers: c11, h5, c2, h7, c5, h10
- acceptance:
  - ask-colleague.sh partial warning prints the actual step count reached and a concrete larger --max-steps value to retry with; a test asserts the hint contains both.
  - ask-colleague.sh branches on the run status and exit code (not the NO_RESULT_PRODUCED sentinel string): an incomplete run prints a no-result / widen-scope warning instead of the success-shaped grade footer; a test asserts this.
  - --max-steps still overrides the default in both directions; any change to write or review defaults is reflected in SKILL.md and the --help usage block; prompts/explore.md steers toward subagents for wide maps.

### t6 — Integration: docs, CLAUDE.md, version bump, and all guards green

- depends on: t1, t2, t3, t4, t5
- covers: c1, h1, c7, h12
- acceptance:
  - CLAUDE.md documents the explore run-completion behavior (forced synthesis, incomplete status, advisory fan-out, grep-free resolver) and its honest limits; CHANGELOG.md gains an entry; pyproject.toml and __init__.py are version-bumped per the version-check CI gate.
  - the full suite is green: e2e mock-vs-vllm shape test, zero-deps guard, and the new R1-R5 regression tests; teken cli doctor --strict clean.
  - each of the four threads (forced synthesis, incomplete status, advisory fan-out, grep-free resolver) is independently demonstrable via its task's test.

## Risks

- [unknown_nonblocking] Default value of N and whether the fan-out trigger keys off files-read count, the context fill-line threshold, or both. Proposed: fire on whichever crosses first, N env-tunable, reuse the existing fill-line plumbing. (task t4)
- [unknown_nonblocking] Whether read-only fan-out may use all 4 MAX_SUBAGENT_FANOUT slots (no merge child reserved for a read-only map) or stays capped like the write path. Proposed: reserve no merge slot but stay within the existing cap. (task t4)
- [unknown_nonblocking] R2 broadens status from ok to incomplete for ANY unfinished run; existing tests and consumers that expect status:ok on a not_finished run (ask-colleague.sh not_finished handling, test_loop, test_clone_lifecycle) must be audited and updated so genuine partials are not mis-flagged. (task t1)
