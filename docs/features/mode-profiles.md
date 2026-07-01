# Mode profiles — each work mode carries its own compute/context budget

> Tracking: [colleague#254](https://github.com/agentculture/colleague/issues/254) ·
> spec R1 in
> [`docs/specs/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md`](../specs/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md).

Before this feature, every work mode (`work`, `plan`, `explore`, `review`)
shared one global knob set — the only per-mode tuning lived caller-side, baked
into `ask-colleague.sh` (a hardcoded `--max-steps 30` plus an exported
`COLLEAGUE_SYNTHESIS_RESERVE_STEPS=3` for `explore`/`review`). Now selecting a
mode resolves a **named profile** — step budget, context-budget fraction,
synthesis reserve, timeout, fill-line threshold — through the runtime's own
config-resolution precedence, so the numbers live in one place and every
caller (CLI, session, `ask-colleague`) gets them for free.

## The catalog (`colleague/profiles.py`)

`MODE_PROFILES` is a `dict[str, Optional[ModeProfile]]` with **exactly one
explicit entry per `colleague.session_modes.MODES` name** — a drift test
(`tests/test_profiles.py`) pins `set(MODE_PROFILES) == set(MODES)` so a new
mode can never ship without an explicit profile decision, even if that
decision is "no profile."

| Mode | max_steps | context_budget_fraction | synthesis_reserve_steps | timeout | fillline_threshold |
|------|-----------|--------------------------|--------------------------|---------|---------------------|
| `auto` | — | — | — | — | — (`None`: resolves to a concrete mode first) |
| `work` | 40 | 1.0 | 0 | 120.0 | 0.8 |
| `explore` | 30 | 0.75 | 3 | 120.0 | 0.7 |
| `review` | 30 | 0.75 | 3 | 120.0 | 0.7 |
| `plan` | 40 | 0.9 | 0 | 120.0 | 0.8 |

`work`'s profile is **deliberately** exactly today's built-in `EngineConfig`
defaults (`max_steps=40`, `context_budget_fraction=1.0` i.e. unscaled,
`timeout=120.0`, `synthesis_reserve_steps=0`, `fillline_threshold=0.8`) — the
R1 honesty condition that selecting `work` mode is behavior-neutral.
`explore`/`review` get a smaller reading budget, a reserved tail for the
verdict turn (#197), and a lower fill-line so compaction kicks in earlier on
the smaller effective window. `resolve_profile(mode)` is a pure lookup: `None`
for `None`, `"auto"`, or an unknown name; no I/O, no env reads.

`colleague/profiles.py` is a deliberately **leaf** module — it imports nothing
from `colleague.config` or `colleague.loop`, so the catalog stays trivially
testable and free of the precedence machinery that consumes it.

## The precedence layer (`colleague/config.py` `apply_mode_profile`)

`apply_mode_profile(config, mode, *, explicit=(), repo_path=None)` is applied
**after** `EngineConfig.resolve()`, filling only the knobs the operator left
untouched. Full precedence per knob:

```text
explicit flag > COLLEAGUE_*/CONVERTIBLE_* env > per-model overlay
> repo overlay > built-in mode profile > resolved value untouched
```

- **`explicit`** names the `EngineConfig` fields the caller set from a CLI
  flag (e.g. `{"max_steps"}` when `--max-steps` was given) — those knobs are
  never overwritten by a profile.
- An env var counts as "already decided" too — `_env_present` checks the same
  `COLLEAGUE_*`/legacy-`CONVERTIBLE_*` pairs every other knob resolution reads
  (`COLLEAGUE_MAX_STEPS`, `COLLEAGUE_TIMEOUT`, `COLLEAGUE_CONTEXT_BUDGET`,
  `COLLEAGUE_FILLLINE_THRESHOLD`, `COLLEAGUE_SYNTHESIS_RESERVE_STEPS`).
- **Operator overlays** — `.colleague/profiles.json` (repo/user, via
  `configdir`) and a **per-model** `.colleague/<sanitize_model(model)>/profiles.json`
  — both shaped `{mode: {knob: value}}`. The per-model path is built by exact
  construction through `colleague.layers.sanitize_model`: model X never loads
  model Y's overlay, the same isolation convention as hooks/skills/approvals.
  The per-model overlay is consulted *before* the repo overlay (per-model-first
  precedence), and both win over the built-in catalog profile.
- `context_budget_tokens` is the one knob with two shapes: an overlay may set
  an absolute `context_budget_tokens` int, or a `context_budget_fraction` in
  `(0, 1]` applied to the *already-resolved* base budget (the built-in default
  or a `COLLEAGUE_CONTEXT_BUDGET` override) — the fraction composes with
  whatever budget resolution already produced, rather than competing with it.

**Strict no-op guarantees:** `apply_mode_profile` returns `config` itself
(same object) for a falsy/unknown mode, when no profile/overlay defines the
mode, or when every knob is already operator-decided — so a run with no mode
selected is byte-identical to today (the e2e mock shape test stays green).

## One code path for every entry door

`apply_mode_profile` is called from exactly one place:
`colleague/cli/_commands/work.py`'s `execute_work`, right before the engine is
loaded:

```python
if mode:
    config = apply_mode_profile(config, mode, explicit=explicit_knobs, repo_path=repo)
```

Both the `colleague work --mode <m>` flag and the interactive session's mode
selection route through `execute_work`, so they resolve the identical profile
— there is no second assembly path to drift.

- **`colleague work --mode`** — `_validated_mode()` checks the value against
  `colleague.session_modes.MODES` and raises a clean, choices-shaped
  `CliError` on a typo (never a silent no-op profile). `--mode` is validated
  explicitly and early rather than via a parse-time `Flag(choices=)` — the
  same reason `--algo` is: it would collide with a value-carrying flag at App
  build time (see `CLAUDE.md`'s agentfront-adoption note). `explicit_knobs` is
  `frozenset({"max_steps"})` when `--max-steps` was passed, else empty — the
  only CLI flag among the profiled knobs today.
- **Session mode selection** — `session.py`'s `_dispatch_work` forwards
  `mode=` straight into the same `work_fn` (`execute_work`) call. `_run_work`
  passes `mode="work"` (behavior-neutral by construction, but keeps the
  one-code-path claim honest and lets an operator overlay tune session `work`
  runs too); `_run_readonly` passes `mode="explore"` / `mode="review"` for the
  session's explore/review paths. A session explore/review run gets its
  profile's budgets with **zero env vars set**.

## `ask-colleague.sh` adoption (t4)

`.claude/skills/ask-colleague/scripts/ask-colleague.sh`'s `explore`/`review`
step budget and synthesis-reserve tail used to be **caller-side overrides**
baked into the wrapper (a fixed `--max-steps 30` plus an exported
`COLLEAGUE_SYNTHESIS_RESERVE_STEPS=3`). Those numbers now live in colleague's
own `explore`/`review` profiles and are applied runtime-side — the wrapper's
job shrinks to *selecting the mode*, so a future retune of the profile reaches
every `ask-colleague` caller for free.

- The wrapper detects whether the resolved `colleague` CLI actually supports
  `--mode` by checking its own `--help` output (`MODE_SUPPORTED`), anchored
  past the flag name so a stale `--help` that only lists `--model` cannot
  false-positive-match `--mode` (`--mode` is a literal prefix of `--model`).
- **Native path** (`MODE_SUPPORTED=1`): `explore`/`review` pass `--mode
  explore|review` and withhold `--max-steps` (unless the caller passed an
  explicit `--max-steps`, which always wins in either direction — the wrapper
  still forwards it, and `apply_mode_profile`'s `explicit`-knobs precedence
  resolves it ahead of the profile).
- **Stale-CLI fallback** (`MODE_SUPPORTED=0`, a checkout predating `--mode`):
  the wrapper falls back to its old caller-side defaults — `--max-steps 30`
  for `explore`/`review` and `COLLEAGUE_SYNTHESIS_RESERVE_STEPS=3` exported —
  so the wrapper keeps working against an older colleague checkout.
- `write` carries no `--mode` at all — its profile would be behavior-neutral
  (identical to no mode), so the wrapper's documented numbers
  (`--max-steps 20`, no reserve override) stay exactly as they were.

## Deviation from the plan

The plan's t2 acceptance criterion mentions "`ContextControls` threading," but
the built profile layer needed **no** `ContextControls` changes at all: because
`apply_mode_profile` runs on the `EngineConfig` itself, before
`ContextControls.from_config(config)` is ever built, every profiled knob
(`max_steps`, `context_budget_tokens`, `synthesis_reserve_steps`, `timeout`,
`fillline_threshold`) reaches the loop through the *existing*
`EngineConfig` → `ContextControls.from_config` mapping unchanged. This is a
smaller, more surgical change than the plan anticipated — no new
`ContextControls` field, no backend-side forwarding code.

## Honest limits

- **The exact per-mode numbers are conservative defaults, not tuned
  constants** — the plan's risk r1: they are deliberately parked pending
  live tuning on a working served model, and may be adjusted in a follow-up PR
  without changing this module's shape.
- **The `plan` verb's own path is not profiled.** `colleague plan run` drives
  the model through `Engine.make_complete` (a one-shot completion seam
  outside the bounded tool-loop, see `docs/features/plan-mode.md`), not
  through `execute_work` — so `apply_mode_profile` never touches it. Only a
  work item *entered* in "plan" mode (e.g. via session mode selection, before
  the free-text router hands off to the plan verb) resolves the `plan`
  profile.
- **Only `--max-steps` is a CLI-level explicit knob today** — `timeout`,
  `context_budget_tokens`, `synthesis_reserve_steps`, and
  `fillline_threshold` have no dedicated CLI flag, so "explicit" for them
  means only "the corresponding env var is set," never a flag.
- **Per-model profile overlays are read fresh per call** — there is no cache
  invalidation concern because `configdir.resolve_file` always reads the
  current file; a malformed overlay file degrades to "no overlay," never a
  crash (the malformed-config convention shared with hooks/approvals/config.json).

## Spec + plan

- Spec: [`docs/specs/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md`](../specs/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md)
- Plan: [`docs/plans/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md`](../plans/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md)
  (tasks t1-t4)

## See also

- [`docs/features/session-modes.md`](session-modes.md) — the `auto/work/plan/explore/review`
  mode catalog + shift-tab cycling this feature's profiles hang off of
- [`docs/features/tier-visibility.md`](tier-visibility.md) — the session
  Capacity panel's "mode profile" row that surfaces the active profile
- [`docs/features/ask-colleague.md`](ask-colleague.md) — the wrapper that adopts
  native profiles
