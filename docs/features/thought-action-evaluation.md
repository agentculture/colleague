# Thought → action → evaluation — a three-seat authority split

> An **authority split**, not a routing policy.

colleague can run in a **thought-action-evaluation (TAE) execution mode**
where three distinct seats carry fixed, non-overlapping authority:

- **front seat** (lobes `senses` role) perceives and commits a typed
  **Thought** — it owns intent, why, constraints, success conditions, and
  uncertainties. It has NO repo tools.
- **worker seat** (lobes `worker` role) realises the thought through tools.
  It ACTS.
- **evaluator seat** (lobes `cortex` role) is tools-off and judges ONLY
  whether an action faithfully realises the thought.

Seats resolve **by role name** from the lobes /capabilities contract — never
by parsing model names. A rig missing a required role REFUSES to arm with a
legible reason; there is no silent fallback. This is **never** an automatic
task-to-model routing policy.

This is the **ninth sanctioned increment** at colleague's router-exclusion
line. It is **opt-in** via `COLLEAGUE_THOUGHT_ACTION_EVALUATION` or
`config.json` `thought_action_evaluation`; absent config is **byte-identical**
to legacy colleague.

## What the mode is — authority split, not three sizes

The three seats are not three models of different capability doing the same
job. They are three seats with **fixed authority boundaries**:

- The **front** seat perceives the operator/environment and commits a typed
  :class:`~colleague.thought.Thought` — it owns intent, rationale, constraints,
  success conditions, and uncertainty. It cannot call repository tools, and a
  thought must never encode an executable tool call.
- The **worker** seat is the only seat that acts on the repo (tools, edits,
  commands). Every consequential action it takes names exactly one live
  ``thought_id``.
- The **evaluator** seat is structurally tools-off — it judges whether a
  proposed action faithfully realises the thought. It never touches the repo,
  never rewrites the thought or the action, and never claims an aligned action
  is *safe* merely because it is aligned.

The split is resolved **by role name** from the lobes gateway — `senses`
(front), `worker` (worker), `cortex` (evaluator) — not by a heuristic that
selects per-task. There is no "worker answers cheap questions" path. The model
never decides which seat handles which input.

## Landed pieces

### Thought contract — `colleague/thought.py`

The front seat commits a typed, versioned :class:`~colleague.thought.Thought`
object. A thought owns **intent**, not evidence: it carries ``thought_id``,
``intent``, ``why``, and optional ``supersedes``, ``observation_refs``,
``constraints``, ``success_conditions``, and ``uncertainties``.

Two cadences, one safety-load-bearing distinction:

1. **Presence mode** — thinking disabled; cheap conversational/environmental
   contact. Represented by :class:`~colleague.thought.PresenceUtterance`, whose
   ONLY field is free text. It structurally CANNOT carry an intent, constraints,
   success conditions, or any other action-authorizing field — extra keys refuse
   the whole payload (:func:`~colleague.thought.validate_presence`).
2. **Thought-commitment mode** — bounded thinking; emits a typed
   :class:`~colleague.thought.Thought` when a decision, replan, or ambiguity
   requires commitment.

The load-bearing rule: the worker must never infer a hidden plan from
presence-mode prose. Only a committed, validated :class:`~colleague.thought.Thought`
grants action-planning authority — see
:func:`~colleague.thought.grants_action_authority`, which returns ``True`` for
exactly one type in this module and ``False`` for every other input (including
a :class:`~colleague.thought.PresenceUtterance`, a bare string, or a
malformed/refused thought payload).

Refuse-whole validation (mirrors :mod:`colleague.lattice` / :mod:`colleague.lessons`):
unknown/extra keys, wrong-typed fields, and a detected embedded tool call all
refuse the WHOLE thought — never stripping the offending part and keeping the
rest. A refused thought is not a partial or repaired thought; the caller gets a
:class:`~colleague.thought.ThoughtVerdict` with ``allowed=False`` and a legible
``reason``, and **never raises**.

### Action proposal — `colleague/actionproposal.py`

The worker seat proposes an :class:`~colleague.actionproposal.ActionProposal`
bound to **exactly one** ``thought_id``. A proposal carries the *what*
(``proposed_action``) and the *why it should work* (``expected_effect``), plus
optional evidence references and a ``consequential`` flag.

Validation additionally checks the ``thought_id`` against the caller's
live/superseded sets: if the ``thought_id`` is not in ``live_thought_ids``, the
proposal is refused; if it is in ``superseded_thought_ids``, the proposal is
refused with a DISTINCT reason that mentions re-evaluation — the action must
route back for re-evaluation and is never silently retargeted to another
thought.

### Evaluation — `colleague/evaluation.py`

The evaluator seat answers exactly ONE question:

> Does this action faithfully realise this thought under the available evidence?

It may detect a constraint violation, an implementation that does not satisfy
the intent, an unsupported expected effect, ambiguity in the thought, action
drift after several tool steps, or an outcome that does not meet the thought's
success conditions — one closed :data:`~colleague.evaluation.VERDICTS` token
each.

**Alignment is not permission, correctness, or wisdom.** The evaluator's
strongest possible output — ``verdict="aligned", route="execute"`` — is a
*fidelity* judgment. It is **never** an authorization:

- it does not grant tool permission and cannot bypass approvals/hooks/policy;
- it does not widen the worker's authority;
- it performs no repository work;
- it never rewrites the thought or the action (a payload smuggling
  thought-/action-authoring content refuses whole);
- it never claims an aligned action is *safe* merely because it is aligned.

:func:`~colleague.evaluation.authorize_execution` encodes the shape: execution
requires BOTH an ``execute``-routed evaluation AND the operator's real approval
gate (:class:`colleague.policy.Policy`) saying yes. The gate is the hard
authority; the evaluation is only a necessary precondition.

The **closed vocabulary** (spec c23) — two enumerated sets, each declared in
exactly ONE place:

- :data:`~colleague.evaluation.VERDICTS` — what the evaluator observed.
- :data:`~colleague.evaluation.ROUTES` — where the run goes next.

Validation refuses the **WHOLE** payload on: a non-dict, an unknown or missing
key, a wrong-typed field, a version mismatch, a verdict or route string outside
the closed sets (no case-folding, no whitespace coercion — ``"Execute"`` is not
``"execute"``), or the single cross-field rule: only
:data:`~colleague.evaluation.VERDICT_ALIGNED` may carry
:data:`~colleague.evaluation.ROUTE_EXECUTE`.

The **bounded envelope** (spec h16 / c28):
:func:`~colleague.evaluation.build_evaluation_envelope` builds the evaluator's
ONLY input — a bounded thought/action/evidence envelope. It is deliberately
**not** the worker's conversation history. Every text/list is capped
(:data:`~colleague.evaluation.MAX_ENVELOPE_TEXT_CHARS` /
:data:`~colleague.evaluation.MAX_ENVELOPE_LIST_ITEMS` /
:data:`~colleague.evaluation.MAX_ENVELOPE_EVIDENCE_ITEMS`) with the truncation
recorded honestly on :data:`~colleague.evaluation.EvaluationEnvelope.truncated`.

### Control primitives — `colleague/tae_control.py`

Pure control logic — no wiring, no I/O. It owns:

- **Evaluator boundaries** — the guard that keeps the slow evaluator seat off
  every tool call. The five sanctioned boundary names are:
  ``initial_plan_commit``, ``consequential_action``, ``declared_infeasible``,
  ``drift_threshold``, ``episode_completion``.
- **Routing table** — maps each route to the next actor seat: ``execute`` →
  ``worker``, ``rethink`` → ``front``, ``replan`` → ``worker``, ``block`` →
  ``host``.
- **Consequential classification** — the worker's ``consequential`` flag is
  **EVIDENCE ONLY**. The host owns the final classification.
- **Supersession policy** — mid-action supersession is
  ``complete_then_re_evaluate``: an in-flight action finishes (avoiding
  half-applied tool state) and its outcome is compared against the NEW thought
  at the next boundary.
- **Evaluator loss policy** — bounded-retry-then-block: it never proceeds
  unevaluated.
- **``may_plan_action``** — delegates to
  :func:`~colleague.thought.grants_action_authority`; a
  :class:`~colleague.thought.PresenceUtterance` yields ``False`` even when its
  text clearly implies an objective.

### Control-loop wiring — `colleague/tae_loop.py`

The wiring half of the TAE mode. It adds the seams: a front seat that runs the
two cadences over a tools-off completion, an evaluator seat invoked at exactly
the five enumerated boundaries with a bounded-retry-then-block loss policy, and
one :class:`~colleague.tae_loop.TaeSession` object the bounded tool loop
(:mod:`colleague.loop`) holds in a single field.

``colleague/loop.py`` itself gains only four thin call sites — an initial-plan
commit, a per-tool-call gate, an observation route, and an episode finalizer —
so its diff stays wiring, not a rewrite.

Key constants:

- :data:`~colleague.tae_loop.FRONT_OFFERED_TOOLS` — an explicit empty list on
  EVERY front completion, so the front structurally cannot carry a repo tool
  schema on the wire.
- :data:`~colleague.tae_loop.COMMITMENT_MAX_ATTEMPTS` — the bound on the
  commitment cadence's deliberation (2). A front that cannot produce a valid
  thought in this many attempts commits nothing.
- :data:`~colleague.tae_loop.DRIFT_REPLAN_THRESHOLD` — consecutive ``replan``
  routes that constitute drift (3). The evaluator has now told the worker its
  action was wrong this many times in a row under an unchanged thought — the
  THOUGHT is the suspect, so the next boundary is ``drift_threshold``.
- :data:`~colleague.tae_loop.CONSEQUENTIAL_TOOLS` — the host's enumerated
  classification of which repo tools are consequential:
  ``write_file``, ``edit_file``, ``run_command``, ``subagent``, ``subagents``.

### Evaluation ledger — `colleague/ledger.py`

An append-only chain of :class:`~colleague.ledger.LedgerEntry` records that
captures one episode of the thought → action → evaluation → reroute → execution
→ outcome cycle. Each entry carries a ``seq`` (assigned by the ledger), a
``kind`` (one of six fixed values), a ``thought_id`` (the chain key), an
optional ``action_id``, a short ``detail`` line, a ``seat`` attribution, and a
``model`` id.

Six kinds, in reading order: ``thought``, ``action``, ``evaluation``,
``reroute``, ``execution``, ``outcome``. Four seats: ``front``, ``worker``,
``evaluator``, ``host``. The ledger exposes exactly ``append`` + ``entries`` —
no edit/remove/clear API exists to rewrite history once an entry lands.

## Configuration

Opt-in via environment variable or config file:

```bash
# Environment variable (highest precedence)
export COLLEAGUE_THOUGHT_ACTION_EVALUATION=1
```

```jsonc
// .colleague/config.json
{
  "thought_action_evaluation": true
}
```

Or: `COLLEAGUE_THOUGHT_ACTION_EVALUATION=1`.

When armed, the lobes gateway's `senses` role fills the front seat, the
`worker` role fills the acting dial, and the `cortex` role fills the evaluator
seat. Unarmed is a strict no-op: no seat is resolved, no field changes, and the
``to_dict()`` key set is byte-identical to the pre-feature snapshot.

### Mutual exclusion with three-tier

TAE is **distinct** from `three_tier`. Arming both refuses loudly — two
execution modes cannot both own the acting seat. The refusal names both modes
and instructs the operator to unset one of
`COLLEAGUE_THREE_TIER` / `COLLEAGUE_THOUGHT_ACTION_EVALUATION`.

### Deepthink is absent

When TAE mode is armed, the deepthink escalation surface is not available. The
front perceives, the worker acts, and the evaluator judges — but there is no
dual-model judgment escalation. This is a deliberate boundary: TAE mode and
dual-model mode are distinct configurations, not layered features.

## The closed vocabulary

### Verdicts

| Verdict | Meaning |
|---|---|
| `aligned` | The action faithfully realises the thought under the available evidence. |
| `constraint_violation` | The action violates a constraint the thought states. |
| `intent_not_satisfied` | The implementation does not satisfy the thought's intent. |
| `unsupported_effect` | The action's expected effect is not supported by the available evidence. |
| `thought_ambiguous` | The thought itself is ambiguous or incomplete. |
| `action_drift` | The action has drifted from the thought over several steps. |
| `success_conditions_unmet` | The observed outcome does not meet the thought's success conditions. |

### Routes

| Route | Next seat | Meaning |
|---|---|---|
| `execute` | worker | Aligned; the host's approval gate still decides whether execution is permitted. |
| `rethink` | front | The thought itself is ambiguous or incomplete; return to the front. |
| `replan` | worker | The action does not express an otherwise usable thought; return to the worker. |
| `block` | host | Structural policy boundary, missing required evidence, or operator decision needed. |

**The one cross-field rule:** only `aligned` may carry `execute`. Alignment is
the *necessary* condition for execution and never the sufficient one; an
aligned verdict may still route to `block`. An unknown verdict or route refuses
the WHOLE payload.

## Load-bearing invariants

### ALIGNMENT IS NOT PERMISSION

An `aligned` verdict still passes approvals/hooks/policy before anything
executes. The evaluator cannot grant permission, widen authority, perform repo
work, or rewrite the thought or action. :func:`~colleague.evaluation.authorize_execution`
encodes this: execution requires BOTH an ``execute``-routed evaluation AND the
operator's real approval gate saying yes.

### PRESENCE CANNOT AUTHORIZE

The front has two cadences: presence (thinking off, cheap conversational
contact) and thought-commitment (bounded thinking, emits a typed Thought). Only
a committed Thought grants action-planning authority; the worker must never
infer a plan from presence prose.
:func:`~colleague.thought.grants_action_authority` returns ``True`` for
exactly one type — a :class:`~colleague.thought.Thought` — and ``False`` for
everything else, including a :class:`~colleague.thought.PresenceUtterance`.

### THE HOST OWNS CONSEQUENTIAL CLASSIFICATION

The worker's ``consequential`` field is **EVIDENCE**, never authority.
:data:`~colleague.tae_loop.CONSEQUENTIAL_TOOLS` is the whole classifier: a
tool named there mutates the tree or executes arbitrary operator-supplied text.
A worker claiming ``consequential=False`` cannot stop a host-classified
consequential action from being treated as consequential.

### THE EVALUATOR IS NOT ON EVERY TOOL CALL

It is invoked only at five enumerated boundaries
(:data:`~colleague.tae_control.EVALUATOR_BOUNDARIES`):

1. `initial_plan_commit` — the worker's first action proposal after a thought.
2. `consequential_action` — any action on a tool in
   :data:`~colleague.tae_loop.CONSEQUENTIAL_TOOLS`.
3. `declared_infeasible` — the worker declares it cannot proceed.
4. `drift_threshold` — after 3 consecutive ``replan`` routes under an
   unchanged thought.
5. `episode_completion` — the episode is ending.

An ordinary tool call is NOT a boundary and never reaches the evaluator.

### EVALUATOR-ONLY VERDICTS NEVER BECOME MEMORY

A verdict is a diagnosis, not ground truth. Durable lessons need external
evidence (an outcome or external evidence ids). The evaluator's judgment does
not write to memory or distillation.

### EVALUATOR AND DISTILLER ARE SEPARATE AUTHORITY CONTRACTS

Even on the same checkpoint, evaluation and distillation are distinct authority
contracts. In the armed mode there is NO safe implicit lesson author — cortex
is the evaluator and the worker is the actor — so a distiller must be declared
explicitly (`distiller_checkpoint`) or distillation falls honestly to the
rung-1 floor.

## Recorded decisions

### Mid-action supersession — COMPLETE-THEN-RE-EVALUATE

When a new thought arrives while an action is in flight, the action completes
first (avoiding half-applied tool state) and its outcome is compared against
the NEW thought at the next boundary. This is the policy returned by
:func:`~colleague.tae_control.supersession_policy` when ``action_in_flight``
is ``True``.

### Evaluator seat loss — BOUNDED-RETRY-THEN-BLOCK

When the evaluator seat is unavailable (transport failure, unparseable output),
the seat retries up to :attr:`~colleague.tae_control.EvaluatorLossPolicy.max_retries`
(default 2). After that, the episode **blocks** — it never proceeds unevaluated.

### Operator/flight guidance routes to the FRONT

Operator or flight guidance routes to the front as an observation, never
straight into the worker — otherwise mid-run words could silently redefine the
thought. The front decides whether to commit a new thought or stay in presence.

## Honest limits

### No live-rig proof yet

All current tests use scripted seat doubles. Whether the three-seat authority
split holds under real model behaviour on a live rig is unmeasured.

### The two front cadences are prompt-and-budget level

colleague's OpenAI surface has no server-side reasoning toggle, so the cadences
differ by system prompt, attempt budget, and output type — not by a server
"thinking" switch. Presence is one completion; commitment is up to
:data:`~colleague.tae_loop.COMMITMENT_MAX_ATTEMPTS` (2).

### Objective-change detection is a deterministic marker list

It is not comprehension; ambiguous wording falls through to presence mode (the
safe direction). It will miss paraphrases.

### `drift_threshold` has no dedicated integration test

:data:`~colleague.tae_loop.DRIFT_REPLAN_THRESHOLD` fires after 3 consecutive
``replan`` routes, but there is no dedicated integration test for this path.

### Whether the front model becomes a quality bottleneck is UNMEASURED

A committed experiment measures this; until it runs, the claim that intent
belongs in the front seat remains a **hypothesis under test**, not a result.
Nothing in this mode's structure is evidence that the split improves outcomes —
the structural tests prove the authority boundary holds, not that holding it is
worth what it costs.

### Legacy vs TAE distinction

In **legacy mode** (no `thought_action_evaluation` config), colleague runs as
before: the cortex drives the tool loop, senses operates as the tools-off front
door, deepthink is available for judgment escalation. The TAE wiring is present
but dormant — byte-identical behavior.

In **TAE mode**, the front seat commits typed Thoughts, the worker acts under
thought-bound actions, and the evaluator judges fidelity at enumerated
boundaries. Deepthink is absent. The authority boundary is fixed: front
perceives, worker acts, evaluator judges.
