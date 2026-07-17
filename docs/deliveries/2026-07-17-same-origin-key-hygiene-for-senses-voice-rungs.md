# Delivery Summary — same-origin key hygiene for senses/voice rungs

plan: `same-origin-key-hygiene-for-senses-voice-rungs` · run: `complete` · date: `2026-07-17`
baseline: `devague summary skeleton`

## Intent

Extend the same-origin `api_key` hygiene the deepthink discovery rung got
in #347 (Qodo finding) to the two remaining lobes discovery rungs — senses and
voice — so the main Bearer token is never forwarded to a cross-origin
wire-advertised endpoint, with explicit keys (env, or a model-less
`config.json` section) as the arming path. Executed as a four-task,
three-wave `/assign-to-workforce` run (waves `[t1,t3] → [t2] → [t4]`, sonnet
subagents in isolated worktrees, TDD-gated merges) from the challenged spec
`docs/specs/2026-07-17-same-origin-key-hygiene-for-senses-voice-rungs.md`.

## Planned Work

Quoted verbatim from the `devague summary` skeleton:

- `t1` — senses rung: _senses_lobes_fallback extraction + 4-test hygiene block
- `t2` — voice rung: _voice_lobes_fallback with the conservative single-field rule + per-role hygiene tests
- `t3` — docs: hygiene lines in cortex-senses.md and senses-live-presence.md
- `t4` — verification sweep + version bump + CHANGELOG upgrade note

## Actual Delivery

| Plan task | Status | What actually landed |
|-----------|--------|----------------------|
| `t1` | delivered | `_senses_lobes_fallback` in `colleague/config.py` (mirrors `_deepthink_lobes_fallback` field-for-field; call site passes `file_senses`) + 4 hygiene tests in `tests/test_config_lobes.py`; commit `62563f3`, merged `5654c5d`. 3 tests demonstrably red pre-fix, 1 pins pre-existing same-origin inheritance. |
| `t2` | delivered | `_voice_lobes_fallback` with the conservative single-field rule (decision c15: main key inherited iff EVERY armed role same-origin; no `CONVERTIBLE_VOICE_API_KEY` invented) + 6 hygiene tests in `tests/test_voice_config.py` incl. the mixed-origin case; commit `2c3e85a`, merged `0cbed21`. 5 red pre-fix, 1 pinning. |
| `t3` | delivered | Hygiene passages in `docs/features/cortex-senses.md` + `docs/features/senses-live-presence.md`, mirroring `deepthink.md`'s wording, citing #349; commit `0895592`, merged `dad1f20`, plus operator fixup `dfd8436` (see drift). markdownlint clean. |
| `t4` | delivered | Verification sweep (full suite, red-on-main demo, protected-surface zero-diff, all lint gates) + v1.51.0 + CHANGELOG upgrade note; commit `e35ed67` (includes the `uv.lock` re-lock from the version bump). |

## Mid-work Decisions

No `/deviate` records — the run followed the confirmed plan. Decisions not
covered by any record, captured directly:

- Arc-scoped worktree branch names (`agent/348-tN` instead of the skill's
  `agent/tN`) — a stale `agent/t1` branch from an earlier workforce run
  collided; scoping avoids deleting another run's branch unexamined.
- The t3 subagent's voice passage implied the per-role key split was tracked
  at #349; the operator scoped that citation post-merge (`dfd8436`) so #349
  is cited only for the withheld-key notice — the split stays a deliberately
  unfiled follow-up, matching the plan text.
- `uv.lock` re-locked when `uv run` first saw the 1.51.0 bump; folded into the
  t4 commit by amend rather than a stray commit.
- User-requested live-test addendum (not a plan task): reference-rig
  resolution proof, cross-origin fake-gateway probe (unarmed + armed), a real
  rig work item, and a direct senses-lane completion — all read-only against
  the repo; results under Evidence.
- The t2 subagent's report said "7 tests"; 6 landed (miscount in the report,
  ≥5 required — verified by counting `^+def test` in the merge diff).

## Drift From Plan

| Plan item | Reason for divergence | Classification |
|-----------|-----------------------|----------------|
| `t3` | delivered passage over-scoped the #349 citation (implied the per-role split is tracked there); corrected post-merge in `dfd8436` — content otherwise per contract | acceptable |

No other drift: `t1`, `t2`, `t4` delivered to their acceptance criteria as
confirmed (task-by-task accounting above).

## Evidence

- tests (post-merge, full): `uv run pytest -n auto -q` — 6598 passed, 20 skipped
- tests (red-on-main): the 10 new hygiene tests run at pre-implementation tip
  `0621b3b` — 8 failed / 3 passed (the 8 behavior-encoding tests red; pinning
  tests green; 1 pre-existing test matched the selector)
- tests (affected files, post-merge): `tests/test_config_lobes.py`
  `tests/test_config_senses.py` `tests/test_config_lobes_deepthink.py`
  `tests/test_voice_config.py` — 120 passed
- protected surface: `git diff main...HEAD` shows zero edits inside
  `_same_origin`, `_deepthink_lobes_fallback`, `_resolve_senses`,
  `_resolve_voice`; zero changes to `tests/test_config_lobes_deepthink.py`
- lint: `black --check` / `isort --check-only` / `flake8` / `bandit -c
  pyproject.toml -r colleague` / `teken cli doctor . --strict` — all clean
- live (reference rig, gateway `:8001`): discovered senses/voice/deepthink all
  resolve INHERITED-MAIN — byte-identical; senses-lane chat completion with
  the inherited key returned HTTP 200
- live (cross-origin fake gateway): unarmed → both rungs resolve the no-auth
  default; `COLLEAGUE_SENSES_API_KEY`/`COLLEAGUE_VOICE_API_KEY` → explicit
  tokens land
- live (rig work item): authenticated completion; run reported honest
  `incomplete` — the pre-existing #346 literal-`<tool_call>` rig condition,
  not this change
- commits: `cc77993..e35ed67` (spec → challenge → plan → 3 TDD-gated waves → t4)
- PRs / issues: PR #350 (CI test job pass; Qodo 0 bugs / 0 rule violations /
  0 requirement gaps; 0 inline threads) · closes #348 · filed #349

## Delivery Claims

| Claim | Confidence | Evidence |
|-------|------------|----------|
| A cross-origin discovered senses role no longer inherits the main key; explicit env/model-less-section keys arm it | high | test `tests/test_config_lobes.py::test_cross_origin_senses_does_not_inherit_main_api_key` (+3 siblings) · live cross-origin probe · commit `62563f3` |
| The voice rung enforces the conservative single-field rule incl. the mixed-origin case | high | test `tests/test_voice_config.py::test_mixed_origin_roles_resolves_default_api_key` (+5 siblings) · commit `2c3e85a` |
| Same-origin rigs are byte-identical (reference deployment unaffected) | high | live reference-rig resolution (all roles INHERITED-MAIN) · senses-lane HTTP 200 · pinning tests · 6598-test suite green |
| Deepthink rung and declared senses/voice paths untouched | high | `git diff main...HEAD` protected-surface check · `tests/test_config_lobes_deepthink.py` unchanged and passing |
| Docs + CHANGELOG carry the rule, arming paths, and upgrade note | high | files `docs/features/cortex-senses.md`, `docs/features/senses-live-presence.md`, `CHANGELOG.md` (1.51.0) · commits `0895592`, `dfd8436`, `e35ed67` |
| The rig's cortex tool-calling works end-to-end after this change | unverified | pre-existing #346 markup collapse blocks any work-item proof; auth proven (completion returned), tool-calling not attributable to this change |

## Remaining Work / Follow-up

- PR #350 — human review + merge (gate 3); Sonar quality gate still computing
  at write time (0 open issues, 0 hotspots so far).
- #349 — unified withheld-key stderr notice across all three discovery rungs +
  the livecheck 401-reads-as-up nuance (filed from this arc's challenge pass).
- Frame park v2 — docs caveat that the explicit arming key follows the
  wire-advertised endpoint (a three-docs sweep incl. `deepthink.md`); unfiled
  by decision.
- Per-role `stt_api_key`/`tts_api_key` split — named follow-up from decision
  c15; unfiled by decision, revisit if a real mixed-origin voice rig appears.
- #346 — rig cortex emits literal `<tool_call>` text (pre-existing, observed
  again in this run's live work item); owned outside this arc.
