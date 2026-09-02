# measure-effort-spikes-484

> colleague measures the #484 effort-spike surface: arms A (low + feedback) / B (+ barrier at low) / C (+ barrier at medium) run on the row-69 recorded brief, each a docs/live-testing.md row with a miss written as a miss, and the pre-registered C-beats-B rule decides whether any spike arms by default — the #484 disposition posts to the issue
> instruction: run order: barrier smoke on a throwaway repo → arm A → arm B → arm C, sequential on the rig, each dispatched from /home/spark/git/colleague against a clean worktree of the target at 5a721b8f; grade each work item before reaping its worktree

## Audience

- colleague's operator deciding the #484 disposition, and the next colleague/Claude session that reads docs/live-testing.md rows 70-73 to know whether any spike may arm by default
  - instruction: rows 70-73 + the #484 comment are readable without this session's context: each names its arm, env, brief source, budget, correctness and spend

## Before → After

- Before: the spike surface is merged dark (v1.75.0) with unit proof only; the barrier has never fired live; #484 is open with a pre-registered rule and no measurement
  - instruction: docs/live-testing.md has no row past 69 and effort-spikes.md 'Honest limits' says 'see docs/live-testing.md for the recorded arms once run'
- After: one barrier smoke row + three arm rows (A/B/C) sit in docs/live-testing.md, effort-spikes.md points at them, and #484 carries a disposition comment that applies the pre-registered rule verbatim — the spike default is either unchanged (miss) or a follow-up issue is filed to arm it (C beat B)
  - instruction: grep docs/live-testing.md for rows 70-73; gh issue view 484 --comments shows the disposition; no default in colleague/effortspikes.py changed in this arc

## Requirements

- The three arms dispatch FRESH from the row-69 artifact's recorded `task_text` (39661f2af608, 700 chars, the verbatim dispatch brief) — NOT via work --continue b702d8249dea: that chain holds zero prior progress (3a87abc231b1 SIGTERM'd at 0 steps, b702 at 2 `read_file` steps) and b702's `task_text` is the synthesized continuation SEED (2,943 chars, 'You are CONTINUING…'), recorded by a build predating the Qodo-thread-5 salvage fix, so continuing it would propagate the seed as the arms' brief
  - instruction: python3 -c 'import json;print(json.load(open("<target>/.colleague/39661f2af608.reduce-colleague-loop-py-from-962-lines.json"))\["`task_text`"\])' > brief.txt; dispatch uv run colleague work "$(cat brief.txt)" --repo <clean worktree at 5a721b8f> --no-pr
  - honesty: sha256 of each arm artifact's `task_text` equals sha256 of 39661f2af608's `task_text`
- Before the arms, ONE pre-flight smoke of the armed barrier on a throwaway repo: t12/row 69 ran spikes OFF and the barrier has never fired live — proof is unit-level only (tests/`test_barrier_pre_mutation.py`). The smoke must show a barrier.`pre_mutation` Step + `effort_spikes` record on the artifact, `chat_template_kwargs` `reasoning_effort`=medium on that one completion, and NO effort-spike-barrier warning
  - instruction: throwaway git repo with one tiny module + a 2-line write brief; `COLLEAGUE_EFFORT_SPIKES`=1 `COLLEAGUE_TIMEOUT`=600 uv run colleague work ... --no-pr; then inspect the artifact's `effort_spikes`, steps and warnings
  - honesty: the smoke artifact carries `effort_spikes` == \[{point: barrier.`pre_mutation`, rung: medium, seat: cortex}\], a Step named barrier.`pre_mutation`, and no effort-spike-barrier warning; the smoke's reasoning sidecar shows the barrier turn's reasoning larger than the surrounding low turns
- Barrier validity is checked per arm, never assumed: `loop_barrier` caps the barrier turn at the STANDARD timeout (min(`base_timeout`, timeout) = `COLLEAGUE_TIMEOUT`) and on timeout/failure warns effort-spike-barrier and lets the turn proceed unbarriered — arm C would silently degrade into arm A. An arm whose artifact carries that warning or lacks the barrier.`pre_mutation` Step is recorded VOID and rerun, not written as a miss
  - instruction: after each B/C arm: python3 reads the artifact; assert 'effort-spike-barrier' not in warnings kinds and a step named barrier.`pre_mutation` exists; else mark VOID and rerun once
  - honesty: arms B and C each carry the barrier.`pre_mutation` Step and record; any arm carrying an effort-spike-barrier warning is marked VOID in its row and rerun once before any comparison is drawn
- Correctness is the primary measure and is verified by the operator on the result branch, never read off the run summary: the branch imports (`importcheck_report`), the six source-text pins hold, affected tests pass, full suite green; spend is secondary (cumulative reasoning chars, wall seconds, model turns, longest single turn). n=1 per arm is stated in every row; rows 71-73 cite rows 67-70
  - instruction: git worktree add <tmp> colleague/<id>; cd <tmp>; python -c 'import colleague.loop'; the six pin greps from row 67; uv run pytest -n auto -q; quote outputs in the row
  - honesty: correctness is asserted by commands run on the result branch checked out in a fresh worktree (python -c 'import colleague.loop', the six pin greps, uv run pytest -n auto -q), with their output quoted in the row; never by the run's own summary

## Honesty conditions

- every arm's artifact records effort {main: low}, sampling row matched, `max_steps` 90, and `task_text` byte-equal to 39661f2af608's — read off the artifact, not the shell history
- arm A's row states whether the run FINISHED (and so whether any fix-turn ran at all) and quotes `importcheck_report` and the affected-tests warning verbatim
- arm B and C artifacts show exactly one `effort_spikes` entry (barrier.`pre_mutation`) unless a gate/fillline point fired at low, in which case that entry is quoted and its rung is low
- git diff 4405d07b -- colleague/ after the arc is empty; the only code-adjacent edits are docs/, CHANGELOG.md and the version bump
- tests/`test_effortspikes_boundary.py` still enumerates exactly three points and passes unchanged after the arc
- a reader with only rows 70-73 and the #484 comment can reproduce each arm's env and brief source without this session's memory file
- before dispatch, grep 'barrier.`pre_mutation`' across docs/live-testing.md returns nothing and no artifact anywhere under sf-t12-target/.colleague carries an `effort_spikes` key
- colleague/effortspikes.py `SPIKE_TABLE` and `spikes_enabled`() are byte-identical to 4405d07b at PR time; any default change is a follow-up issue, not this PR
- the disposition comment quotes the three arms' correctness verdicts and spend figures verbatim from the rows and names the reading with the pre-registered wording from #482

## Success signals

- each of the 3 arms yields a verified correctness verdict (import + 6 pins + affected tests + full suite, checked on the result branch) and 4 spend figures (reasoning chars, wall s, model turns, longest turn); zero arms VOID by barrier degradation after at most 1 rerun each; the disposition names exactly one of the three pre-registered readings
  - instruction: count: 3 rows with a correctness verdict and 4 spend numbers each; grep the arm artifacts' warnings for 'effort-spike-barrier' (must be absent in B and C); the #484 comment quotes one of: close #484 / #484 proceeds / reframe

## Scope / boundaries

- The arms MEASURE; they change no code and no default. The only default change the arc licenses is the pre-registered one — arming a spike by default requires C to beat B — and a miss is written as a miss. Deliverables: three docs/live-testing.md rows, the effort-spikes.md 'Honest limits' pointer to them, the #484 disposition comment, a patch version bump for the docs PR, the memory file update
  - instruction: git diff 4405d07b --stat at PR time shows only docs/, CHANGELOG.md, pyproject.toml, colleague/`__init__.py` (version)
- Nothing in the arms inspects turn content to pick a rung and no new spike point is added: the fixed three-point `SPIKE_TABLE`, the per-point env overrides and the opt-in are the entire surface used; the excluded router stays excluded
  - instruction: diff colleague/effortspikes.py and colleague/`loop_barrier.py` against 4405d07b after the arc: empty

## Assumptions

- Arm A = the v1.75.0 harness at cortex low with spikes unarmed; its 'feedback' is #480's surfaced gate warnings + #482's import check. Honest limit: importcheck.py ships NO fix-turn (CLAUDE.md: 'runs on EVERY exit outcome, no bounded fix-turn') and the affected-tests fix-turn runs only on a FINISHED outcome — so #482's pre-registered 'wired to feed its failure back as a bounded fix turn' is only partly what shipped, and the row must say so
- Arm B = `COLLEAGUE_EFFORT_SPIKES`=1 + `COLLEAGUE_EFFORT_SPIKE_BARRIER_PRE_MUTATION`=low; arm C = `COLLEAGUE_EFFORT_SPIKES`=1 with the table's medium. The one switch ALSO arms gate.`repeat_failure` (medium) and fillline.decision (xhigh via `DESIGN_SITE_TABLE`) in both B and C, so B-vs-C isolates the barrier rung but A-vs-B does not isolate the barrier unless those two points are pinned to low by their per-point overrides
- Rig is ready now: lobes armed at localhost:8001 serving unsloth/Qwen3.8-27B-NVFP4 (cortex ready, context 262144), config show reports cortex low and the matched Qwen3.8 thinking sampling row on the wire, GPU 3% idle with no colleague work running; arms run sequentially with `COLLEAGUE_TIMEOUT`=600 (decision q5/c19 superseded plan t13's 300)

## Scope exploration

- `s1` — `colleague/effortspikes.py`: exactly three points (barrier.`pre_mutation` medium, gate.`repeat_failure` medium, fillline.decision delegated to `DESIGN_SITE_TABLE` xhigh); ONE opt-in `COLLEAGUE_EFFORT_SPIKES`=1 arms all three; per-point override `COLLEAGUE_EFFORT_SPIKE_`<POINT> re-validated through the closed ladder
  - seeds: `c6`, `c9`
- `s2` — `colleague/loop_barrier.py (should_fire/intercept/make_barrier_complete)`: fires at most once per run, only while EVERY prior step named a read-only tool; timeout = min(`base_timeout`, timeout) i.e. the ordinary `COLLEAGUE_TIMEOUT`; a timed-out or failed barrier warns 'effort-spike-barrier' and the turn proceeds unbarriered; mock has no seam and warns once
  - seeds: `c3`, `c4`
- `s3` — `colleague/loop_gateescalation.py + loop_testgates.py:211/314 + loop_context.py:111`: gate.`repeat_failure` escalates the SECOND repair attempt of `test_integrity`/`affected_tests` gates (finished outcomes only); fillline.decision escalates the declaring turn — both armed by the same single switch as the barrier
  - seeds: `c6`
- `s4` — `sf-t12-target/.colleague artifacts 3a87abc231b1, b702d8249dea, 39661f2af608`: 3a87: error, 0 steps, `task_text` = the 700-char brief; b702: `continued_from` 3a87, error after 2 `read_file` steps, `task_text` = the 2,943-char continuation SEED; 39661f2af608 (row 69): incomplete, 63 steps, `task_text` = the same 700-char brief verbatim — the fresh-dispatch source
  - seeds: `c2`
- `s5` — `tests/test_continuation_task_text.py:337 + colleague/cli/_commands/_work_salvage.py:158`: the SIGTERM salvage writer bypassing `apply_continuation_task_text` was found by Qodo thread 5 on #486 and fixed before merge (23:41); b702 was written at 23:02 by the pre-fix build — explains its seed-as-`task_text`, not a live bug
  - seeds: `c2`
- `s6` — `colleague/importcheck.py + CLAUDE.md import-check bullet`: importcheck has no retries/fix-turn code; affected-tests fix turns run only on `_EXIT_FINISHED` outcomes — arm A's 'fed-back fix turn' exists only when the run finishes
  - seeds: `c5`
- `s7` — `docs/live-testing.md rows 67-69 + #484/#482 comments + plan t13 + deviation d1`: rule pre-registered on #482: same correctness at lower spend → close #484; correctness only with the planning turn → #484 proceeds; neither → reframe. Rows 67/69 at 40 steps were budget-bound (incomplete + non-importing); row 68 at 90 steps completed at low — so 40 steps cannot discriminate the arms
  - seeds: `c7`, `c8`
- `s8` — `uv run colleague config show / lobes show / nvidia-smi / pgrep`: lobes armed localhost:8001, cortex Qwen3.8-27B-NVFP4 ready, sampling row matched, cortex low, GPU idle, no colleague work in flight
  - seeds: `c10`
- `s9` — `colleague/roles.py:78-97 (_WRITE_TOOLS / _READONLY_TOOLS) + arm A trace step 1`: `run_command` ∈ `_WRITE_TOOLS`; the barrier's name-only lookup fires on it; arm A ran 'wc -l' at step 1 so B/C will barrier at step 1 unless the model happens not to shell out
  - seeds: `c4`
- `s10` — `arm B first attempt (flight 4f362863a7b5) + loop_barrier.should_fire`: the model's FIRST call was `run_command` (git status); `should_fire` refuses once any prior step is mutating, so the barrier can never fire in that run — VOID under h4, stopped cooperatively at step 4 and rerun once. On this brief the v0 name-only trigger is a coin flip on the model's opening move (arm A opened with `read_file`, its wc -l came second)
  - seeds: `c4`
- `s11` — `arm B rerun opening (step 0: run_command wc -l …)`: the h4 rerun ALSO opened with `run_command` — VOID twice; the v0 barrier is unmeasurable on this brief as shipped; the rerun continues as a spikes-armed-never-fired A replicate (wire-identical to arm A, so it feeds park r2's n=1 noise); C runs as shipped per q6; two voids point the disposition at #482's 'neither → reframe' reading plus the trigger follow-up issue
  - seeds: `c4`
- `s12` — `arm C attempt 1 opening (flight 1452182d4e80: step 0 run_command wc -l; ls -la)`: shell-first again — 4 openings on this brief, 3 shell-first; VOID under c4, stopped at once and rerun once (the h4 allowance)
  - seeds: `c4`

## Decisions

- q1: arms dispatch FRESH from row 69's artifact 39661f2af608 `task_text` (700 chars); never --continue b702d8249dea
- q2: `COLLEAGUE_MAX_STEPS`=90 for the smoke-independent arms A, B and C
- q3: arms B and C set `COLLEAGUE_EFFORT_SPIKE_GATE_REPEAT_FAILURE`=low and `COLLEAGUE_EFFORT_SPIKE_FILLLINE_DECISION`=low so only the barrier rung varies (B low via `COLLEAGUE_EFFORT_SPIKE_BARRIER_PRE_MUTATION`=low, C medium from the table)
- q4: at equal correctness C beats B only by lower total spend; equal correctness at higher spend is a miss for C
- q5: `COLLEAGUE_TIMEOUT`=600 for the smoke and all three arms
- q6: arms B and C measure the barrier AS SHIPPED (name-only trigger, `run_command` mutating); rows record the fire position; a step<=2 fire files a follow-up issue on the trigger

## Open parks

- [unknown_nonblocking] n=1 per arm on a stochastic model at temperature 1.0 — a single-run difference on spend may be noise; the arc has no budget for replicates, so each row states n=1 and the disposition must not overclaim
- [unknown_nonblocking] Whether the row-69 brief crosses the fill-line at all (200k token budget; row 68 spent 413k reasoning chars) — if it never crosses, fillline.decision is untestable on this brief and stays unmeasured
