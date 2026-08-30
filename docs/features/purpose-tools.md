# purpose-tools — the six typed delegation tools (purpose → role → seat)

**Status:** built on the purpose-tools-associate-seat arc (spec
`docs/specs/2026-08-28-purpose-tools-associate-seat.md`, 2026-08-28; issues #435/#436
lineage, #443 evidence). The live proof is pre-registered in
`docs/live-testing.md` rows 49–50 (main baseline `e589451`, v1.65.1); the
motivating numbers are quoted from rows 45/47/48. No qwen-code code is ported
— this is a new tool surface over the existing spawn path, so `NOTICE` and
`docs/adopted-from.md` are unchanged.

## What it is

Six typed delegation loop tools — `web_survey`, `code_survey`, `review`,
`validate`, `plan`, `handover_to_colleague` (`colleague/purpose_schemas.py:47-54`)
— each a FIXED purpose → FIXED built-in role → FIXED seat
(`PURPOSE_ROLE`, `purpose_schemas.py:59-66`): the two surveys run a scout child
(the associate seat when armed), review/validate/plan run a
reviewer/validator/planner child on cortex, and `handover_to_colleague` runs a
writer child on the parent's cortex config. The schemas live OUTSIDE
`tools.SCHEMAS` and are appended by `curate_schemas` (the `DEEPTHINK_SCHEMA`
precedent, spec s1); none exposes an `effort`, `model`, `engine` or `role`
property — the model cannot pick a rung, a backend, or a role
(`purpose_schemas.py:16-20`).

The dispatch (`purpose_schemas.dispatch`, `purpose_schemas.py:432-484`) renders
the FIXED brief (`brief_for`, `purpose_schemas.py:287-294`) and spawns ONE child
through the executor's injected spawn callable with the purpose's fixed role,
rung and step budget (`purpose_schemas.py:466-476`). A child that exhausts its
step budget returns its partial prefixed `[purpose budget exhausted: N steps]`
(`_EXHAUSTED`, `purpose_schemas.py:303`) — never an empty string, never a raise.
Read-only purposes are EXEMPT from the `MAX_SUBAGENT_FANOUT`/TOTAL arithmetic
(`charges_budget`, `purpose_schemas.py:313-325`); `handover_to_colleague`
charges exactly like a manual `subagent`. The child's served model and web
counters fold back onto the parent's step arguments and executor
(`_record`, `purpose_schemas.py:385-409`), and the tool result ends with a
`urls fetched:` block when the child made any `web` call
(`_render`, `purpose_schemas.py:360-382`). `web_survey` is hidden exactly when
`web` is hidden (`hidden_names`, `purpose_schemas.py:204-214`); `code_survey`
is always offered.

## Before → after

**Before** (spec lines 13, 20, 97): cortex holds the raw `web` tool AND
`run_command`; delegation is never chosen — **0 subagent calls in 13 measured
runs** (rows 41–48) while typed tools are (row 47: **8 web calls in one turn**;
row 48: unprompted `grep_search`/`glob`); the associate seat idles (row 45:
**zero associate calls**); the distill child completes with no effort rung at
all (`distill.py:613-647`); one associate-wide `off` row covers scout and
distill alike (`effort.py:69`).

**After** (spec lines 15, 91): on the armed rig `colleague work` offers
`web_survey`/`code_survey`/review/validate/plan and NOT raw `web`; cortex calls
`code_survey` and gets a digest from a scout child whose artifact records the
associate's served model; `web_survey` returns a digest citing
`operation_id`/`evidence_refs` or an honest `unreachable` line; a memory-armed
run's distill child completes at `low` with reasoning chars on its record;
`COLLEAGUE_WEB=0` / no webglass hides `web_survey`, and the unset-knob suite is
byte-identical to v1.65.1.

## Audience by ROLE

- **cortex** (the acting seat) — calls the typed tools and reviews the digests
  before acting; holds `web_survey`/`code_survey` and `handover_to_colleague`,
  and neither raw `web` nor raw `subagent`/`subagents` (q9/q10, spec line 203).
- **associate** (the armed seat, addressed by role name through the gateway) —
  the scout child's served model when `COLLEAGUE_ASSOCIATE_MODEL` is set; it
  only ever receives the tool *result*, never the egress.
- **scout** (the read-only role) — runs `web_survey`/`code_survey` children.
- **reviewer** / **validator** / **planner** — run the review/validate/plan
  purposes on cortex at their own `PURPOSE_TABLE` rungs (low/low/medium).
- **writer** — the `handover_to_colleague` child; the only purpose that can
  mutate the tree.

The audience is named by **role**, never by model id in config code — the
zero-model-ids boundary test keeps passing (spec line 96).

## Why

The shape of the ask decides delegation: a `subagent` demands a meta-decision
(brief, role, isolation), a typed tool is one call. Row 48 showed adding
surface buys deliberation, not delegation — **3.31× wall / 1.41× turns, 2×
reasoning chars, 0/3 delegations on both arms** (main `df6a2ffd0437`,
`b6eb2ac23576`, `d9590dbc7f09`; branch `038619813cc8`, `83a953c5c584`,
`84414109dddd`). Row 47's re-run (`a5fe419b2a36`) showed cortex holding
`web` + `run_command` drifts into host reconnaissance (`/etc/hosts`,
`ss -ltnp`, `~/.cloudflared`; stopped by pilot, d15). The direct-seat numbers
(row 45, artifacts `e6a35cbbdd57`, `69d02da0ba77`, `c6c498415c94` (game) and
`2fb906f2593e`, `f19dfcc7e8a4`, `d96143bc4752` (repo)) say **17 s** survey /
**9 s** digest at thinking **off** versus **25 s / 61 s** at **low** — so
scout=off / distill=low is the right split (spec line 20).

## What shipped

- **`colleague/purpose_schemas.py`** — the six names, the fixed role table, the
  six schemas, the fixed brief templates, the hidden-state rule, and the
  dispatch (all cited in § What it is).
- **`colleague/efforttables.py`** — the two new tables:
  `ASSOCIATE_SEAT_TABLE` = {scout: off, compact: off, synthesis: off, digest:
  off, distill: low} (`efforttables.py:47-53`) and `PURPOSE_TABLE` =
  {`web_survey`: off, `code_survey`: off, review: low, validate: low, plan:
  medium, `handover_to_colleague`: medium} (`efforttables.py:57-64`), with
  `PURPOSE_STEPS` per-purpose step caps (`efforttables.py:68-75`) and the
  resolvers (`efforttables.py:135-163`, `efforttables.py:166-190`).
- **Per-seat effort on the associate side** — the one associate-wide `off` row
  (`effort.py:69`) is split per sub-seat; the detached distill child now
  receives its rung and sends the `chat_template_kwargs` fragment on its second
  raw OpenAI POST site (spec lines 43–45).
- **The raw delegation tools leave cortex** — `subagent` is replaced by
  `handover_to_colleague`, `subagents` is dropped (q9/q10, spec line 203);
  purpose tools are offered to cortex + worker only, never to children (q9,
  spec line 212).
- **Measurement** — `scripts/compare_arms.py` counts a purpose step in the
  `delegations`/`associate_calls` columns off `PURPOSE_TOOL_NAMES` (spec
  lines 37–39).

## Measurement

The live proof is pre-registered in `docs/live-testing.md` **rows 49–50**
(brief text, repo, pass bar, and the main baseline `e589451` written BEFORE any
run; a miss is written as a miss). Row 49 runs the row-48 decomposable brief
n=3 with purpose tools offered and the associate armed (pass: purpose calls ≥ 1
on ≥ 2 of 3 runs, turns ≤ 1.0× / wall ≤ 1.2× vs main @ `e589451` RE-RUN n=3 —
the `4e814c8` numbers do not carry, park v3). Row 50 runs the row-47 web brief
with `web_survey` (cortex holds NO raw `web`): pass is the scout child's served
model = the associate's, evidence ids cited in the answer, and zero
`run_command` steps outside the repo. Both rows name a throwaway repo WITH an
`.eidetic` store (eidetic CLI 0.13.0) and record the memory distill counters.
**Results (2026-08-28, rows 49–50 in `docs/live-testing.md`):** row 49 **MISS** — branch n=3 `78b0f0f90855`/`480b6d6ea857`/`59fb72435645` 88.6 s / 6.67 turns vs main @ `e589451` 327 s / 5.67 (wall 0.27×, turns 1.18×), **0/3 purpose calls** — on a three-small-file brief cortex reads the files itself. Row 50 `0780c75e2519` **MISS on the bar, mechanism proven** — with raw `web` absent, cortex fired `web_survey` ×3 in its first turn, all three scout children ran on the associate seat, digests cite WebGlass operation ids, **zero `run_command`** (the row-47 host-recon path is closed), the one work-item web budget was consumed across the children; cortex then step-stalled (#438) before writing the final answer, so the evidence-ids-in-answer clause missed. The delegation doctrine (#435) stands: a purpose form is chosen where the raw tool is absent, not where reading is cheaper.

**Rows 51–58 (2026-08-30) supersede that last sentence.** Row 51 re-ran row
49's brief verbatim with the #360 markup counter in place and found markup 0 on
every run, so row 49's 0/3 is real behaviour and not a dropped call. The
21-run arm matrix of rows 52–58 then measured the two declared levers and found
neither moved the rate, while restoring the raw `subagent`/`subagents` pair
produced no raw call anywhere in the matrix — so "chosen where the raw tool is
absent" is not the mechanism either. See § The `purpose-tools-get-chosen` arc
below and the closing record in `docs/live-testing.md`.

## Honest limits

- **The single-child spawn path creates no `sub/<id>` worktree (d9).**
  `run_subagent` runs a purpose child in the parent's tree exactly as a manual
  subagent does today; read-only purposes cannot write regardless, and
  `handover_to_colleague` inherits today's manual-subagent behaviour.
- **Thinking continuity is OUT of this arc (q8/#446).**
  `truncate_history_thinking` is a request-side no-op — colleague never
  re-sends a prior turn's reasoning (`loop.py:345-356`); carrying the scout's
  `reasoning_content` back in its own history is a wire-shape change tracked in
  issue #446 (spec line 128).
- **The armed-scout sentence is spliced onto `web_survey`/`code_survey` only
  (d8)** — never `handover_to_colleague`, whose child is a cortex writer.
- **A MANUAL typed child still inherits the parent's cortex seat override
  above its `ROLE_TABLE` row (v5, a follow-up).** Purpose children do not:
  `PURPOSE_TABLE` is passed as the spawn's explicit override
  (`purpose_schemas.py:471`).
- **Purpose tools are not batch-safe (v2)** — they stay outside
  `CONCURRENCY_SAFE_TOOLS` and serialize; the resident webtrust gate on
  `web_survey` is not re-examined (v6); whether flight stop reaches a running
  purpose child is unverified (v7).
- **The read-then-fetch exfiltration channel is accepted under the
  trusted-operator model D2** — now it crosses the purpose boundary: the
  parent's tool result and run-report web line list every URL the child fetched
  (spec lines 74–76).

## Knobs

| Knob | Off value | Mechanism | Module |
| --- | --- | --- | --- |
| `COLLEAGUE_<PURPOSE>_REASONING_EFFORT` / `reasoning_effort_purposes` | unset → `PURPOSE_TABLE` row | Per-purpose rung override, ladder-validated; precedence kill-switch > parent override > purpose override > `PURPOSE_TABLE` (`efforttables.py:166-190`). | `colleague/efforttables.py` |
| `COLLEAGUE_ASSOCIATE_REASONING_EFFORT_<SEAT>` / `reasoning_effort_seats['associate.<seat>']` | unset → `ASSOCIATE_SEAT_TABLE` row | Per-associate-sub-seat override (dotted keys never collide with a plain seat name); precedence kill-switch > parent override > sub-seat override > whole-associate row > `ASSOCIATE_SEAT_TABLE` (`efforttables.py:135-163`). | `colleague/efforttables.py` |
| `default` (kill-switch) | n/a — value | `reasoning_effort='default'` anywhere in the chain drops the fragment everywhere (`efforttables.py:153-154`, `efforttables.py:180-181`). | `colleague/efforttables.py` |
| `COLLEAGUE_WEB` | `0` | Hides `web_survey` together with `web` (schema AND dispatch); `code_survey` is never hidden (`purpose_schemas.py:204-214`). | `colleague/purpose_schemas.py` |
| `PURPOSE_STEPS` | n/a — value table | Per-purpose step caps (12/12/16/16/10; `handover_to_colleague` rides the caller's); exhaustion yields the `[purpose budget exhausted: N steps]` marker (`purpose_schemas.py:347-357`). | `colleague/efforttables.py` |
| `COLLEAGUE_WEB_MAX_CALLS` | n/a — value, default `20` | ONE work-item-wide web budget: the parent passes its remaining count into the child spec and folds the child's counters back, so purpose children never multiply the budget (`purpose_schemas.py:474`, `purpose_schemas.py:405`). | `colleague/webbudget.py` |

## The q3 exemption — why a purpose child is not narrowed from its parent

`colleague/agents/delegation.py`'s `validate_delegation` skips the
`requested_tools` ⊆ parent check when `req.purpose` is set. Under #411 every
model-bound child surface must be identical to or narrower than its parent's,
so this reads at a glance like an escalation path. It is the opposite — the
exemption is *required by* this arc's central decision, and is adjudicated in
the spec at line 59 (raised as `s8`, line 151).

**Replace-don't-add** means cortex GIVES UP the raw `web` tool so that the
scout child becomes its only holder. (The *delegation* half of that principle
— cortex giving up raw `subagent`/`subagents` — was reversed under test by
arm 4 and restored when the matrix rejected that reversal; see the section
below. The `web` half, which is what this exemption turns on, never moved.)
Applying the subset rule here would make
the design impossible: the parent by construction no longer holds what the
child needs, so every `web_survey` call would refuse. The ⊆ rule assumes a
parent that *delegates a portion of its own surface*; a purpose tool instead
routes to a fixed role whose surface was never the parent's to begin with.

This does not widen anyone's authority:

- The child's surface is a `PURPOSE_TABLE` constant — one fixed purpose to one
  fixed role to one fixed seat and rung. It is never model-chosen,
  caller-chosen, or derived from the request.
- The effective surface is that role allow-list intersected with the
  environment (e.g. `web` only when WebGlass is installed), so an absent
  operator CLI still yields no tool.
- Every other bound in `validate_delegation` — authority ceiling, depth,
  fanout, total, context mode — still applies to purpose children unchanged.
- Host policy and the approval gate still gate every route; this is the
  delegation's own arithmetic only.

The predecessor honesty condition (`docs/features/web-scout.md` line 33, "the
scout receives `web` only when the parent's surface contains it") is superseded
by exactly this decision, and its pinning test was rewritten to the new rule.

## Arm 4 (plan t11) — the replace-don't-add reversal, TESTED AND REJECTED

**Status: the reversal was measured and it failed; the default is #443's
purpose-only surface again.** This section is kept in full — the hypothesis,
what it predicted, what the matrix found, and why the default moved back — so
that a later reader can see arm 4 was *tested and rejected on evidence*, not
quietly undone. What survives from the arm is its child-confinement hardening
(`CHILD_FORBIDDEN_TOOLS`), which is kept deliberately.

Issue #443 REPLACED the raw `subagent`/`subagents` tools on cortex with the six typed
purposes ("replace, don't add"). Arm 4 of the `purpose-tools-get-chosen` arc
(spec/plan `2026-08-29-purpose-tools-get-chosen`, task t11) put the two raw
names BACK on the acting seat **alongside** the purpose tools, as a
pre-registered arm, to separate two explanations of the delegation numbers that
row 49 could not tell apart:

- **H1 — crowding.** The raw alternatives are easier to reach for, so offering
  them suppresses the typed purposes.
- **H2 — suppression.** Removing the familiar delegation tools removed
  delegation *itself*, and the typed purposes never replaced it.

### The verdict (live-testing row 56, recorded 2026-08-30)

- **A4 — the raw pair ON the acting seat, drop knob absent: delegation 0/3**,
  calls per run `[0,0,0]`, `markup_tool_calls` 0 on all three runs (so the zero
  is real behaviour, not a #360 dropped call), 3/3 `ok`, turns 0.783× and wall
  0.522× vs A0. **VERDICT: MISS**, decided by the delegation clause.
- **Across the ENTIRE 21-run matrix — arm A4 included, the one arm where both
  raw tools were on the seat — `subagent` and `subagents` were called exactly
  ZERO times.** Every delegation that did occur was `code_survey`, a typed
  purpose: A5 6 calls over 2/3 runs, A6 12 calls over 3/3 runs.
- **H2 (suppression by removal) is refuted**: #443's removal of the raw pair
  was not what suppressed delegation — the suppression predates the removal and
  survived its reversal. **H1 (crowding) has nothing left to explain.** Task
  shape, not surface, is what moved the delegation rate (0 of 15 delegating
  runs on the small decomposable brief; 5 of 6 on the large-surface brief).

**Therefore the default reverted** (Qodo comment `3888125915`): the restoration
produced no measured benefit and reintroduced a delegation path that bypasses
the fixed purpose → role → seat mappings of `PURPOSE_TABLE`.
`_writer_allowlist` drops `web`/`subagent`/`subagents` again, and
`THINKER_CODER_TOOLS`/`ASSOCIATE_TOOLS` mirror it. **The child-confinement half
is KEPT**: `actingsurface.strip_child_forbidden_tools` still strips
`CHILD_FORBIDDEN_TOOLS = ("subagent", "subagents")` at depth >= 1, so a child
can never hold the raw pair *independently of* what the seat's allow-list
carries — defence in depth against this allow-list changing again.

### The two rows the hypothesis was built on, and what each actually showed

| Row | What it did | What it actually showed |
| --- | --- | --- |
| **50** — the row that **justified** replace-don't-add | Web brief on the branch arm: cortex held `web_survey` and **no** raw `web`. One run, `0780c75e2519`. | **Delegation observed**: cortex fired `web_survey` ×3 in its first turn and made **zero** `run_command` steps. The row's own overall verdict is **"MISS on the bar, mechanism proven"** — the pass bar missed because cortex step-stalled (#438) before writing a final answer citing the evidence ids, and the served-model clause landed only PARTIAL. So the row is evidence that the purpose *form* gets called where the raw tool is absent — it is **not** evidence that the outcome improved. |
| **49** — the row that **overturns** it (for the delegation half) | Decomposable code brief, branch arm n=3 vs main @ `e589451` n=3. | **0/3 purpose calls, `sub_results` 0** on the branch — a MISS on the delegation clause, and 1.18× turns (a MISS on the turns bar) at 0.27× wall. All six runs were `ok`. The row's own reading is that on a three-small-file brief cortex reads the files itself and the purpose form does not lower the ask enough to be chosen. So removing the raw delegation tools produced **no delegation of any kind** here, not typed delegation. |

Two honest limits on that reading:

- Row 50's mechanism proof is about `web`, where cortex had **no** alternative
  way to reach the network. Row 49's brief was code work cortex could do
  itself, so its 0/3 is consistent with H2 *and* with "delegation was simply
  not worth it here". Arm 4 does not settle that on its own — it is measured
  against the re-authored briefs of t10 and the pre-registered arm rows of t14.
- Row 49's own 0/3 was re-validated by plan task **t13** (row 51): the brief was
  re-run verbatim with the t6 markup counter in place and **markup was 0 on all
  three runs**, so the 0/3 is real behaviour, not the #360 dropped-markup
  artifact. The framing needed no correction — but see the closing record
  below, which reports what arm 4 actually measured.

### What the arm changed in code, and what the revert put back

| Surface | #443 (before arm 4) | Arm 4 (t11, measured) | Now (post-revert) |
| --- | --- | --- | --- |
| `_writer_allowlist` drop set | `{web, subagent, subagents}` | `{web}` | `{web, subagent, subagents}` |
| Acting-seat allow-list names | 21 | 23 | **21** |
| Acting-seat **rendered** tools (depth 0) | 20 | 22 | **20** |
| Depth-1 child allow-list names | 15 | 15 | **15** |
| Depth-1 child **rendered** tools | 14 | 14 | **14** |
| `THINKER_CODER_TOOLS` / `ASSOCIATE_TOOLS` | 20 | 22 | **20** |
| `strip_child_forbidden_tools` + `CHILD_FORBIDDEN_TOOLS` | (was `strip_purpose_tools`) | added | **KEPT** |

- `colleague/roles.py`'s `_writer_allowlist` drops
  `{"web", "subagent", "subagents"}` again — cortex delegates BY PURPOSE.
- `colleague/agents/tools.py`'s `THINKER_CODER_TOOLS` (and therefore
  `ASSOCIATE_TOOLS`) mirrors it, so the #411 agents-mode acting seat matches.
- **The child confinement arm 4 introduced is KEPT, on purpose.**
  `strip_purpose_tools` was widened into
  `colleague.actingsurface.strip_child_forbidden_tools`, which at depth >= 1
  removes the six purpose names *and*
  `CHILD_FORBIDDEN_TOOLS = ("subagent", "subagents")`. With the seat
  purpose-only again the raw-pair half of that strip is redundant with the
  allow-list — deliberately so: it is the standing, allow-list-independent
  guarantee that a child is the bounded writer, whatever the seat later holds.
  Pinned by `test_strip_child_forbidden_tools_removes_the_restored_raw_delegation`,
  which asserts the guarantee against a role that *does* carry the raw pair so
  the pin cannot rot into a tautology.
- The four exact-set pins (`tests/test_roles.py` ×3,
  `tests/test_purpose_tools_byte_identical.py`, `tests/test_agents_tools.py`)
  moved with the code both ways and are still **exact-set assertions, never
  relaxed to subset/membership checks**:
  `tests/test_knobs_byte_identical.py`'s `_PURPOSE_TOOL_CARVEOUT_DROPPED` is
  `{"subagent", "subagents"}` again, stated explicitly rather than emptied.
- The behavioural consequence arm 4 recorded is likewise reverted:
  `colleague/delegation_text.py`'s armed-facts sentence targets
  `subagent`/`subagents` as well as `web_survey`/`code_survey`, but the raw
  pair is absent from the curated writer surface again, so on an armed rig it
  splices onto **two** descriptions, not four.
- **`docs/live-testing.md` rows 49–58 are untouched.** They are the historical
  record of what ran, and arm A4 genuinely ran against the restored surface;
  no measured figure there was edited by this revert.

## The `purpose-tools-get-chosen` arc (2026-08-30) — what the matrix measured

Spec/plan `2026-08-29-purpose-tools-get-chosen`. Rows **51–58** of
`docs/live-testing.md` carry the evidence; the full closing record (per-arm
table, gaps, deviations, issues) lives there. The headline:

- **Neither declared lever moved the delegation rate.** Prose: A1 0/3, A2 0/3,
  A3 0/3 (wall/turns vs A0: 0.560/0.826, 0.908/0.913, 0.866/0.783). Surface:
  A4 0/3 (0.522/0.783). Every one of the 21 runs was `ok`, carried the
  `prompt_digest` its row pre-registered, and recorded
  `markup_tool_calls` = 0 — so no zero here is a #360 dropped call.
- **Arm 4 answers its own question in the negative, and answers the arc's.**
  It restored raw `subagent`/`subagents` to the acting seat, and **no
  `subagent`/`subagents` call occurred anywhere in the 21-run matrix, that arm
  included**. #443's removal of the raw pair was therefore *not* what
  suppressed delegation — H2 (suppression by removal) is refuted, and H1
  (crowding) has nothing left to explain. The reversal-under-test recorded
  above resolves as: the restoration changed no measured behaviour, and the
  default was reverted to the purpose-only surface on that evidence.
- **Task shape is what moved it.** 0 delegating runs of 15 on the small
  decomposable brief (A0–A4); 5 of 6 on the large-surface brief (A5 2/3 with 6
  `code_survey` calls, A6 3/3 with 12). Every delegation named `code_survey`.
- **Mechanism: cortex substitutes the parallel read-only tool batch.** A0–A4
  show `batches_run` 1–2 / `calls_parallelised` 3–7 with zero delegation, and
  the trade-off is visible inside A5 (run 1: 3 delegations, `batches_run` 0;
  run 2: 0 delegations, `batches_run` 3 / `calls_parallelised` 10). It holds a
  cheaper form of concurrency and prefers it until the surface is too large.
- **Delegating runs succeeded equally often — not more, not less.** 5/5 `ok`
  delegating, 16/16 `ok` non-delegating, each changing exactly one module. With
  row 50's failed delegating run and rows 49/51's successful non-delegating
  ones beside it, the supported conclusion is the one claim c46 exists to make
  reportable: **cortex was right not to delegate on a brief it can hold.**

Two limits bound all of the above:

- **The small-brief prose result is a FLOOR, not a null.** All five small-brief
  arms sat at exactly zero, so that brief cannot detect a prose effect of any
  size. Recorded as *not detectable on this brief* — never as "prose does not
  work".
- **A6-vs-A5 is confounded and did NOT promote.** With no P0 control on the
  large-surface brief it measures the P2 overlay whole — the imperative
  paragraph *and* the replacement of `BUILTIN_ROLES['writer'].prompt_fragment`
  that any operator overlay performs. It meets the q3 promotion numbers
  (6 → 12 calls, turns 0.762×, reasoning 10661 → 10852) and is still not
  promoted; a clean test needs a P0-control arm on a brief that is not already
  at the floor.

**Nothing encouraging shipped.** The default prompt's `Purpose tools
(optional).` section (t9, `_PURPOSE_TOOLS`, **165 words**, down from the
174-word `_SUBAGENTS` section it replaced) *names and describes* the six typed
tools and says "never delegate just to delegate". The imperative encouragement
this arc tested exists only in the P1/P2 overlays under
`docs/live-testing/overlays/` — staged experiment instruments, not shipped
defaults. No claim in this doc, in `CLAUDE.md` or in `adopt-from-qwen-code.md`
asserts encouragement the shipped prompt carries.

**Rendered surfaces, recomputed from source at t15** — *as measured, while
arm 4 was in effect* (`loop.resolve_role` → `loop.curated_schemas`, no
`COLLEAGUE_*` set): depth 0 = **22** offered tools; depth 0 under the arm knob
`COLLEAGUE_ACTING_DROP_TOOLS=subagent,subagents` = **20**; depth 1 = **14**,
with `depth-0 minus depth-1` exactly the six purpose names plus
`subagent`/`subagents`.

**Post-revert** (arm 4 rejected, Qodo `3888125915`): depth 0 = **20** — the
same surface the arm knob produced, since the seat no longer holds the raw
pair; depth 1 = **14**, unchanged, with `depth-0 minus depth-1` exactly the six
purpose names. The A4-vs-A0 comparison the matrix ran is therefore unaffected:
A0 already measured the surface the default now carries.

## The `delegation-follow-ups` arc (2026-08-30) — the two gaps #456 named, closed

Spec/plan `2026-08-30-delegation-follow-ups-a7-p3-hire`. Rows **59–62** of
`docs/live-testing.md` carry the evidence (nine runs on the large-surface
brief, all `ok`, zero voided, every artifact carrying the `prompt_digest` its
row pre-registered AND — new in this arc — an `offered_tools` list, the
depth-0 curated surface read off the artifact rather than from the shell that
launched the run). Both arms close an inference gap; neither fixes a defect,
and both results are negative:

- **Gap 1 — the raw-vs-purpose fair fight (A7, row 59) is UNANSWERED, not
  lost.** With both the raw `subagent`/`subagents` pair and the six purpose
  tools on the acting seat (the `COLLEAGUE_ACTING_ADD_TOOLS` knob — an ADD
  instrument, because since arm 4's revert the writer allow-list drops the
  raw pair unconditionally and unsetting the drop knob restores nothing),
  cortex delegated **0/3** by EITHER form: no raw call, no purpose call, no
  parallel batch — it surveyed in-seat (grep index + ranged `run_command`
  reads) every time. A5, with the identical prompt digest and a purpose-only
  surface, had delegated 2/3 the day before; but the control arm below also
  fell from 3/3 (A6, P2) to 1/3 (P2-0) across the same two days, so the
  brief's delegation rate is volatile day to day and n=3 cannot separate a
  surface effect from that variance. The row's reading is the qualified one
  (h20): with the raw pair offered but undescribed in prose, cortex used
  neither — the preference question needs a matrix where the raw pair is
  also described, and a brief that delegates reliably.
- **Gap 2 — the size trigger (P3, row 61) does not promote.** Against the
  large brief's first clean control (P2-0, row 60: P2's truthful first
  paragraph alone, 1/3 delegating — only the GPU-contended run), P2-0 plus
  ONE explicit trigger sentence ("when the survey does not fit in one pass,
  hand parts of it to `code_survey` …") delegated **0/3**, cost turns
  (ratio 1.286) and reasoning (mean 123k chars vs 9.8k, one 310k-char
  truncated reasoning turn; 19.8k vs 9.8k without it). All three q3 clauses
  fail; `prompttext._PURPOSE_TOOLS` and the writer fragment are untouched
  and the overlay stays a staged instrument under
  `docs/live-testing/overlays/P3/`.
- **The seat the children ran on (row 60, deviations d2/d3).** Every
  `code_survey` child in rows 59–61 ran on cortex (`sub_results[].model` =
  the Qwen3.8 id): the lobes `associate` role (Nemotron 3.5 Lightning) is
  proxied to the Orin and advertised `ready:false`, and the associate seat
  was opt-in. The operator's intended topology is the associate on every
  non-writer seat **by default** — landed as plan task t19 (decisions
  c45/c46) — and a nemotron arm (row 62, `COLLEAGUE_ASSOCIATE_MODEL=lobes`,
  the P0 overlay whose seat description is true for that seat) was
  pre-registered and run behind the matrix; its cells are on that row.
- **Unplanned finding — the purpose child's step cap is not applied
  (#458).** Row 60 run 1's four `code_survey` children ran 23–29 steps
  against `PURPOSE_STEPS['code_survey']` = 12 and 240k–425k tokens each. The
  arms ran on that behaviour and say so; the fix is #458, not this arc.

What survives unchanged: claim c46 — every run in both arcs succeeded whether
or not it delegated (rows 59–61: 9/9 `ok`, one module changed each, public
interface stable), and the in-seat mechanism remains cheaper than four
~300k-token children, which is the rational choice the numbers keep showing.
The shipped default prompt still carries no encouragement to delegate.

## Provenance

- Spec: `docs/specs/2026-08-28-purpose-tools-associate-seat.md` (decisions
  q1–q11, parks v1–v7; every boundary claim cites the `file:lines` it was read
  from).
- Predecessor: `docs/features/web-scout.md` (the raw `web` tool this arc
  replaces on cortex; its honesty condition line 33 is superseded by this
  spec's q3, spec line 59).
- **No qwen-code port.** Nothing is ported; this is a new tool surface over
  the existing spawn path, so `NOTICE` and `docs/adopted-from.md` are
  **unchanged**.
- Follow-up spec: `docs/specs/2026-08-29-purpose-tools-get-chosen.md` with plan
  `docs/plans/2026-08-29-purpose-tools-get-chosen.md` — the measurement arc
  closed above. Deviations `d1`–`d3` (`devague deviate --list`); issues raised:
  #451, #452, #453, #454.

## The per-purpose child context budget (#458 re-scoped, 2026-08-30)

Issue #458 ("children ran 23–29 steps against a 12-step cap") was a
steps-vs-turns misread: `max_steps` bounds MODEL TURNS
(`loop._work_loop`), a turn's parallel read-only batch logs many `step N`
tool calls, and the `incomplete` children in rows 63/64 are the cap FIRING
(forced synthesis at the budget). The real cost lever is the child's
CONTEXT budget — a survey child inherits the parent's window and re-sends a
growing 60–120k history every turn (300–846k tokens per child in rows
63/64), against #461's doctrine that survey work belongs in a 16K–64K band.

The lever: `COLLEAGUE_<PURPOSE>_CONTEXT_BUDGET` (e.g.
`COLLEAGUE_CODE_SURVEY_CONTEXT_BUDGET=65536`) caps that ONE purpose child's
window via `efforttables.purpose_context_override` →
`ChildSpec.context_budget_tokens` (explicit beats derived; the associate
seat still takes `min(child, seat)`). Unset/invalid/`<= 0` = the child
inherits the parent's budget — byte-identical
(`tests/test_purpose_context_budget.py`). An opt-in EXPERIMENT instrument
by the `COLLEAGUE_ACTING_ADD_TOOLS` precedent: row 64b measures it against
row 64 (one changed lever, n=3) and it becomes a `PURPOSE_CONTEXT` table
default only if the arm promotes it.
