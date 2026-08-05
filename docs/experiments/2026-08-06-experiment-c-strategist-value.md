# Experiment C — strategist value gate (pre-registered)

Promotion gate C of the three-tier arc (spec claims c10/h10, plan task t15;
deviation d1 explains the committed-runner vehicle). This is the experiment
#363 §5 says never existed in either repo: give the strategist a genuinely
**misconfigured actor** and ask whether the tier notices — three prior
independent measurements were negative precisely because nothing needed
fixing.

**Pre-registration.** Protocol + runner committed BEFORE the first measured
run; the Results section is appended after, unedited.

**Honest scope limit (deviation d2 / issue #366).** The change-content
consumption lane is not wired in v1, so this gate measures **detection,
false-intervention, and cost** — NOT downstream task-outcome improvement,
which is deferred to the #366 follow-up. #364's fuller design (repo-A/repo-B
live tasks with outcome deltas) becomes possible only after #366.

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

*(appended after the run — empty at pre-registration)*
