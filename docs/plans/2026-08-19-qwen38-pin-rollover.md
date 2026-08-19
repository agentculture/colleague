# Build Plan — qwen38 pin rollover

slug: `qwen38-pin-rollover` · status: `exported` · from frame: `qwen38-pin-rollover`

> colleague's default model pin and rig-sized knobs follow the Spark's cortex rollover: unsloth/Qwen3.6-27B-NVFP4 -> unsloth/Qwen3.8-27B-NVFP4, served at 1,048,576-token YaRN context (issue #404); the stale id 404s on the gateway today

## Tasks

### t1 — Live pre-flight: re-probe the rig and reproduce the before-state

- instruction: curl -H 'Authorization: Bearer $`COLLEAGUE_API_KEY`' <http://localhost:8001/capabilities> and /v1/models; then run one bare 'uv run colleague work' smoke in a throwaway repo (never a dirty tree, #149) with no model pin and capture the 404/refresh-warning evidence. No repo edits in this task — evidence only.
- covers: c1, h1, c14, h6
- acceptance:
  - an authed /capabilities probe at implementation time shows cortex model unsloth/Qwen3.8-27B-NVFP4, context 1048576, ready=true, tools=true (h1)
  - the stale-pin failure is reproduced live BEFORE any fix: a bare run resolving the builtin default either 404s or (lobes-armed) emits the model-refresh warning naming unsloth/Qwen3.6-27B-NVFP4 — output captured verbatim for the PR (h6)

### t2 — Flip the default pin + retune the rig-sized knobs in config.py

- instruction: Touch ONLY the defaults block of colleague/config.py (lines ~59-88) + tests/`test_config.py`:13. Propose 131072 as the budget (128K: conservative end of c10's range; ~2.7x the old 48000) with `MAX_OUTPUT_CHARS` ~68000 (131072 tokens \* ~4 chars \* 13%); state both numbers in the comment. Do not touch senses/deepthink budget defaults (scope entry s16).
- depends on: t1
- covers: c2, h2, c13, h5
- acceptance:
  - colleague/config.py:66 `_DEFAULT_MODEL` == 'unsloth/Qwen3.8-27B-NVFP4' and tests/`test_config.py`'s default assertion matches; the surrounding comment cites the 2026-08-20 /capabilities probe (1048576-token YaRN context)
  - `_DEFAULT_CONTEXT_BUDGET` raised to the chosen moderate value (order 128K-256K per decision c10) with `_DEFAULT_MAX_OUTPUT_CHARS` rescaled to the same ~13%-of-window-chars ratio; the comment records the sizing rationale
  - resolution precedence is byte-identical: every existing precedence test (flag > `COLLEAGUE_MODEL` > config.json > lobes > default) passes UNCHANGED — no precedence test is edited (h2, h5)

### t3 — Harden bounded completions against reasoning-consumes-`max_tokens`

- instruction: Files: colleague/distill.py (the `max_tokens`=1600 completion at ~:559), colleague/oilcheck/`tool_calling.py`, colleague/oilcheck/`three_tier.py`, plus their tests. Measure first (scope entry s14 has the probe recipe: authed POST to /v1/chat/completions), size second. Keep the distill child detached-and-bounded contract intact (memory.md rung 2).
- depends on: t1
- covers: c18, h10, c16, h8
- acceptance:
  - a live sizing experiment with REALISTIC distill prompts (an actual rung-2 cause->lesson->next-delta payload, not a one-liner) is run against the 3.8 and its measured reasoning+content token spend recorded in the PR; new caps derive from that measurement (h10) — if the degradation does not reproduce, the spec's `why_it_matters` is honestly downgraded to theoretical in the PR notes (h8)
  - distill.py's bounded completion either raises `max_tokens` to the measured envelope or handles `finish_reason`=length explicitly; an empty-content completion after the change surfaces as a recorded warning on the artifact, never a silent empty lesson (h10)
  - oilcheck `_PROBE_MAX_TOKENS` (`tool_calling.py`:80, `three_tier.py`:56) is re-validated live against the 3.8: the tool-calling probe still detects tool calls correctly; the cap is raised only if the probe misreports at 128

### t4 — Sweep current-state docs and skills to the new id; document the timeout stance and the overlay hazard

- instruction: Docs/skills files only — zero Python changes in this task. Quote the new context (1,048,576 tokens YaRN) and the t2-chosen budget number where model-selection.md states defaults. Run markdownlint-cli2 on every touched .md.
- depends on: t2
- covers: c3, h3, c19, h11
- acceptance:
  - README.md:106,306, docs/features/model-selection.md:26,79, docs/live-testing.md rig-description rows (~25,~146), .claude/skills/ask-colleague/SKILL.md:30,115 and scripts/ask-colleague.sh:105,184 all carry unsloth/Qwen3.8-27B-NVFP4; every edited line describes current state — no dated proof row, spec, plan, or changelog history is rewritten (h3)
  - `COLLEAGUE_TIMEOUT` is documented for long-context runs per decision c11 (default stays 120.0; streaming #393 + timeout-survival #268 named as the degrade story) in model-selection.md or graceful-degradation.md
  - the per-model overlay note lands: one advisory line in docs/features/per-model-configuration.md (or the CHANGELOG entry) saying .colleague/<sanitized-model-id>/ overlays are exact-id-keyed and old-id dirs must be renamed by the operator — documentation only, no code migrates dirs (c19, h11)

### t5 — Verify the sweep, prove it live, and close the PR loop

- instruction: Run the version-bump skill, then the cicd skill for the PR. The live long-context proof can reuse an existing large-repo explore task; capture `COLLEAGUE_TIMEOUT` guidance in the run notes if the default 120s trips (decision c11 says document, not raise). The before-state evidence from t1 goes in the PR body.
- depends on: t2, t3, t4
- covers: c4, h4, c15, h7, c17, h9
- acceptance:
  - the exclusion grep is clean and its list verbatim in the PR (h9): grep -rn 'Qwen3.6-27B' over the repo excluding CHANGELOG.md, .devague/, docs/specs/, docs/plans/, tools/`tui_sim`/recordings/, .eidetic/, docs/live-testing.md dated rows returns 0 hits on current-state surfaces while historical refs stay untouched (c17)
  - git diff vs main shows zero hunks under CHANGELOG.md history, .devague/ (beyond this arc's own frame/plan), docs/specs/ (beyond this spec), docs/plans/ (beyond this plan), tools/`tui_sim`/recordings/, .eidetic/ (h4)
  - uv run pytest -n auto passes; one live bare work item exits 0 against the rig resolving the new default (c17)
  - one long-context run at the new default budget completes with streaming and no overflow/latency churn, recorded in docs/live-testing.md as a new dated row (h7, c15)
  - version bumped (minor) + CHANGELOG entry naming the pin flip, budget retune, timeout stance, and overlay note

## Risks

- [unknown_nonblocking] whether realistic distill/strive prompts push 3.8 reasoning past the 1600-token cap is unmeasured until t3's experiment runs (frame park v2) (task t3)
