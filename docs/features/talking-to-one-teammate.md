# Talking to colleague feels like one teammate (the senses front door)

> **Opt-in since v1.63 (qwen-direct).** Senses is no longer resolved from the
> lobes gateway by default — a bare run dials exactly one model (cortex). Arm
> this lane explicitly with `COLLEAGUE_SENSES_MODEL=lobes` (discovery) or an
> explicit model id (config.json `senses.model` works too); unarmed, every
> behaviour below is dormant and the artifact is byte-identical to the unarmed
> floor. Spec: `docs/specs/2026-08-22-qwen-direct-no-gemma.md` · doc:
> [`qwen-direct.md`](qwen-direct.md).

Colleague drives with two lobes — **cortex** (the back mind that does the repo
work) and **senses** (the front mind that perceives and presents). Before this
feature, every free-text line in `colleague session` was routed straight to a
full cortex work item: a bare `hi` spawned a `colleague/<id>-hi` git branch **and**
an eidetic memory record, and `what model are you?` was answered — vaguely — by
cortex. The fast front model, when armed at all, only rode along as a one-line
intake ack and a concurrent narrator bolted onto a dispatch that always happened.

Now senses is a genuine **front door**: it answers you first, and only wakes
cortex for real repo work.

## What changed

- **Ack-first.** When senses is armed, its acknowledgment is the *first*
  operator-facing line for a turn — it renders *before* the mechanical `→ work:`
  routing line (previously the ack came after).
- **Senses answers non-repo turns itself.** A greeting, a question about
  colleague itself (`what are you`, `how do you work`), or general non-repo
  conversation is answered **directly by senses** — with **no cortex work item**:
  no git branch, no eidetic record, no work loop. The answer is grounded in a
  curated architecture fact-set (see `colleague/architecture_facts.py`), and
  senses defers to cortex rather than inventing a detail it doesn't hold.
- **Visible hand-off.** When a turn *is* repo work, the operator sees the senses
  ack, then a distinct `cortex ▸ working…` line, then cortex's result — so it is
  unmistakable which mind is speaking (`colleague/attribution.py`).
- **All fronts.** The same decision runs on both the interactive session and the
  resident/`talk` front (`colleague/resident/appserver.py`).

## The bright line (why this is not a router)

This is the **fifth sanctioned increment at the router-exclusion boundary** (after
deepthink, the cortex/senses split, and the senses live-presence + voice arc). It
lands the previously-parked #276 (senses-direct) as a **fixed, enumerated,
repo-untouching** surface — not a general task→model routing policy:

- **The route is deterministic.** `colleague/frontdoor.py` `classify_frontdoor`
  is a pure, stdlib-`re` classifier (a sibling of `session_intent.classify_intent`).
  The same input yields the same route on every call — no per-input model
  judgment decides whether cortex is needed.
- **The invariant: anything touching the repo always → cortex.** Any repo signal
  (a file path/extension, an edit/run/test verb, a git/shell token) — or any
  *ambiguous* input — routes to CORTEX. `SENSES_DIRECT` is returned **only** for a
  confidently non-repo turn. The conservative default is the safety property:
  colleague never withholds cortex from a real task.
- **Senses cannot act.** A senses-direct turn concludes only by *answering*
  (`run_senses_frontdoor` — one tools-off completion, no tool schema, no reachable
  repo tool) or by deferring. Cortex stays the only mind that touches the repo.
- **Degrade never fails.** If senses is unreachable, a would-be senses-direct turn
  falls back to a normal cortex dispatch (`FrontDoorOutcome.dispatch`). An unarmed
  / `--cortex-only` / off-colour-TTY session is byte-identical to before this
  feature — no front door, no ack, same output.

## How it fits together

```text
operator line
   │
   ├─ classify_intent → work | plan | explore | review      (session_intent.py, unchanged)
   │        │
   │        └─ work → run_frontdoor(text)                    (frontdoor.py)
   │                     │  classify_frontdoor (deterministic)
   │                     ├─ SENSES_DIRECT → run_senses_frontdoor (senses.py, tools-off,
   │                     │        grounded in architecture_facts.py) → answer, NO work item
   │                     └─ CORTEX → ack (intake) → "cortex ▸ working…" → work loop
```

- `colleague/frontdoor.py` — `classify_frontdoor` (the deterministic route) and
  `run_frontdoor` / `FrontDoorOutcome` (the shared, front-agnostic decision both
  fronts call).
- `colleague/architecture_facts.py` — the curated self-description fact-set +
  `load_architecture_facts()`.
- `colleague/senses.py` — `run_senses_frontdoor`, the tools-off grounded answer.
- `colleague/attribution.py` — the `senses:` / `cortex ▸ working…` labels
  (colour-capable; plain by default).
- `colleague/cli/_commands/session.py` — session wiring (`_run_frontdoor`,
  `_render_senses_direct`, ack-before-routing reorder).
- `colleague/resident/appserver.py` — the resident/`talk` front, under the c19
  trust model (a non-operator's senses-direct answer is facts-only and exposes no
  repo state; only the operator authorizes a cortex write dispatch).

## Recording

- A **dispatched** turn records the front-door route on `TaskResult.senses.records`
  as a `senses-frontdoor:<route>` entry (via the existing `SensesRecord` shape and
  the session's `_finalize_split_run` fold) — the decision is reconstructable from
  the artifact.
- A **senses-direct** turn produces no work item and therefore no `TaskResult`; it
  is reconstructable from the session transcript / rolling history. A standalone
  artifact for senses-direct turns is a documented follow-up (see below).

## Honest limits

- **Senses-direct turns have no JSON artifact** — they are reconstructable from
  the session transcript, not from a `TaskResult` (there is no work item). A
  lightweight senses-direct artifact is a follow-up.
- **Per-lobe colour in the live cockpit is deferred.** `attribution.py` supports
  distinct colours, but the session renders the labels plain through the cockpit
  reducer (injecting raw ANSI into the reducer would risk the flat renderer). The
  distinct *labels* (`senses:` vs `cortex ▸ working…`) already make the two minds
  unmistakable at a glance.
- **The classifier is conservative.** Ambiguous input routes to cortex, so some
  genuinely non-repo turns still reach cortex (a safe under-trigger, never a
  correctness break). Tuning/expanding the allow-list is a follow-up.
- **The live proof is rig-dependent.** `colleague/livecheck.py`
  `classify_one_teammate_check` SKIPs honestly when senses is unarmed/unreachable
  (the reference rig's state today), never a fabricated pass.
- **Arming is a prerequisite.** If a lobes gateway / senses config is not
  resolved, senses is unarmed and the session runs cortex-only (byte-identical) —
  verify with `colleague lobes show`.

## Spec + plan

- Spec: `docs/specs/2026-07-08-talking-to-colleague-feels-like-one-teammate-the-f.md`
- Plan: `docs/plans/2026-07-08-talking-to-colleague-feels-like-one-teammate-the-f.md`
