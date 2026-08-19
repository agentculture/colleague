# qwen38 pin rollover

> colleague's default model pin and rig-sized knobs follow the Spark's cortex rollover: unsloth/Qwen3.6-27B-NVFP4 -> unsloth/Qwen3.8-27B-NVFP4, served at 1,048,576-token YaRN context (issue #404); the stale id 404s on the gateway today
> instruction: verify against issue #404 + a live /capabilities probe: cortex model unsloth/Qwen3.8-27B-NVFP4, context 1048576, ready

## Audience

- colleague operators on the Spark rig (bare work items resolving the builtin default) plus every doc/skill reader who copies the pinned id
  - instruction: check README.md and model-selection.md name the new id; a bare 'colleague work' with no pin reaches a live model

## Before → After

- Before: every unsloth/Qwen3.6-27B-NVFP4 pin 404s on the gateway since the 2026-08-19 cortex rollover (lobes-cli#185); the context-budget comment still cites the retired 64K serving; distillation caps `max_tokens`=1600 against a reasoning-heavy checkpoint
- After: a bare work item resolves unsloth/Qwen3.8-27B-NVFP4 and completes against the live rig; the context budget is a moderate raise sized for the 1M YaRN window with its comment citing the 2026-08-20 probe; `COLLEAGUE_TIMEOUT` is documented for long-context runs; bounded completions (distill, oilcheck probes) survive reasoning-consumes-`max_tokens`
  - instruction: run a live bare work item against the rig; grep confirms no current-state surface still carries the old id

## Why it matters

- the builtin default exists precisely so a bare run reaches a live model instead of a 404 (config.py:66 comment) — today it does the opposite; and rung-2 distillation silently degrading to empty content undermines the self-learning arc just proven in #387

## Requirements

- flip `_DEFAULT_MODEL` at colleague/config.py:66 to unsloth/Qwen3.8-27B-NVFP4 — the comment there says the builtin fallback exists precisely so a bare work item reaches a live model instead of a 404, and the old id 404s now; tests/`test_config.py`:13 asserts the exact id and moves with it
  - honesty: the flip changes ONLY the default id string; resolution precedence (flag > `COLLEAGUE_MODEL` > config.json > lobes > default) stays byte-identical
- sweep the current-state doc/skill surfaces to the new id: README.md:106,306; docs/features/model-selection.md:26,79; docs/live-testing.md rig-description rows 25/146 (dated proof rows stay verbatim); .claude/skills/ask-colleague/SKILL.md:30,115; .claude/skills/ask-colleague/scripts/ask-colleague.sh:105,184 (the script's hardcoded fallback default)
  - honesty: every edited doc line describes CURRENT state — no dated proof row, changelog entry, or spec/plan artifact is rewritten
- distill.py's `max_tokens`=1600 rises enough to cover reasoning + the ~1600-token lesson payload (or handles `finish_reason`=length explicitly); oilcheck `_PROBE_MAX_TOKENS`=128 is re-validated against the reasoning-heavy 3.8 so probes cannot misreport tool-calling capability
  - instruction: reproduce empty-content-at-length against the live rig with `max_tokens`=128/1600 first; size the new caps from that evidence, not guesswork
  - honesty: new caps are sized from a live reproduction, and a still-empty completion after the raise surfaces as a recorded warning, never a silent empty lesson
- the rollover note tells operators that per-model config overlays are exact-id-keyed (.colleague/<sanitized-model-id>/ via layers.py `sanitize_model`): any overlay dir keyed on the old id silently stops applying after the flip and must be renamed to the new id — one line in docs/features/per-model-configuration.md or the PR/CHANGELOG entry
  - instruction: grep .colleague/ for old-id-keyed dirs at implementation time (none exist locally today, checked 2026-08-20); verify the doc note names `sanitize_model`'s exact-path rule
  - honesty: the note is advisory documentation only — no code migrates or renames operator overlay dirs automatically

## Honesty conditions

- the rig actually serves the new id at 1M when this lands — re-probe /capabilities at implementation time, not just at scoping time
- git diff shows zero hunks under CHANGELOG.md, .devague/, docs/specs/, docs/plans/, tools/`tui_sim`/recordings/, .eidetic/
- operators pinning via env/config.json are NOT broken by the change — their pin wins over the new default exactly as before
- the 404 is reproduced (or the refresh warning observed) against the live rig before fixing, so the before-state is evidence, not narrative
- the moderate budget raise is validated live: one long-context run completes with streaming and no overflow churn at the new default
- the distill degradation is demonstrated (empty content at `finish_reason`=length) or honestly downgraded to theoretical if the 3.8 does not reproduce it
- the grep exclusion list is stated in the spec verbatim so 'current-state surfaces' is not judgment at sweep time

## Success signals

- grep -rn 'Qwen3.6-27B' over current-state surfaces (colleague/, README, docs/features/, .claude/skills/, tests/`test_config.py`) returns 0 hits; historical artifacts keep >200 refs untouched; uv run pytest -n auto passes; one live bare work item exits 0 against the rig
  - instruction: run the grep excluding CHANGELOG/.devague/docs/specs+plans/tools/`tui_sim`/.eidetic; run the test suite; run `COLLEAGUE_VLLM_E2E`=1 live check or a bare 'colleague work' smoke

## Scope / boundaries

- historical artifacts keep the old id verbatim: CHANGELOG.md, .devague/frames|plans|deliveries, docs/specs/ + docs/plans/, tools/`tui_sim`/recordings, .eidetic/memory jsonl, and dated live-testing.md proof rows — never rewrite history

## Non-goals

- the stopped embed-deep lane is a no-op inside colleague: the retrieval-consumption lane of #277 is parked — colleague consumes only cortex/senses/stt/tts role adverts (CLAUDE.md scope section); lobes.py's /v1/embeddings mention is a doc comment about gateway path shape, not a consumer. eidetic's embedder (if its vector mode dials the Spark) is a sibling-repo concern, not this change
- no routing policy and no scope creep ride along: this is a pin flip + rig-sized knob retune under the existing enumerated increments; version bump + CHANGELOG entry per the PR workflow

## Assumptions

- the bounded-completion callers are the real exposure to #404's 'reasoning consumes `max_tokens`' caveat: the main work loop sends NO `max_tokens` (payload at `vllm_openai.py`:896-904 has temperature/tools/stream only), but distill.py:559 caps rung-2 distillation at `max_tokens`=1600 and oilcheck probes cap at `_PROBE_MAX_TOKENS`=128 (`tool_calling.py`:80, `three_tier.py`:56) — a reasoning-heavy 3.8 can return empty content with `finish_reason`=length there, silently degrading distillation and possibly misreporting probes
- the same-role stale-pin refresh already softens this rollover where lobes is armed (resolution-time roster check + call-time 404 catch, lobes.py t9) — but the BUILTIN default has no nameable pin source, so `_model_pin_source` returns None and only the call-time rung covers a bare run; and with lobes UNARMED the 404 surfaces unchanged. The default flip is therefore still required, refresh is a cushion not a fix
- cosmetic/fixture refs move only for consistency, none functionally: layers.py:126,132 docstring sanitization examples; ~16 test files carry the old id as arbitrary fixture strings (only tests/`test_config.py`:13 is tied to the default); tools/experiments/`experiment_b.py`:113 pins `CONVERTIBLE_MODEL` inside a dated #387 experiment (historical — leave)

## Scope exploration

- `s1` — `colleague/config.py:66 (_DEFAULT_MODEL) + tests/test_config.py:13`: the one functional pin: builtin fallback default, documented as 'points at the model the reference rig actually serves'; probed /capabilities 2026-08-20: cortex now serves unsloth/Qwen3.8-27B-NVFP4, ready, tools=true
  - seeds: `c2`
- `s2` — `README.md, docs/features/model-selection.md, docs/live-testing.md, .claude/skills/ask-colleague/*`: grep found 261 total 'Qwen3.6-27B' refs; the ones describing CURRENT state are these doc/skill sites — live-testing.md is mostly a dated ledger whose historical rows must not be rewritten
  - seeds: `c3`
- `s3` — `CHANGELOG.md, .devague/*, docs/specs+plans, tools/tui_sim/recordings`: the bulk of the 261 refs live in append-only/dated records of past runs and merged arcs; rewriting them would falsify provenance
  - seeds: `c4`
- `s4` — `colleague/config.py:70-88 (_DEFAULT_CONTEXT_BUDGET + _DEFAULT_MAX_OUTPUT_CHARS)`: budget comment cites the 64K serving probed 2026-07-02 and says raise for a wider-window model; /capabilities now advertises context 1048576 — the sizing rationale is stale either way, and `MAX_OUTPUT_CHARS` scales with whatever is chosen
- `s5` — `colleague/engines/vllm_openai.py:562-580 (headless streaming default) + timeout knobs`: streaming is armed by default with one env opt-out, so #404's 'stream long requests' guidance is already the shipped behavior — no new streaming work; the open exposure is time-to-first-byte during minutes-long prefill vs the 120s default timeout
- `s6` — `colleague/distill.py:550-575, colleague/oilcheck/tool_calling.py, colleague/oilcheck/three_tier.py`: read the payload builders: only these three sites send `max_tokens`; the adapter already parses both reasoning and `reasoning_content` spellings (`vllm_openai.py`:260-272,425-428) so trace delivery itself is fine
  - seeds: `c5`
- `s7` — `colleague/lobes.py:418-560, colleague/config.py:1698-1800 (_model_pin_source/_refresh_stale_model_pin)`: refresh fires only for flag/env/config.json pins with lobes armed+reachable and a successfully-fetched roster; builtin-default and unarmed paths still hard-404 on the stale id
  - seeds: `c6`
- `s8` — `live lobes gateway http://localhost:8001 (/v1/models vs /capabilities)`: probed 2026-08-20: /v1/models data=\[\] while /capabilities shows cortex=unsloth/Qwen3.8-27B-NVFP4 context=1048576 ready=true; empty-vs-None semantics at lobes.py:497-560 make \[\] a refresh-triggering answer, not a skip
- `s9` — `colleague/lobes.py:372-373 + CLAUDE.md v1-scope section (embedder/reranker parked)`: no code path in colleague dials an embedding endpoint; #404's embed-deep note routes to eidetic/lobes-cli, not here
  - seeds: `c7`
- `s10` — `colleague/layers.py:120-135, tests/*Qwen3.6* fixture sites, tools/experiments/experiment_b.py`: the sanitization mechanism is model-agnostic (id->path examples only); fixture ids pass regardless of served reality — a consistency sweep is cheap but optional
  - seeds: `c8`
- `s11` — `CLAUDE.md v1-scope line (excluded router)`: the change touches which id the ONE default resolves to, never how a task picks a model
  - seeds: `c9`
- `s12` — `challenge pass / depth decision`: lightweight: no c19 escalation signal applies — no migration, distributed state, hardware change, destructive op, or data-loss surface; the flip is env-pin reversible; lenses swept 2026-08-20 against the exported spec + live rig
- `s13` — `challenge pass / cheap probe: authed /v1/models`: probed 2026-08-20 with the operator's `COLLEAGUE_API_KEY`: full roster returned incl. unsloth/Qwen3.8-27B-NVFP4 — the earlier empty roster was an auth artifact (unauthenticated GET gets 200 + data=\[\]); q3's conditional bug-filing is settled: no lobes-cli bug, the refresh rung works when the key is configured
- `s14` — `challenge pass / cheap probe: reasoning-vs-max_tokens on the live 3.8`: authed completion at `max_tokens`=128: `finish_reason`=stop, 209 reasoning chars + 93-char content, 64 completion tokens — the #404 empty-content caveat did NOT reproduce on a short distill prompt at temperature 0; it is prompt-dependent, so c18/h10's sizing-from-realistic-reproduction stands and h8's honest-downgrade-to-theoretical branch is live
- `s15` — `challenge pass / adjacent-systems lens: colleague/layers.py sanitize_model + .colleague/<model>/ overlays`: per-model isolation is exact-path by sanitized id, so a model rollover orphans old-id overlays by design; no such dir exists on this machine (only a history file naming the 35B variant) but the hazard is generic
  - seeds: `c19`
- `s16` — `challenge pass / overlooked-actors lens: senses/deepthink budgets + mode profiles`: only the MAIN budget changes: senses (gemma-12B, own 24000 default) and deepthink (absent in three-tier mode; own default) are untouched; mode profiles scale by `context_budget_fraction` so they follow the new default automatically (profiles.py:75-110)
- `s17` — `challenge pass / reversibility lens: rollback path`: the code flip reverts trivially, but a LIVE rollback needs the rig to serve the old checkpoint again — the old id 404s, so `COLLEAGUE_MODEL` re-pinning cannot roll back alone; rollback is rig-side (lobes-cli), acceptable for a default-pin change
- `s18` — `challenge pass / unstated-assumptions lens: tool-calling on 3.8`: /capabilities advertises tools=true (probed 2026-08-20) and c18 already re-validates via oilcheck probes; the /tokenize exact-counting carve-out degrades to None on error by contract — clean

## Decisions

- q1 resolved: context budget gets a moderate raise (order 128K-256K) with `_DEFAULT_MAX_OUTPUT_CHARS` rescaled to the same ~13% fraction; adaptive prefill — the agent deciding/finding the right context size for best performance — is parked as a follow-up opportunity, not this change
- q2 resolved: `_DEFAULT_TIMEOUT` stays 120.0; document `COLLEAGUE_TIMEOUT` for long-context runs and lean on default-on streaming (#393) + timeout-survival partials (#268)
- q3 resolved: the empty /v1/models roster is possibly a lobes-cli bug, but the fetch requires Bearer auth which colleague should attach — re-probe authed first; file on lobes-cli only if the authed roster is still empty

## Open parks

- [unknown_nonblocking] whether realistic distill/strive prompts push 3.8 reasoning past 1600 tokens (the 128-token probe reasoned in 209 chars; heavier prompts unmeasured)
- [follow_up] adaptive prefill: let the agent decide or discover the right context size per task for best performance (beyond the static moderate-raise default)
