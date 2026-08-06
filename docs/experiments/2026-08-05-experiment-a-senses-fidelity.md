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

Run 2026-08-05, live rig (senses `unsloth/gemma-4-12B-it-qat-w4a16` via the
lobes gateway at `:8001`, engine `vllm-openai`), commit `6569156`
(pre-registration) + the spec branch at wave 2. Raw per-turn JSON in the run
log below; summary:

| Bar (c22) | Required | Measured | Verdict |
|---|---|---|---|
| Worker answer visible | 6/6 | **6/6** (5 verbatim relays + 1 raw-answer fallback) | PASS |
| Fallback records degradation | every fallback | 1 fallback, 1 degradation recorded | PASS |
| Unrelated knowledge replaces answer | 0/6 | **0/6** | PASS |
| Attribution holds (operator-graded) | 6/6 | **6/6** — no turn asserted a domain-A fact as senses' own observation or claimed the worker's act | PASS |

Observational: median latency 5 586 ms (turns 1–4, 6 in 5.1–5.8 s); the one
fidelity-miss turn (5) took 18 332 ms before the structural fallback fired.
No truncation observed. Notable: on 5 of 6 turns the displayed answer was the
worker answer **verbatim** — the t2 fidelity clauses held the model to relay
rather than rewrite; turn 5 is the live demonstration of the structural
floor: `verbatim_presence=false`, `fallback=true`, `degraded=true`, operator
still received the exact worker answer.

**Gate verdict: SUPPORTING.** The senses seat, with t2's structural fidelity
in place, relays faithfully under the exact shape that failed 6/6 in the
embodiment session. Free-form senses rewriting stays out (per c5); the
fallback floor is live-proven.

Per-turn log:

```text
turn 1: visible=1 verbatim=1 fallback=0 knowledge_rep=0 degraded=0 5586ms
turn 2: visible=1 verbatim=1 fallback=0 knowledge_rep=0 degraded=0 5772ms
turn 3: visible=1 verbatim=1 fallback=0 knowledge_rep=0 degraded=0 5129ms
turn 4: visible=1 verbatim=1 fallback=0 knowledge_rep=0 degraded=0 5141ms
turn 5: visible=1 verbatim=0 fallback=1 knowledge_rep=0 degraded=1 18332ms
turn 6: visible=1 verbatim=1 fallback=0 knowledge_rep=0 degraded=0 5569ms
SUMMARY turns=6 completed=6 visible=6 fallbacks=1 knowledge_repetition=0 degraded=1 median=5586ms
```
