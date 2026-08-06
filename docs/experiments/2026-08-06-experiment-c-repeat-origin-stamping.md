# Experiment C repeat — origin-stamping fix (post-#366 wiring)

**Date:** 2026-08-06 · **Runner:** `tools/experiments/experiment_c.py`
(unchanged — the pre-registered protocol of
[`2026-08-06-experiment-c-strategist-value.md`](2026-08-06-experiment-c-strategist-value.md),
re-run verbatim) · **Tree:** `spec/change-content-consumption-lane` with the issue-366
content-lane waves 1–4 merged (notably t6: the configurator auto-stamps
entry-level `origin` on cortex knowledge entries).

## Question

The original run's SUPPORTING verdict carried one structural nuance: every
substantively-correct corrective proposal was **refused** by lattice
validation for a missing entry-level `origin` field. Does the t6
origin-stamping fix turn detection into end-to-end verified proposals, and
does the control arm stay intervention-free?

## Result: **VERIFIED — the refusal nuance is closed**

| arm | trials | detections | interventions | verified | refusals | degraded | median latency |
|---|---|---|---|---|---|---|---|
| mismatch | 4 | **4/4** | 4/4 | **4/4** | **0** | 0 | 65.5 s |
| control | 4 | 0 | **0/4** | 0 | 0 | 0 | 11.2 s |

Every mismatch trial proposed exactly one corrective `worker.knowledge`
change and every proposal **verified and queued** (baseline run: 4/4 refused
on the missing entry origin). The control arm remains 0/4 false
interventions, 0 refusals, 0 degradations.

## Scope

Same as the original protocol (deviation d2 there): this measures the
**review surface** (`review_and_queue` → lattice verification → queue). The
consumption of applied content into the next episode's surface is the #366
arc's own lane, proven separately by `tests/test_work_config_plane.py`,
`tests/test_engine_strategist_seam.py`, and `tests/test_tool_narrowing.py`;
the value-in-anger verdict belongs to the NEBULA RUN benchmark arm (#366).
The strategist remains **opt-in and OFF by default**.

Cortex dial: resolved live from the lobes gateway (`unsloth/Qwen3.6-27B-NVFP4`
via role discovery); engine `vllm-openai`; 8/8 trials non-degraded.
