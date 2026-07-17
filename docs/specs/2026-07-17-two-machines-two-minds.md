# two machines, two minds

> colleague drives with both machines: Qwen3-on-spark stays the working mind while Gemma4-31B-on-thor answers the judgment calls — thinker and worker over the existing deepthink surface, discovered from the lobes muse role
> instruction: verify by running both rig proofs in order (arc A config retarget, then arc B zero-model-id discovery) and recording each in docs/live-testing.md before claiming the announcement holds

## Audience

- operators running colleague on a multi-machine lobes rig (spark cortex + thor muse + orin senses) who want every machine contributing to a work item; secondarily the lobes-cli maintainers, who own the shared /capabilities role contract
  - instruction: check the exported spec names the rig operator as primary audience and cites the lobes /capabilities contract as the boundary with lobes-cli

## Before → After

- Before: thor's Gemma-4-31B sits idle during every colleague run: deepthink is unconfigured on the rig, and the gateway's advertised muse role is read off /capabilities and discarded — _RESOLVED_ROLES in colleague/lobes.py is exactly ('cortex', 'senses')
  - instruction: cite the before-state from code (colleague/lobes.py _RESOLVED_ROLES) and from the rig config at frame time (no deepthink section anywhere)
- After: after arc A, a config-only deepthink section pointed at the gateway's muse proxy has Gemma-31B-on-thor answering colleague's judgment calls while Qwen-on-spark drives the loop; after arc B, a bare lobes gateway URL in config arms cortex + senses + deepthink with zero model ids — both machines contribute to every hard run
  - instruction: demonstrate each after-state live on the rig and record both in docs/live-testing.md (arc A retarget proof, arc B zero-model-id discovery proof)

## Why it matters

- the rig's strongest reasoner joins the loop exactly where judgment is needed, and two models that miss differently become a safety net — model diversity is the recorded motivation of dual-model colleague (deepthink.md), now realized across machines instead of leaving thor idle
  - instruction: the spec should cite deepthink.md's diversity rationale rather than restating it

## Requirements

- the thinker/worker split lands on the EXISTING deepthink surface as a config change: main = Qwen3.6-27B on spark, deepthink = Gemma-4-31B on thor dialed through the lobes gateway's muse proxy (localhost:8001/v1, model nvidia/Gemma-4-31B-IT-NVFP4) — the four enumerated escalation points (deepthink tool, plan-mode proposals, acceptance self-check, reviewer default) ARE the thinker-consultation surface
  - instruction: arc A recipe: add a deepthink section to the rig's .colleague/config.json with model nvidia/Gemma-4-31B-IT-NVFP4, base_url <http://localhost:8001/v1>, the gateway Bearer key, and a context_budget sized per the v2 verification; confirm via colleague config show, then drive one judgment-heavy work item and inspect TaskResult.deepthink
  - honesty: a .colleague/config.json deepthink section naming the muse model against the gateway resolves visibly in config show AND a live rig run records a non-degraded DeepthinkCall — on today's colleague main, unpatched
- the code increment is ONE new lobes discovery rung: deepthink resolved from the advertised muse role (mirroring how senses feeds a default SensesConfig), so a bare {"lobes": "<http://localhost:8001"}> arms cortex + senses + deepthink with zero model ids; this is a SIXTH increment at the router-exclusion boundary and needs its own re-spec before it lands
  - instruction: arc B shape: extend the lobes rung so the muse role feeds a default DeepthinkConfig exactly as senses feeds SensesConfig (per-role endpoint dialing included); pin precedence, absent-lobes byte-identity, and the four-point surface with tests mirroring the senses discovery suite
  - honesty: with lobes armed and no deepthink declared anywhere, resolve() fills a default DeepthinkConfig from the advertised muse role; env and config.json always win (the exact precedence senses discovery uses); lobes absent or muse missing from /capabilities means no deepthink — byte-identical to today

## Honesty conditions

- arc A ships with ZERO colleague code changes, and arc B changes resolution only — after both arcs the escalation surface is still exactly the four enumerated points, and the code-vs-doc drift test over deepthink.md stays green
- no new decision point lands anywhere: after A+B the only caller-side chooser is still the main model's backend-judged deepthink tool call — no trigger table, no per-task model-selection heuristic appears in colleague/
- the arc A diff is zero lines; the arc B diff touches resolution (lobes.py, config.py) plus docs and tests only — senses.py, senses_loop.py, frontdoor.py, and voice.py are untouched
- the spec serves the operator without demanding anything from lobes-cli: consuming muse as advertised requires no gateway change, and any lobes-cli note (loaded/feasible semantics on proxied roles) is filed as a courtesy issue, never a dependency
- each after-state is demonstrated live before it is claimed: the arc A proof runs before the arc B spec is written, and neither is recorded as proven ahead of its run
- the before-state is cited, not asserted: _RESOLVED_ROLES excludes muse in colleague/lobes.py at frame time, and the rig had no deepthink section configured when the frame was opened
- the diversity rationale is quoted from deepthink.md (two models miss differently), and the spec does not claim measured quality improvement — quality stays with the operator feedback loop
- the success signal is measured from TaskResult artifacts and config show output only — runtime facts, never a quality score; a degraded-only run does NOT count as success

## Success signals

- a live work item on the rig records TaskResult.deepthink with >= 1 non-degraded record (point tool or acceptance_selfcheck) served by nvidia/Gemma-4-31B-IT-NVFP4 through the gateway; after arc B, colleague config show with ONLY the lobes URL configured resolves deepthink.model to the advertised muse model with 0 model ids in colleague's own config
  - instruction: measure from TaskResult artifacts and config show output only — runtime facts, no quality judgment; record in docs/live-testing.md

## Scope / boundaries

- no routing policy moves in: the only decision-maker stays the main model's backend-judged deepthink tool call. Issue #332's deterministic trigger table (complexity/uncertainty/impact -> consult thinker), independent parallel deliberation, synthesis, the trace verb, and phase-5 adaptive orchestration all stay OUT pending their own re-spec — a deterministic task->model trigger table is still a task->model routing policy under the v1 hold-line
  - instruction: verify with a scope-line review at PR time: the diff introduces no task-to-model selection code; the deepthink tool remains the only escalation chooser
- senses territory is untouched, and #332's perception/transcriber rows are ALREADY-LANDED surfaces: the live gateway serves senses (gemma-4-12B, now proxied from orin, 32K), stt (parakeet-tdt-0.6b) and tts (chatterbox) — colleague already consumes all of cortex/senses/stt/tts; this idea adds exactly ONE new consumed role (the thinker), nothing else moves
  - instruction: verify by diff inspection at PR time: arc B touches lobes.py, config.py, docs, tests only

## Non-goals

- forced synthesis (#191) and fill-line compaction (#156) stay on the main model (deepthink spec c11): Gemma-31B never receives Qwen's windowed history — those prompts are the main model's own window and re-windowing them to the thinker would discard context, not improve judgment

## Assumptions

- dialing muse through the gateway origin makes deepthink SAME-endpoint as main (both <http://localhost:8001/v1>; the gateway proxies by model id to thor), so the test-integrity diverse-reviewer default fires despite the model living on another machine — the recorded cross-endpoint reviewer limitation is bypassed by proxying, not fixed
- tools-off deepthink is the honest fit for Gemma on this rig: the serving-side tool-call parser gap makes Gemma structurally unable to drive the loop (a Gemma-as-main run finishes via pseudo-markup, status incomplete), while every deepthink invocation is make_complete(tools=[]) — and muse's own advertised forbidden_responsibilities [final_decision, repo_action, security_decision] matches deepthink's cannot-act invariant class exactly
- the wider 'per-role models' variant beyond the thinker maps onto two ALREADY-RECORDED parked follow-ups, not new territory: (a) mode-level model preference (e.g. review mode driving WITH the deepthink model as main) — deliberately not built in deepthink v1; (b) cross-endpoint subagent model switch — a child subagent inherits the parent base_url (only the model is overridden), so a reviewer subagent cannot dial thor directly today; the gateway-proxy path sidesteps (b) the same way it sidesteps the reviewer-default limit
- muse needs no operator warm-up: a live probe on 2026-07-17 answered HTTP 200 in under 1s through the gateway (18 prompt + 2 completion tokens) despite /capabilities advertising loaded=false and feasible=false — for proxied roles those flags are gateway-local bookkeeping, not host truth (worth a lobes-cli doc note, non-blocking)
  - instruction: re-run the one-line curl probe against the gateway with the muse model id before each live proof; treat a 503-with-Retry-After as warming per the stt/tts precedent

## Scope exploration

- `s1` — `docs/features/deepthink.md + colleague/config.py::_resolve_deepthink`: deepthink already supports an independent base_url/api_key/context_budget (env > config.json deepthink section > default); presence keyed solely on a resolved model — so gemma-on-thor as deepthink is config, not code; live-testing.md:625 records test_dual_live.py PASSED (tool escalation, tokens=825), so this is a retarget of a live-proven seam
  - seeds: `c2`
- `s2` — `colleague/config.py reviewer-default guard (~1198-1221) + live GET /capabilities 2026-07-17`: reviewer default is same-endpoint-only by design (deepthink.base_url != main_base_url disables it); the live gateway advertises muse with endpoint=<http://localhost:8001>, proxied=true, hosted_by=thor.tail0be7e0.ts.net:8000 — same endpoint string as cortex, so the guard passes
  - seeds: `c3`
- `s3` — `colleague/lobes.py (_RESOLVED_ROLES) + cortex-senses.md lobes rung`: _RESOLVED_ROLES = ('cortex','senses') — muse is read off the wire and discarded today; no 'muse' string exists anywhere in colleague/; deepthink resolution has NO lobes rung (env > config.json > default only), so discovery-armed deepthink is genuinely new code, but it lands on an already-enumerated escalation surface, not a new one
  - seeds: `c4`
- `s4` — `CLAUDE.md v1 hold-line + issue #332 (decision policy / phases 3-5)`: five sanctioned increments exist, each a FIXED enumerated surface; #332's decision_policy section is a task->model trigger table and its phase 5 is explicitly 'learned routing' — the excluded router; #332 phases 1-2 (role mapping, thinker consultation, critique, tool-authority) largely map onto ALREADY-BUILT parts (deepthink tool = consultation, tools-off = advisory authority), phases 3-5 do not
  - seeds: `c5`
- `s5` — `deepthink.md 'what deliberately stays on the main model'`: spec c11 pins synthesis + compaction to the main model even under dual config, with a test; this boundary predates the thor retarget and survives it unchanged
  - seeds: `c6`
- `s6` — `live GET /capabilities 2026-07-17 (all seven roles) + senses-live-presence.md`: gateway serves cortex(Qwen27B,spark,256K,loaded), senses(gemma-12B,orin,32K,loaded), muse(Gemma-31B,thor,256K,NOT loaded), embedder/reranker(local), stt/tts(local,ready) — the #332 deployment table minus the thinker is already colleague's consumed reality; note senses moved thor->orin since the cortex-senses arc doc was written
  - seeds: `c7`
- `s7` — `cortex-senses.md 'why it matters — hardware' + live muse role payload`: the hardware division (only Qwen tool-calls; Gemma is the perceiver/advisor) is recorded as an honest hardware constraint, not preference; muse's wire contract (divergent_second_opinion in responsibilities, final_decision/repo_action forbidden) independently confirms the thinker-advises-never-acts framing
  - seeds: `c8`
- `s8` — `colleague/subagents.py (child config inherit, ~L325-344) + deepthink.md honest limits`: dataclasses.replace keeps base_url/api_key intact and overrides only model+role — cross-endpoint delegation is structurally absent; deepthink.md records both 'mode-level model preference' and 'cross-endpoint reviewer default' as parked follow-ups with homes
  - seeds: `c9`

## Decisions

- arc order: A then B — first the config-only retarget (deepthink section naming the muse model via the gateway proxy; zero colleague code), live-proven on the rig; then the muse-to-deepthink lobes discovery rung, re-specced as the sixth sanctioned increment at the router boundary. Issue 332's orchestration slice (critique-after-draft, parallel deliberation, synthesis) stays a separate future frame
- consume the advertised muse role as-is as the thinker source — no lobes-cli rename requested; muse's forbidden_responsibilities (final_decision, repo_action, security_decision) already match deepthink's cannot-act invariant class

## Resolved vagueness

- [unknown_blocking] muse advertises ready=true but loaded=false and feasible=false — unknown whether the gateway loads thor's model on demand at first request or the operator must warm it; blocks the live retarget proof. 'feasible' is also a NEW wire field colleague's RoleInfo does not parse (pattern in the payload suggests local-servability: local roles true, proxied false) — semantics unconfirmed with lobes-cli — resolved: resolved by live probe 2026-07-17: a muse completion through the gateway answered HTTP 200 in under 1s with no warm-up — loaded/feasible on proxied roles are gateway-local bookkeeping, not host truth
