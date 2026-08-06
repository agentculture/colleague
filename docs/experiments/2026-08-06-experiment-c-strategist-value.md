# Experiment C — strategist value gate (pre-registered)

Promotion gate C of the three-tier arc (spec claims c10/h10, plan task t15;
deviation d1 explains the committed-runner vehicle). This is the experiment
that issue #363 §5 says never existed in either repo: give the strategist a
genuinely **misconfigured actor**, asking whether the tier notices — three prior
independent measurements were negative precisely because nothing needed
fixing.

**Pre-registration.** Protocol + runner committed BEFORE the first measured
run; the Results section is appended after, unedited.

**Honest scope limit (deviation d2 / issue #366).** The change-content
consumption lane was not wired when this gate ran, so this gate measures
**detection, false-intervention, and cost** — NOT downstream task-outcome
improvement. The lane is now wired (t8–t12), so #364's fuller design
(repo-A/repo-B live tasks with outcome deltas) is possible.

## Design

- **Vehicle:** the real configurator surface —
  `colleague.configurator.review_and_queue` with a real
  `EpisodeConfigLifecycle`, `ConfigEventStream`, and `CapabilityCatalog`,
  against the LIVE cortex dial (`unsloth/Qwen3.6-27B-NVFP4` via the lobes
  gateway). Runner: `tools/experiments/experiment_c.py`.
- **Arms (4 trials each):**
  - `mismatch` — baseline knowledge carries Java/Gradle/checkstyle
    conventions; the episode facts describe a Python/uv/pytest task and note
    the worker's tooling friction (`./gradlew` not found, no `src/main/java`);
  - `control` — knowledge matches the episode facts, no friction.
- **Counted per trial:** proposals (by target), refusals, whether a proposal
  is a *valid corrective* (targets `worker.knowledge` / `senses.knowledge` /
  `worker.prompt.strategist`), latency, tokens.

## Pass bars

- **SUPPORTING** requires: corrective detection in **≥ 3/4** mismatch trials
  AND interventions on **≤ 1/4** control trials (correct non-intervention).
- Anything else is **NOT SUPPORTING**: the strategist stays opt-in and OFF —
  the pre-declared acceptable outcome (plan risk r4); the arc ships the
  worker and senses tiers regardless.

## Results

Run 2026-08-06, live rig (cortex `unsloth/Qwen3.6-27B-NVFP4` via the lobes
gateway), 4 trials per arm, serial. One runner serialization fix
(`ConfiguratorReviewResult` list fields → counts) was applied before the
first completed measurement; no protocol change.

| Bar | Required | Measured | Verdict |
|---|---|---|---|
| Corrective detection (mismatch arm) | ≥ 3/4 | **4/4** — every trial proposed exactly one unit targeting `worker.knowledge` | PASS |
| False intervention (control arm) | ≤ 1/4 | **0/4** — zero proposals on the matched control | PASS |

Observational: median latency 24.7 s (mismatch) vs 18.5 s (control); no
degradations; no truncation.

**Gate verdict: SUPPORTING** — the first positive strategist evidence under
a pre-registered design (the prior three negatives gave the strategist
nothing to fix; this one did, and it noticed 4/4 while staying silent 4/4 on
the control).

**Honest nuance, recorded:** every mismatch proposal was then **refused** by
lattice validation (`verified=0`): a diagnostic probe captured the exact
reason — the model-authored knowledge entry omitted its `origin` field
(`refused: knowledge entries at indices ['0'] missing or empty 'origin'`),
while the corrective CONTENT was substantively right ("This is a Python
package using uv … Do NOT use Gradle commands or look for src/main/java").
Refuse-whole worked as designed; the obvious v1.1 improvement — the
configurator auto-stamping entry-level origins (they are host-known, the
model's claim adds nothing) — landed in the #366 follow-up
(`tests/test_configurator.py::test_entry_lacking_origin_validates_post_stamp`,
`tests/test_configurator.py::test_entry_level_model_supplied_origin_is_discarded_and_restamped`).
Consistent with the pre-registration, the strategist REMAINS opt-in and off
by default: the off-default test stays until a verdict on a build with the
origin-stamping fix repeats this result end-to-end (proposed → verified →
applied). That repeat verdict lands with its own experiment record, not as a
post-hoc amendment to this one.
