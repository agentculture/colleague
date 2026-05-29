# Build Plan — Convertible knows its destination before it drives: a curated devague tool lets an engine set and converge a goal-frame when a task warrants one, drive toward it, and declare the announcement on arrival — so convertible knows where it's going, not just where it is.

slug: `convertible-knows-its-destination-before-it-drives` · status: `exported` · from frame: `convertible-knows-its-destination-before-it-drives`

> Convertible knows its destination before it drives: a curated devague tool lets an engine set and converge a goal-frame when a task warrants one, drive toward it, and declare the announcement on arrival — so convertible knows where it's going, not just where it is.

## Tasks

### t1 — convertible/devague.py — shell out to the operator-installed devague CLI with cwd + CONVERTIBLE_IDENTITY injected; a curated move allow-list that structurally excludes the user-only moves (confirm/reject) and the operator-only export. New module + tests/test_devague.py only.

- covers: c2, h2, c6, h6, h7, h3
- acceptance:
  - run_devague(move, args, *, cwd, identity) launches the resolved devague binary as a subprocess and NEVER imports devague; parses --json output when requested
  - the allow-list permits new/capture/interrogate/park/converge/status/show and REJECTS confirm/reject/export with a typed error (test asserts a rejected move never spawns a subprocess)
  - cwd is the repo path and CONVERTIBLE_IDENTITY is injected into the subprocess env exactly as convertible/culture.py does (test asserts env + cwd propagation via a fake binary)
  - a missing devague binary yields a graceful typed error (no traceback), mirroring culture.py resolution

### t2 — convertible/tools.py — add the 'devague' tool schema + ToolExecutor._devague dispatch in the single chassis tool surface (mirrors _culture); no engine module references it. Touches tools.py + tests/test_tools.py.

- depends on: t1
- covers: c9, h9
- acceptance:
  - the 'devague' tool appears in the loop tool schema with a description naming the allow-listed moves; _devague dispatches to convertible.devague.run_devague
  - an excluded move (confirm/reject/export) returns a tool-error string to the model, never a crash
  - test asserts both engines (mock + vllm-openai) expose the devague tool identically (all-engines rule) and no engine module imports convertible.devague

### t3 — convertible/contract.py + convertible/artifact.py — additive optional TaskResult fields for the destination (frame ref + declared announcement), default None so existing results are byte-identical. Touches contract.py + artifact.py + their tests.

- covers: c8, h8
- acceptance:
  - TaskResult gains optional destination + announcement fields defaulting to None; to_dict/from_dict round-trip them
  - a TaskResult with no destination serializes identically to today (golden/byte-identical assertion; new keys null or absent per existing convention)
  - the JSON artifact records the lightweight arrival declaration only when a destination was set; absent otherwise

### t4 — Engine-base system-prompt guidance (chassis-owned, inherited by every engine): the engine MAY set a destination via the devague tool when a task is vague/new, treats convergence as ADVISORY, cannot confirm its own claims, and declares the announcement on arrival. Touches the Engine base system_prompt path (engine.py/layers.py) + its test.

- depends on: t2, t3
- covers: c1, c3, c5, c10, h10
- acceptance:
  - the Engine base system prompt (inherited by mock + vllm-openai) includes guidance that setting a destination is OPTIONAL + engine-judged, never forced, and that arrival is declared via the announcement
  - the guidance states convergence is advisory and the engine cannot self-confirm (reinforces h3/h7)
  - test asserts the guidance is present in the composed system prompt for every engine (all-engines)
  - a clear task that does not warrant a destination drives normally with no devague subprocess invoked (test)

### t5 — Integration guards: e2e shape unchanged when no destination set, zero-deps guard imports convertible.devague, termination preserved when a destination IS set, and a characterization test of the before-state. Touches tests/test_e2e_mock.py + tests/test_zero_deps.py + new tests/test_destination_e2e.py only.

- depends on: t1, t2, t3, t4
- covers: h1, c4, h4
- acceptance:
  - tests/test_e2e_mock.py still passes: a no-destination drive yields a TaskResult of identical shape (mock = contract reference)
  - tests/test_zero_deps.py imports convertible.devague and still asserts no third-party leak (zero-deps holds with the new module, even with [otel] installed)
  - a drive that sets a destination AND declares arrival still terminates within max_steps via finish/empty-turn/budget (h1; test bounds it, no socket/daemon opened)
  - a characterization test pins the before-state: without this feature the Task/loop carry no goal/convergence concept; the new fields are additive + default-off (h4)

### t6 — Docs: add 'Destination' to the CLAUDE.md car-metaphor list (sibling to GPS), document the devague tool + allow-list + advisory-convergence boundary, and a worked example where a vague task benefits from a destination. Touches CLAUDE.md + README.md + docs/features/destination.md + docs/features/README.md only.

- depends on: t2, t3, t4
- covers: h5
- acceptance:
  - CLAUDE.md gains a Destination entry in the car-metaphor list and states the shell-out/no-dep/no-socket/no-daemon + advisory-convergence boundary
  - docs/features/destination.md includes a worked example of a vague task where setting a destination measurably changes the outcome (h5), plus the allow-list and the lightweight-arrival behavior
  - README references the destination feature and docs/features/README.md indexes it

## Risks

- [unknown_nonblocking] Exact allow-list set: proposed new/capture/interrogate/park/converge/status/show; exclude confirm/reject (user-only) and export (operator-only, since arrival is lightweight). h6 noted export as CLI-reachable but the engine does not need it. Final set is a small build-time call.
