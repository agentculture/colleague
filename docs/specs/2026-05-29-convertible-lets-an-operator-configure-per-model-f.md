# Convertible lets an operator configure per-model fixes that adapt the harness to a model's known biases, so a recurring defect from one model is corrected only when that model is driving and never leaks to other models.

> Convertible lets an operator configure per-model fixes that adapt the harness to a model's known biases, so a recurring defect from one model is corrected only when that model is driving and never leaks to other models.

## Audience

- operators running convertible against a specific model (or small fixed set) whose output has known, recurring biases — e.g. always linking outside the served docroot (finding F9), or chronically over-long output

## Before → After

- Before: per-model adaptation today is prompt-only (AGENTS.convertible.<model>.md, structurally isolated in layers.py); deterministic fixes exist as hooks (pre_tool deny/rewrite, hooks.py) but hooks match only on a tool-name regex and carry no model dimension (.convertible/hooks.json) — so the two mechanisms do not compose and no fix can be scoped to a single model
- After: an operator declares a fix per model and the harness applies it only when that model drives — a prompt-level steer, a deterministic tool-call rewrite/deny, or both — mitigating that model's known bias automatically across every drive of that model

## Why it matters

- one harness, many engines: each model fails differently; the harness should adapt to the model rather than force every model to be perfect or pollute shared config with one model's quirks

## Honesty conditions

- a fix configured for model X demonstrably does not alter a drive of model Y — the 'never leaks to other models' guarantee is backed by a passing per-model isolation test, mirroring the layers.py isolation pattern
- the targeted bias is operator-declared and recurring/reproducible across drives, not a one-off — the audience is operators who can name a model's failure mode, not users expecting automatic detection
- when driving model X the harness builds X's exact fix path and never loads model Y's fix — exact-path construction, no sibling globbing (the same isolation guarantee layers.py provides)
- a model with no configured fix sees byte-identical behavior to a fix-free run — strict no-op; the mock engine reference and the e2e shape test still pass
- verifiable in code: load_hooks (hooks.py:181) reads .convertible/hooks.json with a tool-name matcher and no model parameter, and HookEntry carries no model field
- adding a per-model fix for model X neither requires editing nor degrades the shared model-blind .convertible/hooks.json that other models rely on — shared config stays usable by all models
- the mechanism reuses subprocess-based hooks plus file-based layered config only — no runtime dependency, no socket, no daemon, no mcp.json read
- there is an isolation test proving a fix configured for model X does not fire for model Y, mirroring the layers per-model isolation test
- the implementation adds exactly one new config surface (.convertible/<model>/hooks.json) and reuses the existing layers.py + hooks.py + configdir machinery — verifiable by: no new runtime dependency in pyproject.toml, the zero-deps guard test still passes, and no socket/daemon/mcp.json code path is introduced

## Success signals

- a configured per-model fix changes behavior for that model only (verified by an isolation test like layers'), is a strict no-op for models with no fix (the mock engine reference + the e2e shape test stay unchanged), and the F9 footer-link bias can be expressed and corrected as a worked example

## Scope / boundaries

- the fix surface is bounded to two composable, already-conventional levers — the existing per-model AGENTS prompt layer (layers.py) and a NEW per-model hooks overlay (.convertible/<model>/hooks.json) — adding no third correction mechanism, no bias auto-detector, and no new transport/runtime/daemon

## Non-goals

- convertible does not auto-detect biases — the operator declares both the bias and the fix; not model fine-tuning; adds no runtime dependency, no socket, no daemon, no live MCP client, no execution sandbox, and no new engine drivers

## Decisions

- leading shape: a per-model hooks overlay — .convertible/<model>/hooks.json resolved by the same sanitize_model + configdir path-construction layers.py already uses, composed with the base model-blind .convertible/hooks.json — reusing subprocess hooks plus file-based layered config, adding no new subsystem
- precedence (resolves q1): a per-model fix is evaluated BEFORE base model-blind hooks; the first deny/rewrite wins, extending hooks.py's existing first-wins semantics so model-specific intent takes priority over shared defaults

## Hard questions

- precedence: when both a per-model fix and a base model-blind hook match the same tool call, does the per-model fix override, run-before, or merge with the base hook — and on a deny/rewrite conflict, which wins?
