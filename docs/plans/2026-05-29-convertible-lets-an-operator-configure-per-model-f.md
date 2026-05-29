# Build Plan — Convertible lets an operator configure per-model fixes that adapt the harness to a model's known biases, so a recurring defect from one model is corrected only when that model is driving and never leaks to other models.

slug: `convertible-lets-an-operator-configure-per-model-f` · status: `exported` · from frame: `convertible-lets-an-operator-configure-per-model-f`

> Convertible lets an operator configure per-model fixes that adapt the harness to a model's known biases, so a recurring defect from one model is corrected only when that model is driving and never leaks to other models.

## Tasks

### t1 — Per-model hooks resolution + composition in hooks.py: load_hooks gains an optional model param; resolves .convertible/<sanitize_model(model)>/hooks.json via configdir exact-path (repo-over-user, within-root confinement) and composes per-model entries BEFORE base entries per event, so the existing first-deny/rewrite-wins gives per-model precedence

- covers: c3, c4, c10, h3
- acceptance:
  - load_hooks(repo, model='X') merges .convertible/X/hooks.json entries before base .convertible/hooks.json entries for each event; hooks_for(event,tool) returns per-model matches first
  - the per-model path is built by exact construction via layers.sanitize_model — no glob/iteration of sibling .convertible/*/ dirs; a fix under .convertible/Y/hooks.json is never loaded when model='X'
  - load_hooks with model=None, or a model whose overlay file is absent, returns a HookConfig byte-identical to today's base-only load
  - a malformed/unreadable per-model hooks.json is skipped (never raises), mirroring base load_hooks resilience; the before-state baseline (no model param pre-change) is captured in a test/docstring

### t2 — Wire the driving model into the loop's hook load (chassis): pass config.model to load_hooks at its call site so a real drive fires the composed per-model+base hook set; hooks stay chassis-owned (all-engines rule)

- depends on: t1
- covers: c1
- acceptance:
  - the drive path loads hooks with the current model so a per-model overlay fires during an actual drive (verified by a loop-level test)
  - with no per-model overlay present, hook firing during a drive is unchanged — the mock engine reference and e2e shape test pass identically

### t3 — Per-model isolation test (tests/test_hooks_per_model.py): prove a fix configured for model X does not fire for model Y, mirroring the layers.py per-model isolation test

- depends on: t1
- covers: h1, h5, h6, h8
- acceptance:
  - configuring .convertible/X/hooks.json with a deny on tool T and loading for model Y asserts the deny does NOT apply (isolation, h6)
  - loading the same config for model X asserts the deny DOES apply, and per-model entries are ordered before base entries (precedence)
  - a base .convertible/hooks.json entry still fires for model X alongside the per-model overlay — the base is not edited or degraded (h8)
  - the test mirrors the layers per-model isolation test structure and lives in its own file (h5)

### t4 — Strict no-op + zero-deps guard for the per-model path: extend tests/test_zero_deps.py to import the per-model hooks path and assert no third-party leak; assert the e2e mock shape test is unchanged when no overlay is present; assert no socket/daemon/mcp.json path is introduced

- depends on: t1, t2
- covers: h2, h9
- acceptance:
  - tests/test_zero_deps.py imports convertible.hooks incl. the per-model resolution and asserts zero third-party imports even with [otel] installed (h9)
  - tests/test_e2e_mock.py passes with no per-model overlay — TaskResult shape byte-identical to today (h2)
  - no new code path opens a socket, forks a daemon, or reads mcp.json; pyproject dependencies stay []

### t5 — CLI surface: convertible hooks list --model <m> shows the composed per-model+base set with per-model entries first and tagged by source scope; update hooks overview/explain to document the overlay + precedence

- depends on: t1
- covers: c1
- acceptance:
  - convertible hooks list --model X --json lists per-model entries (from .convertible/X/hooks.json) before base entries, each tagged with its scope; results to stdout, diagnostics to stderr
  - convertible hooks list with no --model is byte-identical to today (base-only) and --json stays parseable
  - convertible explain hooks documents the per-model overlay path and the per-model-first precedence

### t6 — Worked example + docs: a per-model hooks overlay that corrects the F9 footer bias (deny/rewrite a write_file whose footer links outside the served docroot), plus document the overlay (.convertible/<model>/hooks.json), composition order, and operator-declared framing in CLAUDE.md + README + the layered-config feature doc

- depends on: t1, t5
- covers: c2, c5, c7, h7
- acceptance:
  - a worked example shows a per-model hook detecting+correcting the F9 external-ref footer (../README.md) so the output no longer escapes the docroot, affecting only the targeted model (c7)
  - CLAUDE.md + README describe the per-model hooks overlay path, the per-model-first precedence, and that it adds no new dep/socket/daemon (c5; audience framing c2)
  - docs state the bias is operator-declared and recurring — convertible does not auto-detect it (h7)
  - a feature doc docs/features/per-model-configuration.md frames the feature with convertible's car metaphor — the harness can 'adjust seat and mirrors' to fit the specific model (the driver) — and is linked from the docs/features feature index

## Risks

- [follow_up] Deferred (parked in the spec): a per-model post-finish output-validation/correction pass as a third lever beyond prompt-steer + per-model hooks — out of scope for this plan
- [unknown_nonblocking] t2 wiring point: confirm where load_hooks is currently invoked and that config.model is in scope there (loop.py vs drive.py); the edit site moves accordingly (task t2)
