# change-content consumption lane

> A three-tier colleague run now consumes what cortex configures: an applied worker.prompt.strategist note lands verbatim (bounded) in the worker's next-episode composed system prompt, an applied worker.tools narrowing filters the next episode's offered tool schema AND its executor allow-list (narrows, never adds), the work front arms the config plane itself — lifecycle constructed when three-tier is armed, configurator windows before episode 1 and between episodes, config events folded onto TaskResult.`config_events` — cortex knowledge entries are auto-stamped with their host-known entry-level origin, the flight feed names the seat that actually acts, and the NEBULA RUN benchmark re-runs strategist-live against the recorded pre-#366 baseline.

## Audience

- colleague operators running three-tier mode (the #366 thread), the workforce that builds it, and the NEBULA RUN benchmark evaluation — the value-in-anger test experiment C could not yet run

## Before → After

- Before: post-#367 state: proposals validate, apply, and digest at the lifecycle — but no front constructs a lifecycle (d3), no window ever runs, strategist applications are opaque markers (d2), and experiment C's corrective proposals all died on a host-known missing origin field: the strategist is structurally inert at the CLI surface
- After: an applied change is CONSUMED, not just recorded: the worker's next episode runs under the strategist text (composed system prompt), under the narrowed tool schema (offered list + executor), and the full proposed/verified/applied audit rides TaskResult.`config_events` — provable hermetically on the mock engine

## Why it matters

- experiment B promoted the worker and experiment C proved detection (4/4, 0/4 false) — but strategist VALUE is unmeasurable while applied changes reach nothing; wiring the lane is the difference between a config plane that audits itself and one that changes what the next episode actually runs under

## Requirements

- ChangeUnit (colleague/lattice.py) gains an optional bounded content field valid ONLY on the \*.prompt.strategist targets: refuse-whole extended — stripped length capped at layers.`STRATEGIST_SECTION_MAX_CHARS` (4000), content on any other target refuses whole (the `_check_field_target_shape` precedent), the forbidden-key scan stays
  - honesty: refuse-whole extends, never relaxes: content on any non-strategist target refuses whole; content whose stripped length exceeds `STRATEGIST_SECTION_MAX_CHARS` refuses whole; a content-less strategist unit stays valid (existing proposals unbroken)
- configlifecycle.`_apply_change` folds the unit's REAL strategist text into EpisodeConfigSnapshot.`strategist_sections` instead of the opaque origin#N marker (configlifecycle.py:188) — canonical()/digest() already serialize the tuple, so content flows into the effective-config digest with no shape change
  - honesty: the digest moves exactly once per applied strategist proposal (existing timing pins hold) and the snapshot carries the verbatim stripped text — the opaque-marker expectations in `test_configlifecycle.py` are UPDATED, not left green by accident
- configurator.py auto-stamps entry-level origin on cortex `knowledge_entries` — host-known, and its own `_SYSTEM_PROMPT` already promises stamping while `_build_change_unit` never stamps: the exact experiment C refusal (docs/experiments/2026-08-06-experiment-c) — plus content joins `_RECOGNIZED_CHANGE_KEYS` and the prompt drops the carries-no-extra-fields-today line
  - honesty: a cortex knowledge entry lacking origin validates post-stamp with origin=cortex; a model-supplied origin is still discarded (authority never self-declared); re-running experiment C's mismatch fixture yields verified+applied where it previously refused
- the work front arms the config plane when three-tier is armed (config.worker resolved): construct EpisodeConfigLifecycle + ConfigEventStream, `run_configurator_window` at `WINDOW_BEFORE_EPISODE_1` before first dispatch and `WINDOW_BETWEEN_EPISODES` in `execute_work_chain`'s go-verdict path (work.py:1577 loop) — configurator arming stays `configurator_enabled`(), opt-in + OFF
  - honesty: arming is provably layered: no three-tier means byte-identical (no lifecycle, no windows, no events); three-tier armed + configurator OFF means lifecycle constructed, windows run as strict no-op (reviewed=False), zero completions issued; both pinned by tests
- lifecycle/stream events fold onto TaskResult.`config_events` — the contract field (contract.py:1608) exists with full serialization + digest and NOTHING stamps it today
  - honesty: an armed run's final artifact carries `config_events` whose `effective_digest` matches the stream digest; an unarmed run's artifact omits the key entirely (omit-when-empty holds); round-trips through `from_dict`
- prompt consumption rides the ONE base-class assembly path: Engine.`system_prompt` (engine.py:140, called by both mock and vllm-openai) threads the applied snapshot's strategist text into layers.`system_prompt_for`'s EXISTING `strategist_section`/`strategist_seat` kwargs — all-engines by construction
  - honesty: mock and vllm-openai compose the SAME strategist section from the same snapshot (all-engines test on the shared base-class path); an empty/absent section composes a byte-identical prompt to today
  - honesty: the consumer passes RAW strategist text — `system_prompt_for` composes internally, so passing an already-composed section silently double-heads (probe-verified): the wiring pins exactly ONE strategist heading in the final prompt, and a strategist-only composition still carries the engine base (the #363 T3 trap, probe-verified avoided)
- an applied worker.tools narrowing INTERSECTS the role-curated surface on BOTH halves of the existing mechanism — the `curate_schemas` offered list (`vllm_openai.py`:809) and the ToolExecutor allowlist — narrowing only ever removes, never adds (the authority ceiling)
  - honesty: narrowing is intersect-only on both halves: a `tool_set` entry outside the role-curated surface can never ADD a schema or pass the executor; a narrowed-away tool refuses at the executor with the same refusal shape role withholding uses
- flight.py `append_run_start` (line 159) stops hardcoding cortex-started: the run-start line names the seat that actually acts (worker in three-tier mode) — closing the t9 attribution miss the NEBULA baseline run caught on the flight-feed surface
  - honesty: with three-tier armed the run-start feed line names the worker seat; unarmed emits the current cortex-started line byte-identically (both arms tested)
- the structural pins re-prove WITH content flowing: cortex-authored text reaches only the composed SYSTEM prompt at episode resolution (a config surface, never the worker's message history), the acting completion seam stays unwrapped, mid-episode digest constancy holds — tests/`test_configurator_boundary.py` + `test_loop_config_lifecycle.py` extended, never weakened (c7/h7 end-to-end)
  - honesty: `test_configurator_boundary.py` still proves loop.py never imports configurator and no cortex-authored text enters the worker's MESSAGE HISTORY (the composed system prompt is asserted as the ONLY carrier); `test_loop_config_lifecycle.py` proves digest constancy mid-episode with real content applied
- the arc ends with the post-#366 NEBULA RUN arm: fresh ship-game repo (path free; baseline preserved in ship-game-bkp), the IDENTICAL prompt from the #366 protocol comment, three-tier + configurator armed, graded against the recorded baseline stats (2 rounds / 1315 LOC / the honest-README timer inversion as the concrete catch-hook)
  - honesty: the benchmark arm uses the verbatim protocol prompt and env, changing ONLY the configurator arming; mechanical stats post to #366 before any quality grading; an inert outcome (0 applied/consumed changes) is reported as-is, never smoothed
- docs/features/three-tier.md Honest limits (the d2/#366 section, lines 194-213) flips to describe the wired lane; the experiment C doc gets its origin-stamping repeat-verdict hook
  - honesty: the flipped docs claim only what a cited test or the benchmark record proves; the strategist-ships-opt-in-and-OFF statement survives verbatim (defaults unchanged this arc)
- an empty `tool_ids` list on a worker.tools unit refuses whole at the lattice — a narrowing that selects nothing is malformed; () stays the snapshot's unset/no-narrowing default, so ambiguity between narrow-to-nothing and not-narrowed never exists
  - honesty: an empty-`tool_ids` worker.tools unit refuses at `validate_change` with a reason naming the empty narrowing; the snapshot default () keeps meaning not-narrowed everywhere it is read
- the review-input assembly is SPECIFIED: before-episode-1 composes the digest from the task's instruction + goal/acceptance; between-episodes from the just-finished episode's terminal facts (summary, exit reason, steps, changed files, gate outcomes) — always a compact TEXT digest, never a message-history list (structural pin 1 upheld at the assembler too)
  - honesty: the assembler is a pure function over TaskResult/Task fields with a size bound; no field of the worker's conversation history appears in its output (pinned alongside the existing structural pins)
- the PERSISTED artifact carries the folded `config_events`: the front updates the on-disk artifact after folding (the loop already wrote it at run end), `read_artifact` round-trips the events, and --continue reads them from disk
  - honesty: a chained run killed between fold and artifact-update loses at most the LAST window's events (crash-window stated honestly); a clean run's disk artifact and in-memory result carry identical `config_events`
- successive worker.tools proposals REPLACE the narrowed set (the existing `_apply_change` replace semantics, now stated): the ceiling is always the role-curated surface, so recovery from an over-aggressive narrowing is possible at any later window — never a ratchet that can strand the worker
  - honesty: a second worker.tools application on top of a narrower first one WIDENS back up to (never past) the role-curated ceiling — pinned by a test exercising narrow-then-replace
- strategist accumulation is bounded by REPLACE semantics: a later worker.prompt.strategist proposal replaces the current note (symmetric with tools-replace) — the composed section can never exceed `STRATEGIST_SECTION_MAX_CHARS` by accumulation, and `compose_strategist_section`'s over-cap raise is structurally unreachable from validated units
  - honesty: two strategist applications across two windows leave exactly ONE current note (the later), the composed prompt carries exactly ONE strategist heading, and a unit whose content is at the cap composes without raising
- a degraded configurator review is VISIBLE, never silent: both degraded early-returns in `review_and_queue` (no cortex dial resolvable; completion exception) record onto the stream/artifact and surface on the feed — the #363 armed-is-not-alive lesson applied to the new front wiring
  - honesty: an armed run with an unreachable cortex dial produces a visible degraded record (stream/artifact/feed) AND zero proposed/applied events — distinguishable from a healthy nothing-to-change window ({"changes": \[\]}), which is NOT degraded
- a subagent spawned mid-episode consumes the inherited `child_snapshot` both ways: its curated tool schema intersects the applied `tool_set` (role allowlist AND narrowing, on offered schemas + executor alike) and its composed prompt carries the current strategist note; queued-but-unapplied proposals never reach a child (the r2 rule, now consumed rather than merely returned)
  - honesty: a child spawned under a narrowing cannot call a narrowed-away tool (offered schema and executor both refuse, pinned by test); a child spawned with no narrowing applied is byte-identical to today; grandchildren at depth>1 inherit the same way
- TaskResult and the persisted artifact record each APPLIED strategist unit's content verbatim (bounded by the lattice cap); refused records keep reason-only; an unarmed run's artifact shape is unchanged
  - honesty: an artifact round-trip preserves applied content byte-for-byte; content appears only on applied records; the omit-when-empty stance on unarmed runs holds

## Honesty conditions

- every lane the announcement names is proven by a test that FAILS on the pre-arc tree: content-bearing lattice unit, real text in the snapshot, auto-stamped origins, front-armed windows, folded `config_events`, prompt+schema consumption, seat-correct flight line, and the benchmark arm recorded on #366
- the arc's diff to colleague/loop.py's turn loop is zero — consumption lives at engine resolution, the fold lives at the front per the q2 decision
- the arc's diff to colleague/chain.py is zero or docstring-only
- the #366 thread carries the arc's protocol and results so the named audience can follow the arc without this session's context
- the after-state is proven hermetically on mock: a scripted cortex reply's strategist content appears in the NEXT episode's composed prompt and its narrowing in the offered schema — no rig required
- the before-state is pinned failing-first: each lane's new test demonstrably fails against the pre-arc tree before the wiring lands
- the value claim stays conditional until measured: the arc claims wiring + measurability, never that the strategist improves outcomes — that verdict belongs to the benchmark comparison
- the signal counts only verified+applied+CONSUMED changes (stream evidence AND prompt/schema evidence together), never proposals or detections alone
- the containment claims are each pinned: over-cap refuses whole, the section renders under the heading in every engine's composed prompt, and an unarmed run has no code path by which cortex text reaches any prompt

## Success signals

- the post-#366 NEBULA arm runs configurator-live: >=1 change verified+applied+CONSUMED end-to-end (strategist text present in an episode-2+ composed prompt, or a narrowed schema in force), 0 entry-origin refusals on cortex knowledge entries, and the baseline-vs-live comparison table (rounds, steps, operator grade) lands on #366

## Scope / boundaries

- colleague/loop.py's turn loop stays untouched by the content lane: consumption happens at ENGINE RESOLUTION (system prompt + offered tools resolve at work() start), and the existing ContextControls.`config_lifecycle` seam (`observe_turn`/`end_episode`, threaded via getattr at loop.py:2934) already suffices
- colleague/chain.py's decision layer needs no change: `run_configurator_window` + `apply_config_window` are complete and tested — the d3 gap is exactly that no front calls them
- content containment is by construction, not heuristics: bounded (4000), rendered ONLY under the named task-local strategist heading (never interleaved as raw instructions), and flowing only when the operator armed the configurator — NO content-text scan is attempted (a heuristic scan would fake assurance); the forbidden-KEY scan stays exactly as-is

## Non-goals

- no senses.\* content consumption this arc: the configurator's prompt offers worker targets only, EpisodeConfigLifecycle refuses senses.\* by name (configlifecycle.py propose), and no producer proposes them — a senses-side lifecycle is a future re-spec
- the configurator STAYS opt-in + OFF by default: this arc wires consumption, it does not change arming defaults — only end-to-end verified/applied evidence (the benchmark arm) could justify a future default change, per experiment C's recorded nuance

## Assumptions

- layers.py needs no (or minimal) change: `compose_strategist_section` + `system_prompt_for`'s strategist kwargs are built and tested with ZERO callers passing them — the lane's prompt half is prebuilt

## Scope exploration

- `s1` — `colleague/lattice.py`: ChangeUnit carries target/origin/`tool_ids`/`knowledge_entries`/`extra_fields` — NO free-text content field; knowledge entries already carry content (canonical JSON) but the strategist targets are field-less; refuse-whole runs 7 ordered checks incl. field/target shape
  - seeds: `c2`
- `s2` — `colleague/configlifecycle.py`: `_apply_change` folds an opaque origin#N marker for `WORKER_PROMPT_STRATEGIST` (line 188) — the snapshot/digest machinery is content-ready (tuples serialize canonically); the lifecycle refuses senses.\* by name; loop consults it read-only
  - seeds: `c3`, `c13`
- `s3` — `colleague/configurator.py`: `_build_change_unit` never stamps entry-level origins although `_SYSTEM_PROMPT` promises 'each will be stamped with your origin' — the exact experiment C refusal; `_RECOGNIZED_CHANGE_KEYS` = target/`tool_ids`/`knowledge_entries`; prompt says strategist changes carry no extra fields today; `resolve_cortex_dial` + `review_and_queue` complete and degrade-never-raise
  - seeds: `c4`
- `s4` — `colleague/chain.py`: `run_configurator_window` + `apply_config_window` are complete: armed=False is a strict no-op, review then apply at the SAME sanctioned window, `record_applied` folds applied events — the decision layer needs no change; the gap is the absent caller
  - seeds: `c12`
- `s5` — `colleague/cli/_commands/work.py (execute_work_chain, line 1577 dispatch loop)`: no EpisodeConfigLifecycle construction, no window call before episode 1 or in the go-verdict path, nothing stamps TaskResult.`config_events` — deviation d3 confirmed at the exact seam where ChainState/verdicts already live
  - seeds: `c5`, `c6`
- `s6` — `colleague/loop.py (config_lifecycle seam)`: ContextControls.`config_lifecycle` EXISTS: `observe_turn` per completed model turn (line 2589), `end_episode` once per run on every exit path, threaded forward-compatibly via getattr(config, '`config_lifecycle`', None) at line 2934 — EngineConfig has no such field yet, so the front attaches it; the turn loop needs nothing else
  - seeds: `c11`
- `s7` — `colleague/engine.py system_prompt (base class, lines 140-167)`: the ONE assembly path every backend inherits (mock.py:158 and `vllm_openai.py`:814 both call self.`system_prompt`) — calls layers.`system_prompt_for` WITHOUT strategist kwargs today; threading applied text here is all-engines by construction
  - seeds: `c7`
- `s8` — `colleague/layers.py (t5 strategist section)`: `compose_strategist_section` + `STRATEGIST_SECTION_MAX_CHARS`=4000 + `system_prompt_for`'s `strategist_section`/`strategist_seat` kwargs are built and tested with ZERO callers passing them — the prompt half of the lane is prebuilt
  - seeds: `c17`, `c2`
- `s9` — `colleague/tools.py curate_schemas + ToolExecutor allowlist (via roles.py)`: the narrowing mechanism exists in BOTH halves: `curate_schemas` filters the offered schema (`vllm_openai.py`:809), ToolExecutor(allowlist=role) refuses withheld tools — an applied `tool_set` must intersect the role-curated surface on both, never widen it
  - seeds: `c8`
- `s10` — `colleague/contract.py + colleague/configevents.py`: TaskResult.`config_events` (contract.py:1608) exists with omit-when-empty serialization, coercion, and `effective_digest` — contract imports configevents.ConfigEvent, which is a DIFFERENT class from configlifecycle.ConfigEvent; nothing stamps the field today
  - seeds: `c6`
- `s11` — `colleague/flight.py append_run_start (line 159)`: hardcodes 'cortex started' regardless of the acting seat — the t9 attribution-sweep miss the NEBULA baseline caught live; loop.py:4476 is the emit site
  - seeds: `c9`
- `s12` — `tests/ (structural pins)`: `test_configurator_boundary.py` pins nothing-cortex-authored-reaches-worker-history + acting-seam-never-wrapped; `test_loop_config_lifecycle.py` pins mid-episode digest constancy; `test_lattice`/`test_configlifecycle`/`test_configevents`/`test_attribution_three_tier` exist — content flowing must extend these, never weaken them
  - seeds: `c10`
- `s13` — `docs/features/three-tier.md (Honest limits, lines 192-221)`: states d2 (content lane NOT wired, `compose_strategist_section` unconnected) and the strategist-off rationale honestly — both statements flip when the lane wires; deepthink-absent-in-three-tier boundary unaffected
  - seeds: `c16`
- `s14` — `docs/experiments/2026-08-06-experiment-c-strategist-value.md`: SUPPORTING verdict with the recorded nuance: every corrective proposal refused for a missing entry-level origin (host-known, content substantively right) — names auto-stamping as the v1.1 improvement folded into #366, and holds the strategist opt-in+off pending a repeat with the fix
  - seeds: `c4`, `c14`
- `s15` — `benchmark surfaces (#366 protocol comment + /home/spark/git/ship-game-bkp + ship-game-v1)`: the baseline arm is fully recorded: exact NEBULA RUN prompt verbatim, env (`COLLEAGUE_THREE_TIER`=1, worker seat artifact-verified), stats (2 rounds, 1315 LOC, node --check clean, honest-README timer inversion as the strategist catch-hook); ship-game path is free for the post-#366 arm
  - seeds: `c15`
- `s16` — `colleague/config.py (three-tier arming, t8)`: `_resolve_three_tier_enabled` + worker-role resolution + doctor-visible failure reasons exist; `configurator_enabled`() resolves env > `three_tier`.configurator > OFF — the front reads config.worker as the armed signal; EngineConfig carries no `config_lifecycle` field (the loop getattr is forward-compatible)
  - seeds: `c5`
- `s17` — `challenge pass / probe: layers.system_prompt_for strategist composition`: T3 (#363) avoided: a strategist-only composition still carries the engine base (probe-verified); the param takes RAW text and composes internally — passing a composed section silently double-heads; applied sections ACCUMULATE in the snapshot while the composer takes one string and RAISES past the cap
  - seeds: `c30`, `c7`
- `s18` — `challenge pass / observability lens: configurator.review_and_queue degraded paths`: both degraded early-returns (no dial, lines 469-470; completion exception, 484-485) append NOTHING to the stream — an armed-but-dead configurator is invisible: reviewed=True, degraded=True, zero events, no error anywhere (the #363 armed-is-not-alive trap reproduced in the new module)
  - seeds: `c31`
- `s19` — `challenge pass / adjacent-systems lens: subagents.py + configlifecycle.child_snapshot`: `child_snapshot` (r2 inherit default) exists and is NEVER read by subagents.py — an applied worker.tools narrowing does not reach a child today, so child spawn is a narrowing bypass unless decided otherwise (q4)
  - seeds: `c29`
- `s20` — `challenge pass / failure-mode lens: artifact persistence timing`: the loop persists the artifact at run end; a front-side fold AFTER `execute_work` returns must update the on-disk artifact or --continue and the benchmark read stale events
  - seeds: `c28`
- `s21` — `challenge pass / concurrency lens: configlifecycle threading`: clean pass: the module imports no threading primitive, the loop observes on the main thread only, children never hold the lifecycle, worktree admin has its own fcntl serialization — residual risk only if a future front drives windows concurrently
- `s22` — `challenge pass / adjacent-systems lens: oilcheck/three_tier.py + doctor`: oilcheck mirrors THREE-TIER arming (`_three_tier_armed`) but not CONFIGURATOR arming; consistent as long as the front reads arming via config.py resolution — a configurator readiness line is parked (v2), not a spec change
- `s23` — `challenge pass / security lens: cross-tier authored text`: the c19 escalation signal that made this pass rigorous: cortex-authored free text enters the acting seat's system prompt for the first time — containment stance recorded as c32 (bounded + named section + opt-in, no heuristic scan)
  - seeds: `c32`
- `s24` — `challenge pass / adjudication: subagents.py joins the touched surfaces (q4)`: operator chose consumed child inheritance over the stated-limit option — subagents.py child schema/prompt resolution must read `child_snapshot`; the spawn bypass closes this arc
  - seeds: `c35`

## Decisions

- q1 resolved: the before-episode-1 configurator window arms on ALL armed runs (three-tier + configurator enabled), plain work included; chains additionally get the between-episode window — one up-front cortex review per armed run is the accepted cost
- q2 resolved: the `config_events` fold is CUMULATIVE — each episode's TaskResult.`config_events` carries the stream as known at its finalize, post-episode window events land on the NEXT episode's record, the final episode carries the complete audit
- q3 resolved: the fold MAPS configlifecycle's internal events into configevents.ConfigEvent — the two classes stay distinct; configevents remains the durable vocabulary; no churn in the landed t6/t7 modules
- q4 resolved: child inheritance is WIRED this arc — subagents.py joins the touched surfaces; the r2 inherit default becomes consumed inheritance, closing the spawn bypass
- q5 resolved: the artifact carries applied strategist content VERBATIM (bounded) — auditability and live-benchmark consumption evidence from the artifact alone

## Open parks

- [unknown_nonblocking] per-window cortex review latency on a serializing rig (one extra completion per armed window) — unmeasured until the benchmark arm runs
- [unknown_nonblocking] whether oilcheck/doctor should grow a configurator-armed readiness line (oilcheck/`three_tier.py` mirrors three-tier arming today, not configurator arming) — candidate plan-side task, not a spec change
