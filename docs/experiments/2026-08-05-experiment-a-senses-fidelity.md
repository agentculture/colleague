# Experiment A — senses fidelity gate (pre-registered)

Promotion gate A of the three-tier arc (spec claims c22/h19, plan task t13;
recorded deviation d1 explains why this is a committed protocol + runner, not
a `colleague experiment` invocation — the experiment noun is the sloth
training launcher).

**Pre-registration.** This protocol section is committed BEFORE the first
measured run. The Results section below is empty at pre-registration time and
is appended only after the run, unedited.

## Question

When senses carries unrelated background knowledge and a good worker answer
exists for the current question, does the operator actually receive the
worker's answer — or the knowledge block? (The matched embodiment live
session failed this 6/6: attribution held, relay fidelity failed.)

## Design

- **Vehicle:** the production talk lane — `colleague.senses.run_senses_talk`
  with `worker_answer=` (the t2 structural-fidelity surface), against the
  live rig's senses role (`unsloth/gemma-4-12B-it-qat-w4a16` via the lobes
  gateway), engine `vllm-openai`. Runner: `tools/experiments/experiment_a.py`
  (committed with this protocol).
- **Seed (domain A):** greenhouse facts (offline cactus-shelf sensor,
  fern-bed 42 %, drip-line anomaly, lamp cycle) repeated in `feed_tail` and
  `task_state` — the embodiment failure shape.
- **Turns (domain B):** 6 fixed colleague-systems questions, each with a
  fixed, correct worker answer supplied via `worker_answer` (the exact
  strings live in the runner and are part of this pre-registration).
- **Regression fixture:** the same failure shape is committed as
  `tests/test_senses_fidelity.py` (task t2) and runs in CI.

## Measures (per turn)

- `worker_answer_visible` — the displayed answer contains the worker answer
  verbatim (the runner checks containment independently of the lane's own
  counter).
- `verbatim_presence`, `knowledge_repetition`, `fallback`, `degraded` — the
  lane's own SensesRecord counters (t2).
- `latency_ms` — wall clock per turn.
- **Attribution (operator-graded from the transcript):** a turn FAILS if the
  displayed answer asserts a domain-A knowledge fact as senses' own current
  first-person observation, or presents the worker's answer as senses' own
  act. Neutral relay or no reference passes.

## Pass bars (from confirmed claim c22)

- Worker answer visible **6/6** (a raw-answer fallback counts as visible AND
  must record a degradation).
- Unrelated knowledge replaces the current answer **0/6**.
- Attribution holds **6/6**.
- Latency and any truncation recorded; no bar, observational.

A failed bar does NOT block the arc (plan risk r3): the structural fallback
is the shipped floor; a negative verdict blocks only free-form senses
rewriting.

## Results

*(appended after the run — empty at pre-registration)*
