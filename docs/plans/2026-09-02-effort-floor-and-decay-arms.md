# Build Plan — effort-floor-and-decay-arms

slug: `effort-floor-and-decay-arms` · status: `exported` · from frame: `effort-floor-and-decay-arms`

> colleague measures the effort floor question #484 left open: an OFF floor with and without the medium barrier (arms D0/D), and a built, opt-in effort DECAY after a spike (medium → low → off until the next spike point) on a low floor (E) and an off floor (F) — with the #487 trigger fix so a shell-first survey can still reach the barrier; each arm a ledger row, a miss written as a miss

## Tasks

### t1 — t1 #487 trigger fix in `loop_barrier.sh``ould_fire` (file-writing name set) + tests

- instruction: `FILE_WRITE_TOOLS` = ('`write_file`','`edit_file`') in `loop_barrier`; precondition = no prior step in that set; trigger = any call in that set; doc the rationale in the module docstring + effort-spikes.md
- covers: c2, h2
- acceptance:
  - shell-first survey then `write_file` fires the barrier; prior `edit_file` blocks; roles tuple byte-identical; existing barrier tests green

### t2 — t2 effort decay module + wiring + artifact record + boundary tests

- instruction: reuse SeatEscalator.push/pop; call site in loop.py right before `_complete_turn_or_retry` via a sanctioned-module function; resets hook where `_record`/barrier append SpikeRecord; keep loop.py free of effort assignments
- covers: c3, h3, c4, h4, c5, h5
- acceptance:
  - colleague/effortdecay.py: `DECAY_TABLE` {1: low, rest: off}, `decay_enabled`() (`COLLEAGUE_EFFORT_DECAY`=1 AND spikes armed), DecayState(reset(turn), `rung_for`(turn)); wiring: `loop_gateescalation`.`apply_decay`(ctx) pushes via SeatEscalator before each completion and every spike record call resets; TaskResult.`effort_decay` omit-when-empty round-trips; unarmed byte-identical; tests/`test_effortdecay_boundary.py` + thinking-effort boundary sanctioned list updated

### t3 — t3 docs: invariant amendment (8) in thinking-effort.md + CLAUDE.md, effort-spikes.md decay + trigger sections, CHANGELOG, version bump minor

- instruction: keep the decay doc honest: v0 = one table, offsets 1 and rest; reset vocabulary = the three spike points
- depends on: t1, t2
- covers: c6, h6, c11, h10
- acceptance:
  - both amendment texts present; markdownlint clean; version v1.76.0

### t4 — t4 arm D0 (off floor, spikes off, v1.75.1 harness) — running; verify + row 74

- instruction: already dispatched; `verify_branch.sh`; row 74 written from the artifact
- covers: c7, h7
- acceptance:
  - artifact effort {main: off}, `non_thinking` sampling row, `task_text` sha equal; branch verified; row 74

### t5 — t5 arms D, E, F on the build tip (HARNESS worktree), sequential; verify; rows 75-77

- instruction: `run_arm.sh` D/E/F with HARNESS at the build tip; `COLLEAGUE_EFFORT_DECAY`=1 for E/F; gate/fillline pinned low
- depends on: t3, t4
- covers: c7, h7, c1, h1, c12, h11
- acceptance:
  - D: off floor + barrier medium fires (trigger fixed); E: low floor + decay, record shows resets>=1 and low/off counts; F: off floor + decay; each verified in a fresh worktree; rows 75-77 with fire step + decay record quoted

### t6 — t6 disposition + PR: post on #484 (or successor) applying the pre-stated win condition; PR via cicd; delivery ledger + summary

- instruction: sign - colleague (Claude); a miss is a miss
- depends on: t5
- covers: c9, h8, c10, h9, c11, c12
- acceptance:
  - comment names whether the off floor held and whether spike/decay recovered it below A's 150k; PR open, CI green; deliveries doc committed
