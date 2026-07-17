# Build Plan — two machines, two minds

slug: `two-machines-two-minds` · status: `exported` · from frame: `two-machines-two-minds`

> colleague drives with both machines: Qwen3-on-spark stays the working mind while Gemma4-31B-on-thor answers the judgment calls — thinker and worker over the existing deepthink surface, discovered from the lobes muse role

## Tasks

### t1 — Verify thor's real serving window for Gemma-31B and size the deepthink context budget (arc A prep)

- instruction: check thor via model-gear or the vllm launch config for max_model_len (thor's /v1/models reports None); if unreachable, binary-search a long-prompt probe through the gateway; then size budget with the senses precedent (~73 percent of window, quarter reserved for completion) and record the recipe for t2
- covers: c2
- acceptance:
  - thor's actual max context for nvidia/Gemma-4-31B-IT-NVFP4 is confirmed from the serving side (model-gear/vllm launch config or logs; probe fallback), not read off /capabilities
  - the chosen deepthink context_budget is derived from the VERIFIED window with its ratio stated, and the v2 risk is resolved or re-parked with the verified number

### t2 — Arc A rig retarget: deepthink section resolves against the gateway muse proxy on unpatched main

- instruction: config change ONLY — if anything appears to need a code patch, STOP and record the h2 breach honestly instead of patching; verify with colleague config show --json and colleague doctor --probe
- depends on: t1
- covers: c2, h2
- acceptance:
  - the rig config carries a deepthink section naming nvidia/Gemma-4-31B-IT-NVFP4 at the gateway origin with the t1-sized budget, and colleague config show resolves the block (model, base_url, budget; api_key redacted) on unpatched colleague main
  - deepthink.base_url equals the main base_url (gateway origin), arming the same-endpoint test-integrity reviewer default

### t3 — Arc A live proof: Gemma-31B-on-thor answers a judgment call in a real work item

- instruction: drive a judgment-heavy task: give it acceptance criteria (triggers the acceptance self-check point) and a brief that invites the deepthink tool; COLLEAGUE_TIMEOUT=300; inspect the artifact JSON for the deepthink records before claiming anything
- depends on: t2
- covers: c11, c14, h2, h7, h10
- acceptance:
  - a live work item on the rig records TaskResult.deepthink with >= 1 non-degraded record (point tool or acceptance_selfcheck) served through the gateway by the muse model; a degraded-only run FAILS this criterion
  - the proof is recorded in docs/live-testing.md with work-item ids, token counts, and durations — runtime facts only, no quality score

### t4 — Arc B: lobes.py parses and resolves the muse role

- instruction: touch colleague/lobes.py, colleague/cli/_commands/lobes.py, and their tests only; do NOT start parsing the new feasible wire field or inferring loaded semantics — RoleInfo stays a tolerant superset reader
- depends on: t3
- covers: c4, c12
- acceptance:
  - resolve_roles returns muse as a RoleInfo when advertised, with optional-role semantics (absent or malformed muse leaves it None without failing resolution, like stt/tts)
  - resolve_role_base_url dials muse's own endpoint with the gateway-origin fallback; colleague lobes show lists muse with its ready-kind classification (config-proxy)
  - tests mirror the senses discovery suite for muse: present, absent, malformed payloads

### t5 — Arc B: the deepthink discovery rung in EngineConfig.resolve()

- instruction: mirror _resolve_senses and _resolve_lobes_rung field-for-field; presence keyed solely on a resolved model; touch colleague/config.py and its tests only
- depends on: t4
- covers: c4, h3, c5, h4, h1
- acceptance:
  - with lobes armed and no deepthink declared via env or config.json, resolve() fills a default DeepthinkConfig from the advertised muse role (model, per-role endpoint, budget derived from the advertised window the same way senses derives its default); env and config.json always win
  - lobes absent, or muse missing from /capabilities, yields deepthink None — byte-identity pinned by extending the e2e shape tests; the four-point escalation surface is unchanged and the code-vs-doc drift test stays green
  - no task-to-model selection code appears in the diff; config show renders the discovered deepthink block with api_key redacted

### t6 — Arc B docs: record the sixth sanctioned increment and update stale numbers

- instruction: write docs after t5's shape settles; keep the no-routing-policy wording verbatim from the spec's boundary claims; run the doc-test-alignment skill before the PR
- depends on: t5
- covers: c1, c5, c7, h1, h5, c10, h6, c13, h9, h8
- acceptance:
  - deepthink.md gains the muse discovery rung and corrects the stale 128K/64K context numbers; CLAUDE.md's v1 scope line and the honest-line sections record the SIXTH increment in the same fixed-enumerated-surface language as the first five, with the #332 remainder (trigger table, parallel deliberation, synthesis) explicitly still OUT
  - docs name the rig operator audience and the lobes /capabilities contract as the lobes-cli boundary; the before-state is cited from code (_RESOLVED_ROLES) and the diversity rationale is quoted from deepthink.md, not restated; doc-test alignment passes
  - PR-time diff inspection confirms arc B touched lobes.py, config.py, cli lobes command, docs, and tests only

### t7 — Arc B live proof: zero-model-id discovery arms the thinker

- instruction: temporarily move the rig's deepthink config section aside so the discovery rung is provably the only source; restore it after the proof; runtime facts only in the record
- depends on: t5
- covers: c11, c14, h3, h7, h10
- acceptance:
  - on the rig with ONLY the lobes URL configured (deepthink section moved aside; no model ids anywhere in colleague config), config show resolves deepthink.model to nvidia/Gemma-4-31B-IT-NVFP4
  - a live work item under discovery-only config records >= 1 non-degraded deepthink record; recorded in docs/live-testing.md; the rig's explicit config is restored afterwards

### t8 — Courtesy lobes-cli issue: loaded/feasible semantics on proxied roles

- instruction: file via the communicate skill (agtag-backed, auto-signed); quote the probe numbers verbatim; link the two-machines-two-minds spec for context
- covers: h6
- acceptance:
  - a lobes-cli issue exists carrying the 2026-07-17 probe evidence (muse loaded=false feasible=false while the host answered HTTP 200 in under 1s) and asks for documented per-field semantics on proxied roles; filed as a courtesy — no colleague task blocks on it

## Risks

- [unknown_nonblocking] thor's real serving window for the 31B is unverified (advertised 262144; thor /v1/models reports max_model_len None) — t1 resolves it before any budget is trusted (task t1)
- [unknown_nonblocking] the deepthink dial through the gateway needs the Bearer key present in the environment; a missing key degrades visibly (degraded records), never silently (task t2)
