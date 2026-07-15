# Build Plan — interactive-finishes-what-it-starts

slug: `interactive-finishes-what-it-starts` · status: `exported` · from frame: `interactive-finishes-what-it-starts`

> colleague's interactive session finishes what it starts: a cut work item continues with one flag, a dirty tree heals with one explicit choice instead of a refusal, and the PR a run just opened is one glance away

## Tasks

### t1 — t1: TaskResult.continued_from lineage field (contract)

- instruction: colleague/contract.py only (+ NEW tests/test_contract_lineage.py). Follow the existing omit-when-None convention used by pr_url/incompletion (contract.py ~1150-1346). Do NOT touch loop.py or work.py — consumers land in later tasks.
- covers: c13, h11
- acceptance:
  - TaskResult gains optional continued_from: Optional[str]=None; to_dict omits it when None (byte-identical artifacts for non-continued runs); from_dict round-trips it
  - tests in tests/test_contract_lineage.py: omit-when-None pin, round-trip, and a populated field serializes

### t2 — t2: NEW colleague/continuation.py — resolve + guard + seed

- instruction: NEW files only: colleague/continuation.py + tests/test_continuation.py. build_continuation(result, result.stats) is the record builder (colleague/escalation.py:187) — probed at ~1.3K tokens on a real artifact, no truncation needed. Seed text shape: a short preamble ('You are CONTINUING work item <id> that stopped early. Prior state:') + the record + the original request verbatim.
- covers: c2, h6, c16, h13
- acceptance:
  - resolve_continuation(repo, ref, allow_completed=False) resolves ref ('last' via feedback.get_last_work, else explicit task id), loads the artifact, and returns (task_id, seed_text) where seed_text embeds build_continuation VERBATIM
  - wrong-run guard: a status-ok artifact raises ContinuationError "nothing to continue: <id> finished ok" unless allow_completed; missing/corrupt artifact raises ContinuationError naming the id — never a silent fresh start
  - pure stdlib module; imports only colleague.{artifact,feedback,escalation,contract}; NEW tests/test_continuation.py covers last-resolution, explicit id, ok-guard, missing artifact, corrupt JSON

### t3 — t5: NEW heal choice model (pure) — 3 choices with consequence+undo copy

- instruction: NEW files only: colleague/heal.py + tests/test_heal.py. No session wiring here (t6 does that). No git calls in this module — it is copy + parsing only; the ACTIONS run in t6. Follow the cockpit label-state-consequence policy (docs/features/cockpit-ux.md).
- covers: c17, h14
- acceptance:
  - a pure module exposes the heal choices [(key,label,consequence,undo)]: commit-onto-work-branch (names the #149 sweep consequence), stash (undo line 'git stash pop'), abort (default); render_heal_prompt() returns the prompt text carrying consequence AND undo verbatim; parse_heal_choice('') == ABORT
  - NEW tests/test_heal.py asserts the prompt copy verbatim (consequence + undo per choice) and empty-input-aborts

### t4 — t4: work --continue/-c CLI flag

- instruction: colleague/cli/_commands/work.py + NEW tests/test_cli_work_continue.py. --continue and the task text are mutually exclusive-ish: with --continue, the positional task text is optional extra guidance appended AFTER the seed. Keep --json output shape unchanged apart from the already-serialized lineage field.
- depends on: t1, t2
- covers: c6, h10, c13
- acceptance:
  - colleague work --continue <id|last> (short -c) seeds the new Task from resolve_continuation's seed_text, records continued_from=<old id> on the new TaskResult, and re-resolves engine/model exactly like a fresh run (no routing: the diff touches no engine/model resolution code)
  - the flag value is validated explicitly in the command (agentfront#38: Flag choices= does not validate value-carrying flags); a ContinuationError renders as a clean CliError with the id in the message
  - e2e test: cut a scripted mock run mid-flight (max_steps=1), then work --continue last reaches a terminal state with >=1 further step and the new artifact carries continued_from (lineage, success signal c13)

### t5 — t5: session heal wiring — dirty-blocked dispatch offers the choice

- instruction: colleague/cli/_commands/session.py (the _work_line dispatch + the Next panel suggestion at ~931-946) + NEW tests/test_session_heal.py. Import the copy/parsing from colleague/heal.py (t3) — do not duplicate strings. The stash action shells out via the session's existing git plumbing; capture the stash ref from 'git stash create'-style porcelain output.
- depends on: t3
- covers: c3, h7, c14, h12, c5, h9
- acceptance:
  - a session free-text dispatch on a dirty tree (facts.dirty and not allow_dirty) renders the heal prompt BEFORE any run starts; choice 1 re-dispatches with allow_dirty for this run only; choice 2 runs git stash (prints the created ref + 'git stash pop' recovery); empty/abort cancels the dispatch with the tree untouched
  - off-TTY/piped sessions and --json never render the prompt — dirty-blocked dispatch falls back to today's refusal text byte-identically (test pins both paths)
  - the runtime guard is untouched: a bare 'colleague work' on a dirty repo still refuses with the #149 error verbatim (pin test), and 0 dirty-tree refusals reach a colour-TTY session dispatch (success signal c14)

### t6 — t6: session /continue slash + free-text affordance

- instruction: colleague/cli/_commands/session.py (SlashSpec catalog ~2506 + a handler) + NEW tests/test_session_continue.py. Runs AFTER t5 lands (same hot file — rebase, do not parallel-edit).
- depends on: t2, t5
- covers: c1, h1, c9, h2, c2
- acceptance:
  - /continue [id|last] appears in the SlashSpec catalog (category runtime, safety-tagged) and dispatches the same resolve_continuation path work -c uses; bare /continue defaults to 'last'
  - the affordance is agent-parseable: off-TTY the result line stays machine-readable and the ok-guard error text is identical to the CLI's (audience h2)
  - one-move acceptance: from a fresh session in a repo whose last run was cut, /continue resumes it (test: scripted session input '/continue' then quit)

### t7 — t7: PR link on the session surface

- instruction: colleague/cockpit_run.py (Ledger ~113 + observed_ledger), colleague/cli/_commands/_tui_sink.py, session.py Last-run panel; tests extend tests/test_session_cockpit.py + tests/test_cockpit_run.py if present. publish_state already distinguishes publish outcomes — mirror its plumbing.
- depends on: t6
- covers: c4, h8
- acceptance:
  - cockpit Ledger gains pr_url: Optional[str] (None-safe); observed_ledger threads it from the folded run state; the session Last-run panel renders 'PR: <url>' only when non-None; the post-run session line appends the PR url when the handoff returned one
  - a local-only run renders exactly today's output (pin test); no synthesized URLs anywhere (h8)

### t8 — t8: docs + boundary grep gate + acceptance sweep

- instruction: Docs + verification only — no runtime code. Run the grep gate against the full arc diff (git diff main...HEAD) and paste the result into the feature doc's honest-limits section.
- depends on: t4, t7
- covers: c10, h3, c11, h4, c12, h5, c19, h15
- acceptance:
  - docs/features/session-continue-heal.md documents the three affordances honestly (incl. the top-level-only boundary and the last_work race residual); CLAUDE.md gains the architecture bullet; the #170 closure note cites the spec (decision c15)
  - boundary grep gate executed and recorded in the doc: the arc diff touches no resident/, plan/, subagents.py dispatch, and no engine/model resolution (c19/h15, c6)
  - acceptance sweep table maps each of the three flows to its landed test (one flag / one choice / zero moves — h1, h4): each named test fails on main, passes on the branch

## Risks

- [unknown_nonblocking] the 27B under load historically stalls on large-existing-file edits (session.py is ~2600 lines) — session tasks t5/t6/t7 may need Claude-side surgery if colleague drives time out (the colleague-edits-large-files lesson)
- [unknown_nonblocking] two concurrent sessions racing the last_work pointer: 'continue last' may resolve the other session's run; explicit id is exact (parked spec-side as v2)
