# Review — delegation-follow-ups-a7-p3-hire

> **Review artifact — nothing confirmed yet.** These are unconfirmed, LLM-proposed items; they are NOT authoritative and NOT a buildable spec. To apply, change a line's `pending` to `confirm` or `reject`, then run `devague confirm --from-review <file>` (or `devague confirm <id> ...`).

## Proposed claims

- pending `c2` (requirement): A7: run docs/live-testing/briefs/arm-large-surface.md with BOTH the raw subagent/subagents pair AND the six purpose tools on the acting seat, n=3, baseline A5 (row 57, 2/3 delegating, wall mean ~586 s); the row is pre-registered before the first run and its delegation cell is broken down BY TOOL NAME, read off artifact step tool names, never prose
  - instruction: verify: row 59's verdict sentence contains the qualification
- pending `c34` (requirement): The arms PR records the depth-0 OFFERED tool names on TaskResult (an offered_tools list, omit-when-None beside prompt_digest) so that A7's 'both halves on the seat' condition (h2) is read from the artifact — today neither COLLEAGUE_ACTING_DROP_TOOLS nor the offered list is persisted anywhere (grep: no reference outside actingsurface/prompttext/tools comments; row 56 recorded the drop knob's absence by hand and a GAP for the offered lists)
  - instruction: verify: python one-liner over .colleague/<id>.json in the row
- pending `c35` (assumption): Under A7 the raw subagent schema (tools.SCHEMAS) exposes context_mode/effort/engine/model/profile/role — the model may pick a role, rung, engine or model per call, exactly what the purpose spec's c24/h27 removed. The A7 row records, per raw call, the role/effort/engine/model arguments the model chose; a raw call naming an engine or model is a finding in its own right, not noise
  - instruction: verify: the table or the line is present in row 59
- pending `c36` (assumption): The overlays are effort-neutral: colleague.effort.ROLE_TABLE['writer'] == 'medium' and every overlay's effort line is 'medium', so P2-0/P3 versus A5/A7 differ in prose only, never in rung — a P3 result cannot be a hidden effort effect
  - instruction: verify: assert ROLE_TABLE['writer']=='medium' in the row's preflight and paste each overlay's first line
- pending `c37` (requirement): hire_colleague and assign_to_colleague stay OUT of toolbatch.CONCURRENCY_SAFE_TOOLS (toolbatch.py:92) and serialize like the six purpose tools (purpose-tools.md honest limit v2); a model batch that mixes them with read-only calls runs the read-only part in the pool and the hire/assign part on the main thread, in request order
  - instruction: verify: tests/test_hire.py::test_not_batch_safe
- pending `c38` (requirement): Refs, not payloads: a hire's ledger event (when agents is armed) carries the authored prompt's digest and a ref to the artifact, never the text — the ledger refuses lines over MAX_EVENT_BYTES 4096 (agents/state/ledger.py:82); the text itself lives on TaskResult.hires. The tool schema caps the authored prompt (<= 2000 chars) and the when clause (<= 200 chars); over-cap = a readable refusal, no hire
  - instruction: verify: tests/test_hire.py::test_caps_and_ledger_refs
- pending `c39` (assumption): A hired scout holds web, deepthink and memory (BUILTIN_ROLES['scout'].tool_allowlist), so an authored prompt can direct URL fetches (the read-then-fetch channel already accepted under trusted-operator D2 for purpose children), spend deepthink, and write the shared eidetic store via memory remember. The same D2 acceptance extends to hires: an assignment's web calls fold into the parent's budget and stats.web_calls exactly as a purpose child's do (webbudget.fold_child_counts), its fetched urls list on the tool result, and a memory record written by a hire carries the hire's agent id as provenance
  - instruction: verify: tests/test_hire.py::test_web_folds_like_purpose
- pending `c40` (requirement): All-engines: TaskResult.hires (and the negotiation) hold on mock identically to vllm-openai — the mock engine answers the candidate turn deterministically (accept unless the proposed purpose contains a 'decline' marker) so the bounded-negotiation and caps tests run rig-free, and tests/test_e2e_mock.py's result-shape parity extends to the hires block
  - instruction: verify: pytest tests/test_e2e_mock.py tests/test_hire.py without COLLEAGUE_VLLM_E2E
- pending `c41` (requirement): When COLLEAGUE_HIRE is armed the hire pair joins agents/tools.THINKER_CODER_TOOLS / ASSOCIATE_TOOLS (agents/tools.py:161-166) — otherwise the armed-agents seat's effective_tools intersection silently drops them — and joins _NOT_INHERITABLE (:88) alongside the purpose tools; tests/test_agents_tools.py pins both
  - instruction: verify: tests/test_agents_tools.py additions
- pending `c42` (requirement): COLLEAGUE_HIRE and COLLEAGUE_ACTING_ADD_TOOLS appear in colleague config show and as config events on the artifact (contract.config_digest_for), so a byte-identical or arm claim is attestable from the artifact rather than from the shell that launched the run
  - instruction: verify: tests/test_config_show + a digest inequality test

## Proposed honesty conditions

- pending `h20` (on `c2` requirement): A7's reading is QUALIFIED verbatim: with the raw pair undescribed in prose (c4), 0 raw calls + N code_survey calls supports 'cortex chose code_survey while subagent was offered but undescribed' — never a bare 'cortex prefers code_survey'; only a matrix where the raw pair is also described could support the bare form
- pending `h18` (on `c34` requirement): Every A7/P3/P2-0 artifact carries offered_tools; the A7 ones contain subagent, subagents and all six purpose names; the P3/P2-0 ones contain no raw pair — checked by a script over the 9 artifacts, pasted in the rows
- pending `h19` (on `c35` assumption): The A7 row has a per-raw-call table of (role, effort, engine, model) arguments, or the line 'no raw call occurred' — never omitted
- pending `h21` (on `c37` requirement): A test asserts neither name is in CONCURRENCY_SAFE_TOOLS and that a mixed batch executes the hire/assign step outside the pool
- pending `h22` (on `c38` requirement): A test hires with a 2001-char prompt and asserts the readable refusal + empty roster; a test under COLLEAGUE_AGENTS=1 asserts the ledger line has no prompt text and is under 4096 bytes
- pending `h23` (on `c39` assumption): An assignment that fetches two urls leaves the parent's stats.web_calls +2 and the tool result ending with a 'urls fetched:' block — the purpose-child test pattern re-run against a hire
- pending `h24` (on `c40` requirement): test_e2e_mock's shape check passes with a hires block present on both engines' artifacts; h9 runs on mock alone
- pending `h25` (on `c41` requirement): Under COLLEAGUE_AGENTS=1 COLLEAGUE_HIRE=1 the thinker_coder effective surface contains both names; under COLLEAGUE_AGENTS=1 alone it contains neither; a talker profile with either name is refused by validate_profile_tools
- pending `h26` (on `c42` requirement): config show --json lists both knobs (value or unset) and two artifacts that differ only in COLLEAGUE_HIRE differ in config_digest
