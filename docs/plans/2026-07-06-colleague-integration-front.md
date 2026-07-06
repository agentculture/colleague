# Build Plan — colleague-integration-front

slug: `colleague-integration-front` · status: `exported` · from frame: `colleague-integration-front`

> Ask colleague, and one coherent AI-coworker system answers: behind colleague's single operator front, lobes serves its minds, eidetic remembers every run, coherence scores the work, unsloth trains the next local model, data-refinery curates the datasets, agent-lifecycle supervises the processes, and cultureagent embodies it on the Culture mesh — each organ behind a published contract, closing the flywheel from graded work items to a better local model

## Tasks

### t9 — [colleague · S1] lobes 0.38 re-sync: dial per-role endpoints from /capabilities (gateway-origin only as empty-endpoint fallback), honor ready semantics (config-proxy vs live-probed audio), voice 503+Retry-After warming retry, refresh docstring + cortex-senses feature doc + livecheck voice rows

- covers: c18, h1, c6, h15
- acceptance:
  - A /capabilities fixture with distinct per-role endpoints resolves each role to its own endpoint; empty endpoint falls back to gateway origin
  - Absent/unreachable lobes stays byte-identical (degrade-to-None, one stderr notice); voice livecheck row exercises ready-probing, SKIPs only when the rig is genuinely down

### t10 — [colleague · S7] artifact contract: docs/contract.md v1 freezing TaskResult artifact + feedback record + last_work + exit codes, drift-test vs TaskResult.to_dict, and feedback export --min-rating --since --format jsonl joining artifact+grade

- covers: c24, h7
- acceptance:
  - Drift-test enumerates TaskResult.to_dict keys from a maximal fixture against the checked-in contract table; a key change fails CI
  - feedback export emits exactly one JSONL line per graded work item (grade attached); ungraded excluded; empty store exits 0 with empty output

### t11 — [colleague · S10] organism visibility: oilcheck organs check-group (presence/version/armed, zero-network, advisory) + --probe reachability + organs list rendered tool + docs/organs.md index (per-organ contract doc + seam + cited organ non-goals + per-spec PR splits; cultureagent 0.12.0 released) + explain catalog entries

- covers: c27, h10, c15, h22, c5, c11, h20, c3, h13
- acceptance:
  - Bare colleague doctor with organs configured makes zero network calls (no-network guard test extends to the organs group); missing optional organ is a warning with remediation, never unhealthy
  - organs list --json and the doctor group agree (one resolver, two views); docs/organs.md cites each respected organ non-goal to the owning repo's artifact

### t12 — [unsloth-cli · S4a] standalone sloth validate (shared code path with train) + sloth config init writing a TOML that passes train --dry-run unedited

- covers: c21
- acceptance:
  - sloth validate --dataset <jsonl> --json exits 0/1 with the same validator rules train applies (shared code path, drift-proof)
  - sloth config init output passes sloth train --dry-run unedited

### t13 — [agent-lifecycle · S8] batch run-to-completion contract: decide + document timeout semantics, artifact hand-back, BatchOutcome exit-code mapping (ok/failed/timeout/incomplete) aligned to colleague 0/1/2; runnable example extracted+executed by a test; colleague-embed.md batch question closed

- covers: c25, h8
- acceptance:
  - Docs define all three parked pieces and record the decision (restart-policy never + batch value types, or a real mode) with why
  - BatchOutcome classification is pure/deterministic/stdlib-only with a test-executed doc example; no scheduler, no registry

### t14 — [eidetic-cli · S9] memory scope contract: docs contract naming scope-naming convention (suffix scope; task/experiment as type/metadata facets) + visibility default public-in-repo; fix vendored recall/remember wrappers to --visibility public; eidetic-side test that wrapper and raw CLI land the same scope+visibility

- covers: c26, h9
- acceptance:
  - The eidetic-side integration test shells the vendored wrapper and the raw CLI with no flags and asserts identical scope+visibility routing (fails before the fix, passes after)
  - Contract doc versions the store-resolution table (EIDETIC_DATA_DIR > public-in-repo > HOME); no store-format or routing-code changes

### t15 — [coherence-cli · S2] align embedder docs: README + embed module doc name the lobes embedder role as the reference deployment for COHERENCE_EMBED_URL/MODEL (no behavior change)

- covers: c19
- acceptance:
  - README names lobes capabilities as the discovery source and the gateway embeddings endpoint as the reference COHERENCE_EMBED_URL; defaults unchanged
  - Doc wording slots into the coherence-cli#11 five-domain positioning (meaning as Layer 2) and #10's model-relative framing — it never re-asserts the old claims-only description

### t16 — [colleague] boundary pins: test asserting no colleague module imports cultureagent (absent edge pinned) and test_zero_deps allow-list stays exactly agentfront

- covers: c8, h17, c10, h19
- acceptance:
  - Import-graph test fails if any colleague module imports cultureagent; test_zero_deps asserts no third-party leak beyond agentfront both before and after this arc's tasks

### t17 — [unsloth-cli · S4b] run registry (train appends atomic runs.jsonl line: run_id/config_hash/output_dir/model/method/dataset sha+count/started/finished/status) + sloth runs list|show + sloth summarize (metadata + trainer_state loss) + sloth compare

- depends on: t12
- covers: c21, h4
- acceptance:
  - An agent enumerates, inspects, and summarizes past runs from CLI verbs alone (runs list/show, summarize --json) with no directory walking
  - Registry append is atomic and crash-safe (killed train leaves status incomplete, not a corrupt line); missing registry degrades runs list to an honest empty list; existing verbs byte-identical when unused

### t18 — [colleague · S9-consumer] memory-convention drift-test: colleague-side test pinning memory.py scope/visibility flags to the eidetic contract doc convention (mismatch fails a test, not a user)

- depends on: t14
- covers: h9, h12
- acceptance:
  - A colleague test asserts memory.py's hardcoded --scope/--visibility match the documented convention; diverging either side fails the respective repo's CI

### t19 — [colleague · S2] one embedder: parse optional embedder role in lobes.py (absence never fails resolution); inject EIDETIC_EMBED_URL/MODEL + COHERENCE_EMBED_URL/MODEL into organ shell-out envs when armed; operator-set env always wins; structural test colleague never issues /v1/embeddings itself

- depends on: t9
- covers: c19, h2, c9, h18, c7
- acceptance:
  - With lobes armed, tests assert eidetic and coherence subprocess envs carry the SAME embedder endpoint colleague resolved; with lobes absent both shell-outs are byte-identical to today
  - A caller-provided EIDETIC_EMBED_URL/COHERENCE_EMBED_URL is never overwritten; a structural test pins that colleague makes no /v1/embeddings request of its own

### t20 — [eidetic-cli · S2-align] embedder default alignment: code default (embed.py) and wrapper/README default agree (one documented default, lobes embedder as reference); drift-test pins them together

- depends on: t14
- covers: c19
- acceptance:
  - eidetic's code default EIDETIC_EMBED_URL/MODEL equals the documented default (drift-test); wrappers and README name the same endpoint+model

### t21 — [data-refinery-cli · S6] refine dataset + lineage: consume colleague feedback-export JSONL, map to sloth chat-schema examples, filter --min-rating, split train/eval disjoint-by-construction, per-example provenance (task_id/rating/content sha), refine lineage summary; contract.md v4; reuse dedup/integrity/validate primitives; no LLM, no network

- depends on: t10
- covers: c23, h6
- acceptance:
  - A 3-line graded.jsonl fixture (ratings 5,4,2; threshold 4) yields exactly 2 examples, each carrying task_id+rating provenance, the rating-2 item absent; splits share no content hash
  - Produced train/eval JSONL passes sloth validate / train --dry-run verbatim; refine contract frozen in docs/contract.md v4

### t22 — [colleague · S3] coherence gate: colleague/coherence.py + _maybe_run_coherence_gate on changed .md artifacts post-loop pre-handoff; curated allow-list exactly coherence; TaskResult.coherence_report omit-when-None; diagnostics as stderr hints; default-ON warn-only with --no-coherence/COLLEAGUE_COHERENCE=0/config opt-out; degrade-to-skipped; all-engines

- depends on: t19
- covers: c20, h3, h16
- acceptance:
  - A run with no changed .md files, no findings, or no coherence CLI yields a byte-identical TaskResult (e2e mock shape test passes); the gate never blocks handoff
  - Offline (no embed endpoint) the gate still records coherence's lexical diagnostics; fires identically for mock and vllm-openai
  - coherence_report records the measurement's frame provenance (embed model + endpoint that produced each score — the injected lobes embedder when armed), phrased model-relative per coherence-cli#10; the gate pins the meaning score --json shape with a consumer fixture so the coherence-cli#11 domain restructure (which keeps the meaning noun stable per its own decision) cannot silently break the seam

### t23 — [colleague · S5] experiment noun: experiment start (sloth validate then detached sloth train, background.py one-shot-detach precedent, machine-readable start payload) + status + summarize --remember (eidetic record per t14 convention) + list; clean reaps dead-pid experiment residue; allow-list exactly sloth; no torch/unsloth import

- depends on: t17, t18, t22
- covers: c22, h5, h14
- acceptance:
  - experiment start with a stubbed sloth writes the start payload and detaches (no .wait()/.poll() — background.py boundary-test pattern); status queryable mid-run; summary + eidetic record on completion; missing sloth degrades to a structured error with remediation
  - test_zero_deps/test_boundary pin no torch/unsloth import and experiment joins _SUBPROCESS_ALLOWED with a stated reason; every new verb ships --json + structured errors
  - An experiment is gradeable via colleague feedback record <exp-id> (the ROI loop covers experiments)

### t24 — [flywheel · live proof] end-to-end demo + ledger: feedback export -> refine -> sloth validate/dry-run -> real smoke LoRA detached via colleague experiment -> summarize --remember -> adapter visible to lobes; one live-testing row per leg with evidence; legs that cannot run live are recorded SKIP with reason

- depends on: t21, t22, t23
- covers: c1, h11, c2, c14, h21
- acceptance:
  - docs/live-testing.md gains one row per flywheel leg with evidence (command + observed output); a leg that cannot run live is SKIP with the reason, never inferred to pass
  - The demo drives only colleague/organ CLI verbs (no ad-hoc scripts beyond the documented commands)

## Risks

- [unknown_nonblocking] Live rig availability bounds t24: a real LoRA smoke needs free GPU memory and the NGC image; lobes serving the exported adapter needs a fleet restart — legs SKIP honestly when the rig cannot host them
- [unknown_nonblocking] Builder capability: colleague/27B nails NEW-file tasks with self-contained briefs but blows budget on large existing files (dogfood lesson) — hot-file tasks (loop.py, lobes.py, session-adjacent) route to Claude/sonnet; cap colleague fan-out at 2 with COLLEAGUE_TIMEOUT=300
- [unknown_nonblocking] Sibling-repo merge latency: each repo's PR needs human merge + version-bump CI; cross-repo deps (t18 on t14, t21 on t10) build against local branches and note the upstream PR in the brief
- [follow_up] JSON Schema for lobes /capabilities is a lobes-cli ask, not in this plan (follow-up); colleague pins the shape with a consumer fixture test meanwhile
- [follow_up] Coherence calibration experiment stays upstream (coherence-cli phase-3); the t22 gate ships warn-only and never grows a threshold in this arc
- [unknown_nonblocking] Upstream coherence-cli restructure (#11: quality/meaning/signal/investiture/frames domains; #10: frame provenance + gauge robustness) — the meaning noun and CLI behavior stay stable per #11's own decision; colleague's gate consumes meaning score --json behind a pinned fixture and passes through any future frame/provenance block verbatim
