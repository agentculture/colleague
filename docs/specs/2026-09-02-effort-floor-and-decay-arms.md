# effort-floor-and-decay-arms

> colleague measures the effort floor question #484 left open: an OFF floor with and without the medium barrier (arms D0/D), and a built, opt-in effort DECAY after a spike (medium → low → off until the next spike point) on a low floor (E) and an off floor (F) — with the #487 trigger fix so a shell-first survey can still reach the barrier; each arm a ledger row, a miss written as a miss
> instruction: order: build (#487 fix + decay + tests + docs) on branch feat/effort-decay-487 → suite green → dispatch D (needs the fix) → E → F sequentially on a harness worktree at the build tip; D0 already running on v1.75.1; rows 74-77; disposition

## Audience

- the operator deciding whether an off floor is viable and whether decay earns a default, and the next session reading rows 74-77

## Before → After

- Before: the ladder has one measured floor (low); off has never been run on this brief; decay exists only as a comment on #484; the barrier cannot fire on a shell-first survey (#487)
- After: rows 74-77 in the ledger; #487 fixed; effort decay built dark behind `COLLEAGUE_EFFORT_DECAY`; the invariant amended once more as a recorded convention change; a disposition on #484 (or a successor issue) says whether the off floor holds and whether a spike/decay recovers it

## Requirements

- \#487 fix, name-only: `loop_barrier.sh``ould_fire`'s precondition becomes 'no prior step named `write_file` or `edit_file`' and its trigger 'this turn requests `write_file` or `edit_file`' (a `FILE_WRITE_TOOLS` name set) — `run_command` stays mutating for roles and policy; the barrier just stops latching on a shell-first survey
  - instruction: edit `should_fire` only; add tests: shell-first survey then `write_file` fires; a prior `edit_file` blocks; the roles tuple is untouched
  - honesty: a unit test drives a shell-first survey (`run_command`, `read_file`) then a `write_file` turn and asserts the barrier fires; a second asserts a prior `edit_file` step blocks it; roles.`_WRITE_TOOLS` and `is_read_only_tool` are byte-identical to 5b163084
- Effort decay, opt-in (`COLLEAGUE_EFFORT_DECAY`=1, requires `COLLEAGUE_EFFORT_SPIKES`=1): after ANY spike point fires (a reset), the acting seat's rung for the following turns comes from a FIXED table keyed by OFFSET since the reset — `DECAY_TABLE` = {1: low, rest: off} — set through the already-sanctioned SeatEscalator push on the live config before each completion, never from turn content; a further reset restarts the offset; unarmed = byte-identical
  - instruction: new colleague/effortdecay.py (table + opt-in + DecayState); wiring in `loop_gateescalation.py` (already in the effort-assign sanctioned set) called from loop.py before `_complete_turn_or_retry`; the AST guard's sanctioned list gains effortdecay.py only if it assigns
  - honesty: with `COLLEAGUE_EFFORT_DECAY` unset, tests/`test_offknob_byte_identity.py`-style comparison shows identical payloads and no attribute writes; armed, a mock-driven test shows turn offsets 1→low, 2+→off after a spike and a restart after a second reset
- Artifact record TaskResult.`effort_decay` (omit-when-empty): {resets: \[turn indices\], turns: {low: n, off: n}} so a row can state how many acting turns ran at each decayed rung
  - instruction: contract.py field + `contract_taskresult_io` round-trip, same omit-when-empty pattern as `effort_spikes`
  - honesty: TaskResult.`to_dict` omits `effort_decay` when empty; `from_dict` round-trips it; an unarmed artifact is byte-identical to v1.75.1
- Arms on the row-69 brief (`task_text` 815f5c3f…1ac9), `MAX_STEPS` 90, TIMEOUT 600, gate/fillline pinned low, each verified on the result branch: D0 = off floor, spikes off (control, running now on v1.75.1) · D = off floor + barrier medium · E = low floor + decay · F = off floor + decay; D/E/F on the fixed trigger; primary = correctness, secondary = spend; readings pre-stated: an off floor that loses correctness and a spike/decay arm that recovers it at lower spend than low-floor A (150k chars) is the win condition; equal correctness at higher spend is a miss
  - instruction: `run_arm.sh` gains D/E/F (HARNESS = a worktree at the build branch tip); rows 74-77
  - honesty: rows 74-77 each quote import/pins/suite output from a fresh worktree of the result branch and the four spend figures; the barrier fire step is recorded for D/E/F; the decay record (resets, low/off counts) is quoted for E/F

## Honesty conditions

- every arm artifact records the expected effort {main: off|low}, sampling half matching the rung (`non_thinking` row at off), `task_text` sha 815f5c3f…1ac9, `max_steps` 90; read off the artifact
- tests/`test_thinking_effort_boundary.py` passes with the decay module named in its sanctioned set; a new tests/`test_effortdecay_boundary.py` pins `DECAY_TABLE`, the reset vocabulary == `SPIKE_POINTS`, and that no function accepts an effort/rung keyword
- git diff shows the amended sentence in docs/features/thinking-effort.md line ~11 AND a convention change (8) bullet in CLAUDE.md's v0→v1 list, in the same PR as the code
- rows 74-77 + the disposition let a reader reproduce each arm's env without this session
- before dispatch, no ledger row below 74 carries an off-floor arm and grep `effort_decay` across colleague/ is empty at 5b163084
- colleague/effortdecay.py exists behind `COLLEAGUE_EFFORT_DECAY` (default off); `should_fire` no longer references `is_mutating_tool` for the precondition; the disposition comment exists
- counted from the rows: 4 verdicts, 16 spend figures, 0 trigger voids in D/E/F, decay resets >= 1 in E and F; `test_offknob_byte_identity` passes

## Success signals

- 4 arm rows each with a correctness verdict and 4 spend figures; 0 arms VOID on the trigger after the fix (the fix's own test); the decay artifact record shows >= 1 reset and the expected low/off turn counts in E and F; unarmed byte-identity test passes

## Scope / boundaries

- Nothing inspects turn content or a model value to choose a rung: the decay is keyed by offset-since-reset from a fixed table, the reset triggers are exactly the three enumerated spike points, and no tool parameter reaches it; the excluded router stays excluded
  - instruction: tests/`test_thinking_effort_boundary.py` sanctioned set edited explicitly; a decay boundary test pins the table and the reset vocabulary
- Convention change (8), RECORDED not silent: the thinking-effort invariant reads 'never per turn FROM CONTENT — per enumerated point, or per fixed OFFSET from such a point, from a fixed table'; CLAUDE.md's v0→v1 list and thinking-effort.md line 11 carry it
  - instruction: edit both texts in the same PR as the code

## Assumptions

- D0 runs on v1.75.1 (harness-v1751 worktree) because it needs neither the fix nor the decay; D/E/F run on the build branch — the only harness difference D0 lacks is the #487 precondition, which cannot fire in a spikes-off run, so D0 stays a valid control

## Scope exploration

- `s1` — `colleague/engines/vllm_payload.py:_effort_for + loop_gateescalation.SeatEscalator`: the rung a completion carries is read from the live config's `reasoning_effort_seat` attribute at payload time; SeatEscalator already pushes/pops it on the live config from a sanctioned module — the decay reuses this exact seam
  - seeds: `c3`
- `s2` — `colleague/loop.py:_advance_turn + the _complete_turn_or_retry call site`: the barrier intercepts inside `_advance_turn`; the per-turn completion is built at one call site before `_account_turn` — the decay hook goes immediately before that call, as a CALL into the sanctioned module (loop.py itself may not assign effort)
  - seeds: `c3`
- `s3` — `tests/test_thinking_effort_boundary.py:146-215`: AST guard: effort attributes may be ASSIGNED only in a closed sanctioned set; loop.py/`senses_loop.py` are hard-forbidden; adding a writer means editing the test explicitly — the decay must land in a sanctioned module and the test's list must name it
  - seeds: `c5`, `c6`
- `s4` — `colleague/loop_barrier.should_fire + colleague/roles.py:78`: precondition uses `is_mutating_tool` over ALL prior steps (`run_command` included) — the #487 latch; the fix narrows both precondition and trigger to a file-writing name set
  - seeds: `c2`
- `s5` — `docs/features/thinking-effort.md:11 + CLAUDE.md convention change (7)`: the invariant was amended once for #484 (per enumerated point); decay keyed by offset needs a second recorded amendment, never a silent one
  - seeds: `c6`
