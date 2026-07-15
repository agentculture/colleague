# continue-working — colleague finishes what it starts

> A run that stalls (a no-tool-call turn the loop treats as an implicit stop) now
> resumes **past the first stall** instead of stopping after one nudge, and a
> context-rich stop returns a clean summary of the work that was actually done
> rather than a stale trailing line.

Two run-completion features (#142 extended) born from a live dogfood stall: a
served 27B narrated `"Let me check:"` with no tool call after editing 1 of 4
files, and the loop treated the no-tool-call turn as an implicit stop.

## continue-working — a configurable nudge cap

The single finish-nudge (`_handle_no_tool_turn` / `_FINISH_NUDGE`) became a
**configurable cap**: `COLLEAGUE_MAX_CONTINUE_NUDGES`
(`EngineConfig.max_continue_nudges`, default 2, lifting the old hardcoded
`_MAX_FINISH_NUDGES = 1`), threaded `config → ContextControls → _Work`. A stalled
run resumes past the first stall.

- Termination stays bounded by the cap **plus** the existing step/token budget.
- An explicit `finish` still ends immediately (no nudge).
- The direct `run()` path falls back to `_MAX_FINISH_NUDGES` (back-compat).

## auto-compact-on-finish — a clean summary survives to the exit

A context-rich stop no longer pre-empts the #191 forced synthesis.
`_handle_no_tool_turn` leaves the summary empty so
[forced synthesis](explore-never-wastes.md) produces a clean summary from what was
read. Summary resolution lives in one helper
(`colleague/loop.py` `_resolve_terminal_summary`) with explicit precedence:

```text
finish summary  →  fresh forced synthesis (#191)  →  compaction self-summary fallback
                →  last-substantive  →  NO_RESULT_PRODUCED
```

Synthesis runs **before** the compaction fallback, so a run that compacted and
then *kept working* returns a summary reflecting the post-compaction work — never
the stale pre-work compaction note (the Qodo PR #198 stale-summary fix).

## Honest scope

The "free context to continue" half is already delivered by existing windowing +
the [fill-line](capacity-standard.md); this adds **no new compaction-firing
code**, only makes the clean summary survive to the exit. A *short* run (one that
never crossed the fill line) that stalls still falls back to its trailing prose
when forced synthesis yields nothing — a documented follow-up.

## Beyond one episode

The nudge cap keeps a run finishing **within** its episode; a run that
exhausts its step budget anyway can now finish **across** episodes: an armed
`--until-done` run chains a budget-exhausted exit into a new episode carrying
the prior episode's actual tree, handing off once at chain end — with honest
limits (best-effort WIP sweep, per-episode gate cost, crawl risk under
`--max-episodes 0`). Doc: [indefinite-run.md](indefinite-run.md).

## Key files

- `colleague/loop.py` — `_handle_no_tool_turn`, `_resolve_terminal_summary`.

## Spec + plan

- [`docs/specs/2026-06-15-colleague-finishes-what-it-starts-a-run-that-stall.md`](../specs/2026-06-15-colleague-finishes-what-it-starts-a-run-that-stall.md)
- [`docs/plans/2026-06-15-colleague-finishes-what-it-starts-a-run-that-stall.md`](../plans/2026-06-15-colleague-finishes-what-it-starts-a-run-that-stall.md)
