# At home on your machine: global config, an owned input line, and self-knowledge

Colleague now feels at home on the machine it runs on, not just inside one
repo. Three frictions — each reproduced live before it was fixed — made the
cortex/senses split feel broken even when the machinery underneath it worked:
a machine-wide lobes default could silently die the moment a repo had *any*
`config.json` of its own; typing while cortex posted mid-run updates visually
destroyed the operator's in-progress sentence; and a question about colleague
itself got a shrug instead of a real answer. The operator's own words, cited
verbatim:

> "I don't feel like I talk with Gemma - feels like it gets right to Qwen"
>
> typing while cortex posts updates "clears my text, so I have to type really
> fast"

Spec + plan:
`docs/specs/2026-07-09-colleague-now-feels-at-home-on-your-machine-arm-th.md`
and `docs/plans/2026-07-09-colleague-now-feels-at-home-on-your-machine-arm-th.md`.

## Leg 1 — Global config, per-key merge

**The bug:** `colleague/configdir.py`'s `resolve_file` returns only the
*first* existing match across config roots — whole-file shadowing. A
repo-level `.colleague/config.json` that never mentioned `lobes` used to make
a user-level `~/.colleague/config.json` `{"lobes": ...}` disappear entirely,
so a machine-wide default died the moment any repo had a config file of its
own for an unrelated reason.

**The fix:** `configdir.resolve_files` (plural) returns *every* existing
match, precedence-ordered `[repo/.colleague, repo/.convertible,
user/.colleague, user/.convertible]`. `colleague/config.py`'s
`_merged_config_json` folds them per **top-level key** — a higher-precedence
file's key wins, but a key it never mentions falls through to the next file
that defines it — and `load_config_file`, `_load_lobes_override`, and the
senses/voice/deepthink section loaders all read through it. A user-level
`lobes` default now survives a repo-level `config.json` that carries
unrelated keys. Merge granularity stops at the top-level key: a repo-level
`senses` section wholly replaces a user-level `senses` section, never a
field-by-field deep merge — precedence stays explainable in one sentence.
Malformed JSON at any single level is skipped for that level only, never
aborting the merge of the others.

A companion hermeticity guard, `COLLEAGUE_HOME` (`configdir._default_user_home`,
`CONVERTIBLE_HOME` honored as a deprecated fallback), lets the test suite point
every test at a fake home directory instead of the developer's real
`~/.colleague/` — closing a gap where a real user-level config could leak into
any test that forgot to isolate it.

**Introspection honesty:** `colleague lobes show` (`colleague/cli/_commands/
lobes.py`) now resolves the gateway URL via the same
`resolve_lobes_gateway_url(repo_path)` the runtime itself consults — env >
repo config > user config — and gained `--repo`. It can no longer contradict
`colleague config show`; a drift test pins that the two never disagree about
the armed state.

Where it lives: `colleague/configdir.py` (`resolve_files`, `config_roots`,
`COLLEAGUE_HOME`), `colleague/config.py` (`_merged_config_json`,
`load_config_file`, `_load_lobes_override`, `_load_senses_overrides`,
`_load_voice_overrides`, `_load_deepthink_overrides`), `colleague/cli/
_commands/lobes.py`, `tests/test_config_merge.py`, `tests/test_cli_lobes.py`.

## Leg 2 — The owned input line

**The friction:** `colleague session`'s talk lane read stdin in cooked mode
(`_poll_talk_lane`). While cortex worked, any update line the cockpit printed
mid-run — a senses ack, a proactive update, a feed line — visually destroyed
whatever the operator had half-typed, because the terminal's own line-editing
buffer and colleague's own prints both fought over the same screen line. This
is the friction behind the operator's complaint above.

**The fix:** `colleague/cli/_commands/_input_line.py`'s `OwnedInputLine` takes
ownership of the bottom input line on a colour TTY: a single daemon reader
thread reads raw stdin per-character into a private *pending* buffer with
instant echo, and `print_above(text)` — under one shared lock with the echo
path — erases the current input line, prints the new text on its own line,
then repaints the prompt and the operator's in-progress buffer below it (a
hand-rolled `patch_stdout`). `colleague/cli/_commands/session.py` wires this
into the colour-TTY talk lane: `emit()` is the one choke point (`_arm_owned_line`
/ `_disarm_owned_line` / `_emit_over_owned_line`) — every mid-run redraw scrolls
new conversation lines above the owned line instead of doing a full-frame
clear-and-redraw that would clobber cooked typing.

**This is the 4th recorded thread-confinement sanction** in this repo
(previously `threading` was confined to `colleague/subagents.py`) — an
operator-decided q1 call, already recorded in the conventions section above
and the v1-scope graduation note (see **Threads and subprocesses are confined
to an explicit sanctioned list** and the four-convention-breaks list); this
doc doesn't restate that record, only points at it. In short: scoped to the
interactive session's colour-TTY path only, never the runtime work loop;
daemon thread with a bounded `join` at `stop`; any setup/spawn/reader failure
degrades to today's cooked-mode behavior, never a crashed session.

Off a colour TTY (piped, `--json`, `--no-tui`, Windows) the session is
byte-identical — the owned input line exists only on the live-ANSI path,
exactly like the slash-autocomplete popup precedent.

Where it lives: `colleague/cli/_commands/_input_line.py` (`OwnedInputLine`),
`colleague/cli/_commands/session.py` (`_arm_owned_line`, `_disarm_owned_line`,
`_enqueue_talk`, `emit`, `_emit_over_owned_line`), `tests/test_input_line.py`,
`tests/test_session_input_line.py`.

## Leg 3 — Self-knowledge, on both minds

**The friction:** the senses front door (#305) answered "what model are
you?" from a thin, hardcoded fact-set — colleague could tell you it had a
front door, but not which model actually sat behind either lobe. Cortex had
no self-knowledge path at all: a self-referential question dispatched to
cortex like any other work item, and cortex had to guess. That gap is what
the operator's "feels like it gets right to Qwen" complaint names — the
front door existed, but it didn't yet know or say who it was talking through.

**The fix, in two pure modules plus two wiring sites:**

- `colleague/selfknowledge.py`'s `classify_selfknowledge` is a deterministic,
  stdlib-`re` classifier — a structural sibling of `frontdoor.py`'s
  `classify_frontdoor` — that returns `True` only for a confidently
  self-knowledge question (identity, architecture, gates, capabilities);
  any imperative-work verb or repo-touching signal wins first, and ambiguous
  input defaults to `False` (an ordinary turn, unaffected).
- The same module's `build_guide_index(repo_path)` returns colleague's own
  live guide paths that actually exist — `CLAUDE.md` plus every
  `docs/features/*.md` — never a dead reference, capped at 40 entries when
  injected (overflow reported honestly as "… and N more", never silently
  dropped).
- `build_self_facts(config, gateway_url=...)` renders the **resolved**
  runtime state as a short plain-text block: the cortex model id, the senses
  model id (or an honest `not configured`), the armed lobes gateway (or an
  honest `not armed`), and which of the five gates (lint, testintegrity,
  affected_tests, memory, coherence) are on. Every value is copied verbatim
  from the resolved config — never guessed, never fabricated.
- **Cortex side** (`colleague/loop.py` `_maybe_inject_self_knowledge`): when
  `classify_selfknowledge` fires on the task's instruction, the loop appends
  ONE advisory user message — the guide index plus the resolved facts block —
  before cortex's first turn, so cortex answers from its own live docs (via
  `read_file`, its existing tool) and the real resolved state instead of
  guessing. An ordinary (non-self-knowledge) turn is a strict no-op: no guide
  index, no facts block, no extra message — pinned byte-identical by test.
- **Senses side** (`colleague/frontdoor.py` `run_frontdoor`, now taking
  `config=`/`gateway_url=` params): once a turn has *already* routed to
  `SENSES_DIRECT` via the pre-existing `classify_frontdoor`, and the caller
  passes its original resolved `EngineConfig`, the front door appends
  `build_self_facts(config, gateway_url=gateway_url)` onto the curated
  architecture fact-set before asking senses to answer — so "what model are
  you?" through the front door now names the real resolved cortex/senses
  ids instead of deferring. `colleague/cli/_commands/session.py` and
  `colleague/resident/appserver.py` both pass their own original config +
  `resolve_lobes_gateway_url(repo)` through this same parameter.

Where it lives: `colleague/selfknowledge.py` (`classify_selfknowledge`,
`build_guide_index`, `build_self_facts`), `colleague/loop.py`
(`_maybe_inject_self_knowledge`, `_SelfFactsSource`, `ContextControls.senses_model`
/ `.lobes_gateway`), `colleague/frontdoor.py` (`run_frontdoor`'s `config`/
`gateway_url` params), `tests/test_selfknowledge.py`,
`tests/test_loop_selfknowledge.py`, `tests/test_frontdoor_runtime.py`.

## The bright line (why this still isn't a router)

Self-knowledge is an **advisory enrichment** of an existing, unchanged
decision — not a new route:

- **The routes stay exactly as drawn in #305/#306.** `classify_frontdoor`
  (unchanged) still decides `SENSES_DIRECT` vs `CORTEX` before self-knowledge
  is ever consulted; `classify_selfknowledge` never redirects a turn between
  cortex and senses — it only decides whether ONE advisory message is
  injected into the turn a turn was *already* going to take.
- **Both classifiers are deterministic, stdlib-`re`, code-locked** — no
  per-input model judgment picks a route or a fact-set. `classify_frontdoor`
  defaults ambiguous input to `CORTEX` (cortex is never withheld from a real
  task); `classify_selfknowledge` defaults ambiguous input to `False` (no
  advisory injected, an ordinary turn proceeds unchanged). Both are the safe,
  conservative default, never a false positive risking a repo action.
- **Cortex stays the only repo actor.** The guide-index advisory only hands
  cortex paths to read with its *existing* `read_file` tool — no new tool
  surface, no write path, nothing senses-side gains any ability to act.
- **No N-role generalization.** No new named role is introduced (a
  guide/docent role was considered and deliberately deferred — see
  Follow-ups below); the fixed cortex-acts / senses-perceives-and-presents
  boundary from the cortex/senses split holds unchanged.

## Honest limits

- **Cortex-side facts render from `ContextControls`, not a full
  `EngineConfig`.** The loop deliberately does not hold a resolved
  `EngineConfig` (the same import-cycle boundary `from_config`/`resolve_role`
  already observe) — `_SelfFactsSource` exposes exactly the fields
  `ContextControls.from_config` threads through (`senses_model`,
  `lobes_gateway`, the five gate booleans, the cortex model id), never the
  gateway's raw role metadata. When even the cortex model id is unknown (a
  direct `run()` caller that passed no model) the facts block is dropped
  entirely and only the guide index is injected — never a fabricated facts
  block.
- **Senses-direct answers remain transcript-only.** A `SENSES_DIRECT` turn
  (with or without the self-facts enrichment) produces no work item and
  therefore no `TaskResult` — it is reconstructable only from the session
  transcript / rolling history, not from an artifact. This is the pre-existing
  #305 limit; it still applies here since the self-facts enrichment rides the
  same path.
- **The classifiers are conservative by construction.** `classify_frontdoor`
  routes ambiguous input to `CORTEX` (a safe under-trigger of senses-direct,
  never a correctness break); `classify_selfknowledge` routes ambiguous input
  to `False` (a safe under-trigger of the advisory, never an over-inject). A
  genuinely self-referential question phrased unusually may get no advisory
  and no guide-grounded answer — tuning the trigger lists is a follow-up, not
  a correctness bug.
- **The guide index only names what exists, and only entry points.**
  `build_guide_index` returns `CLAUDE.md` plus `docs/features/*.md` paths —
  cortex must still `read_file` a listed doc for detail; the index itself is
  capped at 40 entries with an honest overflow line, so it does not grow
  unbounded as feature docs accumulate.
- **The owned input line is colour-TTY session-only.** It is not wired into
  the `colleague talk` attach REPL or the mesh resident — those keep their
  existing cooked-mode/file-based flows. Any arm failure (no real TTY, a
  termios error, a thread that fails to start) silently degrades to the
  pre-existing cooked `_poll_talk_lane` path.
- **Live proofs: PASSED 2026-07-10** (`docs/live-testing.md` rows 27–29,
  graded by `colleague/livecheck.py`'s `classify_at_home_check`). The three
  success signals named in the spec all passed on the reference rig: (a) the
  pre-arc shadow case (repo config carrying only `model`, user-level `lobes`
  default, zero env vars) armed BOTH introspection verbs; (b) `status please`
  typed per-keystroke over a real PTY survived mid-run update lines (the
  patch_stdout repaint captured live); (c) "what model are you?" answered
  with BOTH exact resolved ids via the senses front door (no work item) AND
  via a cortex `--mode explore` run that also explained the affected-tests
  gate correctly from the live guide. One nuance: the live capture proves
  visibility/survival; mid-run line *delivery* to the talk lane is pinned at
  the unit level (`tests/test_input_line.py`, `tests/test_session_input_line.py`).

## Follow-ups

- **A named guide/docent role.** #306's fuller sketch — a dedicated role
  (rather than an advisory message injected into cortex's own turn) — stays
  parked unless the current advisory-injection approach proves too shallow
  in practice (e.g. cortex reading only the index line and never opening a
  listed doc). Draft: `docs/drafts/issue-guide-role.md`.
- **`config show` should list every contributing file.** Now that
  `config.json` resolution is a per-key merge across up to four roots, `colleague
  config show`'s `config_file:` line still names only the single first-matched
  file (`colleague/cli/_commands/config.py` `_config_show`) rather than every
  file that actually contributed a key post-merge. A cosmetic, non-blocking
  follow-up from the spec's own open items. Draft:
  `docs/drafts/issue-config-show-files.md`.
