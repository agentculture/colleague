# Build Plan — Talking to colleague feels like one teammate: the front model (senses) answers you first — in its own words, instantly — and only wakes cortex for real repo work, visibly handing off; greetings and 'what/how are you' get a self-aware reply from the front door, not a vague cortex detour that spawns a branch and a memory record.

slug: `talking-to-colleague-feels-like-one-teammate-the-f` · status: `exported` · from frame: `talking-to-colleague-feels-like-one-teammate-the-f`

> Talking to colleague feels like one teammate: the front model (senses) answers you first — in its own words, instantly — and only wakes cortex for real repo work, visibly handing off; greetings and 'what/how are you' get a self-aware reply from the front door, not a vague cortex detour that spawns a branch and a memory record.

## Tasks

### t1 — Deterministic front-door classifier: colleague/frontdoor.py classify_frontdoor(text)->SENSES_DIRECT|CORTEX, sibling to session_intent.py

- covers: c15, c16, h8, h13, h14
- acceptance:
  - classify_frontdoor(text) is pure + deterministic (stdlib re only): the same input yields the same route on every call, verified over a fixture corpus
  - returns SENSES_DIRECT only for confidently non-repo turns (greeting/social, about-colleague/identity, general non-repo conversation); ANY repo-touching signal (file path/extension, an edit/run/test/build verb, a git or shell-command token) OR ambiguous/empty input returns CORTEX (conservative default); the allow-list + repo signals are enumerated in ONE place for docs/review

### t2 — Curated colleague architecture/identity fact-set (colleague/architecture_facts.py) + single loader

- covers: c10, h4
- acceptance:
  - colleague self-description facts (front=senses / back=cortex, the two-lobe split, core capabilities, and that senses never touches the repo) load from ONE maintained source via a single loader function; a test pins the presence of those key facts

### t3 — run_senses_frontdoor in colleague/senses.py: ONE tools-off grounded answer for a senses-direct turn

- depends on: t2
- covers: c14, h4
- acceptance:
  - run_senses_frontdoor(text, facts, config, ...) issues exactly ONE make_complete(senses_config, tools=[]) windowed to senses' own budget, grounded in the fact-set + operator text, returns an advisory answer, and degrades (never raises) on a dead/empty endpoint
  - the front-door answer path carries NO tool schema and imports neither ToolExecutor nor subprocess (structural pin test); the prompt instructs deference ('cortex can check') beyond the fact-set and a grounding test asserts a fabricated architecture claim fails

### t4 — Attribution renderer (colleague/attribution.py): senses: prefix + 'cortex working' line, colour on TTY, plain otherwise

- covers: c11, h5
- acceptance:
  - a pure renderer labels senses output with a 'senses:' prefix and cortex operation as a 'cortex working…' line, distinct colours on a colour TTY and plain labels otherwise; snapshot tests pin both forms and assert no ANSI leaks into non-colour/--json output

### t5 — run_frontdoor shared helper (colleague/frontdoor.py) + omit-when-empty front-door record on SensesBlock

- depends on: t1, t3
- covers: c8, c16, h5
- acceptance:
  - run_frontdoor(text, ...) is the ONE shared front-agnostic entry: on SENSES_DIRECT it returns an outcome carrying the senses answer and NO work-item/dispatch; on CORTEX it returns the senses ack (from intake) to render BEFORE dispatch — senses can conclude a turn only as a senses-direct answer or a clarify, never by acting on the repo
  - the front-door decision (route + attribution + any senses answer) is captured on an omit-when-empty record so a dispatched turn is reconstructable from TaskResult.senses and a senses-direct turn from its own record; an unarmed run degrades to CORTEX with the record absent (byte-identical)

### t6 — Wire the front door into colleague session (_work_line): ack-first, senses-direct returns without a work item, visible cortex dispatch

- depends on: t4, t5
- covers: c8, h2, h1, c14, c7, c11
- acceptance:
  - an armed conversational turn renders the senses ack/answer as the FIRST operator-facing line — before any '→ work:' routing line; a SENSES_DIRECT turn prints the 'senses:' answer and RETURNS without running the work loop (no git branch, no eidetic record); a CORTEX turn prints the ack then a 'cortex working…' indicator and dispatches
  - an unarmed / --cortex-only / off-colour-TTY session is byte-identical to today (no ack, no front-door path), and a senses failure degrades to a normal cortex dispatch with a diagnosable notice — never a hard failure

### t7 — Wire the SAME run_frontdoor into the resident/talk front (appserver) for all-fronts one-teammate behavior

- depends on: t4, t5
- covers: c2, h9
- acceptance:
  - the resident/talk front routes an inbound operator message through the SAME run_frontdoor helper: a senses-direct answer replies with no cortex work item, a cortex route acks-then-dispatches, and the reply carries senses/cortex attribution — proving the behavior holds on the resident front, not only the session
  - the c19 trust model is preserved: a non-operator senses-direct reply exposes no repo state (facts only), and only the operator's identity authorizes a cortex write dispatch

### t8 — colleague livecheck one-teammate proof (baseline + after, senses-direct latency, honest SKIP)

- depends on: t6, t7
- covers: c1, h1, c4, h10, c5, h11, c7, h12
- acceptance:
  - on the real armed rig the check asserts: a baseline 'hi' BEFORE the change produced a branch+record (documents c4/h10), and AFTER 'hi' yields an instant senses reply with NO new branch and NO eidetic record; 'what model are you' is answered by senses (not cortex) grounded in the facts; and a dispatched task shows senses-ack -> cortex-working -> result
  - the check measures senses-direct latency as the front model's alone (no cortex round-trip) and SKIPs honestly (never a false PASS) when the senses endpoint is unreachable, mirroring the existing live-proof degradation convention

### t9 — Docs: docs/features/talking-to-one-teammate.md + CLAUDE.md reconciling senses-direct (#276) as the FIFTH sanctioned increment

- depends on: t1, t5, t6
- covers: c15, h14
- acceptance:
  - docs/features/talking-to-one-teammate.md documents the ack-first flow, the fixed enumerated senses-direct surface, the repo-touching bright-line invariant, and the attribution scheme; a reviewer can point to the enumerated allow-list + invariant in the shipped docs
  - CLAUDE.md records senses-direct (#276) as the FIFTH sanctioned router-exclusion increment — fixed/enumerated, not a general router — reconciling the prior 'STAYS parked' line explicitly

## Risks

- [unknown_nonblocking] senses-direct latency proof + the full one-teammate live round-trip depend on the rig serving a reachable senses endpoint; they may SKIP honestly (cf. lobes 502 / dead-endpoint history, lobes-cli#89/#92) (task t8)
- [follow_up] front-door classifier precision: the conservative ambiguous->cortex default means some genuinely non-repo turns still go to cortex (safe under-trigger, not a correctness break); tuning/expanding the allow-list is a follow-up
- [unknown_nonblocking] exact home for the senses-direct record when there is no cortex TaskResult (SensesBlock front-door field vs a standalone senses-direct artifact vs a session-log line) — settle in t5/t6 (task t5)
