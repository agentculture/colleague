# Talking to colleague feels like one teammate: the front model (senses) answers you first — in its own words, instantly — and only wakes cortex for real repo work, visibly handing off; greetings and 'what/how are you' get a self-aware reply from the front door, not a vague cortex detour that spawns a branch and a memory record.

> Talking to colleague feels like one teammate: the front model (senses) answers you first — in its own words, instantly — and only wakes cortex for real repo work, visibly handing off; greetings and 'what/how are you' get a self-aware reply from the front door, not a vague cortex detour that spawns a branch and a memory record.

## Audience

- the operator driving 'colleague session' interactively at the prompt (a human typing free text), and — by the presence-default-everywhere all-fronts rule — anyone conversing with a colleague resident/talk surface where senses fronts cortex

## Before → After

- Before: every free-text line is classify_intent->work->a full cortex work item: 'hi' spawns colleague/<id>-hi + a memory record, and 'what model are you?' is answered by cortex (vaguely: 'no visibility into which backend'); the front model, if armed, only rides as a one-line intake-ack + a concurrent narrator layered on top of a cortex dispatch that ALWAYS happens — so the operator cannot tell a distinct, faster front mind is even involved
- After: senses answers FIRST in its own words; ANY non-repo turn — greetings/social, questions about colleague itself, and general conversation/advice needing no repo access — is answered by senses directly with NO cortex work item (no branch, no eidetic record); the moment a turn needs to read/write the repo, run a command, or produce a work artifact, it gets a senses ack, then a distinct labeled cortex-is-working indicator, then cortex's result presented conversationally; senses' self-answers are grounded in a real colleague-architecture fact-set

## Why it matters

- the two-model split (fast wide front + strong back) only pays off if the operator FEELS one coherent, responsive teammate; otherwise it is just cortex plus extra latency, and burning a full work item (git branch + memory write) on 'hi' is both slow and litters the repo/store

## Requirements

- Ack-first ordering: when senses is armed, senses perceives the operator's line and its acknowledgment is the FIRST operator-facing output for that turn — before any mechanical routing/dispatch line; a cortex-only / unarmed session stays byte-identical (no ack, same output as today)
  - honesty: The senses ack renders before the mechanical routing/dispatch line on every armed front (session/talk/resident); a cortex-only or unarmed run emits no ack and is byte-identical to today's output — test-pinned
- Grounded self-knowledge: senses answers 'what/how are you' from a CURATED colleague architecture/identity fact-set and defers ('I don't know / cortex can check') beyond it; a fabricated architecture claim is a test failure, mirroring the existing grounded-narration honesty rail
  - honesty: Senses' self-answer draws only on the curated architecture fact-set; asked something outside it, senses defers to cortex rather than inventing, and a fabricated architecture claim is a test failure
- Visible hand-off: on a real dispatch the operator sees a distinct, labeled indicator that cortex (the back model) is now working, visually separable from senses' own lines; the senses-vs-cortex attribution is reconstructable from TaskResult.senses in the artifact
  - honesty: An operator can tell at a glance which line is senses vs cortex-working, and both the attribution and the senses-direct-vs-dispatch decision are recorded on TaskResult.senses so the turn is reconstructable from the artifact alone
- Enumerated senses-direct surface: senses may CONCLUDE a turn without cortex ONLY via reply_to_operator/clarify, and ONLY for non-repo turns (social, about-colleague, general non-repo conversation); a turn that would read/write the repo, run a command, or produce a work artifact provably STILL dispatches to cortex, and senses has no reachable repo tool
  - honesty: A repo-touching request (reads/writes files, runs a command, or produces a work artifact) provably STILL dispatches to cortex — test-pinned; senses concludes a turn without cortex ONLY via reply_to_operator/clarify and has no reachable repo tool (existing structural pin holds)

## Honesty conditions

- In a real armed session, the operator's FIRST response to 'hi' comes from senses (the front model), not cortex, and that turn creates NO git branch and NO eidetic record
- The change is felt on BOTH the interactive session prompt and the resident/talk fronts (all-fronts presence rule), not a single surface
- The pain is real today: a bare 'hi' in a live armed session currently produces a colleague/<id>-hi branch AND an eidetic record — reproducible before the change
- With senses-direct, a non-repo turn's latency is the fast front model's alone (no cortex round-trip), measurably quicker than routing through cortex
- Every success signal is observable by an operator in one live session at the prompt / in the artifact, without reading code
- The shipped spec/docs state the FIXED enumerated senses-direct surface + the repo-untouching invariant and reconcile #276 explicitly — it is provably not a learned/general task->model router
- If senses fails to arm, the session degrades to today's cortex-only behavior with a diagnosable notice, never a hard failure
- Given the repo-touching invariant, the senses-direct-vs-cortex split is deterministic — the same input yields the same routing every run, no per-input drift
- A reviewer can point to the fixed enumerated surface + repo-touching invariant in the shipped spec/docs and confirm it is not a learned/general router

## Success signals

- in a live session: 'hi' returns an instant senses reply and creates NO branch and NO eidetic record; 'what model are you / how do you work' returns a correct colleague-architecture-grounded answer from senses with no cortex dispatch; a real task shows senses-ack -> a distinct labeled cortex-working indicator -> cortex result; and every operator-facing line is unmistakably attributable to senses vs cortex

## Scope / boundaries

- NOT a general task->model routing policy. Bright-line invariant: any turn that TOUCHES THE REPO (reads/writes files, runs a command, produces a work artifact) ALWAYS dispatches to cortex — cortex stays the ONLY mind that acts on the repo. Senses-direct is the NON-REPO complement, expressed ONLY through senses' EXISTING reply_to_operator/clarify moves (no new capability, no repo tool reachable). Not changing plan/explore/review verbs; not a new GUI

## Assumptions

- Senses actually ARMS in the operator's live setup — the lobes gateway resolves gemma4 as the senses role and qwen as cortex and the senses endpoint is reachable (cf. the known lobes dead-endpoint workaround); if senses does not arm, that is a config prerequisite, out of scope for this behavior spec

## Decisions

- Land this as the FIFTH sanctioned router-exclusion increment via re-spec: senses-direct (#276) becomes a fixed, enumerated, repo-untouching surface rather than a general routing policy — documented with the #276 relationship stated explicitly (closes or re-scopes #276)
- Attribution style: senses lines carry a 'senses:' prefix and cortex operation shows a 'cortex ▸ working…' status line, with distinct colours on a colour TTY (senses one hue, cortex another); off a colour TTY it degrades to plain labels — machine-parseable stdout preserved, presence rides stderr, --json unaffected

## Hard questions

- Does the user sanction landing #276 (senses answers some turns without cortex) as a fifth fixed/enumerated router-exclusion increment — or must senses ALWAYS dispatch (keeping #276 parked), making this spec only ack-first + visible-handoff + architecture-informed-context-to-cortex?

## Open / follow-up

- Where the curated colleague-architecture fact-set lives and how it stays current (a dedicated doc/prompt fragment vs derived from CLAUDE.md/docs) — drift risk
