# Hire colleague — a run-scoped employee with an agreed purpose

**Audiences:** the operator deciding whether to arm `COLLEAGUE_HIRE`, and the
next agent touching `colleague/hire*.py`.

## What

Two tools on the depth-0 acting seat, offered ONLY when the operator arms
`COLLEAGUE_HIRE` (env > config.json `hire` > OFF): `hire_colleague`
(purpose, when, base_role, prompt — a bounded TWO-round negotiation with a
tools-off candidate voice on the same cortex seat: accept | amend | decline;
at most 2 completions by construction) and `assign_to_colleague`
(agent_id, task, acceptance — ONE child spawned per assignment on the hired
role). A hire is run-scoped state (`colleague/hire.py`: the ten-field `Hire`,
a `Roster` capped at `MAX_SUBAGENT_FANOUT` = 4), dies at every continuation
cut (D43 — never rehydrated as live), and lands on the artifact as
`TaskResult.hires` (omit-when-empty, the authored prompt TEXT included)
plus — under `COLLEAGUE_AGENTS=1` — ONE task-ledger event carrying digests
and an artifact ref, never the prompt payload.

## Before / after

Before: repeating a sub-task shape meant restating a full `code_survey`/
`subagent` brief every call. After (armed): cortex agrees a purpose ONCE with
a negotiated employee and then assigns work by id; the standing prompt rides
each assignment's brief. Unarmed: byte-identical — the two schemas are
hidden, the system prompt is one sentence shorter (the exact delta
`tests/test_hire_schemas.py` pins), no roster exists.

## Why it is not a router

Presentation + explicit calls, never dispatch: the MODEL calls the tools; the
runtime never picks a hire, a model, or a moment. The hired role is a FIXED
builtin base whose allow-list the authored prompt can NEVER widen
(`hired_role` replaces only `prompt_fragment`; a parametrised test proves the
effective surface = base − purpose tools − child-forbidden − the hire pair).
Children, agents-mode profiles and the read-only batch pool never hold the
pair (`tests/test_hire_confinement.py`). The twelfth sanctioned increment —
the deepthink precedent applied to a persistent purpose, like the six purpose
tools before it.

## Shipped surface

| piece | where |
|---|---|
| `Hire` / `Roster` / `mint_hire` / `hired_role` | `colleague/hire.py` |
| schemas + `COLLEAGUE_HIRE` hidden rule + splice | `colleague/hire_schemas.py`, `colleague/tools.py` |
| negotiation handler (tools-off seam, ≤ 2 completions) | `colleague/hire_dispatch.py` |
| assign handler + `TaskResult.hires` | `colleague/hire_assign.py`, `colleague/contract.py` |
| confinement (children / agents sets / batch pool) | `colleague/actingsurface.py`, `colleague/agents/tools.py` |
| ledger event (refs, not payloads) + dead-at-the-cut | `colleague/agents/state/ledger.py`, `colleague/hire_dispatch.py`, `colleague/continuation.py` |
| arm instruments | `scripts/make_repeated_subtasks_fixture.py`, `docs/live-testing/briefs/arm-repeated-subtasks.md`, `scripts/compare_arms.py` (hires/assignments columns) |

## Knobs

| knob | default | meaning |
|---|---|---|
| `COLLEAGUE_HIRE` / config.json `hire` (bare bool or `{"enabled": …}`) | OFF | offer the two tools + the one prompt sentence; unset = byte-identical |

## Measurement (row 65 — recorded 2026-08-31)

Arm H (`COLLEAGUE_HIRE=1`) vs control, n=3 each, interleaved, on the
repeated-sub-tasks brief (eight identical-shape package audits):

- **hires 0/3, assignments 0/3** — cortex never called the lane; no
  negotiation ever started (accept/amend/decline: n/a). Pre-declared
  publishable; recorded as the finding.
- Task success 6/6 `ok`, **8/8 contradictions vs the answer key in every
  run**, one docstring fixed each; the armed surface cost nothing
  measurable (wall_ratio 1.117, turns_ratio 0.939 — both bars pass).
- Validity: the armed/unarmed prompt-digest pair (`b348c6ff…`/`b7491476…`)
  reproduced exactly through the composition path; controls never saw the
  tool names.

The decision this supports: `COLLEAGUE_HIRE` stays **default-OFF**. The
amortisation hypothesis is untested above the in-seat capacity ceiling —
the brief fits in one seat (~49.6k tokens), and rows 51–58 already showed
a brief cortex can hold produces zero delegation of ANY form; a
larger-than-seat repeated-shape brief is the parked follow-up.

## Honest limits (measurement)

- **Self-negotiation theatre is unobserved, not refuted** (challenge park):
  no negotiation ran outside the mock tests, so the accept/amend/decline
  dynamics on a live model are unmeasured.
- The zero is a FLOOR on this brief shape, not "the tool is never chosen"
  — the same limit rows 51–58 recorded for the purpose tools.
- One H attempt was VOIDED for a runner env bug (`hire=unset`), caught by
  the log's per-run env echo and re-run; details in row 65.

## Honest limits (build-time)

- `role=hired_role(hire)` cannot ride the spawn seam (a Role OBJECT silently
  widens through `load_role` → `None` → the full surface): the child runs the
  base role NAME and the authored fragment opens the assignment brief.
- `Hire.task_id`/`created_step` are best-effort (`""`/`0`) — the executor
  carries no task id or live step counter today.
- The agents-mode set arming reads `COLLEAGUE_HIRE` from env in the static
  module (`agents/tools._hire_pair()`); the wire gate stays
  `hire_schemas.hidden_names` over the RESOLVED flag.

## Provenance

Spec `docs/specs/2026-08-30-delegation-follow-ups-a7-p3-hire.md` (c14–c41,
q5–q7, D43/D44), plan t9–t18/t20; built 2026-08-30 by worktree agents,
integrated on `feat/hire-colleague`.
