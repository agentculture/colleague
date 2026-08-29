# Build Plan — purpose-tools-get-chosen

slug: `purpose-tools-get-chosen` · status: `exported` · from frame: `purpose-tools-get-chosen`

> Colleague's cortex chooses its purpose tools: the prompt no longer advertises delegation tools the acting seat does not hold, the raw alternatives that crowd the typed purposes out are removed where measurement says they should be, and every change lands as a pre-registered arm whose delegation rate is a tracked number

## Tasks

### t1 — \#438a: bound the blocking-fallback path with the same StreamGuards

- instruction: `_stream_or_blocking` (`vllm_openai.py`:719) falls back to a plain `_post_json` (:53) that never constructs StreamGuards; give the fallback the same guard object the streaming reader gets at :574. #438 guidance 1 asks specifically for a REAL-socket drip-feed test, not a mock — see the fake-streams-hide-blocking-reader-bugs lesson.
- acceptance:
  - a real-socket drip-feed test on the non-streaming fallback trips the idle guard within its bound instead of hanging until the request timeout
  - colleague/engines/`vllm_openai.py` is the only file changed; the streaming path's behaviour is byte-identical when the fallback is not taken

### t2 — \#438b: stop backpressure's timeout self-raise when stream guards are armed

- instruction: `_escalate_request_timeout` (loop.py:1931) via `_make_timeout_escalator` (:3472-3510) doubles config.timeout once, fired from :1928 and :1722. It is NOT currently conditional on guards being armed — #438 guidance 3 says the raise is what pushed runs into the unguarded window.
- acceptance:
  - with guards armed, a backpressure departure-from-CLEAR no longer doubles config.timeout; with guards unarmed the existing doubling is unchanged
  - colleague/loop.py is the only file changed and existing backpressure tests pass unmodified

### t3 — \#438c: the idle guard treats SSE keepalive lines as non-activity

- instruction: the idle deadline is `last_bytes`+idle (streamguards.py:107-110). #438 guidance 4: a gateway relaying keepalives over a dead upstream currently looks alive. Count only non-comment payload lines as activity.
- acceptance:
  - a stream emitting only ':' comment lines trips the idle guard at its deadline instead of being kept alive by them
  - colleague/streamguards.py is the only file changed; a stream emitting real data is unaffected

### t4 — \#438d: tally stream-guard trips onto the artifact

- instruction: runcounts.finalize (:76-85) tallies only kind=='loop-guard' (:41). A StreamGuardTripped records a step-stall warning (loop.py:1820-1841) that never becomes a counter — #438 guidance 5 asks for stalls-cut/stalls-escaped so a live-testing row can cite a number.
- acceptance:
  - a run whose stream guard tripped shows a nonzero stream-guard trip count in WorkStats.counts, readable without parsing the warnings array
  - colleague/runcounts.py is the only file changed; loop-guard counting is unchanged

### t5 — Prompt/surface unification: the depth-0 writer substitution feeds the prompt as well as the tool surface

- instruction: Engine.`system_prompt` (engine.py:140-204) reads config.role BY NAME at :184 and only composes the fragment at :190; actingsurface.`curate_for_depth` (:111-120) already substitutes `BUILTIN_ROLES`\['writer'\] for the SURFACE at depth 0. Make one resolution feed both halves. Probe to reproduce the bug first: MockEngine().`system_prompt`(Task(id='x',instruction='x',`repo_path`=<repo with .colleague/agents/writer.md>), EngineConfig(role=None)) returns '' today.
- depends on: t2
- covers: c50, h37, c38, h27
- acceptance:
  - a bare run (config.role None) and an explicit --role writer run compose an IDENTICAL system prompt and an identical tool surface, asserted by rendering both
  - an operator overlay .colleague/agents/writer.md reaches a bare run: the probe that returns `overlay_reached`=False today returns True
  - seats that deliberately carry no role fragment are unchanged: three-tier worker, agents-mode lobes seats, and the tools-off evaluator seat compose exactly as before

### t6 — Count markup-shaped tool calls for any function name on the artifact

- instruction: loop.py:255-270 `_parse_literal_finish` matches the literal string 'function=finish' only; `_TOOL_MARKUP_MARKERS` (:283-289) already lists the shapes. Generalise DETECTION to any function name, count it, leave execution alone. #360 is the measured failure this makes visible.
- depends on: t2, t5
- covers: c51, h38
- acceptance:
  - a turn whose assistant content carries tool-call markup naming any function (not just finish) increments a markup counter visible on the artifact without parsing the warnings array
  - finish-markup recovery (#248 mode B) and the synthesis guard (#264) are behaviourally unchanged - their existing tests pass unmodified
  - the counter is a COUNT only: no markup is executed or converted into a tool call (that would confound every arm)

### t7 — Record a system-prompt digest on the artifact so a prose arm is attributable

- instruction: TaskResult carries role (contract.py:1551-1556, serialized :1791-1792) and `config_digest` (:1717-1724, a sha256 over `config_events`) but nothing about the prompt. Follow `config_digest`'s shape exactly. This is what lets a row cite the digest read back off the artifact instead of the overlay file the operator believes was in place.
- depends on: t2, t5
- covers: c49, h36
- acceptance:
  - two runs whose composed system prompts differ show different prompt digests on their artifacts; two runs with identical prompts show identical digests
  - the digest is a sha256 of the composed system prompt, sits beside `config_digest`, and is omitted-when-None like role

### t8 — Acting-seat-scoped tool drop knob (the surface lever's instrument)

- instruction: `COLLEAGUE_TOOLS_LEGACY` is REJECTED as the instrument: it is role-blind (`curate_schemas` consults it for every role) and strips the scout child too, 8 tools -> 6. Thread a named drop-set through tools.`narrow_role_by_tool_set` (:634-687), applied where actingsurface already knows the depth.
- covers: c11, h13, c41, h31
- acceptance:
  - with the knob naming `grep_search` and glob, the acting seat's rendered surface lacks both while a scout child's rendered surface still holds them
  - with the knob unset, every rendered surface is byte-identical to today for every role
  - the drop applies at depth 0 only and flows through the single composed value that feeds `curate_schemas` AND ToolExecutor's refusal half - no second refusal mechanism

### t9 — Repair the stale SUBAGENTS prompt section in both literals

- instruction: The paragraph is DUPLICATED: inlined in `V1_DEFAULT_SYSTEM` (prompttext.py:69-82) and kept as `_SUBAGENTS` (:124-139) for the qwen variant and `SECTION_TABLE` - edit both or `test_prompttext.py`:71-74 fails. Regenerating tests/snapshots/`prompttext_v1`.txt with `COLLEAGUE_UPDATE_SNAPSHOTS`=1 is deliberate and must be called out in the PR; see plan risk r3 for the conflict with c39's instruction.
- depends on: t5
- covers: c2, h10, c24, h16
- acceptance:
  - 'subagent' and 'subagents' appear nowhere in the composed acting-seat prompt, and each of `web_survey` / `code_survey` / review / validate / plan / `handover_to_colleague` appears at least once
  - the repaired section is no longer than the 174 words it replaces
  - a test demonstrates that `COLLEAGUE_PROMPT_SECTIONS` with the variant unset yields a prompt byte-identical to the v1 text (c24's claim proven, not asserted)

### t10 — Author the arm briefs: re-authored decomposable brief + a large-surface brief

- instruction: docs/live-testing/briefs/row49-purpose.md tells the model to use '(subagent / subagents)' while the arm offers neither - that confound must not survive. For the large-surface brief: row 49's own reading says cortex reads three small files itself, which is RATIONAL; find a size where it demonstrably cannot, or record that no such brief could be constructed.
- covers: c6, h12, c47, h35
- acceptance:
  - grep for 'subagent' and 'subagents' in every branch-arm brief returns nothing
  - the large-surface brief's non-delegating baseline provably hits a budget or context limit, evidenced by a recorded pilot run
  - both briefs are committed under docs/live-testing/briefs/ before any arm runs

### t11 — Arm 4: restore subagent/subagents to the acting seat without leaking to children

- instruction: roles.`_writer_allowlist` (:133-146) drops {web, subagent, subagents}; removing the latter two from that set also hands them to children, because actingsurface.`strip_purpose_tools` (:74-90) strips only purpose names at depth>=1 - verified: a depth-1 child is a 15-tool bounded writer today. Extend the depth>=1 strip. Pins: tests/`test_roles.py`:126-138,140-155,294-304; tests/`test_purpose_tools_byte_identical.py`:88-100; tests/`test_agents_tools.py`:89-92.
- depends on: t8, t5
- covers: c33, h24, c42, h32
- acceptance:
  - the acting seat offers subagent and subagents; a depth-1 child does NOT (it stays the bounded 15-tool writer it is today)
  - the four exact-set pins are updated in the same commit with the changed expectation visible in the diff, never relaxed to a subset check
  - CLAUDE.md and docs/features/purpose-tools.md record the reversal of #443's 'replace, don't add' with both the row that justified it and the row that overturns it

### t12 — Author the three prose overlays P0/P1/P2

- instruction: P1 keeps `delegation_text.py`:44-52's shipped descriptive sentence verbatim (quicker seat, cannot write, reasoning off). P2 replaces that weaker-helper framing with capability-equal framing: same model family on a peer seat, a second independent pass worth having on its own, digest returned for review. roles.`_split_effort_frontmatter` (:310-324) consumes and validates the leading effort line - an unknown rung raises CliError, so every file must carry the same valid one (this also pins the acting-seat rung across arms, removing the #417/#421 confound).
- depends on: t5
- covers: c37, h26, c52, h39, c39, h28
- acceptance:
  - three overlay files exist, each beginning with the SAME 'effort: <rung>' line, and P0 reproduces the built-in writer sentence verbatim after it
  - P1 and P2 differ ONLY in capability framing - diffing them shows no other change
  - with no overlay present the composed acting-seat prompt is byte-identical to the pre-arc composition

### t13 — Row 49 validity re-run: is the 0/3 real or dropped markup?

- instruction: This verifies the arc's own motivating evidence before four levers are built on it. #360's failure mode produces steps:\[\] and `stopped_without_finish`:true; a partial drop would produce fewer steps than the model intended with no other signal. Use the SAME brief text as row 49 so the comparison is exact.
- depends on: t6, t10
- covers: c19, h15
- acceptance:
  - the row-49 brief is re-run n=3 on the current tip with the markup counter armed, and the row records delegation count AND markup count per run
  - if any run shows markup>0 the original 0/3 is written as inconclusive and the arc's framing is corrected in docs/live-testing.md and docs/features/purpose-tools.md
  - scripts/`compare_arms.py` is not modified: git diff on that file is empty

### t14 — Pre-register the arm rows and their pass bars

- instruction: Follow the rows 47-50 shape. The bar is scripts/`compare_arms.py` --bar-wall 1.2 --bar-turns 1.0 (its defaults are 0.7/0.8, so the override is explicit). c46 is the one that changes the row shape most: task success sits beside the delegation rate because the only outcome evidence so far says the delegating run failed and the non-delegating ones succeeded.
- depends on: t10, t12, t11, t13
- covers: c5, h11, c13, h3, c14, h6, c44, h29, c46, h34
- acceptance:
  - every arm row exists in docs/live-testing.md with 'result: pending' and its brief and overlay files committed BEFORE the first run of that arm, provable by git log order
  - each row's cells are delegation rate, markup count, task success, turns ratio, wall ratio and reasoning chars - and the verdict line names which clause decided it, never a bare PASS/MISS
  - each row names exactly one lever and cites its instrument (overlay digest, drop-knob value, or allow-list diff)

### t16 — Run the arm matrix and record results honestly

- instruction: Six arms plus baseline at n=3 is ~21 runs, roughly 1.5-3h serialized on the rig before any stall (#438's history: 5 hangs in 15 runs). Sequence the cheapest and most decisive first - P0 baseline then P2 prose - so a partial matrix still answers something. The #438 tasks (t1-t4) land first precisely so these runs can complete.
- depends on: t14, t1, t3, t4, t7, t5, t8, t9, t13
- acceptance:
  - each row's result cell is filled from `compare_arms.py` output and artifact fields, never from prose
  - a miss is written as a miss, and an incomplete matrix says which arms ran, which did not and why
  - every run's prompt digest read off its artifact matches the arm the row claims; a mismatch voids that run

### t15 — Close the arc: docs, honest conclusion, and the before-state record

- instruction: Recompute the before-state numbers from source rather than from the spec. Run the doc-test-alignment skill. The conclusion is allowed to be 'cortex was right not to delegate' - c46 exists precisely so that outcome is reportable rather than embarrassing.
- depends on: t14, t16
- covers: c1, h1, c15, h5, c18, h9, c20, h4, c21, h2
- acceptance:
  - the closing record names which lever moved the delegation rate and by how much, or states that none did, with the measured ratios beside it
  - it states plainly whether delegating runs succeeded more, less or equally often than non-delegating ones
  - docs/features/purpose-tools.md, docs/features/adopt-from-qwen-code.md, CLAUDE.md and docs/live-testing.md are updated in the same diff, and none claims encouragement the shipped prompt does not carry

## Risks

- [unknown_blocking] The prose lever's instrument (the role overlay) does not reach a bare run until c50's prompt/surface unification lands - so the prose arms are BLOCKED on that task, and running them before it would measure an --role writer configuration rather than the default one operators use.
- [unknown_blocking] Row 49's 0/3 result may be an instrumentation artifact rather than a behavioural finding (#360 markup-drop). Until c51's markup counter exists, the arc's own motivating evidence is unverified.
- [unknown_blocking] c39's instruction says tests/snapshots/`prompttext_v1`.txt is unchanged across the WHOLE arc, but t9 (repairing the stale SUBAGENTS section) necessarily regenerates it. The two confirmed claims conflict: c39/h28 scope the no-change guarantee to the prose arm's instruments, while c2/h10 require the default prompt to stop naming absent tools. Needs an operator ruling before t9 lands. (task t9)
- [unknown_nonblocking] loop.py serializes four tasks (t2, t5, t6 and parts of t9) that are otherwise independent - the known big-file problem of #399/#413. Waves are narrower than the dependency graph requires.
- [follow_up] Wave-1 file collisions forced t6, t7 and t11 to depend on t5 rather than run beside it: t5 touches loop.py (`resolve_role`), engine.py (`system_prompt`) and actingsurface.py, which are exactly the files those three need. The dependency is a MERGE constraint, not a content one - the parallel-equals-serial invariant requires it.
