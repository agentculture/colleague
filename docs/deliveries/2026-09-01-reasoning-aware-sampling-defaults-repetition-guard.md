# Delivery Summary — reasoning-aware sampling defaults + repetition guard (#479)

plan: `reasoning-aware-sampling-defaults-repetition-guard` · run: `complete` · date: `2026-09-01`
baseline: `devague summary skeleton`

## Intent

> Colleague sends each model's recommended sampling profile on every turn — a thinking profile when a reasoning rung is armed, a non-thinking profile when effort is off — instead of hard-coded greedy decoding; a model-independent guard cuts a turn whose reasoning has started repeating itself instead of riding it into the output budget; and a long turn keeps reporting liveness while it runs, so a runaway is visible while it happens rather than at the post-mortem.

After: Each seat's completion carries its model's recommended sampling profile chosen by the already-resolved effort rung — Qwen3.8 thinking (1.0 / 0.95 / `top_k` 20) when a rung is armed, Qwen3.8 non-thinking (0.7 / 0.80 / `top_k` 20 / presence 1.5) when effort is off — declared in the tracked .colleague/models.json so every clone and worktree reads the same table, and a model-independent guard ends a turn whose reasoning has begun repeating instead of letting it ride to the output budget.

## Planned Work

- `t1` — Oilcheck probes stay greedy and byte-identical
- `t2` — Sampling leaf module: profile table, model-id match rule, resolution ladder
- `t3` — models.json: tracked file, loader, merge granularity, gitignore allow-list
- `t4` — Repetition detector: pure tail-repeat function, turn-scoped state, escalation constant
- `t5` — Adapter wiring: send the resolved profile, only differing keys, plus the `COLLEAGUE_SAMPLING` kill switch
- `t6` — Guard wiring: cut the turn on the streaming and blocking paths, record what it cost
- `t7` — Config lane: deprecate the env knobs, render the sampling match in config show
- `t8` — Distill child: the second greedy site gets the same profile
- `t9` — Record the resolved profile on the run artifact
- `t10` — In-flight liveness on the streaming path
- `t11` — Documentation, the fourth carve-out, and the recorded probe evidence
- `t12` — The definitive measurement arm and its behavioural discriminator

## Actual Delivery

| Plan task | Status | What actually landed |
|-----------|--------|----------------------|
| `t1` | delivered | `tests/test_oilcheck_greedy_probes.py` — 3 tests pinning both probes' bodies to exactly six keys, `temperature 0.0`, no sampling keys. I verified it bites by injecting `top_p` and watching 2 of 3 fail. |
| `t2` | delivered | `colleague/sampling.py` (263 lines) + 46 tests. Frozen `SamplingProfile`/`SamplingRow`, `BUILTIN_SAMPLING_ROWS`, `normalize_model_id`, `half_for_rung`, `resolve_sampling`, `sampling_payload`. Leaf module: stdlib + `colleague.effort` only. |
| `t3` | delivered | `colleague/samplingfile.py` — tolerant `.colleague/models.json` loader, per-model merge granularity, plus the one-line `!models.json` allow-list in `artifact.py`'s self-written `.gitignore`. Criterion 4 tested via a real `worktree_add()` dispatch. |
| `t4` | delivered | `colleague/repetitionguard.py` + 16 tests. Verbatim-tail detector, KMP minimal-period guarded, state threaded not module-scoped, named constants 48 / 8 / 8192 / 3. |
| `t5` | delivered | The single write site in `_build_chat_payload`'s non-associate branch; `COLLEAGUE_SAMPLING=0` kill switch; operator `models.json` rows layered over the builtin table. Criterion 5 not met as literally written — see `d1`. |
| `t6` | delivered | `RepetitionTripped` on the streaming read, the same detector once post-turn on the blocking path, one trip per TURN (not per callback), escalation on the third. `loopguards.py`'s docstring records the reversal honestly. |
| `t7` | delivered | `CONVERTIBLE_TEMPERATURE` removed + warns; `COLLEAGUE_TEMPERATURE` deprecated over one release + warns naming `models.json`; `config show` states the sampling match positively. Two integrator fixes on top — `d4` and `d6`. |
| `t8` | delivered | `colleague/distill.py`'s bounded completion resolves its own profile from its own `distilleffort` rung, with a `COLLEAGUE_DUMP_REQUEST` path added. Proven independent of the acting seat's rung under poisoned env. |
| `t9` | delivered | `colleague/samplingrecord.py` + the one fold-in point in `loop_outcomes.py`. Landed on a new `TaskResult.sampling` field rather than `warnings` — see `d5`. |
| `t10` | partial | `delta_heartbeat()` exists, is throttled, thread-free, `step_count`-safe and proven against genuinely slow arrival — but nothing arms it on the work path, so no production run is less silent. See `d3` and #483. |
| `t11` | delivered | `docs/features/sampling.md` (471 lines) + `tests/test_sampling_docs.py` (47 tests that EXECUTE the documented claims). CLAUDE.md's fourth carve-out, `thinking-effort.md`'s retraction, live-testing row 66b. Found `d6` by reading. |
| `t12` | partial | Criteria 1, 2 and 4 PASS (rows 67/68). Criterion 3 splits: the completion half PASSES on arm 2, the reasoning-shape half FAILS at 119,602 chars against the 50,000 bar. The brief is RECONSTRUCTED, not preserved — see Remaining Work. |

## Mid-work Decisions

- `d1` — t5 criterion 5 is NOT met as literally written: tests/`test_associate_sampling.py` does not pass unchanged. Its `test_cortex_payload_is_byte_identical` asserts the CORTEX payload keeps temperature 0.0 and carries no `top_p`, on a config that resolves the served unsloth/Qwen3.8-27B-NVFP4 at the default low rung - exactly the greedy-in-thinking-mode behaviour this arc removes. Criterion 5 and criterion 2 are mutually exclusive on that one test. I kept the guarantee the test exists for (an unarmed seat sees nothing of the associate profile, still asserted) and updated only the sampling baseline, renaming it to `test_cortex_payload_carries_no_associate_leakage`. The criterion's stated REASON - the associate branch is untouched - is met in full: the other tests in the file pass unchanged and t5 added a new one proving an armed associate payload carries no `top_k` or `min_p`. — The confirmed criterion assumed a test file whose contents nobody had re-read against the change; the file turned out to pin the defect under an associate-sounding name.
- `d2` — t5 and t8 each landed a private copy of the server-default sampling table, which tripped t5's own single-write-site guard once both merged. Reconciled into a NEW leaf module colleague/samplingwire.py holding `SERVER_DEFAULT_SAMPLING`, `SAMPLING_COERCERS` and `wire_fragment`(); the adapter and the detached distill child both delegate to it. Two consequences: the guard now names samplingwire.py as the owning module, and the distill child now also drops `presence_penalty` 0.0 (a server default t8's narrower two-key table had kept) - the two sites now agree by construction, which was the point. — Parallel same-wave tasks could not import each other, so both correctly implemented and flagged the duplication rather than guessing; reconciliation was always going to be the integrator's job. Landing it in a new leaf module also honours the spec's line-140 preference over growing an existing one.
- `d3` — t10 ships a proven MECHANISM, not the delivered behaviour its criterion 1 describes. `delta_heartbeat` exists, is throttled (`COLLEAGUE_DELTA_HEARTBEAT_INTERVAL`, default 3.0s), adds no thread, never advances `step_count`, and is proven against genuinely slow arrival — but no caller arms it outside the tests, so no real run is less silent than before. The agent stated this plainly rather than claiming the criterion met, which is the behaviour I want; I am recording it rather than quietly accepting a helper nobody calls. — The composition point needs the loop's `_Work` ctx and therefore a file outside the task's confirmed ownership; wiring it mid-wave while t9 edits `loop_outcomes.py` would have been the riskier choice.
- `d4` — t7's config show sampling section rendered the matched ROW verbatim, including `min_p` 0.0 / `presence_penalty` 0.0 / `repetition_penalty` 1.0 — three keys the wire filter drops because they already equal the server default. A reader would have concluded they go on the wire. Fixed to state what actually goes out, plus a separate dropped-as-server-default clause; --json gains wire and `dropped_at_server_default` beside the existing payload. The no-row-matched line is unchanged. (RE-RECORDED as d4: this was the ORIGINAL d3 the user confirmed; its record was destroyed by an operator-side git checkout of .devague/ and the id d3 has since been taken by an unrelated t10 deviation. Shipped in commit 1e18f366.) — t7 was briefed not to import t5's work and could not see the wire filter, which only existed once both merged and were reconciled into samplingwire.py. The command whose stated job is to state the sampling match honestly is the one place this misstatement would cost the most.
- `d5` — t9's sampling record moved from TaskResult.warnings to a dedicated TaskResult.sampling field at merge time. t9's instruction said to follow effortrecord.py exactly; it could not, because effortrecord folds onto a dedicated TaskResult.effort field and adding the sampling equivalent needs contract.py + `contract_taskresult_io.py`, outside t9's file ownership. It rode warnings and said so plainly. I finished the pattern because a sampling record is not a warning, and because the default model+rung match the builtin Qwen3.8 row it made warnings unconditionally non-empty on every ordinary run - so six byte-identical shape pins had to name warnings as newly unconditional, which is a misleading thing to pin. Verified omit-when-None on `to_dict` and a clean `from_dict` round trip. — The task was correct to stop at its file boundary and flag it; completing the contract change is integrator work, not something to leave as a semantic compromise in the shipped artifact.
- `d6` — config show and the vLLM adapter disagreed about the `COLLEAGUE_SAMPLING` kill switch: the adapter disabled on any of 0|false|no|off, config show matched only the literal 0. `COLLEAGUE_SAMPLING`=off therefore sent no sampling keys while config show reported a match. `SAMPLING_ENV_KEY`, `SAMPLING_DISABLING_VALUES` and `sampling_enabled`() moved into colleague/samplingwire.py; both sites now call one predicate and the rendered line names the actual value. New test covers all four spellings plus case and whitespace variants. — Found by t11's documentation pass, which had to read both implementations to document the kill switch and noticed they did not agree. A silent divergence in the arc's own anti-silent-failure reporting surface is the least acceptable place to leave one.

## Drift From Plan

| Plan item | Reason for divergence | Classification |
|-----------|------------------------|-----------------|
| `t5` (`d1`) | The confirmed criterion assumed a test file whose contents nobody had re-read against the change; the file turned out to pin the defect under an associate-sounding name. | `acceptable` |
| `t8` (`d2`) | Parallel same-wave tasks could not import each other, so both correctly implemented and flagged the duplication rather than guessing; reconciliation was always going to be the integrator's job. Landing it in a new leaf module also honours the spec's line-140 preference over growing an existing one. | `acceptable` |
| `t10` (`d3`) | The composition point needs the loop's `_Work` ctx and therefore a file outside the task's confirmed ownership; wiring it mid-wave while t9 edits `loop_outcomes.py` would have been the riskier choice. | `needs-follow-up` |
| `t7` (`d4`) | t7 was briefed not to import t5's work and could not see the wire filter, which only existed once both merged and were reconciled into samplingwire.py. The command whose stated job is to state the sampling match honestly is the one place this misstatement would cost the most. | `acceptable` |
| `t9` (`d5`) | The task was correct to stop at its file boundary and flag it; completing the contract change is integrator work, not something to leave as a semantic compromise in the shipped artifact. | `acceptable` |
| `t7` (`d6`) | Found by t11's documentation pass, which had to read both implementations to document the kill switch and noticed they did not agree. A silent divergence in the arc's own anti-silent-failure reporting surface is the least acceptable place to leave one. | `acceptable` |

## Evidence

- tests: full suite on the branch — **11,565 passed, 51 skipped** (`uv run pytest -n auto -q`)
- tests: `tests/test_sampling_table.py` (46) · `tests/test_sampling_payload_wiring.py` · `tests/test_repetitionguard.py` (16) · `tests/test_repetition_wiring.py` (13) · `tests/test_samplingfile.py` (9) · `tests/test_distill_sampling.py` (10) · `tests/test_sampling_recording.py` (9) · `tests/test_temperature_deprecation.py` (11) · `tests/test_config_show_sampling.py` (9) · `tests/test_sampling_docs.py` (47) — all pass
- lint: `black --check` · `isort --check-only` · `flake8` · `bandit -c pyproject.toml -r colleague` — all clean
- lint: `markdownlint-cli2 docs/features/sampling.md CLAUDE.md docs/live-testing.md CHANGELOG.md` — 0 errors
- live probe (t12 c1): armed vs off-rung bodies differ in exactly `temperature`, `top_p`, `presence_penalty`, `chat_template_kwargs`; `top_k` 20 in both
- live probe (t12 c2): 3 completions at `temperature 2.0` with `top_k: 1` byte-identical (`b66a7e837e` ×3); without it, 3 distinct hashes
- live probe (t12 c4): guard first fires at 704 chars, cut at 1,056 — vs the incident's 271,486 (257× reduction)
- live arm (row 68): artifact `9a96880b64c4` `status: ok`, `loop.py` 962 → 881, affected-tests **passed**, 11,226 tests green on the result branch
- live arm (row 67): artifact `cc5d1f1a2c5f` `status: incomplete`, branch does not import — a hallucinated `Policy` symbol and a lost `ToolCall` re-export
- commits: `cc3e8479..f2abb44b` (35 commits on `reasoning-aware-sampling-479`)
- devague: 6 approved deviations (`d1`–`d6`), 8 approved evidence records (`e1`–`e8`), 4 obligations (`o1`–`o4`), 7 risks (`r1`–`r7`)
- issues filed from this run: #480, #481, #482, #483, #484 · devague#112

## Delivery Claims

| Claim | Confidence | Evidence |
|-------|------------|----------|
| A run on this rig now sends the Qwen3.8 thinking profile (`temperature 1.0` / `top_p 0.95` / `top_k 20`) instead of greedy while thinking is armed | high | live payload dump; `config show`; artifact `9a96880b64c4`'s own `sampling` block |
| An unmatched model sends no sampling keys at all — byte-identical to pre-change | high | `tests/test_sampling_payload_wiring.py` (3 pins incl. the real wire body via `COLLEAGUE_DUMP_REQUEST`); evidence `e2` |
| The served id and the card id resolve to the same builtin row; `Qwen3.8-4B` inherits nothing | high | `tests/test_sampling_table.py`; my own fresh-interpreter probe; the rig serves exactly `unsloth/Qwen3.8-27B-NVFP4`; evidence `e1` |
| `top_k` is the only vLLM extension key on the wire — the fourth carve-out stays one key | high | `colleague/samplingwire.py::SERVER_DEFAULT_SAMPLING`; `tests/test_sampling_docs.py`; `config show` output |
| `COLLEAGUE_SAMPLING=0` restores the pre-change payload key for key | high | live probe (`KILLSWITCH` line); `tests/test_sampling_payload_wiring.py` |
| A repeating stream cuts the TURN and the run continues; the third trip ends it | high | `tests/test_repetition_wiring.py` (13); evidence `e3` |
| The guard would have cut the #479 incident 257× earlier | high | live probe: first detection at 704 chars vs 271,486; evidence `e7` |
| A pre-arc operator config resolves to the same values this release | high | `tests/test_temperature_deprecation.py` (11); two fresh-interpreter probes; evidence `e4` |
| The rig honours `top_k` at the moment of measurement, so a green sampling result is not a rig ignoring the key | high | the discriminator, 3+3 completions; evidence `e6` — filed at `sensitivity` because its first form was falsified and fixed |
| Sampling bounds PER-TURN reasoning length | medium | no turn in rows 67/68 hit `finish_reason=length`; but n=1 per arm and no `COLLEAGUE_SAMPLING=0` control was run |
| Sampling reduces TOTAL reasoning spend | unverified | contradicted, if anything: arm 2 spent 413,134 chars — 3× the failing incident — with sampling armed |
| The card profile is why the arc's live arm completed | unverified | arm 2 differed from arm 1 only in step budget; no control isolates sampling from the #475 rung change |
| A long turn reports liveness while it runs | unverified | `t10` shipped a mechanism nothing arms — see `d3`, #483 |

## Remaining Work / Follow-up

- `t10` — `delta_heartbeat` is unwired; no production run gained liveness. **#483** carries the finding that the last mile is smaller than the task assumed: headless streaming is already on by default, so arming a sink does not flip the transport. The obstacle is placement (`_Work` ctx), not risk.
- `t12` — criterion 3's reasoning-shape half FAILS (119,602 chars vs the 50,000 bar) and the arc has **no clean measurement of sampling's marginal effect** over the #475 rung change: rows 66, 67 and 68 all sit at `low`, and row 66 (the intended `low`+greedy control) was SIGTERM'd. The missing control is a `COLLEAGUE_SAMPLING=0` run at 90 steps on the same brief.
- The t12 brief is **RECONSTRUCTED**, not preserved — colleague stores only `prompt_digest`. The six pins were recovered from the incident run's own first grep and each verified against a real test, but the prose is mine, so neither arm compares like-for-like to the recorded 2,851 s / 506 s baselines. **#481** proposes persisting the brief.
- **#480** — a budget-exhausted run's affected-tests gate reports `failed` and the result reaches neither `TaskResult.warnings` nor the operator. Verified: re-running the gate against row 67's branch returns `failed`, so the harness knew the branch was broken while the model reported "UNVERIFIED, I did not run pytest".
- **#482** — a millisecond-cost pre-finish importability check would have named both of row 67's defects directly.
- **#484** — effort spikes on an enumerated surface. Measured basis: 74% of arm 2's reasoning went to turns that were *acting*, not deciding — at `low`, so it is a placement problem no global rung setting fixes.
- **devague#112** — the five behavioural-validation resolve flags take one id at a time; batch adjudication of `d1`–`d6` and `e1`–`e8` needed a shell loop.
- Operator-side: `.colleague/models.json` ships no rows by default. An operator wanting per-seat sampling needs a role level the file format does not have (rows resolve with `role=None`), and `config show` renders the **builtin table only** (`r7`), so an operator override shows one thing and sends another.
