# same-origin key hygiene for senses/voice rungs

> The senses and voice lobes discovery rungs apply the same same-origin api_key hygiene deepthink got in #347: the main Bearer token is never forwarded to a cross-origin wire-advertised endpoint; explicit keys (env or a model-less config.json section) arm a cross-origin role
> instruction: existing same-origin tests in tests/test_config_lobes*.py and test_voice_config.py pass unchanged

## Audience

- operators running colleague against a lobes gateway whose advertised senses/stt/tts endpoints live on a different origin than the main endpoint — multi-machine rigs like the spark+thor deployment — plus every same-origin operator, who must see zero behavior change
  - instruction: the same-origin rig shape is the reference deployment pinned at tests/test_config_lobes_deepthink.py:51; the cross-machine rig is the two-machines-two-minds arc (PR 347)

## Before → After

- Before: since the senses discovery rung (cortex/senses t4) and the voice rung (live-presence t1) landed, the resolved main api_key is forwarded verbatim to whatever endpoint the gateway wire payload advertises for those roles — config.py:1983 and :1995 pass resolved_api_key unconditionally
  - instruction: read config.py:1972-1997 on main to verify the unconditional pass-through
- After: a discovered senses/stt/tts role dialing a foreign origin resolves with the no-auth default key unless explicitly armed (env var or config.json section key, model-less included); same-origin discovery still inherits the main key; declared senses/voice are untouched
  - instruction: grep the new fallbacks: the ONLY main_api_key propagation path is behind _same_origin(dial_target, main_base_url)

## Why it matters

- the gateway payload is wire data, not operator config — forwarding the main Bearer token to a host that data names is credential leakage; PR 347 fixed exactly this for the deepthink rung (Qodo finding), leaving senses/voice as the two remaining unpatched discovery rungs
  - instruction: the threat model is 347's verbatim: see _same_origin's docstring (config.py:657-666)

## Requirements

- the senses discovery rung applies deepthink's key rule: explicit COLLEAGUE_SENSES_API_KEY env / config.json senses.api_key wins > main key inherited only when the senses dial target passes _same_origin vs the resolved main base_url > else _DEFAULT_API_KEY — at resolve()'s fallback call site (config.py:1981-1985), likely extracted to a _senses_lobes_fallback mirroring _deepthink_lobes_fallback (which also holds resolve() under SonarCloud S3776)
  - instruction: mirror _deepthink_lobes_fallback exactly: explicit key wins, then _same_origin inherit, then _DEFAULT_API_KEY; pin with a cross-origin senses test in tests/test_config_lobes.py
  - honesty: a discovered senses role whose dial target differs from the resolved main base_url in scheme, host, or port resolves api_key to _DEFAULT_API_KEY ('EMPTY') unless COLLEAGUE_SENSES_API_KEY or config.json senses.api_key is set
- the voice discovery rung applies the same rule with COLLEAGUE_VOICE_API_KEY env / config.json voice.api_key as the explicit arming path — at resolve()'s fallback call site (config.py:1994-1997), likely a _voice_lobes_fallback extraction
  - instruction: same fallback shape as senses; per-role tests in tests/test_voice_config.py (stt-only, tts-only, both, cross-origin variants)
  - honesty: a discovered voice role set whose armed dial target crosses origins never receives the main key by inheritance; COLLEAGUE_VOICE_API_KEY or config.json voice.api_key arms it explicitly
- model-less-section arming must work like deepthink's: today a senses/voice config.json section carrying only api_key (no model) is IGNORED at the discovery rung — _resolve_senses/_resolve_voice return None on a blank model and the fallback call sites never consult file_senses/file_voice or the *_API_KEY env vars; the fix threads them in, mirroring test_config_json_deepthink_api_key_without_model_arms_discovery
  - instruction: thread file_senses/file_voice plus the *_API_KEY env consult into the new fallbacks; add the model-less-section test for senses and for voice
  - honesty: a config.json senses or voice section carrying ONLY api_key (no model) arms a discovered cross-origin role — the exact behavior test_config_json_deepthink_api_key_without_model_arms_discovery pins for deepthink
- tests mirror the four-test hygiene block of tests/test_config_lobes_deepthink.py:335-402 (cross-origin no-inherit / same-origin inherit / explicit env key wins cross-origin / config.json key without model arms): the senses block lands in tests/test_config_lobes.py (home of the senses lobes-rung tests), the voice block per role in tests/test_voice_config.py (home of test_voice_from_lobes_*)
  - instruction: mirror tests/test_config_lobes_deepthink.py:335-402; senses block in tests/test_config_lobes.py, voice block in tests/test_voice_config.py
  - honesty: each mirrored test fails against current main (red) and passes with the fix (green) — the TDD gate
- one docs line each in docs/features/cortex-senses.md (the 'defaults to the MAIN api_key' comment at line 76) and docs/features/senses-live-presence.md (the VoiceConfig field list at line 72), mirroring the hygiene wording of docs/features/deepthink.md:63-68
  - instruction: one line each near cortex-senses.md:76 and senses-live-presence.md:72, mirroring deepthink.md:63-68 wording; lint with markdownlint-cli2 --config ~/.markdownlint-cli2.yaml
  - honesty: the docs lines state the same-origin inheritance rule and the explicit arming path, and markdownlint-cli2 passes on both files

## Honesty conditions

- with no lobes gateway armed, or with every discovered role dialing the main origin, resolution is byte-identical to today — the reference same-origin rig sees zero change
- existing declared-path tests (tests/test_config_senses.py and test_voice_config.py's env/config.json blocks) pass without modification
- tests/test_config_lobes_deepthink.py passes unchanged and git diff shows no edits inside _same_origin or _deepthink_lobes_fallback
- the reference same-origin rig (everything proxied at one gateway origin) keeps inheriting the main key exactly as today
- no resolution path forwards the resolved main api_key to an origin other than the main endpoint's own, except by explicit operator declaration
- verified by reading config.py:1972-1997 on main — resolved_api_key passes unconditionally into both fallback call sites while each role dials its own advertised endpoint
- the threat model matches 347's: a compromised or misconfigured gateway advertising a foreign endpoint must not receive the operator's main Bearer token
- the new tests are demonstrably red on main before the fix lands — not written green against the fixed tree only
- on the reference rig (every role proxied at one gateway origin, cortex included) all discovered roles still inherit the main key — the anchor subtlety only bites when cortex itself advertises a foreign endpoint
- a declared-path senses/voice config with a foreign base_url and no api_key key continues to send the main key there — pinned by the unchanged declared-path tests (c5/h5), and the docs describe inheritance as the declared-path default

## Success signals

- at least 8 new hygiene tests land (4 mirroring the deepthink block for senses, at least 4 for voice covering each role), every one red against current main and green with the fix; the full suite passes and the deepthink rung shows zero diff
  - instruction: run the new test blocks against main first (expect failures), then on the branch with uv run pytest -n auto

## Scope / boundaries

- the DECLARED paths stay unchanged: _resolve_senses (config.py:1221-1226) and _resolve_voice (config.py:1291-1295) keep their 'file api_key or main_api_key' inheritance — hygiene applies only to DISCOVERED wire-advertised dial targets, exactly deepthink's declared/discovered split (#347 left _resolve_deepthink:1131-1136 untouched)
  - instruction: git diff must show no changes inside _resolve_senses or _resolve_voice
- _same_origin (config.py:657-666) and _deepthink_lobes_fallback (config.py:669-709) are reused as-is, never modified — the deepthink rung landed in #347 and is out of this change's blast radius
  - instruction: run uv run pytest tests/test_config_lobes_deepthink.py before opening the PR

## Non-goals

- resolution-layer only: no backend/engine/loop changes, so no all-engines divergence risk (mock and vllm-openai both consume the already-resolved EngineConfig); voice.py and livecheck.py consumers stay untouched under the single-api_key-field option

## Assumptions

- the _same_origin anchor is MAIN's dial target, which under full discovery is CORTEX's own advertised endpoint (_resolve_lobes_rung: lobes_base_url = _role_dial_base_url(lobes_roles.cortex, ...)), not the gateway origin — on a remote-cortex rig, gateway-proxied senses/voice roles are cross-origin vs main and get the default key even though the gateway is the host the operator's key was minted for; conservative in the safe direction, explicit arming covers it, and it is exact deepthink parity
- the hygiene rule distinguishes WIRE-ADVERTISED from OPERATOR-DECLARED origins, not local from remote: a declared senses/voice base_url (with model) still inherits the main key via the preserved 'file or main' default (boundary c5) even when foreign — declaring the endpoint IS the operator's trust grant, exactly deepthink's landed semantics (_resolve_deepthink config.py:1135); after_state honesty h10's 'except by explicit operator declaration' must be read this way

## Scope exploration

- `s1` — `colleague/config.py resolve() senses fallback (1972-1985) + _senses_from_lobes_role (586-608)`: passes resolved_api_key unconditionally to the discovered senses role while dialing the role's OWN endpoint (_role_dial_base_url) — the exact pre-#347 deepthink shape; no _same_origin check, no explicit-key consult
  - seeds: `c2`, `c4`
- `s2` — `colleague/config.py resolve() voice fallback (1986-1997) + _voice_from_lobes_roles (712-752)`: same unconditional main-key inherit, while stt/tts EACH resolve their own dial target independently (#292) — so the key can cross origins on either role
  - seeds: `c3`, `c4`
- `s3` — `colleague/config.py _same_origin (657-666) + _deepthink_lobes_fallback (669-709)`: the landed #347 pattern to reuse verbatim: explicit key (env, or config.json section key usable model-less) > same-origin inherit > _DEFAULT_API_KEY; degrades visibly at the escalation point, never fails the run
  - seeds: `c5`, `c6`
- `s4` — `colleague/config.py _resolve_senses (1163-1250) + _resolve_voice (1253-1302)`: the DECLARED paths inherit main key via 'file or main' by design (pinned by test_config_file_empty_base_url_and_api_key_fall_through_to_main); they return None on a blank model, which is why a model-less section's api_key never reaches the discovery rung today
  - seeds: `c4`, `c5`
- `s5` — `colleague/config.py VoiceConfig (1580-1605) + colleague/voice.py:233 + colleague/livecheck.py`: VoiceConfig carries ONE api_key against TWO per-role dial targets; voice.py duck-types getattr(voice_config, 'api_key') — a per-role key split is a shape change touching both consumers, the conservative all-armed-roles-same-origin rule is not; decision parked as q1
  - seeds: `c7`
- `s6` — `tests/test_config_lobes_deepthink.py:335-402 + tests/test_config_lobes.py + tests/test_voice_config.py`: the four-test hygiene block to mirror lives in the deepthink lobes test file; senses lobes-rung tests already live in test_config_lobes.py and voice lobes-rung tests (test_voice_from_lobes_*) in test_voice_config.py — the mirrored blocks land in those homes
  - seeds: `c8`
- `s7` — `docs/features/deepthink.md:63-68 + cortex-senses.md:66-85 + senses-live-presence.md:72`: deepthink.md carries the hygiene wording to mirror; cortex-senses.md line 76 and senses-live-presence.md line 72 both currently say api_key 'defaults to the MAIN api_key' with no cross-origin caveat — one line each
  - seeds: `c9`
- `s8` — `challenge pass / adjacent-systems lens: config.py _resolve_lobes_rung main-anchor derivation`: lobes_base_url is cortex's own resolved dial target, so the hygiene anchor moves with cortex on cross-machine rigs; seeded the anchor assumption
  - seeds: `c16`
- `s9` — `challenge pass / counter-evidence lens: after_state h10 vs the declared path (_resolve_senses/_resolve_voice 'file or main')`: hunted counter-evidence to h10's absolute wording and found the declared path forwards the main key to declared foreign origins by design; seeded the declared-vs-advertised assumption
  - seeds: `c17`
- `s10` — `challenge pass / observability lens: voice.py transcribe/synthesize degrade paths + livecheck.py:72`: a 401 from a withheld key degrades to None plus ONE generic stderr notice (never raises), and the reachability probe explicitly grades 401 as server-up — so an auth-degraded role reads healthy to livecheck; routed as question q2
- `s11` — `challenge pass / security lens: explicit-arming path endpoint trust (deepthink.md:63-68 + _deepthink_lobes_fallback)`: the explicit key follows whatever endpoint the gateway advertises — a known residual shared with the landed deepthink rung; parked as a follow-up docs caveat, not a blocker
- `s12` — `challenge pass / concurrency lens: config.py resolve() + the new fallbacks`: clean pass — resolution is a pure single-threaded function with no locking or shared mutable state implicated; no concurrency surface in this change
- `s13` — `challenge pass / lifecycle lens: upgrade path for existing cross-origin rigs`: a rig where the main key happens to be valid on a foreign advertised host degrades on upgrade from working calls to notice-level 401s; parked as unknown_nonblocking (no evidence any deployed rig depends on it — spark+thor proofs used same-origin proxying or explicit keys)

## Decisions

- the voice rung uses the conservative single-field rule: main key inherited only when every armed role's dial target passes _same_origin vs main; any cross-origin armed role means the whole VoiceConfig resolves _DEFAULT_API_KEY, with COLLEAGUE_VOICE_API_KEY / config.json voice.api_key as the explicit arming path; the per-role stt_api_key/tts_api_key split is a documented follow-up, not built here
  - instruction: pin with a mixed-origin test: stt same-origin + tts cross-origin resolves api_key=_DEFAULT_API_KEY; note the follow-up in the voice docs line
- the withheld-key case stays silent at resolution, mirror-exact with the landed deepthink rung — no notice lands in this change; a follow-up issue covers a unified withheld-key notice for all three discovery rungs and the livecheck.py:72 401-as-up nuance
  - instruction: file the follow-up issue on agentculture/colleague before the PR opens and cite it from the PR body

## Open / follow-up

- consider a docs caveat that the explicit arming key (env or model-less section) still follows the WIRE-ADVERTISED endpoint — an operator who needs the endpoint pinned must use the fully-declared path (model + base_url + api_key); deepthink.md:63-68 carries no such caveat today, so adding one is a three-docs sweep, not part of this change
