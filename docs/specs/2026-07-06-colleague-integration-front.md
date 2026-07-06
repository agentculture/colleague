# colleague-integration-front

> Ask colleague, and one coherent AI-coworker system answers: behind colleague's single operator front, lobes serves its minds, eidetic remembers every run, coherence scores the work, unsloth trains the next local model, data-refinery curates the datasets, agent-lifecycle supervises the processes, and cultureagent embodies it on the Culture mesh — each organ behind a published contract, closing the flywheel from graded work items to a better local model

## Audience

- The operator driving a DGX Spark local-AI coworker through colleague session/work, plus sibling Culture agents and repos that consume colleague's artifacts and contracts

## Before → After

- Before: Seven organ repos ship clean agent-first CLIs (--json everywhere, 0/1/2 exit codes, teken rubric CI) but near-zero wired integration: colleague consumes only lobes (against a stale pre-0.38 contract in colleague/lobes.py), eidetic (recall/remember allow-list), and agent-lifecycle (resident embed); coherence-cli, unsloth-cli, and data-refinery-cli are consumed by nobody; cross-repo contracts are prose or missing (surveyed all seven repos 2026-07-06)
- After: One front: the operator asks colleague; organ capabilities (memory, evaluation, training, dataset curation, model serving, supervision, mesh presence) are reachable through colleague's three existing integration patterns — curated allow-listed shell-outs (culture/devague/memory precedent), the post-loop gate rack (lint/test-integrity/affected-tests precedent), and the lobes discovery rung — each behind a published owner-repo contract

## Why it matters

- Colleague is the highest-ROI repo and the product; the surrounding repos are organs; the goal is not more tools but one coherent AI coworker operating system (issue #291, operator mandate)

## Requirements

- R1 lobes re-sync (owner colleague; deps lobes-cli>=0.38): colleague/lobes.py drops the stale pre-0.38 assumptions — per-role endpoints are client-reachable now (#87 closed: Host-derived origin, GATEWAY_PUBLIC_URL), lobes capabilities/endpoint CLI verbs exist, stt/tts ready is live-probed (#89 closed: 503+Retry-After while warming) — dial role endpoints directly, honor ready semantics, refresh the docstring, and re-probe the voice round-trip that was skipping on the 502s
  - honesty: A test proves the gateway-origin workaround is gone (role endpoints dialed directly from /capabilities) and a refreshed livecheck row exercises stt/tts ready semantics against a lobes>=0.38 rig; the voice round-trip proof no longer SKIPs on the old 502s
- R2 one embedder contract (owner colleague wiring; deps lobes-cli, eidetic-cli, coherence-cli): today three defaults disagree (eidetic code localhost:8101/v1 text-embedding-3-small vs its own skill wrappers localhost:8002/v1 Qwen3-Embedding-0.6B; coherence localhost:8002/v1; lobes serves the embedder role with a reachable endpoint) — colleague resolves the embedder endpoint from lobes /capabilities and injects EIDETIC_EMBED_URL/EIDETIC_EMBED_MODEL/COHERENCE_EMBED_URL/COHERENCE_EMBED_MODEL into its eidetic/coherence shell-out env; eidetic and coherence align their documented defaults; absent lobes = byte-identical behavior
  - honesty: With lobes armed, a test asserts the eidetic and coherence subprocess envs carry the SAME embedder endpoint colleague resolved; with lobes absent or unreachable, both shell-outs are byte-identical to today (no new hard dependency, degrade-never-raise)
- R3 coherence gate (owner colleague; dep coherence-cli): a fourth rack gate shells out to coherence meaning score on the work item's changed documentation/spec artifacts, recording TaskResult.coherence_report (omit-when-None) — advisory, non-blocking, default-on with opt-out like lint/testintegrity/affected-tests; configured-but-missing CLI degrades to skipped; subdimension diagnostics (missing_consequence/owner/next_action) surface as actionable hints
  - honesty: A run with no coherence finding, no changed doc artifacts, or no coherence CLI installed yields a byte-identical TaskResult (omit-when-None coherence_report, degrade-to-skipped) and the gate never blocks the git handoff
- R4 experiment operability (owner unsloth-cli): the verbs an agent needs around train/eval/export — standalone sloth validate; sloth config init (generate a starting TOML); a run registry (runs land with an index so sloth runs list/show enumerates past runs without directory walking); sloth summarize reading training_metadata.json + trainer_state.json into one JSON experiment summary; sloth compare across runs
  - honesty: An agent can enumerate, inspect, and summarize past training runs from CLI verbs alone (sloth runs list/show, sloth summarize --json) with no directory walking, and sloth validate accepts a dataset standalone before any container is pulled
- R5 experiment orchestration (owner colleague; deps unsloth-cli R4, eidetic-cli): a colleague experiment surface drives sloth via a curated allow-listed shell-out (culture-tool pattern) with the long-run problem solved job-shaped — launched detached with a job handle (the work --background session-leader-detach precedent), status queryable mid-run, and on completion the experiment summary is remembered to eidetic (scope convention from R9) and surfaced in colleague feedback for grading; colleague never imports torch/unsloth
  - honesty: A training run driven through colleague survives the operator closing the session: launched detached with a machine-readable job handle, status queryable mid-run, and on completion the experiment summary lands in eidetic and is gradeable via colleague feedback; test_zero_deps/test_boundary pin that colleague imports no torch/unsloth and only the sanctioned subprocess module shells out
- R6 dataset pipeline v0 (owner per open question q1; deps colleague R7, unsloth-cli): the missing transcript-to-dataset stage — graded colleague work items (artifact + feedback rating) are refined into sloth-validatable train/eval JSONL with per-example provenance (task_id, grade, source hash); data-refinery's envelope store + quality primitives (validate/dedup/integrity/freshness) are the natural substrate; daria's pipeline.md stays the autonomous-driver vision, not the v0 implementation
  - honesty: sloth train --dry-run accepts the pipeline's produced train/eval JSONL verbatim, and every emitted example carries provenance naming the source work item (task_id, grade, content hash) — an ungraded or rejected work item never silently enters a dataset
- R7 artifact contract (owner colleague): the run report + feedback record schemas become a published, versioned docs/contract.md (data-refinery precedent) drift-tested against TaskResult.to_dict, plus a colleague feedback export --format jsonl verb emitting one line per graded work item — the input contract the dataset pipeline consumes
  - honesty: The published artifact schema is versioned and drift-tested against TaskResult.to_dict (a shape change fails the test, not a downstream consumer), and feedback export emits exactly one JSONL line per graded work item with the grade attached
- R8 batch run contract (owner agent-lifecycle; consumers colleague, cultureagent): resolve the parked run-to-completion hard question (docs/colleague-embed.md) — define timeout semantics, artifact collection, and an exit-code contract for batch agents; colleague's resident/one-shot consumption pins the answer (restart-policy never vs a real batch mode) with a consumer drift-test
  - honesty: The batch contract defines all three parked pieces — timeout semantics, artifact collection, exit-code mapping — and a colleague-side consumer test pins them (the restart-policy-never question is answered in the contract, not left implicit)
- R9 memory scope contract (owner eidetic-cli; consumers colleague, every organ repo): one documented scope+visibility convention — today colleague/memory.py hardcodes scope colleague/public while eidetic's own vendored wrappers default to the culture.yaml suffix with private visibility and the skill description claims public; the contract names the scope taxonomy conventions (agent/repo/experiment as scope-name patterns, not new primitives), fixes the wrapper divergence, and adds drift-tests on both sides
  - honesty: One contract doc names the scope+visibility convention; colleague/memory.py and the vendored recall/remember wrappers resolve to the SAME store for the same repo, and a drift-test on each side fails when the defaults diverge again
- R10 organism visibility (owner colleague): a doctor organs check-group (or organs noun) reporting each organ CLI's presence, version, and config/armed state with zero network by default — reachability probes only under --probe (oilcheck invariant); colleague explain gains one entry per organ naming its contract doc and seam
  - honesty: A bare colleague doctor with every organ configured makes zero network calls (the oilcheck invariant test extends to the organs group); reachability appears only under --probe

## Honesty conditions

- The announcement claims only what ships: every organ named is reachable through a shipped colleague verb, gate, or config rung with a live-testing ledger row per flywheel leg — an organ integration without live proof is described as staged, never shipped
- One-coherent-system is measured by consumption, not existence: each organ contract gains at least one consumer-side drift-test in a sibling repo — prose-only integration does not count
- Every opened spec names its 1-3 PR split and a concrete first implementation step up front; a spec that cannot state its first step is not opened (issue #291 quality bar)
- The operator surface stays agent-first: every new verb ships --json and structured errors so sibling agents, not only the human, can drive the front
- The before-state is cited, not assumed: every missing/unconsumed claim traces to a named file or grep result from the 2026-07-06 survey; anything that landed since gets the spec corrected, not forced
- The three-pattern claim is falsifiable: if any S1-S10 build cannot mount on shell-out, gate rack, discovery rung, or resident embed, the frame is re-opened rather than a fourth pattern silently invented
- CI-testable: colleague's import graph and pyproject never reference cultureagent — a boundary test pins the absent edge
- Pass-through is structural: colleague never issues a /v1/embeddings request itself (boundary-testable) and injected env never overrides an operator-set value
- test_zero_deps.py stays an allow-list of exactly agentfront; every new organ integration joins _SUBPROCESS_ALLOWED with a stated reason or it does not merge
- Each respected organ non-goal cites the owning repo's own artifact (eidetic spec non-goal, lobes test_colleague_contract.py, sloth scope guard, devague#20) — colleague never documents an organ behavior the organ does not declare
- The demo is graded honestly: each flywheel leg gets its own live-testing row with evidence; a leg that cannot run live is recorded SKIP with the reason, never inferred to pass
- The organs check-group obeys the oilcheck no-network contract (test-enforced); a missing optional organ is a warning, never an unhealthy report

## Success signals

- The flywheel demo passes end-to-end driven only through colleague verbs: a graded work item's artifact+feedback export feeds the dataset pipeline, sloth train --dry-run accepts the produced JSONL, a real LoRA run completes with the experiment recorded in eidetic and enumerable from the CLI, and the exported adapter appears in lobes /capabilities — with a live-testing ledger row per leg
- One-front visibility: colleague doctor (or an organs noun) reports presence+version+armed-state for every organ with zero network calls by default (oilcheck no-network invariant), and colleague explain names each organ contract

## Scope / boundaries

- Every spec lands in 1-3 focused PRs; no broad rewrites unless a repo boundary is actively harmful; no specs that only create architecture without a clear implementation path (issue #291 constraints)
- No dependency reversal: cultureagent already depends on colleague (backend-colleague extra wraps colleague.resident.harness.ColleagueHarness via the agent-lifecycle Supervisor seam); colleague must never import or depend on cultureagent — mesh embodiment stays cultureagent-side (cultureagent survey: pyproject extras + clients/colleague/runtime/wiring.py)
- The router-exclusion line holds: no automatic task-to-model routing policy anywhere — lobes stays a static role registry plus pressure-shed gateway (lobes/gateway/_routing.py; lobes route is advisory and does not feed the gateway), colleague keeps fixed named-role consumption; passing a lobes-resolved embedder URL into organ subprocess env is endpoint pass-through, not role consumption or routing
- Colleague conventions hold: no second base dependency, no socket, no colleague-owned daemon; every new organ integration is a curated allow-listed subprocess shell-out or a stdlib urllib GET (colleague CLAUDE.md conventions; test_zero_deps.py / test_boundary.py pins)
- Organ non-goals are respected: no in-eidetic summarization (explicit non-goal in eidetic specs), no hard-delete memory (sweep shadows/archives only), lobes never emits quality claims (enforced by test_colleague_contract.py), unsloth full fine-tuning stays hard-refused (sloth/tune/scope.py), no LLM calls inside the devague CLI (devague#20)

## Non-goals

- Not built in this arc: a lobes policy engine routing by persona/skill/context/task/tool; a unified agent-lifecycle FSM (registered/blocked/waiting/archived, pause/resume) — the charter's small enums suffice for colleague's needs today; senses-direct-for-cheap-tasks (colleague#276 stays parked); robot/tool operation; repo merges of any organ
- Coherence never becomes a blocking gate in this arc: measured separations hug the 0.5 midpoint (0.558 vs 0.459, docs/meaning-gradient-live-tests.md) with no calibrated threshold — every coherence check lands warn-only/advisory until a calibration experiment exists

## Assumptions

- cultureagent 0.12.0 (feat/colleague-backend, 29 commits ahead of main, unmerged) merges and releases upstream so culture[colleague] resolves; colleague-side needs no code for mesh participation — coordination item, not a colleague spec

## Decisions

- Priority order: operator shell, then integration contracts, then agent-lifecycle state/events, eidetic continuity, coherence hooks, lobes routing MVP, unsloth orchestration, data-refinery pipeline, cultureagent participation (issue #291 prioritization guidance)
- Cross-repo contracts live in the OWNER repo as docs/contract.md (the data-refinery-cli contract v3 precedent) with drift-tests on the consumer side; colleague keeps a docs/organs.md map indexing every organ, its contract doc, and its consumption seam
- Dataset pipeline v0 (R6) is owned by data-refinery-cli: refine verbs over its envelope store + quality primitives; daria stays the autonomous driver vision (operator decision, 2026-07-06)
- The coherence gate (R3) lands default-ON warn-only with the standard opt-out precedence, matching the rack precedent (operator decision, 2026-07-06)

## Hard questions

- risk: Overengineering: inventing a generic organ-registry abstraction before two-plus new organ integrations exist in the wild — the three existing patterns (shell-out, gate rack, discovery rung) must be exhausted first
- risk: Version-floor drift: backend-colleague pins colleague[culture]>=1.31 but was validated only against 1.34 — the true floor is unverified upstream
- risk: Coupling: env injection quietly makes lobes a runtime dependency of memory/coherence paths — every injection must degrade to the organ's own defaults when lobes is absent
- risk: Wrong abstraction: colleague drifting into a training-job daemon — the job surface must stay one-shot detach + file-based status (the work --background precedent), never a resident scheduler
- risk: Garbage-in flywheel: refining ungraded or low-graded work items into training data poisons the LoRA — the pipeline must filter on explicit grade thresholds and keep eval/train splits disjoint by construction

## Open / follow-up

- Unified agent-lifecycle FSM (registered/blocked/waiting/archived + pause/resume/retire) — deliberately deferred; revisit only when a consumer needs a state the small enums cannot express
- Lobes gateway auth (fleet gateway is not auth-aware; bearer auth only on the single-model tunnel) — security follow-up owned by lobes-cli
- Robot/tool operation via colleague (issue #291 mentions it 'where relevant') — no organ surveyed serves it; out of this arc
