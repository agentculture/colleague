# Build Plan — same-origin key hygiene for senses/voice rungs

slug: `same-origin-key-hygiene-for-senses-voice-rungs` · status: `exported` · from frame: `same-origin-key-hygiene-for-senses-voice-rungs`

> The senses and voice lobes discovery rungs apply the same same-origin api_key hygiene deepthink got in #347: the main Bearer token is never forwarded to a cross-origin wire-advertised endpoint; explicit keys (env or a model-less config.json section) arm a cross-origin role

## Tasks

### t1 — senses rung: _senses_lobes_fallback extraction + 4-test hygiene block

- instruction: mirror config.py:669-709 (_deepthink_lobes_fallback) exactly, including the docstring's hygiene paragraph adapted to senses; keep resolve() under SonarCloud S3776 by moving the whole senses-fallback branch into the new function; touch NOTHING inside _resolve_senses, _same_origin, or _deepthink_lobes_fallback; the dial target stays _role_dial_base_url(lobes_roles.senses, gateway)
- covers: c2, h1, c4, h4, c10, h9, c12, h11, c1, h2
- acceptance:
  - tests/test_config_lobes.py gains a 4-test hygiene block mirroring tests/test_config_lobes_deepthink.py:335-402 — cross-origin discovered senses resolves _DEFAULT_API_KEY; same-origin inherits the main key; COLLEAGUE_SENSES_API_KEY wins even cross-origin; a config.json senses section carrying ONLY api_key (no model) arms discovery — each test red on main, green with the fix
  - colleague/config.py gains _senses_lobes_fallback mirroring _deepthink_lobes_fallback field-for-field: explicit key (COLLEAGUE_SENSES_API_KEY env, CONVERTIBLE_SENSES_API_KEY fallback, file senses.api_key) wins, then _same_origin(dial, main) inherit, then _DEFAULT_API_KEY; the resolve() call site passes file_senses into it
  - every pre-existing test in tests/test_config_lobes.py and tests/test_config_senses.py passes unchanged

### t2 — voice rung: _voice_lobes_fallback with the conservative single-field rule + per-role hygiene tests

- instruction: same extraction shape as t1's _senses_lobes_fallback; VoiceConfig keeps its single api_key field (the per-role stt_api_key/tts_api_key split is the parked follow-up, decision c15 — do not build it); depends on t1 only because both tasks edit colleague/config.py — build after t1 merges
- depends on: t1
- covers: c3, h3, c4, h4, c11, h10
- acceptance:
  - tests/test_voice_config.py gains at least 5 hygiene tests: stt-only cross-origin resolves _DEFAULT_API_KEY; tts-only cross-origin likewise; all-armed-roles-same-origin inherits the main key; MIXED origins (stt same-origin, tts cross-origin) resolve the whole VoiceConfig to _DEFAULT_API_KEY (decision c15); COLLEAGUE_VOICE_API_KEY and a model-less config.json voice.api_key each arm a cross-origin role — each test red on main, green with the fix
  - the rule is conservative single-field: the main key is inherited iff EVERY armed role's dial target (armed = non-blank model; an unarmed role's gateway-fallback base_url is excluded from the check) passes _same_origin vs main; the explicit key always wins; no CONVERTIBLE_VOICE_API_KEY fallback is invented — voice postdates the rename
  - pre-existing tests in tests/test_voice_config.py pass unchanged; git diff shows no edits inside _resolve_voice

### t3 — docs: hygiene lines in cortex-senses.md and senses-live-presence.md

- instruction: quote deepthink.md's hygiene paragraph structure rather than inventing new phrasing; the threat-model sentence (wire data, not operator config) carries why_it_matters c13; file-disjoint from t1/t2 so it can build in wave 1
- covers: c9, h8, c13, h12
- acceptance:
  - one hygiene passage each in docs/features/cortex-senses.md (near the line-76 'defaults to the MAIN api_key' comment) and docs/features/senses-live-presence.md (near the line-72 VoiceConfig field list), mirroring docs/features/deepthink.md:63-68 wording: same-origin inherit, cross-origin no-auth default, explicit arming path including the model-less section key; the voice passage states the conservative all-armed-roles rule and names the per-role split as a follow-up; both cite issue 349 for the withheld-key notice
  - markdownlint-cli2 --config ~/.markdownlint-cli2.yaml passes on both files

### t4 — verification sweep + version bump + CHANGELOG upgrade note

- instruction: the upgrade note is decision c18's mitigation for park v1 (a rig relying on cross-origin main-key validity degrades to 401 notices); cite issue 349 from the PR body when the cicd skill opens it
- depends on: t1, t2, t3
- covers: c14, h13, c5, h5, c6, h6, c8, h7, c1, h2
- acceptance:
  - uv run pytest -n auto is fully green; git diff vs main shows zero edits inside _same_origin, _deepthink_lobes_fallback, _resolve_senses, _resolve_voice, and zero changes to tests/test_config_lobes_deepthink.py
  - at least 8 new hygiene tests exist across the two blocks and each was demonstrated red on main (run the new test node ids against the pre-implementation tree and record the failures)
  - version bumped via the version-bump skill and CHANGELOG.md carries the behavior-change entry with an explicit upgrade note: a cross-origin DISCOVERED senses/voice role that previously inherited the main key now resolves the no-auth default; names COLLEAGUE_SENSES_API_KEY / COLLEAGUE_VOICE_API_KEY / the model-less section keys as arming paths; declared paths unaffected
  - lint gates pass: black --check, isort --check-only, flake8, bandit, and teken cli doctor . --strict

## Risks

- [unknown_nonblocking] an existing rig that RELIES on cross-origin main-key validity for discovered senses/voice roles (a shared token across machines) degrades from working calls to notice-level 401s on upgrade — no evidence any deployed rig does; CHANGELOG upgrade note + docs arming pointer are the mitigation (frame park v1)
