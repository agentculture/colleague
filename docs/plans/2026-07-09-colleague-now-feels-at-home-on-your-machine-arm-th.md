# Build Plan — Colleague now feels at home on your machine: arm the lobes gateway once globally and every repo gets cortex+senses; type mid-run without the cockpit eating your words; and ask colleague anything about itself — it answers from its own live guide, through senses or cortex.

slug: `colleague-now-feels-at-home-on-your-machine-arm-th` · status: `exported` · from frame: `colleague-now-feels-at-home-on-your-machine-arm-th`

> Colleague now feels at home on your machine: arm the lobes gateway once globally and every repo gets cortex+senses; type mid-run without the cockpit eating your words; and ask colleague anything about itself — it answers from its own live guide, through senses or cortex.

## Tasks

### t1 — t1 per-key config merge: configdir gains resolve_files (all matches in precedence order); config.py's load_config_file, _load_lobes_override, and the senses/voice/deepthink section loaders merge per top-level key across roots (repo wins, user fills absent keys). TDD: the shadow test (repo config without lobes + user config with lobes => armed) written FIRST as the failing reproduction

- instruction: Write the shadow test FIRST (tests/test_config_merge.py, fake user_home fixture — the tmp-repo pattern). Then: configdir.resolve_files (plural, all matches precedence-ordered) + per-top-level-key merge in load_config_file/_load_lobes_override/section loaders. Do NOT change EngineConfig.resolve's rung order.
- covers: c6, h1, h2, c3, h12, h16
- acceptance:
  - Failing-first shadow test: repo .colleague/config.json {model:x} + user ~/.colleague/config.json {lobes:URL} => resolve_lobes_gateway_url returns URL
  - A repo config carrying a key behaves byte-identically (merge only fills absent keys); existing config tests green unchanged
  - Malformed JSON at any level skips that level, never raises; legacy .convertible roots keep their place in the order
  - Merge granularity is top-level key: a repo senses section wholly replaces a user senses section (test-pinned)

### t2 — t2 lobes show honesty: widen colleague/cli/_commands/lobes.py to the real precedence via resolve_lobes_gateway_url(repo_path), add --repo (default cwd); drop the env-only scope note

- instruction: lobes.py CLI: replace the env-only _GATEWAY_URL_ENV read with config.resolve_lobes_gateway_url(repo_path); add --repo (default cwd) to show; update the module docstring (the deferred-widening note is now discharged); drift test in tests/test_cli_lobes.py.
- covers: c7, h3
- acceptance:
  - lobes show --repo <r> reports armed when only the config-file rung arms it (env unset)
  - Drift test pins lobes show and config show agree on armed state in armed and unarmed states (shared resolver, no duplicated parsing)

### t4 — Owned-input-line machinery: new module colleague/cli/_commands/_input_line.py — a reader thread owning raw stdin (instant per-key echo into an owned buffer) + a locked print_above(text) helper that repaints the pending line after every print (hand-rolled patch_stdout); bounded join at stop; any failure degrades to cooked mode. Includes the test_boundary.py thread allow-list edit with the recorded rationale (the operator-decided q1 sanction — the module can't land green without it)

- instruction: New module colleague/cli/_commands/_input_line.py: OwnedInputLine(stream_in, stream_out) with start/stop/print_above; reader thread daemon=True, join(timeout). Test via io streams — no real TTY. The test_boundary.py allow-list edit lands IN THIS TASK with rationale 'operator-decided q1 sanction, colour-TTY session path only'.
- covers: h5, h10, c13
- acceptance:
  - print_above pytest: pending buffer 'tell it to' + print_above('[edit_file] x') => update line ABOVE a repainted '> tell it to' (fake-stream test, no real TTY)
  - Reader thread starts only when armed, joins (bounded) on stop; a thread failure degrades to cooked-mode behavior, never raises out
  - test_boundary.py allow-list names the module + reason; zero new dependencies (stdlib threading/termios only)

### t5 — Session wiring: the colour-TTY talk lane uses the owned input line — sink/update prints route through print_above; _poll_talk_lane's cooked select path stays as the off-colour-TTY fallback. TDD: the typing-clobber reproduction written FIRST

- instruction: session.py: arm OwnedInputLine when the talk lane arms on a colour TTY; route _log/update prints through print_above while armed; keep _poll_talk_lane as the non-colour-TTY fallback; presence-pin tests must stay green.
- depends on: t4
- covers: c8, h4, c3
- acceptance:
  - Failing-first test: an update printed while input is pending destroys the pending line pre-fix, preserved post-fix (fake-stream)
  - Off a colour TTY (piped, --json, --no-tui) the session is byte-identical — existing presence-pin tests green unchanged
  - A mid-run submitted line reaches _handle_talk_input verbatim (talk-lane behavior unchanged)

### t6 — Record the 4th convention break: CLAUDE.md conventions section documents the sanctioned session reader thread (confinement to the colour-TTY session path, join semantics, degrade path) alongside the three existing recorded breaks

- instruction: CLAUDE.md conventions bullet: the 4th recorded break (session reader thread), confinement + join + degrade stated; reference _input_line.py and test_boundary.py.
- depends on: t4
- covers: c13
- acceptance:
  - CLAUDE.md names the break, its confinement, and why cooked mode couldn't fix it; markdownlint green

### t7 — Self-knowledge classifier + guide index: new module colleague/selfknowledge.py — a deterministic stdlib-re classifier (classify_frontdoor sibling; ambiguous => NOT self-knowledge) + build_guide_index() naming the live guide paths (CLAUDE.md architecture bullets, docs/features/*)

- instruction: colleague/selfknowledge.py: classify_selfknowledge(text) (stdlib re, deterministic, ambiguous=>False) + build_guide_index(repo_path) returning existing doc paths only. Mirror frontdoor.py's classifier test style.
- covers: c12, h15, c9
- acceptance:
  - Boundary test pins the classifier is deterministic and ambiguous input routes to the default (never the guide surface)
  - 'how does the affected-tests gate work?' / 'what model are you?' classify as self-knowledge; 'fix the affected-tests gate' does NOT (repo work stays cortex work)
  - build_guide_index returns only paths that exist in the repo (no dead references)

### t8 — Runtime self-facts builder in colleague/selfknowledge.py: build_self_facts(config) renders the RESOLVED state — cortex+senses model ids, armed gateway, active gates — from EngineConfig.resolve output only

- instruction: build_self_facts(config): pure function over EngineConfig fields (model, senses.model, lobes.gateway, gates on/off). No network, no model call. Unarmed => 'lobes not armed' string, never a fabricated id.
- depends on: t7
- covers: c10, h7
- acceptance:
  - Armed config => facts name the exact resolved model id strings; unarmed => honest 'lobes not armed', never a fabricated id (test-pinned)
  - Facts are built from config values only — no model call, no network (pure function)

### t9 — Cortex-side wiring in colleague/loop.py: a self-knowledge-classified turn injects ONE advisory message (guide index + self-facts) before the cortex turn; cortex reads the live docs via existing read_file. Pin the #306 acceptance: ordinary turns byte-identical

- instruction: loop.py: inject ONE advisory user-role message (guide index + self-facts) when classify_selfknowledge fires on the task instruction — mirror _maybe_inject_context_packet's pattern. Byte-identical pin test for ordinary turns; all-engines (mock + vllm-openai).
- depends on: t7, t8
- covers: c9, c11, h6, h8, h11
- acceptance:
  - Test pins an ordinary (non-self-knowledge) turn's system prompt + initial messages byte-identical with the feature present
  - A self-knowledge turn's injected advisory names the guide paths + resolved facts; fires identically for mock and vllm-openai (all-engines)
  - TaskResult contract unchanged for ordinary runs (e2e shape test green); no new tool surface

### t10 — Senses-side self-facts: the front door's fact-set (colleague/architecture_facts.py + frontdoor/senses path) gains the resolved runtime facts so 'what model are you?' through senses answers with the real ids — replacing the live-proven 'I don't know which model' deferral. TDD: that deferral is the failing reproduction

- instruction: architecture_facts.py/frontdoor.py: append build_self_facts output to the front-door fact-set when armed. Failing-first test: 'what model are you?' answer must contain the exact resolved id strings.
- depends on: t8
- covers: c10, c3, h7
- acceptance:
  - Failing-first: front-door answer to 'what model are you?' contains the exact resolved senses+cortex model id strings when armed
  - Unarmed stays honest ('not armed'/operator-configured), never fabricated; c19 trust holds — facts expose config identity, no repo state

### t11 — Live proofs: livecheck classifiers for the three success signals — (a) global-arming shadow proof (zero env vars, repo config without lobes => armed + lobes show agrees), (b) input-line survival (print-above pytest + a recorded live session), (c) self-knowledge answers with exact resolved model ids via senses AND cortex, guide question answered from real docs. Graded from evidence, honest SKIP when the rig is down; rows added to docs/live-testing.md

- instruction: livecheck.py: classify_at_home_check grading the three proofs from evidence (honest SKIP when rig/senses down); add graded rows to docs/live-testing.md. Run the proofs live on the reference rig before grading.
- depends on: t1, t2, t5, t9, t10
- covers: c1, c4, c14, c18, h9, h13, h17, h18, c2
- acceptance:
  - Each proof is a runnable check (livecheck classifier or pytest), graded from evidence, SKIPs honestly when senses/rig is unavailable
  - 'what model are you?' grading is exact-match on the resolved model id string; instant-echo grading is structural (echo on keypress, not at boundaries — a boundary-wait regression fails)
  - docs/live-testing.md gains one graded row per proof before the arc announces

### t12 — Feature doc + arc closing: docs/features/at-home-on-your-machine.md (motivation cites the operator complaint verbatim; restates the router-exclusion line; names the guide/docent role follow-up and the config-show contributing-files follow-up), CLAUDE.md architecture bullet, version bump

- instruction: docs/features/at-home-on-your-machine.md (cite the operator complaint verbatim; router-exclusion restated; follow-ups r3/r4 filed as issues), CLAUDE.md architecture bullet, CHANGELOG + version-bump skill (minor).
- depends on: t10, t9, t5
- covers: c5, h14, c2
- acceptance:
  - Feature doc cites the felt complaint verbatim and the three proofs; boundary section restates no-router/no-N-role; follow-ups filed as issues, not silently dropped
  - CLAUDE.md bullet + CHANGELOG entry land; version bumped (version-check CI green); markdownlint green

## Risks

- [unknown_nonblocking] Faithful pytest coverage of real-terminal thread/echo interaction is limited (pseudo-TTY vs real TTY differ); mitigated by the pure print_above helper tests + the recorded live session proof (task t4)
- [unknown_nonblocking] Guide-index injection + cortex doc reads consume context budget on the 27B's 48K window; v1 caps the advisory size and lets windowing handle the rest — measured during the live proof (task t9)
- [follow_up] Named guide/docent role (#306's fuller sketch) deliberately deferred — file as follow-up issue if injected answers prove shallow
- [follow_up] config show listing ALL contributing config files post-merge — cosmetic follow-up from the frame (v2)
