# g8 ON-arm cycle record (final ON task)

- work: SINGLE leg — c21ce9e98352, ok, 33 steps, PR #8; recall 5 records /
  3531 chars
- PR: <https://github.com/OriNachum/transformer-arm-on/pull/8> → squash 9990665
- verification (subagent, 50 evidence files): ALL FIVE criteria PASS — win
  screen by exit-AABB (extract screen:'won'), lose + R-restart both proven by
  extract, TIMED playthrough boot→won in 35.9s (route: plate→d1, guard
  outrun/killed, lever→d2, stair-step mounts to y=4, exit), beauty pass
  present (fog/3 lights/emissive accents; honest note: scene reads dark),
  README agent-access schema an EXACT bijection with the live extract (27 key
  paths, zero undocumented), zero errors across 3 playthroughs
- corrections: NONE (0 lines)
- grade: 5; capture fired, 0 hunks (the honest zero)
- anomalies: inter-dispatch idle is lethal near the guard (CLI playthroughs
  must cross x 12-21.5 in one dispatch); platform-stand oscillation makes
  hops luck-dependent; README binding names are internal ids not
  KeyboardEvent.key values (pre-dates g8); the worker's own verification
  claim was syntax-only (NEBULA pattern — the invariant held but was unproven
  at delivery)

## ON ARM COMPLETE — totals

| task | corr. lines | grade | capture |
|------|------------|-------|---------|
| g1 | 0 | 5 | fired(0) |
| g2 | 0 | 5 | fired(0) |
| g3 | 10 | 3 | fired(1 hunk, 1 lesson) |
| g4 | 17 | 3 | fired(1 hunk, 1 lesson) |
| g5 | 1 | 3 | fired(1 hunk, 1 lesson) |
| g6 | 2 | 3 | fired(1 hunk, 1 lesson) |
| g7 | 27 | 3 | fired(4 hunks, 4 lessons) |
| g8 | 0 | 5 | fired(0) |
| **Σ** | **57** | mean 3.75 | 8 lessons stored |

Worker: unsloth/Qwen3.6-35B-A3B-NVFP4 on every leg (verbatim from WorkStats).
All 8 tasks landed via real PRs, squash-merged, immediately graded; every
capture sidecar fired. Store at arm end: 8 code-lessons + work-lessons.
Transfer observations inline in the per-task records (g5/g6: both input
lessons applied unprompted; input-correction class did not recur after
storing).
