# Build Plan — hard 1000-line file limit

slug: `hard-1000-line-file-limit` · status: `exported` · from frame: `hard-1000-line-file-limit`

> Every tracked source file in colleague is under 1000 lines, and a CI test keeps it that way — the same hard gate culture-nodes enforces, ported to pytest and covering .py.

## Tasks

### t1 — Land the gate, record the baseline, add the blame-ignore file

- instruction: The gate file is already in the working tree. Add .git-blame-ignore-revs (header comment only; append each pure-move SHA as it lands) and record 'uv run pytest -n auto'. Split nothing in this task.
- covers: c2, h2, c4, h3, c25, h21, c33, h29
- acceptance:
  - tests/`test_file_length_limit.py` is committed and its 4 tests pass, including `test_the_gate_covers_python` and `test_the_scanner_actually_scans`
  - GRANDFATHERED lists exactly the 21 over-limit files at their branch-point counts, matching issue #412's table where it overlaps
  - .git-blame-ignore-revs exists and 'git blame --ignore-revs-file' returns the original author for a line moved by a pure-move commit
  - the pre-split passing count (10715) is recorded before any file is split, and .github/workflows/tests.yml gains no new job

### t2 — Build a read-only pin-audit helper for a module path

- instruction: This is the safety net for every later task: before moving code out of a module, run it and read each hit. It reports coupling; a human decides keep-in-place vs deliberate pin update. Never weaken a pin to make a split fit.
- covers: c8, h4, c11, h13, c32, h28, c9, h5
- acceptance:
  - given a module path it reports: tests containing that path as a string literal, monkeypatch/patch targets naming the module, and membership in `test_boundary.py`'s two allow-lists
  - run against colleague/loop.py it finds the exactly-one-`read_control` pin in `test_senses_live_presence_proofs.py`; against colleague/cli/`_commands`/work.py it finds the `config_lifecycle` pin in `test_content_lane_e2e.py`
  - it emits a monkeypatch-effectiveness checklist naming each test whose patch target would move, since a patch that stops binding stays green
  - the helper lives under scripts/ and is read-only — it never edits a file

### t3 — Split colleague/explain/catalog.py — the pilot that proves the workflow

- instruction: Do this file FIRST — 39 docstring constants, one consumer, zero test pins, 100% covered. It validates the whole workflow (split, delete the grandfather entry, regenerate the ratchet baseline) at near-zero risk before anything harder.
- depends on: t1, t2
- covers: c10, h12
- acceptance:
  - catalog.py is under 1000 lines, the docstring constants live in topic-grouped siblings, and ENTRIES stays importable as 'from colleague.explain.catalog import ENTRIES'
  - its GRANDFATHERED entry is deleted in the same commit; the full suite still reports 10715 passed

### t4 — Split the five oversized test files other than `test_boundary.py`

- instruction: Split by test theme into sibling test modules. `test_boundary.py` is deliberately excluded — it is parsed by other tests and is handled in its own task.
- depends on: t1, t2
- acceptance:
  - `test_ask_colleague_skill.py`, `test_configurator.py`, `test_loop_memory.py`, `test_loop.py` and `test_plan_orchestrator.py` are each under 1000 lines with their GRANDFATHERED entries deleted
  - the total collected test count is unchanged — splitting moved tests, it did not drop any
  - no test body is edited; only file boundaries and shared-fixture imports change

### t5 — Split colleague/tools.py, keeping subprocess in place

- instruction: The design constraint for this whole arc: move pure data and pure helpers OUT, leave the subprocess/threading import and its using code IN. That keeps the two-sided allow-lists and their six mirrors untouched.
- depends on: t1, t2
- acceptance:
  - tools.py is under 1000 lines: SCHEMAS/`TOOL_NAMES`/`DEEPTHINK_SCHEMA`/`curate_schemas` move to a data sibling, ToolExecutor stays
  - subprocess and Path remain imported and USED in tools.py, so `test_boundary.py`'s allow-lists are untouched and the colleague.tools.subprocess.run patches still bind
  - colleague/loop.py's 'from colleague.tools import ToolError, ToolExecutor, ToolOutcome, UnknownToolError' is unmodified and resolves

### t6 — Split colleague/senses.py by lane

- instruction: session.py imports six names from senses; keep every one re-exported. The tools=\[\] count and the `run_senses_talk` FunctionDef are pinned by source-text tests — run the pin-audit helper first.
- depends on: t1, t2
- acceptance:
  - senses.py is under 1000 lines with shared plumbing and the talk lane in siblings; each `run_senses_`\* entry point stays importable from colleague.senses
  - `test_senses_all_engines.py`'s ban still passes — senses.py imports no socket/subprocess/threading/asyncio — and `test_senses_live_presence_proofs.py` still finds `run_senses_talk` and its four tools=\[\] occurrences

### t7 — Split colleague/subagents.py, keeping threading in place

- instruction: The threads allow-list is two-sided and mirrored in six places including CLAUDE.md prose. Keeping concurrent.futures in subagents.py avoids all six edits — that is the point of the constraint.
- depends on: t1, t2
- covers: c6, h9, c7, h11
- acceptance:
  - subagents.py is under 1000 lines with the batch lane and seat/binding resolution in siblings
  - concurrent.futures stays imported and used in subagents.py, so `_THREADS_ALLOWED` is unchanged and its byte-for-byte mirrors in `test_agents_boundary.py` and `test_chain_e2e.py` pass unmodified
  - 'colleague.subagents.registry' remains a module-level name so the four registry.load patches still bind

### t8 — Split livecheck.py, memory.py and handoff.py, keeping subprocess in place

- instruction: Three small files, one PR. Each is just over the limit, so a single clean extraction per file suffices — do not over-engineer.
- depends on: t1, t2
- acceptance:
  - all three are under 1000 lines with their GRANDFATHERED entries deleted
  - each retains its subprocess import AND a use of it, so `_SUBPROCESS_ALLOWED` needs no edit and neither half of the two-sided check fails
  - `test_memory_module_issues_no_embeddings_request` still reads memory.py and passes; `test_livecheck_realtime.py`'s 'no response.create in livecheck' source check still passes

### t9 — Split colleague/engines/`vllm_openai.py`

- instruction: The entry point pins both the module path and the class name. Verify with 'uv run colleague backends list', not just the suite.
- depends on: t1, t2
- covers: c10, h12
- acceptance:
  - `vllm_openai.py` is under 1000 lines and 'from colleague.engines.`vllm_openai` import VllmOpenAIEngine' still resolves, so the pyproject entry point is intact and 'colleague backends list' still discovers vllm-openai
  - `test_loop_batch_wiring.py` and `test_loop_subagent_wiring.py` still find their `batch_spawn`/spawn source lines in `vllm_openai.py`, and `test_headless_streaming.py`'s getsource check still passes
  - the all-engines rule holds: mock and vllm-openai remain identical in result shape per tests/`test_e2e_mock.py`

### t10 — Split colleague/resident/appserver.py under a real safety net

- instruction: This is the ONE file the default suite cannot vouch for — 325 statements at 0% coverage because its tests skip without the extra. Install it FIRST ('uv sync --extra resident') and confirm the tests are running, not skipping, before you move a line. If they cannot be made to run, stop and report rather than splitting blind.
- depends on: t1, t2
- covers: c12, h14, c29, h25
- acceptance:
  - the \[resident\] extra is installed and appserver's own tests actually RUN (not skipped) both before and after the split, with identical results
  - every new module sits under colleague/resident/, so `test_boundary.py`'s `_ASYNC_EXEMPT_PREFIX` is unchanged and the asyncio scan stays green
  - appserver.py is under 1000 lines, still contains `execute_work` and cli.`_commands`.work, and still imports no subprocess (`test_resident_appserver.py`:269,276)

### t11 — Split colleague/`tae_loop.py`

- instruction: Smallest of the hot-adjacent files at 1043 lines; one extraction of ~100 lines clears it. Run the pin-audit helper first — two source-text tests read this module.
- depends on: t1, t2
- acceptance:
  - `tae_loop.py` is under 1000 lines with its GRANDFATHERED entry deleted
  - `test_prompt_surface_unification.py` still passes: getsource(`tae_loop`) contains self.`_complete_once`("", prompt) and does not contain `system_prompt`(task
  - `test_thinking_effort_boundary.py`'s `_SANCTIONED_ASSIGN_FILES` still holds — effort assignment stays in `tae_loop.py` or the list is updated deliberately

### t12 — Split tests/`test_boundary.py` last, after the allow-lists have settled

- instruction: This file is parsed and grepped by other tests, so it goes last and the two frozensets never leave it. Depends on the allow-list-adjacent splits so their outcome is known before this moves.
- depends on: t4, t7, t8
- acceptance:
  - `test_boundary.py` is under 1000 lines and `_SUBPROCESS_ALLOWED` and `_THREADS_ALLOWED` remain literal frozenset AnnAssign statements in it, since `test_agents_boundary.py` AST-extracts them
  - the six importers of those names still resolve, and `test_toolbatch_loop.py` still finds the literal strings 'colleague/toolbatch.py' and 'convention change (6)' by reading the file as text
  - `test_chain_e2e.py`'s exact frozenset equality assertion passes unmodified

### t13 — Decompose colleague/contract.py — the star-shaped split

- instruction: Do this hot file FIRST of the five: it is pure data, has ZERO monkeypatch targets, and is 99% covered. TaskResult.`to_dict`/`from_dict` reference nearly every sibling, so the split is star-shaped — TaskResult stays and imports the new leaves.
- depends on: t1, t2, t3
- covers: c19, h18
- acceptance:
  - contract.py is under 1000 lines with senses records, gate reports, config-event mapping and coercers in siblings
  - importing colleague.contract still pulls in neither colleague.testintegrity nor colleague.affectedtests — the two lazy class getters' pattern is preserved in whichever module holds them
  - all 427 existing 'from colleague.contract import ...' call sites resolve unmodified

### t14 — Decompose colleague/config.py — helpers out, then resolve() itself

- instruction: Two phases in one task: extract the six helper groups (~2600 lines), THEN decompose resolve(). Extraction alone leaves ~1200 lines, so the second phase is mandatory, not optional. `test_single_model_default.py` parses this file by line adjacency — run the pin-audit helper.
- depends on: t1, t2, t3
- covers: c18, h17
- acceptance:
  - config.py is under 1000 lines: file/JSON loading, lobes discovery, sub-config dataclasses, flag resolvers, profiles and model-pin refresh are siblings, and EngineConfig.resolve is decomposed rather than left as one 680-line function
  - the private names other modules import still resolve from their original modules: `_DEFAULT_MAX_OUTPUT_CHARS` from config (used by tools.py:46) and `MAX_SUBAGENT_FANOUT` (used by loop.py:73)
  - colleague.config.`_merged_config_json` is still patchable and its two patches still bind; `test_single_model_default.py`'s line-window parse of the lobes sentinel still passes or is updated deliberately

### t15 — Decompose colleague/loop.py — leaf types first, then the lanes

- instruction: Move `_Work` and ContextControls to `loop_types.py` FIRST — every other extraction depends on that leaf existing, and doing it second means circular imports. actingsurface.py:223 already does a function-local import of colleague.loop to dodge a live cycle; do not make that worse. The exactly-one-occurrence pins are the trap here.
- depends on: t1, t2, t3
- covers: c15, h15
- acceptance:
  - colleague/`loop_types.py` holds `_Work` and ContextControls and imports NO other extracted sibling — verified as a true leaf with no cycle back into loop.py
  - loop.py is under 1000 lines with gates, injections, context/compaction, transport, tool execution, memory, synthesis and flight in siblings
  - `test_senses_live_presence_proofs.py` still counts exactly ONE `read_control`() and exactly one pilot-guidance append across the loop surface; `test_memory_split_record.py` still finds no `build_split_record` in loop.py; `test_toolbatch_loop.py` still finds loop.`_execute_tool` and no ThreadPoolExecutor in loop's own file
  - colleague.loop.`load_telemetry` and colleague.loop.time remain patchable through the colleague.loop namespace

### t16 — Decompose colleague/cli/`_commands`/work.py

- instruction: The `config_lifecycle` pin sweeps every other module and excludes only work.py's own path, so a new `work_`\*.py holding that line FAILS the test. Keep that assignment in work.py. salvage.py:6 documents reading `_arm_interrupt_commit` — keep that name where salvage expects it.
- depends on: t1, t2, t3
- acceptance:
  - work.py is under 1000 lines with the chain lane, config plane, salvage/isolation and argparse in siblings, and `execute_work` decomposed rather than left as a 370-line hub
  - session.py's imports of `execute_work_chain` and `_resolve_chain_arming` resolve unmodified, and colleague.cli.`_commands`.work.`load_telemetry` still binds
  - `test_content_lane_e2e.py` still finds EXACTLY ONE `config_lifecycle` assignment and finds none in any other colleague module — including the new siblings; `test_timeout_survival.py`'s string-split on `_engine_failure_error` still succeeds; `test_resident_no_work_path.py` still finds no 'resident' string in work.py

### t17 — Decompose colleague/cli/`_commands`/session.py via mixins

- instruction: The hardest file: `_Session` is 2700 lines across 85 methods mutating shared instance state, so lanes come out as MIXINS or self-taking functions, never a value-passing split. Depends on the work.py split because session imports work three ways. Do the zero-dependency lanes first — the slash table and the argparse block are pure and carry no `_Session` coupling.
- depends on: t1, t2, t3, t6, t16
- covers: c17, h16
- acceptance:
  - session.py is under 1000 lines with the talk, voice, panel, senses, slash-table and parser lanes extracted, `_Session` composed from mixins with no behaviour change
  - `test_talking_to_one_boundary.py` still finds exactly 2 `_maybe_proactive_update` occurrences with the call site inside `_WorkSink`.`__call__` in a file named session.py — so `_WorkSink` stays in session.py
  - `test_senses_live_presence_proofs.py`'s session source checks still pass: the .summary assignment, the absence of colleague.loop/ctx.messages, and the flight.`append_guidance` call site
  - colleague/cli/`__init__.py` still imports the module by name and `cmd_session` is unchanged

### t18 — Sweep the live docs so no cited module path is stale

- instruction: Paths only, not line numbers: the 144 file:line citations mostly sit in append-only docs/specs/ and go stale by design (c34). Fix what the live pointers claim, leave history alone.
- depends on: t3, t4, t5, t6, t7, t8, t9, t10, t11, t12, t13, t14, t15, t16, t17
- covers: c13, h10
- acceptance:
  - every colleague/\*.py path cited in docs/features/, CLAUDE.md, AGENTS.colleague.md and README.md resolves to a file that exists, verified by a script that greps each citation against the tree
  - docs/specs/ is untouched — 'git diff --stat -- docs/specs/' is empty apart from the arc's own new spec
  - CLAUDE.md's architecture bullets name the new module layout where they previously named a split file

### t19 — Measure whether the ceiling actually buys delegation

- instruction: This is the honesty condition the whole rationale rests on. Prior evidence cuts both ways: a 610-line edit timed out at 8 minutes (colleague#173), but that predates the tolerant `edit_file` adopted in the qwen-code arc. Measure it; do not argue it. A negative result is a valid, publishable outcome here.
- depends on: t3, t4, t5, t6, t7, t8, t9, t10, t11, t12, t13, t14, t15, t16, t17
- covers: c23, h19, c26, h22
- acceptance:
  - at least one delegated colleague run is dispatched against a ~900-line post-split module and its outcome recorded in docs/live-testing.md — landed edit, or timeout with the elapsed time
  - if the run fails, the arc records honestly that 1000 was chosen for reviewability rather than for delegation, and c23/c26 are amended rather than left standing unproven
  - the recorded result names the model, the seat and the file size, so the number is reproducible

### t20 — Sequence the arc as thematic PRs and keep the Sonar gate honest

- instruction: sonar.qualitygate.wait=true blocks CI, and a move-only diff counts as NEW code to Sonar, so new-code coverage and duplication conditions apply to all 18,750 moved lines. Watch the appserver PR in particular. Whether those conditions actually fire on a pure move is an open risk, not a known.
- depends on: t3, t4, t5, t6, t7, t8, t9, t10, t11, t12, t13, t14, t15, t16, t17
- covers: c30, h26, c31, h27
- acceptance:
  - the arc lands as roughly six to eight PRs — one for the sixteen ordinary extractions, one per hot file — each with its own version bump so the version-check job passes
  - each PR is independently revertible: reverting it leaves main green, and any PR that builds on an earlier split says so explicitly
  - the SonarCloud quality gate is green on every PR, or a failure is recorded with its explanation rather than merged past silently

### t21 — Close the arc: empty the grandfather list and prove behaviour is unchanged

- instruction: The closing gate. Compare the passing counts as NUMBERS, before and after — a suite that reports 10715 passed with three tests silently converted to skips has not proven anything. Check the skip count too.
- depends on: t3, t4, t5, t6, t7, t8, t9, t10, t11, t12, t13, t14, t15, t16, t17, t18, t19, t20
- covers: c1, h1, c24, h20, c27, h23
- acceptance:
  - GRANDFATHERED is literally the empty dict and `test_the_grandfather_list_is_reaped` passes, so no tracked source file exceeds 1000 lines
  - 'uv run pytest -n auto' reports 10715 passed — the same count as the recorded pre-split baseline, with no test deleted, weakened, or converted from pass to skip
  - the file-length ratchet baseline is regenerated via `FILE_LENGTH_BASELINE_UPDATE`=1 and committed, so the soft ratchet now pins the reduced sizes
  - the all-engines rule holds: mock and vllm-openai remain identical in result shape

## Risks

- [unknown_nonblocking] Whether Sonar's new-code coverage and duplication conditions actually fire on a pure-move diff — only the blocking config was read, the behaviour was never probed (task t20)
- [unknown_nonblocking] A mid-sequence revert breaks later splits that built on it — thematic PRs bound the blast radius but do not eliminate the ordering coupling (task t20)
- [unknown_nonblocking] The five second-order decompositions (resolve(), `_Session`, `execute_work`, TaskResult, loop's run()) are judgement work whose effort is far less predictable than the sixteen extractions
