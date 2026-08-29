# Arm brief — decomposable survey, tool-neutral (successor to row49-purpose.md)

Pre-registered for the `purpose-tools-get-chosen` arm matrix (plan t10, spec
`docs/specs/2026-08-29-purpose-tools-get-chosen.md`, covers c6/h12). The row
number is assigned by plan t14, which pre-registers the arm rows; each row
cites this file by path, in the rows 47-50 shape.

This brief REPLACES `docs/live-testing/briefs/row49-purpose.md` for every arm
of this arc. Row 49's text told the model to hand one or more of the
read-only surveys to scout children, naming in a parenthetical the two RAW
delegation tools (the sub-agent pair) — while the arm's acting surface
offered NEITHER of them. The brief advertised the same absent tools the stale
prompt section does (spec c6). The task shape is unchanged (survey three
modules, then change one) so the comparison against row 48 / row 49 stays
readable; only the tool-naming sentence is re-authored.

The two raw tool names are deliberately not written anywhere in this file,
not even in this rationale, so plan t10's acceptance grep over the whole file
comes back empty.

## Naming choice: the brief names NO tool at all

The re-authored brief names no tool — neither of the two raw delegation
tools row 49 named, nor `code_survey`. Three reasons, recorded here so a
later reader does not mistake it for an oversight:

1. **The same brief runs across arms with DIFFERENT surfaces.** The matrix is
   P0/P1/P2 prose x surface x both x restore (spec, arm design). The restore
   arm (plan t11) puts the two raw delegation tools back on the acting seat;
   the purpose arms do not offer them. A brief naming `code_survey` would be
   a steer the restore arm cannot act on; a brief naming a raw delegation
   tool would be a steer the purpose arms cannot act on. Only a tool-free
   brief is VALID across every arm, and cross-arm validity is the whole
   point of holding the brief constant.
2. **Naming a tool in the brief would swamp the lever under test.** The
   manipulated variable in this arc is the prompt prose (the P0/P1/P2
   overlays) and the acting-seat surface. A tool name in the task text is
   itself prose encouragement — the strongest kind, because it is the
   operator's own words rather than the system prompt's. It would plausibly
   push delegation to a ceiling in every arm and make the overlay difference
   unmeasurable.
3. **Delegation is observed, never forced (#435).** A tool-free brief
   measures what the model CHOOSES given the prompt and the surface it holds,
   which is exactly the quantity this arc is trying to move.

The brief still tells the model that delegating a read-only survey is an
option and that the choice is its own — that sentence survives from rows 48
and 49 with the parenthetical tool names deleted, so the invitation is held
constant and only the tool advertisement is removed.

## Pass bar (committed BEFORE the run)

- delegation calls >= 1 on >= 2 of 3 runs, where a delegation call is a step
  naming any tool that spawns a child on the arm's own surface (a purpose
  tool on the purpose arms; the raw delegation pair on the restore arm) —
  read off the artifact steps, never from prose
- markup count per run recorded beside it (the #360 dropped-call counter,
  plan t6): a zero-delegation run with markup > 0 is INCONCLUSIVE, not a
  refusal to delegate
- task success recorded beside the delegation rate (spec c46): status,
  whether exactly one module changed, and whether its public interface stayed
  stable — the arc's conclusion is allowed to be "cortex was right not to
  delegate"
- turns <= 1.0x and wall <= 1.2x vs the baseline arm at the same tip, n=3
  (computed by `scripts/compare_arms.py --bar-wall 1.2 --bar-turns 1.0` from
  artifact stats, never from prose)
- reasoning chars recorded per run (row 48 measured 2x reasoning chars for
  added surface that bought zero delegations)
- a miss is written as a miss

## The brief (paste into `colleague work`)

```text
Survey three modules, then change one.

1. Survey the three modules `alpha`, `beta` and `gamma` in this repo —
   their public interfaces, how they call each other, and where the
   duplication lives. If the survey is large, you may hand one or more of
   the read-only surveys to a helper and review its digest before acting —
   or do all of it yourself; the choice is yours.

2. Then change exactly one of the three modules to remove the duplication
   you found, keeping its public interface stable. Make the smallest edit
   that does it and say which module you changed and why.
```

## After the run — record (never fill before)

Per-run delegation count and which tool was called, markup count, task
success (status / module changed / interface stable), the child's served
model where a child ran, turns, wall-clock and reasoning chars; the
delegation-rate column from `scripts/compare_arms.py` output; the arm's
prompt digest read off the artifact (a digest that does not match the arm the
row claims voids that run); the memory distill counters
(attempts/validated/detached) and the distill child's served model.
