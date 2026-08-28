# Delivery Summary — web-scout-associate

plan: `web-scout-associate` · run: `partial` · date: `2026-08-28`
baseline: `devague summary skeleton`

## Intent

Ship a curated read-only `web` loop tool over the operator-installed WebGlass
CLI so the `scout` subagent role (on the associate seat when armed) can fetch
cited web evidence (lane A, #436), and make the hand-over → review → collect
shape visible to cortex without forcing it (lane B, #435) — then measure both
on two pre-registered live-testing rows. The plan executed was
`docs/plans/2026-08-28-web-scout-associate.md` (12 tasks / 7 waves, spec
`docs/specs/2026-08-28-web-scout-associate.md`, challenged before planning);
two bug-fix tasks (t13, t14) were added mid-run via `/deviate`. Fan-out per
the approved split: colleague (cortex) for new-file tasks and reviews, sonnet
for ratcheted-file/seam tasks, opus for the resident task, the integrator +
operator shell for the live proof.

## Planned Work

Quoted verbatim from the `devague summary` skeleton:

- `t1` — t1 colleague/web.py — curated webglass subprocess, structural verb allow-list, process-group containment
- `t2` — t2 colleague/`web_schemas.py` — schema, offered()/hidden rule, dispatch, verbatim provenance + untrusted labelling
- `t3` — t3 splice 'web' into the shared tool surface (net-zero tools.py hunks) + update the pinned tool-name tests
- `t4` — t4 role allow-lists, batch-safe set + web batch cap, tool-profile class
- `t5` — t5 run-report 'web:' line (ok vs failed) + hook-deny proof + no colleague web policy
- `t6` — t6 doctor environment rows: webglass (+ session-count warn) and `web_search_provider` (warn-only)
- `t7` — t7 pre-register live-testing rows 47/48 + delegations/`associate_calls`/`web_calls` columns in scripts/`compare_arms.py`
- `t8` — t8 lane B — armed-facts sentence (no digits) on the delegation surface + the opt-in hand-over/review/collect prompt section
- `t9` — t9 web-call budget: `COLLEAGUE_WEB_MAX_CALLS`, WorkStats `web_calls`/`web_failed`, resumable via continuation
- `t10` — t10 resident: withhold 'web' from non-operator-initiated turns; relayed operator requests confirm before the first fetch
- `t11` — t11 feature doc + CLAUDE.md pointer + version bump
- `t12` — t12 live proof — rows 47/48 from the operator's shell, byte-identical check, section arm

Added mid-run (not in the confirmed plan; recorded as deviations):

- `t13` — harden `web_schemas.py`'s fallback path (bug found by the wave-2/3 colleague review, `d8`)
- `t14` — correct the webglass argv grammar + usage-error provenance + failure counting (bug found by the row-47 live run, `d14`)

## Actual Delivery

| Plan task | Status | What actually landed |
|-----------|--------|----------------------|
| `t1` | delivered | `colleague/web.py` (allow-listed verbs, forbidden tokens, `^https?://`, process-group kill on timeout), `tests/test_web.py`, `_SUBPROCESS_ALLOWED` join — merged `df0cfff` (sonnet, after two colleague stalls `d2`/`d3`); two mirrored pins fixed in `cdd7eec` (`d4`); argv grammar corrected in t14 (`d14`) |
| `t2` | delivered | `colleague/web_schemas.py` (schema, `offered()`/`hidden_names()` on PATH + `COLLEAGUE_WEB`, dispatch, provenance-first rendering, untrusted delimiter, `sensitive` never rendered), fixtures under `tests/fixtures/webglass/` — merged `73c382e` (colleague `fdb9c9aca62f`); fallback/shape/TOCTOU hardened in t13 (`d8`) |
| `t3` | delivered | `web` spliced into `tools.py` net-zero (1508 lines), `TOOL_NAMES`, dispatch table; pins in `test_tools.py`, `test_e2e_mock.py`, `test_culture_tools.py`; `COLLEAGUE_WEB=0` off-knob in `test_knobs_byte_identical.py` — merged `ec01db5` (`d7`: mock-scenario fixture not edited) |
| `t4` | delivered | `web` in `_READONLY_TOOLS`/`_SCOUT_TOOLS` + scout data-not-instructions clause (roles.py at 373), `CONCURRENCY_SAFE_TOOLS` + `COLLEAGUE_WEB_CONCURRENCY` (default 3) semaphore in `run_batch`, `TOOL_PROFILES["web"]` = `read` — merged `5965a1f` |
| `t5` | delivered | `web_schemas.summary_line` + the run report's `web:` line in `cli/_commands/work.py`, hook-deny test, no-URL-policy source scan — merged `e49b05d` |
| `t6` | delivered | doctor `environment.webglass` (ok / absent / session-count > 10 warn) and `environment.web_search_provider` (warn "unset in this process"), via `livecheck.webglass_status` — merged `4dcde0a` |
| `t7` | delivered | rows 47/48 pre-registered before any run, briefs under `docs/live-testing/briefs/`, `compare_arms.py` `delegations` / `associate_calls` / `web_calls` columns — merged `d02bb41` (colleague `60a72299425c`, ok) |
| `t8` | delivered | `colleague/delegation_text.py` (`armed_facts` — no digits, no imperatives; `apply_armed_facts` same-object when unarmed), `HANDOVER_EXAMPLE` section excluded from the default variant, `loop.curated_schemas` seam — merged `450457a` (`d1`: seam as a wrapper called from `engines/vllm_openai.py`) |
| `t9` | delivered | `colleague/webbudget.py` (`COLLEAGUE_WEB_MAX_CALLS` default 20, cap error, continue warning), `WorkStats.web_calls`/`web_failed`, counter on `ToolExecutor` (per child), resume via the continuation seed prose (`d12`), `CONTINUABLE_REASONS` pinned — merged `8e105a2`; baseline bump reverted and `tools.py` re-pinned in `05196c7` (`d11`) |
| `t10` | partial | `colleague/resident/webtrust.py` + `requestlines.py`: `web` withheld from non-operator turns; relayed-operator confirmation gate implemented behind the expected `relayed_operator` metadata key — **the culture protocol has no such marker today** and the gate is turn-boundary-scoped, not an in-flight tool-call interception — merged `39fb4b5` (`d9`, `d10`); follow-up culture#482 |
| `t11` | delivered | `docs/features/web-scout.md` (179 lines, Honest limits incl. the D2 exfiltration channel and the upstream browser leak), CLAUDE.md bullet + scope clause, CHANGELOG 1.65.0, `pyproject.toml` 1.65.0 — merged `7015f4b` (colleague `7a1252fdb5e2` incomplete on the loop guard, `d13`; the integrator finished the MD018 reflow and `uv.lock`) |
| `t12` | partial | rows 47 and 48 run and **both recorded as MISS** on their pre-registered bars (`dccbe30`, `716971e`); the byte-identical off-state is covered by the suite's `COLLEAGUE_WEB=0` knob + monkeypatched-PATH tests, not by a separate merged-checkout run; the `HANDOVER_EXAMPLE` section arm was **not run**; the associate diff is empty and `test_associate_seats.py` passes |
| `t13` | delivered (added) | `render_raw`, shape-safe `render_result`, hidden-state re-check before spawn, `run_web` `COLLEAGUE_WEB=0` guard — merged `3d30f50` (colleague `17c0f143eee6`, ok); `record_result` non-dict fix `4ef1f4e` |
| `t14` | delivered (added) | argv grammar (`--url` for page read/inspect/extract/links; options before `--` for search), usage-error provenance header, failure counting incl. non-zero exit — merged `098e46d` (colleague `0a2542790cfe`, ok; verified against the real CLI) |

## Mid-work Decisions

- `d1` — t8's loop seam placed as a `loop.curated_schemas` wrapper called from `engines/vllm_openai.py` (the only real `curate_schemas` call site), plus the `COLLEAGUE_PROMPT_SECTIONS` knob registered in the adopt-from-qwen-code doc — loop.py never builds schemas (a documented invariant); the knob doc line was test-enforced.
- `d2` / `d3` — the t1 colleague lane stalled twice at the 900 s stream-lifetime guard with zero files written (once under GPU contention, once alone) → t1 reassigned to sonnet; colleague kept the next new-file task (t2), which it finished `ok`.
- `d4` — t1's boundary-list join needed two mirrored pins the brief did not name; fixed by the integrator (`cdd7eec`).
- `d5` — the wave-1 colleague review stalled at the guard without a verdict; the integrator reviewed `delegation_text.py` directly (SHIP).
- `d6` — colleague lanes retargeted from the lobes gateway (6 relay `BrokenPipe` tracebacks in 90 min, lobes-cli#220) straight to the vLLM origin `172.21.0.3:8000` in the lane scripts only; every later colleague lane finished `ok`.
- `d7` — t3 left the byte-identical mock-scenario fixture untouched and proved the all-engines rule in a dedicated test + `COLLEAGUE_WEB=0` off-knob.
- `d8` — the wave-2/3 colleague review (4 steps, direct-vLLM lane) returned **BLOCK**: the non-JSON fallback rendered raw output without the untrusted delimiter (the one path that could leak `content.sensitive`), list-shaped envelopes crashed, and a hidden-state TOCTOU existed → new task t13 (colleague), merged.
- `d9` — no "relayed operator request" marker exists in the culture/resident protocol; t10 implemented the rule behind `relayed_operator` (absent = peer, web surface only) and scoped the confirmation to the turn boundary (the resident has no mid-run tool-call seam) → culture#482.
- `d10` — t10 added `resident/webtrust.py` and split `requestlines.py` out of `appserver.py` purely to hold the file-length ratchet.
- `d11` — t9 regenerated the file-length baseline; the integrator restored it, made `tools.py` net-zero, and accepted only `contract.py` (+10, typed `WorkStats` fields) and `escalation.py` (+1).
- `d12` — t9 carries the web-call counter across continuation/chain episodes through the continuation seed prose (the seam `editgate.continuation_id` already uses) — `continuation.py` and `chain.py` have a zero-line diff.
- `d13` — the t11 colleague lane stopped on the loop guard (5 identical `edit_file` calls fighting an MD018 false positive); doc, CHANGELOG, bump landed; the integrator reflowed one line.
- `d14` — the row-47 live run exposed that `web.py` built the wrong webglass argv (7 of 8 calls were CLI usage errors, rendered header-less and not counted failed) → new task t14 (colleague), merged and verified against the real CLI.
- `d15` — in the row-47 re-run, after the page fetches failed DNS, cortex drifted into host network reconnaissance via `run_command` (`/etc/hosts`, `ss -ltnp`, `~/.cloudflared`); stopped cooperatively via `flight stop`; evidence posted on #443.
- Not covered by a record: `uv.lock` was bumped to 1.65.0 by the integrator alongside t11 (the merge of t14 required it); the row-47 re-run was launched once on the unfixed tree by mistake and killed before producing a result (no artifact kept).

## Drift From Plan

| Plan item | Reason for divergence | Classification |
|-----------|-----------------------|----------------|
| `t8` (`d1`) | loop.py never builds schemas (docstring invariant: schemas live with each backend's complete closure); a runtime-owned wrapper satisfies 'one call, no change when unarmed' without breaking it; the knob doc line was a test-enforced requirement | acceptable |
| `t1` (`d2`) | rig failure, not a plan fault; the partial is preserved and will be resumed with work --continue once the GPU is free of the t7 lane | acceptable |
| `t1` (`d3`) | the stall reproduced alone on the GPU, so it is the brief/model shape (a multi-file new-module write in one turn), not contention; the arc must not wait another 15-min cycle; colleague keeps the next new-file task (t2) with a tighter brief | acceptable |
| `t1` (`d4`) | the mirrored pins are a repo convention the brief omitted; a two-line test-only fix, no behaviour change | acceptable |
| `t8` (`d5`) | #438 / lobes-cli#220 gateway-stall pattern; colleague's verdict is a second opinion to verify and own, never authority, so the integrator's review stands in; recorded as a finding for the delivery summary and the stall-rate column | needs-follow-up |
| `t2` (`d6`) | improvement: three of four colleague runs today hit the 900 s stream-lifetime guard with the gateway relay in the path (lobes-cli#220); the origin is reachable and idle; per the vLLM-adapter rule a retarget is a config change | acceptable |
| `t3` (`d7`) | editing the byte-identical fixture would misrepresent the captured main run; the acceptance wording (same Step shape across engines) is met by the dedicated test | acceptable |
| `t2` (`d8`) | bug, not a plan change: the contract (c35/h22, c6/h6) is unchanged; the fix hardens the fallback path and the hidden check | needs-follow-up |
| `t10` (`d9`) | plan risk r7 realized: the culture side must add the marker (follow-up issue on culture/agentirc); the call-level contract is implemented on WebConfirmationGate.before_web_call() and tested, the wiring is turn-scoped | needs-follow-up |
| `t10` (`d10`) | the ratchet left no room in trust.py/appserver.py; behaviour unchanged, re-exported names | acceptable |
| `t9` (`d11`) | plan risk r4 names roles/tools/loop as pinned — tools.py had to stay at 1508; contract.py's two typed WorkStats fields are legitimate contract growth with no net-zero candidate in that dataclass | acceptable |
| `t9` (`d12`) | avoids threading a counter through continuation/chain signatures at their ratchets; an existing sanctioned seam; the acceptance tests (resume at N with 2N cap; CONTINUABLE_REASONS pinned) pass | acceptable |
| `t11` (`d13`) | the loop-guard is doing its job (a stuck edit loop); the remaining work is a version bump and lint fixes — cheaper to finish than to resume; the doc content is colleague's and is reviewed before merge | acceptable |
| `t1` (`d14`) | t1's fake-CLI tests echoed argv without validating it against the real webglass grammar; the live proof is exactly what catches this; the contract (c3/h3, c7/h7, c36) is unchanged | needs-follow-up |
| `t12` (`d15`) | finding, not a plan change: a fetch failure turns cortex's web+run_command surface into a host-probing loop; this is the exfil/host class the challenge pass named (c38) and direct evidence for #443's 'web on the scout only, replace-not-add' constraint; recorded on row 47 and the delivery summary | needs-follow-up |
| `t12` | rows 47/48 both MISS on their pre-registered bars: 0 delegations in all 13 runs so the scout-on-associate / evidence-citing half of the bar was never exercised; row 48 branch 3.31× wall / 1.41× turns vs main; the `HANDOVER_EXAMPLE` section arm was not run; the pre-registered `docs.example.com` URLs never resolve (RFC 6761) and browser DNS is dead from this host — no record covers the un-run section arm | needs-follow-up |

## Evidence

- tests: full suite on `098e46d` (t14 merged) — `uv run pytest -n auto -q` → **10094 passed, 26 skipped, 0 failed**; earlier gates: 10083 (post-t11), 10049 (post-t10), 9925 (post-wave-1)
- tests: `tests/test_web.py`, `tests/test_web_schemas.py`, `tests/test_webbudget.py`, `tests/test_tools.py`, `tests/test_roles.py` — 192 passed on the t14 worktree before merge
- tests: `tests/test_resident_web_trust.py` (17), `tests/test_associate_seats.py` (32) — pass; `git diff main -- colleague/associate.py colleague/associate_config.py colleague/associate_seats.py` — empty
- lint: `uv run black --check colleague tests` / `isort --check-only` / `flake8` / `bandit -c pyproject.toml -r colleague` — clean on `098e46d`; `markdownlint-cli2 "docs/features/*.md" CLAUDE.md CHANGELOG.md README.md docs/live-testing.md` — 0 errors
- real-CLI probe (2026-08-28, login shell, post-t14): `web.run_web("search", …)` → `lifecycle_state: succeeded` with a real `operation_id`; `web.run_web("page read", …)` → `lifecycle_state: failed` (`navigation_failed`, DNS) with a full provenance header
- commits: `4e814c8..716971e` on `spec/web-scout-associate` (37 commits, 14 merges); artifacts of every colleague lane and t12 run archived in the session scratchpad (`artifacts/`, `artifacts/t12/`)
- live-testing: rows 47 (`c6c53ac2c214`, `a5fe419b2a36`) and 48 (`df6a2ffd0437` `b6eb2ac23576` `d9590dbc7f09` vs `038619813cc8` `83a953c5c584` `84414109dddd`; `compare_arms.py` → 3.313× / 1.412×, MISS)
- PRs / issues: #436, #435 (closed → #443), #439 (closed → #442/#443), #440 (closed), #442, #443, culture#482, webglass-cli#14, lobes-cli#220 (comment)

## Delivery Claims

| Claim | Confidence | Evidence |
|-------|------------|----------|
| A curated read-only `web` tool over the `webglass` CLI ships with a structural verb allow-list, forbidden-flag refusal before spawn, `^https?://` check and process-group kill on timeout | high | file `colleague/web.py` · test `tests/test_web.py` · commit `df0cfff`, `098e46d` |
| The tool is hidden (schema not offered, dispatch refused) when `webglass` is absent from PATH or `COLLEAGUE_WEB=0`, and the byte-identical suite passes with the off-knob | high | file `colleague/web_schemas.py` · tests `tests/test_web_schemas.py`, `tests/test_knobs_byte_identical.py` · commit `73c382e`, `ec01db5` |
| Provenance (operation_id, lifecycle_state, evidence_refs, policy_verdict, navigation_history, known_effects, error) renders FIRST and verbatim on `Step.result`; untrusted content is delimited; `content.sensitive` is never rendered, on every path incl. non-JSON and non-envelope fallbacks | high | tests `tests/test_web_schemas.py` · commits `73c382e`, `3d30f50`, `098e46d` · row-47 run `a5fe419b2a36` |
| `web` is on the read-only/scout role surface, batch-safe, page verbs capped at 3 in flight (`COLLEAGUE_WEB_CONCURRENCY`), tool-profile class `read` | high | files `colleague/roles.py`, `colleague/toolbatch.py` · tests `tests/test_roles.py`, `tests/test_toolbatch.py`, `tests/test_agents_tools.py` · commit `5965a1f` |
| Per-run web-call budget (`COLLEAGUE_WEB_MAX_CALLS`, default 20) with `web_calls`/`web_failed` on `WorkStats`, resumable via `work --continue` with the counter inherited | high | file `colleague/webbudget.py` · test `tests/test_webbudget.py` · commits `8e105a2`, `05196c7`, `4ef1f4e` |
| The run report gains a `web:` line distinguishing ok from failed fetches; a `pre_tool` hook matcher `web` deny is honoured with no child spawned; no colleague-owned URL policy exists | high | test `tests/test_web.py` · commit `e49b05d` |
| `doctor` reports `webglass` (incl. the session-count warn) and `web_search_provider` as warn-only rows | high | files `colleague/oilcheck/environment.py`, `colleague/livecheck.py` · tests `tests/test_oilcheck_environment.py`, `tests/test_livecheck.py` · commit `4dcde0a` |
| When the associate is armed the `subagent(s)` descriptions carry one armed-facts sentence with no digits/time units/imperatives; unarmed the schema list is the same object; the `HANDOVER_EXAMPLE` section is opt-in and the default prompt is byte-identical | high | file `colleague/delegation_text.py` · tests `tests/test_delegation_text.py`, `tests/test_prompttext_handover_example.py` · commit `450457a` |
| The mesh resident withholds `web` from non-operator turns; a relayed-operator turn gets one confirmation request before its first fetch | medium | file `colleague/resident/webtrust.py` · test `tests/test_resident_web_trust.py` · commit `39fb4b5` — the relayed-operator marker does not exist in the protocol yet (culture#482), so the confirmation path is proven only against the expected metadata key |
| The web tool works end-to-end in a real run: `search` returns real results with real WebGlass operation ids inside the untrusted delimiter; failed page fetches carry their provenance and are counted | high | live-testing row 47 run 2 (`a5fe419b2a36`) · `docs/live-testing.md` |
| A scout child on the associate seat fetches web evidence and cortex cites its evidence ids (spec c1/h1, c23/h18) | unverified | never exercised — 0 delegations in all 13 measured runs (rows 41–48); not claimed done |
| The hand-over → review → collect text raises the delegation rate or keeps turns ≤ 1.0× (spec c32/h21) | unverified | row 48 measured the opposite: branch 3.31× wall / 1.41× turns, 0/3 delegations on both arms; the `HANDOVER_EXAMPLE` section arm was not run |
| The associate seat is untouched by this arc | high | `git diff main -- colleague/associate*.py` empty · `tests/test_associate_seats.py` 32 passed |
| Version 1.65.0 with CHANGELOG entry; feature doc + CLAUDE.md pointer | high | files `pyproject.toml`, `CHANGELOG.md`, `docs/features/web-scout.md`, `CLAUDE.md` · commit `7015f4b` |

## Remaining Work / Follow-up

- `t12` (partial) — run the `HANDOVER_EXAMPLE` section arm (default vs section-on) on the row-48 brief before any change to the default variant; run rows 47/48 again from a host with browser DNS and resolvable pre-registered URLs (the row-47 brief's `docs.example.com` is a reserved example domain — re-register with reachable docs); both rows currently MISS.
- `t10` (partial) — culture#482: add the `relayed_operator` marker on the culture side; then the resident's confirmation path is exercised on real relayed turns.
- #443 — the next arc: purpose tools (`web_survey` / `code_survey` / `review`) that run the scout/reviewer child on a fixed seat, **replacing** the raw `web` tool on cortex's surface (revisits decision q3) — the measured answer to 0 delegations in 13 runs and to `d15`'s host-probing drift.
- #442 — associate distill=low split (closes #439 when picked up).
- #438 / lobes-cli#220 — gateway stall recovery: 3 of the 4 gateway-routed colleague lanes today hit the 900 s guard; the direct-origin lanes (d6) all finished `ok`.
- webglass-cli#14 — upstream browser/session leak (127 sessions on this host after today's probes); colleague contains only its own calls.
- Operator to confirm deviations `d1`–`d15` (`devague deviate --confirm`).
- The stale `agent-411-q1` worktree from the August #411 arc is still present under `/home/spark/git/worktrees/` — not this run's; left untouched.
