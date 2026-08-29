# Delivery Summary — purpose-tools-get-chosen

plan: `purpose-tools-get-chosen` · run: `partial` · date: `2026-08-29`
baseline: `devague summary skeleton`

## Intent

Make colleague's cortex actually choose the six purpose tools it has held since
v1.66.0 — and settle, with a number, whether non-delegation is a *prompt*
problem or a *surface* problem. The plan is 16 tasks in 7 waves: four #438
stall-recovery fixes and three instrumentation fixes first, then four measured
levers (prose at three encouragement rungs, an acting-seat surface narrowing,
both, and restoring `subagent`/`subagents`), then a pre-registered arm matrix.

**This run executed wave 1 only** (6 tasks), with **colleague as the main
developer** — dogfooding and live-testing the harness against its own arc.
Waves 2–7 were not started; that was the approved scope of the fan-out
(operator: "Approved — wave 1 only, then reassess").

## Planned Work

Quoted verbatim from the `devague summary` skeleton:

- `t1` — \#438a: bound the blocking-fallback path with the same StreamGuards
- `t2` — \#438b: stop backpressure's timeout self-raise when stream guards are armed
- `t3` — \#438c: the idle guard treats SSE keepalive lines as non-activity
- `t4` — \#438d: tally stream-guard trips onto the artifact
- `t5` — Prompt/surface unification: the depth-0 writer substitution feeds the prompt as well as the tool surface
- `t6` — Count markup-shaped tool calls for any function name on the artifact
- `t7` — Record a system-prompt digest on the artifact so a prose arm is attributable
- `t8` — Acting-seat-scoped tool drop knob (the surface lever's instrument)
- `t9` — Repair the stale SUBAGENTS prompt section in both literals
- `t10` — Author the arm briefs: re-authored decomposable brief + a large-surface brief
- `t11` — Arm 4: restore subagent/subagents to the acting seat without leaking to children
- `t12` — Author the three prose overlays P0/P1/P2
- `t13` — Row 49 validity re-run: is the 0/3 real or dropped markup?
- `t14` — Pre-register the arm rows and their pass bars
- `t15` — Close the arc: docs, honest conclusion, and the before-state record
- `t16` — Run the arm matrix and record results honestly

## Actual Delivery

| Plan task | Status | What actually landed |
|-----------|--------|----------------------|
| `t1` | delivered | Guards built once per turn in `_stream_or_blocking` and shared with the blocking fallback; merged `73546bf`, integration fixes `4a17e67` |
| `t2` | delivered | Proactive backpressure timeout raise suppressed while guards are armed; merged `0924f9f`, defect fix `909bc41` |
| `t3` | delivered | SSE comment lines no longer restart the idle clock, both read paths; merged `3e355e9` |
| `t4` | delivered | `stream_guard_trips` counter on `WorkStats.counts`; merged `a0d46b6` |
| `t5` | not started | wave 2 — outside this run's approved scope |
| `t6` | not started | wave 3 |
| `t7` | not started | wave 3 |
| `t8` | delivered | `COLLEAGUE_ACTING_DROP_TOOLS`, depth-0 only; merged `a811661` |
| `t9` | not started | wave 3 |
| `t10` | delivered | Both briefs authored and merged (`d2160a8`); criterion 2 discharged by a three-attempt operator pilot recorded in the brief, with the deterministic fixture generator committed (`8af3ee6`) |
| `t11` | not started | wave 3 |
| `t12` | not started | wave 3 |
| `t13` | not started | wave 4 |
| `t14` | not started | wave 5 |
| `t15` | not started | wave 7 |
| `t16` | not started | wave 6 |

Six of sixteen tasks delivered. Ten not started — wave 1 was the approved
scope; the remaining waves are unblocked and unattempted, not failed.

## Mid-work Decisions

No `devague deviate` records exist for this run (`devague deviate --list` →
"no deviations recorded yet"). The decisions below were made and approved in
session but were **not** routed through `/deviate` at the time — a process
miss recorded here rather than retrofitted into the delivery store.

- **`t10` criterion 2 narrowed, then the task reassigned.** The criterion
  demanded "evidenced by a recorded pilot run"; colleague spent all 15 steps
  probing the rig (`curl /v1/models`, `config show`, `env`) and produced no
  files. The criterion was mis-specified for a doc-authoring seat. Narrowed so
  the briefs *specify* what the pilot must demonstrate and which artifact
  fields evidence it, with the pilot itself becoming operator work; the task
  was reassigned to an opus subagent, which delivered.
- **Brief 1 names no tool at all.** The plan allowed either the purpose-tool
  names or none. The subagent chose none, on a constraint the plan had not
  articulated: the same brief runs across arms whose *surfaces differ*
  (`t11`'s restore arm holds `subagent`/`subagents`; the purpose arms do not),
  so any tool name is a steer one arm cannot act on. The row-48/49 invitation
  sentence survives; only the advertisement was removed.
- **Stream max-lifetime default raised 900 s → 1800 s** (`b581b2c`), outside
  the plan. Operator call, made against this run's own evidence: `t3` died at
  exactly 900 s with its implementation unwritten. Historical measurement
  records citing the 900 s bound were deliberately left unchanged.
- **`COLLEAGUE_TOOLS_LEGACY` rejected as the surface-arm instrument.** Found
  during the challenge pass to be role-blind — it strips `grep_search`/`glob`
  from the scout child too (8 tools → 6), degrading the delegate the arm exists
  to make attractive. `t8` was respecified as a depth-0-scoped drop knob.
- **Two file-length ratchet baselines raised by hand**, not by
  `FILE_LENGTH_BASELINE_UPDATE=1` — the bulk path also reaps stale entries and
  would have masked other growth. `colleague/tools.py` 1508 → 1526 (the drop-set
  feature); `colleague/engines/vllm_openai.py` 1324 → 1358 (the shared-guards
  feature). `colleague/loop.py` was trimmed back to its 5281 baseline exactly
  rather than raised.
- **The large-surface pilot was discharged as a NEGATIVE finding, not
  engineered around.** Three attempts (`eeb7f261f87d` `ok` with no limit hit;
  `75b0c4a23087` VOID on a 1800 s stall with `stream_guard_trips == 1`;
  `b7b2c91748f9` SIGTERM'd at 5 steps under external GPU contention) showed
  the acting seat never uses `read_file` for a survey — it builds a symbol
  index with one `grep -nE '^(def |class |import |from )'` and then reads
  ranges with `sed -n`. Two fixture flaws found en route were mine, not the
  model's: shared pair doclines, and every algorithm sitting in the first ~36
  lines so one uniform slice surfaced all twelve. Scattering the algorithms to
  per-module offsets did not defeat the strategy — the grep index hands the
  model the offsets.
- **"Small briefs only" accepted as the matrix's reported scope** (spec `c55`,
  operator). The alternative — dropping `run_command` from the acting seat to
  force the cannot-fit condition — was rejected as a larger surface change
  than the arc measures. This takes h35's "reported as measuring small briefs
  only" branch, which spec c47 authorises explicitly.
- **`t1` salvaged from an orphaned worktree.** A machine restart killed the run;
  a hard kill fires no #222 WIP-on-stop commit, so the work survived only as
  178 uncommitted insertions on disk.

## Drift From Plan

| Plan item | Reason for divergence | Classification |
|-----------|-----------------------|----------------|
| `t10` | Acceptance criterion 2 (pilot run) was mis-specified for a doc-authoring seat; narrowed to specification-of-the-pilot and executed by the operator instead. Task reassigned from colleague to an opus subagent. Criterion 2 is now discharged — as a negative finding, which spec c47 explicitly authorises. | acceptable |
| `t1` | Delivered work broke nine existing tests (doubles of the `_post_json` signature it changed) and its own new test recursed against conftest's autouse SSE bridge, so it never ran green as delivered. Integrator wrote a degrade path and rewrote the test as a socket-free unit test. | acceptable |
| `t2` | Delivered with two self-reported defects — a duplicated `_escalate_request_timeout` call and +2 over the file-length ratchet — fixed by the integrator in `909bc41`. | acceptable |
| `t8` | Merged without `test_file_length_ratchet.py` in its affected-test set, so `tools.py` growth surfaced two merges later. Operator gate gap, not a defect in delegated work. | acceptable |
| `t5`–`t7`, `t9`, `t11`–`t16` | Not started — wave 1 was the approved fan-out scope. | acceptable |

## Evidence

- tests: full suite `uv run pytest -n auto` — **10400 passed, 26 skipped**
- tests: `tests/test_stream_guards.py` — 16 passed (incl. the rewritten
  `test_fallback_shares_the_streaming_guards_object`)
- tests: `tests/test_acting_drop_knob.py` — 13 passed
- tests: `tests/test_runcounts.py`, `tests/test_file_length_ratchet.py` — pass
- lint: `uv run black --check colleague tests` · `isort --check-only` ·
  `flake8 colleague tests` — all clean
- security: `uv run bandit -c pyproject.toml -r colleague` — 0 medium, 0 high
- commits: `origin/main..HEAD` (18 commits), merges `a0d46b6` `a811661`
  `3e355e9` `d2160a8` `0924f9f` `73546bf`
- probe: `COLLEAGUE_ACTING_DROP_TOOLS=grep_search,glob` → acting seat lacks
  both, scout child retains both
- pilot: `eeb7f261f87d` (`ok`, 18 steps, no limit) · `75b0c4a23087` (VOID,
  `stats.counts.stream_guard_trips == 1`) · `b7b2c91748f9` (SIGTERM, 5 steps)
- fixture: `scripts/make_large_surface_fixture.py` — 12 modules, 17,996 lines,
  708,496 chars, deterministic
- issues: #438 (four guidance points addressed), #435, #437, #443, #360, #399,
  #413

## Delivery Claims

| Claim | Confidence | Evidence |
|-------|------------|----------|
| The blocking fallback is bounded by the same guards as the streaming path, sharing one guard object per turn | high | commit `73546bf` · test `tests/test_stream_guards.py::test_fallback_shares_the_streaming_guards_object` |
| Backpressure no longer raises the request timeout while stream guards are armed | high | commit `0924f9f` · file `tests/test_backpressure_guard_suppression.py` |
| SSE keepalive comment lines no longer restart the idle clock, on both read paths | high | commit `3e355e9` · test `tests/test_stream_guards.py::test_keepalive_comment_lines_do_not_reset_the_idle_clock` |
| Stream-guard trips are countable from the artifact without parsing warnings | high | commit `a0d46b6` · test `tests/test_runcounts.py::test_finalize_tallies_stream_guard_trips` |
| The acting seat can drop named tools while children keep them | high | commit `a811661` · test file `tests/test_acting_drop_knob.py` · live probe recorded above |
| Two arm briefs exist, neither naming a tool its arm does not offer | high | commit `d2160a8` · `grep -rn subagent docs/live-testing/briefs/arm-*.md` exits 1 |
| The 1800 s guard default is safer for real test-first tasks on this rig | medium | commit `b581b2c` · `t3` died at exactly 900 s; n=1 |
| The large-surface brief's baseline provably hits a budget limit | **refuted** | pilot `eeb7f261f87d` finished `ok` in 18 steps with no limit hit; recorded in the brief |
| The acting seat surveys via a shell symbol index rather than `read_file`, so `read_file` paging never binds | high | pilot steps 2-3 of `eeb7f261f87d` and `b7b2c91748f9` (`grep -nE '^(def \|class \|import \|from )'` then `sed -n`) |
| `t4`'s stream-guard counter works against a real stall | high | pilot `75b0c4a23087` artifact: `stats.counts.stream_guard_trips == 1` |
| Arm results will be reported as measuring small briefs only | high | operator decision recorded as spec `c55`; the underlying refutation is the negative pilot above (one fixture size tested; size-independence argued, not measured) |
| #438's stall class is closed | unverified | four guidance points implemented, but no post-fix live run has exercised them against a stalling gateway |
| Purpose tools are more likely to be chosen after these changes | unverified | no arm has run — that is waves 4–6 |

## Remaining Work / Follow-up

- **Scope of the matrix — DECIDED, no longer open.** The operator accepted
  "small briefs only" as the reported scope of every arm (spec `c55`); the
  acting seat is not narrowed further. Plan `t14` must carry the scope line
  verbatim on every row, and `t15`'s closing record must repeat it.
- **`t5`** (wave 2, the linchpin) — prompt/surface unification. Blocks every
  prose arm: the overlay instrument does not reach a bare run until it lands.
- **`t6`, `t7`, `t9`, `t11`, `t12`** (wave 3) — markup counter, prompt digest,
  stale-section repair, arm 4, the three overlays.
- **`t13`** (wave 4) — row-49 validity re-run. Until this runs, the arc's
  motivating evidence (0 purpose calls in 3 runs) is unverified against #360's
  silent markup-drop failure mode.
- **`t14`, `t16`, `t15`** (waves 5–7) — pre-register, run the matrix, close.
- **Version bump** — `pyproject.toml` still reads `1.66.0`; the PR needs a bump
  or CI's `version-check` job blocks the merge.
- **File an issue: the step budget has no headroom for the commit.** Five of
  five completed colleague runs finished the engineering and exhausted their
  budget before `git commit`; all five survived only via the #222 WIP-on-stop
  commit, and two named their leftovers precisely. The brief asks for a commit
  the budget does not allow.
- **File an issue: `work --continue` re-bases on HEAD**, discarding the
  interrupted run's WIP branch. Episode chaining bases on the prior
  `colleague/<id>` tip; continuation does not. Cost here: one rebuilt test file
  (`4daeee92674b` reported "the prior partial edit (2126 bytes) was lost").
- **Record: a hard kill leaves no WIP commit.** The #222 mechanism needs a
  cooperative signal; a machine restart leaves only the on-disk worktree, which
  `colleague clean` would eventually reap.
- **Process: route mid-run departures through `/deviate`.** This run produced
  six recordable decisions and zero `dN` records.
