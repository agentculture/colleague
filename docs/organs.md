# The AI-coworker organism: an organ index

colleague is the single operator front for a small organism of sibling CLIs —
each an independent repo, each behind its own published contract
([colleague#291](https://github.com/agentculture/colleague/issues/291), the
`colleague-integration-front` arc). This page indexes every organ colleague
knows about: what it owns, the seam colleague talks to it through, its
contract artifact, the spec issue that covers colleague's side of the
integration, and the organ's own respected non-goals — each cited to the
owning repo's artifact, never asserted from colleague's side alone.

It is the doc-side twin of `colleague doctor`'s **organs** check-group and the
`colleague organs list` rendered tool (`colleague/oilcheck/organs.py`): both
read the SAME curated table, which is hand-maintained (not a dynamically
discovered plugin registry) — see `colleague explain organs`. This page and
that surface are themselves S10
([colleague#297](https://github.com/agentculture/colleague/issues/297), owner
colleague, planned as **1 PR** — plan task t11).

## Reading the table

- **Owns** — what the organ repo is responsible for.
- **Seam** — how colleague talks to it today (a curated allow-listed
  shell-out, a post-loop gate, a discovery rung) or would, once its planned
  integration lands.
- **Contract artifact** — the organ's own published, owner-repo document or
  wire shape that a consumer may pin against.
- **Spec issue** — the colleague-integration-front requirement (`S1`-`S10`)
  covering colleague's side of the integration, and its owner.

| Organ | Owns | Seam | Contract artifact | Spec issue (owner) |
|---|---|---|---|---|
| [lobes](#lobes) | Serving + role discovery for colleague's minds | discovery rung | `GET /capabilities` `RoleInfo` shape | S1 [colleague#292](https://github.com/agentculture/colleague/issues/292); S2 [colleague#293](https://github.com/agentculture/colleague/issues/293) (owner colleague) |
| [eidetic](#eidetic) | Perfect-recall agent memory | memory shell-out | eidetic conventions (README.md#storage) | S9 [eidetic-cli#28](https://github.com/agentculture/eidetic-cli/issues/28) (owner eidetic-cli) |
| [coherence](#coherence) | Information-quality scoring | gate — planned, not yet built | `coherence meaning score --json` shape | S3 [colleague#294](https://github.com/agentculture/colleague/issues/294) (owner colleague) |
| [sloth (unsloth-cli)](#sloth-unsloth-cli) | LoRA/QLoRA fine-tuning | experiment noun (`colleague/experiment.py`; allow-list sloth) | run TOML config + `training_metadata.json` | S4 [unsloth-cli#12](https://github.com/agentculture/unsloth-cli/issues/12) (owner unsloth-cli); S5 [colleague#295](https://github.com/agentculture/colleague/issues/295) (owner colleague) |
| [data-refinery](#data-refinery) | Dataset quality + the refine pipeline | dataset pipeline — planned, not yet built colleague-side | `docs/contract.md` v3 | S6 [data-refinery-cli#14](https://github.com/agentculture/data-refinery-cli/issues/14) (owner data-refinery-cli) |
| [agtag](#agtag) | Agent-to-agent mesh messaging (issues) | culture tool | `agtag issue --json` shape | shipped — mesh-member re-spec (`colleague/culture.py`) |
| [devex](#devex) | Agent-operated dev-experience briefings + PR lifecycle | culture tool | `devex explain`/`learn` catalog | shipped — mesh-member re-spec (`colleague/culture.py`) |
| [devague](#devague) | Vague-idea → spec → plan convergence | destination tool | `docs/spec-contract.md` move I/O | shipped — destination re-spec (`colleague/devague.py`) |

## Planned PR splits (per spec issue)

Each spec issue names its planned 1-3 PR split up front (the #291 quality
bar); the splits below derive from the committed build plan
(`docs/plans/2026-07-06-colleague-integration-front.md`, tasks t9-t24):

- **S1** [colleague#292](https://github.com/agentculture/colleague/issues/292)
  — 1 PR (t9: lobes 0.38 re-sync).
- **S2** [colleague#293](https://github.com/agentculture/colleague/issues/293)
  — up to 3 PRs across repos: colleague t19 (embedder resolution + env
  injection), coherence-cli t15 (doc alignment), eidetic-cli t20 (default
  alignment).
- **S3** [colleague#294](https://github.com/agentculture/colleague/issues/294)
  — 1 PR (t22: the coherence gate).
- **S4** [unsloth-cli#12](https://github.com/agentculture/unsloth-cli/issues/12)
  — 2 PRs (t12: validate + config init; t17: run registry + summarize +
  compare).
- **S5** [colleague#295](https://github.com/agentculture/colleague/issues/295)
  — 1 PR (t23: the experiment noun).
- **S6** [data-refinery-cli#14](https://github.com/agentculture/data-refinery-cli/issues/14)
  — 1 PR (t21: refine dataset + lineage, contract.md v4).
- **S7** [colleague#296](https://github.com/agentculture/colleague/issues/296)
  — 1 PR (t10: docs/contract.md v1 + feedback export).
- **S8** [agent-lifecycle#34](https://github.com/agentculture/agent-lifecycle/issues/34)
  — 1 PR (t13: the batch run-to-completion contract).
- **S9** [eidetic-cli#28](https://github.com/agentculture/eidetic-cli/issues/28)
  — 2 PRs: eidetic-cli t14 (the contract + wrapper fix) and colleague t18 (the
  consumer drift-test).
- **S10** [colleague#297](https://github.com/agentculture/colleague/issues/297)
  — 1 PR (t11: this surface — the organs doctor group, the `organs` noun, and
  this index).

Two organs referenced elsewhere in the S1-S10 set are not colleague-consumed
CLIs and so are **not rows in the curated table**, but are named here for
completeness of the spec-issue index:

- **agent-lifecycle** — S8 [agent-lifecycle#34](https://github.com/agentculture/agent-lifecycle/issues/34)
  (owner agent-lifecycle): the batch run-to-completion contract. colleague
  already consumes agent-lifecycle as a **library embed**
  (`colleague/resident/appserver.py`, the `[resident]` extra) — a Python
  import, not a shell-out or discovery rung — so it does not fit this table's
  seam vocabulary.
- **colleague itself** — S7 [colleague#296](https://github.com/agentculture/colleague/issues/296)
  (owner colleague): the artifact contract (`TaskResult` + feedback record +
  `docs/contract.md`) that data-refinery-cli's dataset pipeline (S6) consumes.

**cultureagent** is the mesh-embodiment leg (issue #291's "closing the
flywheel"), released at 0.12.0 — it depends on colleague (via
`agent-lifecycle`'s `Supervisor` seam, `culture[colleague]`), never the other
way around; colleague imports nothing from cultureagent (a boundary test pins
the absent edge — [colleague#291](https://github.com/agentculture/colleague/issues/291)
task t16). It is not a colleague-consumed organ and has no row above.

## lobes

**Owns:** serving, assessing, and switching the local vLLM model(s) behind a
fleet gateway; the `/capabilities` contract that names typed model **roles**
(`cortex`, `senses`, `embedder`, `reranker`, `stt`, `tts`) instead of literal
model ids.

**Seam:** the **discovery rung** — `colleague/lobes.py`'s `resolve_roles` GETs
`{gateway}/capabilities` (stdlib `urllib`, no network in the registered
`colleague doctor` check-group; the live GET is opt-in via `doctor --probe`
only) and `colleague/config.py`'s `resolve_lobes_gateway_url` slots the
gateway into `EngineConfig.resolve()`'s precedence chain: explicit flag >
`COLLEAGUE_LOBES_URL` env > `.colleague/config.json` `lobes` section > builtin
default.

**Contract artifact:** the `GET /capabilities` wire shape (`RoleInfo`: `role`,
`model`, `runtime`, `endpoint`, `path`, `context`, `quant`, `mtp`,
`responsibilities`, `forbidden_responsibilities`, `ready`, `loaded`) —
documented in lobes-cli's `docs/colleague-stack.md` ("The Colleague stack: six
roles, one contract").

**Spec issue:** S1 [colleague#292](https://github.com/agentculture/colleague/issues/292)
(owner colleague) — the 0.38 re-sync: dial per-role endpoints directly instead
of the gateway-origin workaround, honor `ready` semantics, refresh the voice
round-trip proof. S2 [colleague#293](https://github.com/agentculture/colleague/issues/293)
(owner colleague) — resolve the `embedder` role and inject one shared embedder
endpoint into eidetic's and coherence's shell-out env.

**Respected non-goal:** lobes emits only runtime metrics, **never task-quality
claims** — enforced by its own test suite, not merely documented:
`test_capabilities_contract_is_runtime_descriptor_only` and
`test_measure_registry_emits_only_allowed_runtime_metric_keys` in
`lobes-cli/tests/test_colleague_contract.py` assert no `/capabilities` field
or `measure` metric key contains a quality/correctness token. colleague's own
`_embedder_endpoint` probe (`colleague/oilcheck/organs.py`) reads only the
`endpoint` field for exactly this reason — it never reads or reports a
`ready`/quality-shaped value as a correctness signal.

## eidetic

**Owns:** perfect-recall agent memory — `eidetic recall`/`eidetic remember`
over a visibility-aware store (public-in-repo vs. private-in-`$HOME`), with a
transparent-heuristic freshness/decay model and no hard-delete (shadow +
archive only).

**Seam:** the **memory shell-out** — `colleague/memory.py` allow-lists exactly
`recall`/`remember`, launched as a subprocess (never imported) with the
resolved identity injected; the runtime does recall-before /
remember-after around every work item (`colleague/loop.py`), and a
model-callable `memory` loop tool offers the same two verbs mid-work.

**Contract artifact:** eidetic's documented store/scope conventions
(`eidetic-cli/README.md`'s "Storage" section — the `EIDETIC_DATA_DIR` >
public-in-repo > `$HOME` resolution order); a formal, versioned contract doc
naming the scope-naming convention explicitly is S9's own deliverable (not yet
published as of this writing).

**Spec issue:** S9 [eidetic-cli#28](https://github.com/agentculture/eidetic-cli/issues/28)
(owner eidetic-cli) — the memory scope contract: name the scope-naming
convention (suffix scope; task/experiment as type/metadata facets, not new
primitives) and the public-in-repo visibility default; a colleague-side
consumer drift-test (task t18) pins `colleague/memory.py`'s hardcoded
`--scope`/`--visibility` flags against that published convention once it
lands.

**Respected non-goal:** eidetic is explicitly **not an autonomous
fact-extraction or summarisation agent** — "eidetic only remembers and
retrieves; producers still author records" — a scope/boundaries line from
`eidetic-cli/docs/specs/2026-06-20-eidetic-cli-now-remembers-like-a-mind-a-one-shot-m.md`,
which also states the non-goal is enforceable: "no code path extracts or
summarises autonomously". colleague's `build_recall_block`
(`colleague/memory.py`) only formats records it is handed verbatim — it never
asks eidetic to summarize, and never summarizes on eidetic's behalf.

## coherence

**Owns:** information-quality assessment — freshness, provenance, fidelity,
and task-specific validity of claims — via a `meaning` score over changed
documentation/spec artifacts.

**Seam:** **planned as a post-loop gate** (colleague#294 / S3), the fourth in
the rack alongside lint / test-integrity / affected-tests — not yet built.
`colleague organs list` / `colleague doctor` report `coherence` as present iff
the `coherence` binary is on `PATH` (`shutil.which`), but always `armed=False`
today (see `colleague/oilcheck/organs.py`'s `_not_yet_wired`) — there is no
colleague-side code path that invokes it yet, so reporting anything else would
be dishonest.

**Contract artifact:** the `coherence meaning score --json` shape
(`coherence-cli`'s CLI contract); the S3 gate will pin a consumer fixture
against it so coherence-cli's own domain restructure (coherence-cli#10/#11)
cannot silently break the seam.

**Spec issue:** S3 [colleague#294](https://github.com/agentculture/colleague/issues/294)
(owner colleague) — a fourth rack gate recording `TaskResult.coherence_report`
(advisory, non-blocking, default-ON with the standard opt-out precedence,
warn-only in this arc per the spec's own decision — "Coherence never becomes
a blocking gate in this arc").

**Respected non-goal:** per the colleague-integration-front spec's own
decision, "every coherence check lands warn-only/advisory until a calibration
experiment exists" — coherence never becomes a blocking gate in this arc; a
missing coherence CLI degrades to a skipped, byte-identical `TaskResult`, the
same convention as the other rack gates.

## sloth (unsloth-cli)

**Owns:** simplified LoRA/QLoRA fine-tuning on top of Unsloth — train, eval,
export — plus the agent-operability verbs (`validate`, `config init`, a run
registry, `summarize`, `compare`).

**Seam:** the **experiment noun** (`colleague/experiment.py`, colleague#295 /
S5) — a curated allow-listed shell-out (allow-list exactly `sloth`), following
the culture-tool pattern, launched detached with a job handle (the `work
--background` session-leader-detach precedent). `colleague experiment start`
validates the dataset (`sloth validate --dataset … --json`) before spending
any GPU time, then detaches `sloth train --config <toml>` exactly the way
`colleague/background.py` detaches a background work item — no `.wait()`/
`.poll()`, stdio redirected to a log file, a machine-readable start payload
(`{id, pid, config, output_dir, log_dir, started}`). `experiment status`
reports pid liveness + a log tail + a best-effort correlation against sloth's
own run registry (`sloth runs list`/`show --json`); `experiment summarize
[--remember]` joins `sloth summarize --json` and optionally upserts a compact
record into eidetic (the same `--scope colleague --visibility public`
convention as `colleague/memory.py`, reusing its `remember()` as-is);
`colleague clean` reaps dead-pid experiment residue, never a live run. Present
iff `shutil.which("sloth")` succeeds; `armed=True` unconditionally (like
`agtag`/`devex`/`devague` — the noun is always wired in, no operator opt-out
toggle to read; running a real experiment still needs the `sloth` binary
installed).

**Contract artifact:** a run's TOML config (e.g. `unsloth-cli/examples/lora-smoke.toml`)
plus the `training_metadata.json` a completed run writes beside its output
directory (`runs/<name>/training_metadata.json`).

**Spec issue:** S4 [unsloth-cli#12](https://github.com/agentculture/unsloth-cli/issues/12)
(owner unsloth-cli) — experiment operability: standalone `sloth validate`,
`sloth config init`, a run registry (`runs list`/`show`), `sloth summarize`,
`sloth compare` — the CLI-side verbs an agent needs before any container is
pulled. S5 [colleague#295](https://github.com/agentculture/colleague/issues/295)
(owner colleague) — the colleague-side `experiment` noun that drives sloth
through those verbs, remembers the summary to eidetic, and surfaces it via
`colleague feedback` (an experiment id is a valid `feedback record` task_id).

**Respected non-goal:** full parameter fine-tuning is **hard-refused**, not
merely discouraged — `unsloth-cli/sloth/tune/scope.py`'s `check_scope` guard
classifies any `method` in `FULL_FT_METHODS` as out-of-scope for a "large
dense" model, returning a structured `ScopeResult(out_of_scope=True, ...)`
with a `downgrade_to` suggestion (`lora`/`qlora`) rather than proceeding.
colleague's `experiment` noun (S5) never bypasses this guard — it drives
`sloth train` as-is and surfaces whatever `check_scope` decides.

## data-refinery

**Owns:** data quality for storage and retrieval — validating, deduplicating,
and checking the integrity and freshness of stored/fetched data — split out of
eidetic-cli so eidetic keeps agent-memory as its own concern.

**Seam:** **planned dataset pipeline consumer** (data-refinery-cli#14 / S6) —
not yet built colleague-side. data-refinery-cli is the OWNER of the S6
refine-and-lineage work (consuming colleague's `feedback export` JSONL, per
S7); colleague does not shell out to `data-refinery` directly in this arc.
Reported the same way as coherence/sloth: present iff
`shutil.which("data-refinery")` succeeds, `armed=False` always today.

**Contract artifact:** `data-refinery-cli/docs/contract.md`, versioned —
**contract version 3** as of this writing ("Wave 3 — adds the store-migration
endpoint to the Wave 2 store + data-quality surface"), governed by semver
discipline (a shape change requires a version bump, CI-enforced).

**Spec issue:** S6 [data-refinery-cli#14](https://github.com/agentculture/data-refinery-cli/issues/14)
(owner data-refinery-cli) — refine dataset + lineage: consume colleague's
`feedback export` JSONL (S7), map to sloth's chat-schema examples, filter by
`--min-rating`, split train/eval disjoint-by-construction, attach per-example
provenance (`task_id`/rating/content hash); reuses data-refinery's existing
dedup/integrity/validate primitives — no LLM, no network.

**Respected non-goal:** the S6 requirement's own honesty condition holds
data-refinery to no-LLM, no-network dataset construction — "reuse
dedup/integrity/validate primitives; no LLM, no network" — matching
data-refinery-cli's existing quality-primitive scope (it validates and refines
data it is given; it does not generate or fetch data itself).

## agtag

**Owns:** agent-to-agent communication over the Culture mesh — posting,
fetching, and replying to tracked issues (`agtag issue post/fetch/reply`).

**Seam:** the **culture tool** — one of two CLIs reachable through
colleague's single shared `culture` loop tool
(`colleague/culture.py`'s `ALLOWED_CLIS`), with the resolved identity injected
so an auto-signed post carries the right nick. Already shipped (the
mesh-member re-spec), not part of the S1-S10 set.

**Contract artifact:** the `agtag issue --json` shape (`agtag`'s own CLI
contract — `agtag learn` / `agtag --help` surface the live shape; agtag ships
no separate `docs/contract.md`).

**Spec issue:** none — shipped prior to colleague-integration-front.

## devex

**Owns:** agent-operated developer-experience briefings (deterministic,
per-backend markdown) and the PR lifecycle (`devex pr` — lint / open / read /
reply / delta), also invocable as `agex`.

**Seam:** the **culture tool** — the second of the two CLIs reachable through
`colleague/culture.py`'s `ALLOWED_CLIS` (`devex explain`/`overview`/`learn`).
Already shipped, not part of the S1-S10 set.

**Contract artifact:** the `devex explain`/`learn` catalog (its own
agent-first `--json` surface; devex ships no separate `docs/contract.md`).

**Spec issue:** none — shipped prior to colleague-integration-front.

## devague

**Owns:** turning a vague feature idea into a buildable spec, then that spec
into a buildable plan — a deterministic, move-driven state machine over
claims, honesty conditions, open vagueness, and a convergence gate.

**Seam:** the **destination tool** — `colleague/devague.py`'s curated
`ALLOWED_MOVES` (`new`, `capture`, `interrogate`, `park`, `converge`,
`status`, `show`), excluding the user-only `confirm`/`reject` moves and the
operator-only `export` move. Already shipped (the destination re-spec), not
part of the S1-S10 set.

**Contract artifact:** `devague/docs/spec-contract.md` — "the durable,
reloadable artifact model … and the moves that operate on it", the source of
truth for the entity model and the per-move I/O contract.

**Spec issue:** none — shipped prior to colleague-integration-front.

**Respected non-goal:** devague makes **no LLM calls inside the CLI** — "It is
a small, deterministic Python CLI (no LLM calls inside it, fully unit-tested)"
(`devague/README.md`), reaffirmed in `devague/docs/llm-guidance.md`: "There are
no LLM calls inside the CLI — it only records moves and reports what is still
missing." This is the non-orchestration boundary tracked as
[devague#20](https://github.com/agentculture/devague/issues/20): the CLI is
deterministic and move-driven, the assisting model (here, colleague's backend)
chooses moves. colleague's `devague` loop tool only ever shells out to
`devague` as an external process and never asks it to reason on colleague's
behalf — the model driving the loop is the one making move choices.

## Status note

`cultureagent` 0.12.0 released 2026-07-02 — the mesh-embodiment leg of the
organism is done from cultureagent's side (`culture[colleague]` resolves).
Nothing here changes: cultureagent depends on colleague, colleague depends on
nothing from cultureagent, and it remains outside this table because it is
not a colleague-consumed CLI.

## See also

- `colleague explain organs` / `colleague explain doctor` / `colleague explain lobes`
- [`docs/specs/2026-07-06-colleague-integration-front.md`](specs/2026-07-06-colleague-integration-front.md)
  — the full requirements (R1-R10) this index summarizes
- [`docs/plans/2026-07-06-colleague-integration-front.md`](plans/2026-07-06-colleague-integration-front.md)
  — the task-level build plan (t9-t24) each spec issue's PR split derives from
