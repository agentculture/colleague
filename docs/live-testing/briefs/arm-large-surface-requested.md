# Arm brief — large surface, delegation EXPLICITLY REQUESTED (arm R)

Pre-registered 2026-08-30 for the `delegation-follow-ups-a7-p3-hire` arc
(deviation d4, rows 63-64 of `docs/live-testing.md`). Everything about the
fixture, the rig and the cells is `arm-large-surface.md`'s; the ONLY change
is item 2 of the brief, which no longer leaves delegation to cortex's
judgement — the operator's task text asks for it. This is not a router: the
runtime decides nothing; the brief is what an operator would write when they
want the survey delegated.

## Why this arm exists

Every arm on the large brief (rows 57-62) left delegation to cortex, and the
pooled result is that cortex delegates rarely (6/15 runs) and the delegating
runs were SLOWER (median 707 s vs 392 s in-seat) — with the parent re-reading
the duplicate-pair modules in full after the digests in 5 of 6 delegating
runs. Whether delegation can speed a result up cannot be measured while the
choice variable is in the way. Arm R removes it: with delegation requested,
the run measures (a) compliance, (b) the child's cost per call, (c) whether
the parent re-validates (ranged reads of the cited lines) or re-does the work
(full-module reads), and (d) wall time against the pooled in-seat median.

Two conditions, n=3 each, interleaved, no overlay on either (the default
writer fragment says nothing about the scout seat, so it is truthful for
both; `prompt_digest` is the no-overlay `b7491476…` for every run):

- **R-cortex** (row 63): the associate seat unarmed — children on cortex.
- **R-nemotron** (row 64): `COLLEAGUE_ASSOCIATE_MODEL=lobes` — children on the
  Orin-proxied Nemotron 3.5 Lightning associate (row 62's precondition).

## Pass bar (committed BEFORE the run)

- compliance: >= 4 `code_survey` calls before the first `read_file` of a
  module body, on >= 2 of 3 runs per condition — a non-compliant run is
  REPORTED (it is a finding about instruction-following), not voided
- child wall per call: from the parent's step timestamps; per-child
  `usage` tokens and served model from `sub_results[]`
- post-digest reads: count of `read_file` / ranged `run_command` reads after
  the last child, and whether each targets a cited line range (verify) or a
  whole module (redo); the verdict names which
- **delegation speeds up results** iff, for R-nemotron, mean wall < the
  pooled non-delegating median of rows 57-61 (392 s) AND post-digest reads
  are ranged, not full; task success recorded beside it; a miss is a miss
- the standard six cells, ratios vs row 60 (P2-0) descriptively with
  `--bar-wall 1.2 --bar-turns 1.0`

## The brief (paste into `colleague work`)

```text
Survey twelve modules, then remove one duplication.

1. Survey every module under `src/` in this repo — there are twelve, `mod_a`
   through `mod_l`, and each is around 1,500 lines. For each module report
   its public functions and what they do, and say which other modules it
   calls. Then name the pairs of modules that implement the SAME algorithm
   under different function names — the names and local variables differ, so
   matching identifiers alone will not find them.

2. Hand the survey to helpers: call `code_survey` for each group of three
   modules (four calls: a-c, d-f, g-i, j-l), each returning the public
   functions, what they do, which modules they call, and any duplicate-
   algorithm candidates with file paths and line ranges. Do not read module
   bodies yourself before the digests return; after they return, verify only
   the lines the digests cite, then do the edit yourself.

3. Then change exactly ONE module to remove ONE of the duplications you
   found, keeping its public interface stable. Make the smallest edit that
   does it, say which module you changed, which duplicate pair it belonged
   to, and why you picked that one.
```
