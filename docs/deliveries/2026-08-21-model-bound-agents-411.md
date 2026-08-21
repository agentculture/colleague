# Delivery Summary — model-bound agents (#411)

plan: `model-bound-agents-411` · run: `complete (experiment arms pending)` · date: `2026-08-21`
baseline: the confirmed 23-task / 7-wave plan `docs/plans/2026-08-21-model-bound-agents-411.md`

## Intent

Land the eleventh sanctioned increment at colleague's router-exclusion line:
explicit, attributable agents bound to lobes roles (typed `AgentProfile`,
per-invocation identity + context manifest + tool-surface digest), cross-role
subagents that only narrow, typed agent-to-agent messages, the append-only
task ledger + per-agent reconstruction, continuation that rehydrates from the
ledger, the Talker/Worker/Thinker-Coder reference topology by role — with the
non-coding worker **dormant** and the fast-coder `associate` reserved (d3) —
and a **recorded cortex fallback** wherever a role is absent (today's rig),
plus the seam hardening the complexity doctrine demanded first (#410 SIGTERM
artifact, #400 step-stall watchdog, truncated-turn lane).

## Before-state evidence (c3 / h4)

Reproduced in this session against the live gateway BEFORE any change, with
`three_tier: true` still armed in BOTH `.colleague/config.json` and
`~/.colleague/config.json`:

```text
$ uv run colleague config show
error: three-tier execution is armed (three_tier) but the lobes gateway
'http://localhost:8001' advertises no ready worker role
hint: arm a ready worker role on the lobes gateway, or unset three_tier
```

and `doctor` → `[FAIL] provider_config: … the worker role could not be
resolved`. The 2026-08-21 `/capabilities` dump is committed verbatim as
`tests/fixtures/capabilities-2026-08-21.json` (cortex `unsloth/Qwen3.8-27B-NVFP4`
ready — context re-advertised 131072 → 1,048,576 during the day; senses
`gemma-4-12B` ready; **worker `NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4`
advertised, `ready: false`**; no `associate`; muse/stt/tts not ready). That
advert drives `tests/test_agents_fallback.py` (t20) and `tests/test_doctor_agents.py`.

## Pre-registered bars for the matched experiment (c45 / h32) — committed BEFORE the arms run

Brief: the self-playable game benchmark recipe (`~/.colleague/commands/game-benchmark.md`,
the same brief the 2026-08-20 two-arm benchmark used), same rig, same day,
`COLLEAGUE_MAX_STEPS=60`, streaming on, no flight guidance unless a run is
provably wedged (then recorded as a correction).

| arm | configuration |
|---|---|
| A — solo cortex (legacy) | `agents` unset, `three_tier` unset; cortex `unsloth/Qwen3.8-27B-NVFP4` |
| B — agents mode | `agents: true`; same cortex; worker/associate absent → recorded fallback; the brief asks for ONE `associate` subagent (`context_mode: clear`) for the test file |

Measures recorded for BOTH arms: completion (`status`), quality (the
benchmark's own grade: tests pass + skill gradient greedy > random > passive),
wall-clock latency, tokens per model (exact `usage`), tool calls per model,
escalation/delegation rate (delegations ÷ model turns), invalid tool calls
(`ToolError` count), corrections (guidance injections + truncated/stalled
turns), and for B the manifest ratio (max `token_estimate` ÷ 1,048,576).

Promotion bar (agents mode becomes a documented default candidate ONLY if ALL
hold): B completes `status: ok`; B's grade ≥ A's grade; B's wall-clock ≤ 1.5 × A's;
B's total tokens ≤ 1.25 × A's; B's invalid tool calls ≤ A's; B's corrections
≤ A's + 1; every B invocation attributed (100 %); manifest ratio < 0.5.
Any miss → the mode stays **opt-in** and the row records both arms unspun
(the 2026-08-20 precedent: a falsifying outcome is recorded, never re-argued).

## Planned Work

Quoted from the plan (23 tasks, 7 waves): t1 profile · t2 tools · t3 messages
· t4 ledger · t5 #410 · t6 #400 · t7 `agents` opt-in · t8 truncated turn ·
t9 runtime · t10 context · t11 delegation · t12 guidance · t13 artifact block ·
t14 cross-role subagents · t15 loop wiring · t16 talker · t17 continuation ·
t18 guards + ratchet · t19 ledger location/reap · t20 fallback proof · t21
continuity regression · t22 docs · t23 live proof.

## Actual Delivery

| Plan task | Status | What actually landed |
|-----------|--------|----------------------|
| t1 | merged | `colleague/agents/profile.py` (+ `associate` purpose, `DORMANT_PURPOSES`, d3) — colleague-built |
| t2 | merged | `colleague/agents/tools.py` — Claude-built in parallel (d5); colleague's run stalled 70 min with nothing written |
| t3 | merged | `colleague/agents/messages.py` + `MAX_AGENT_MESSAGES` — colleague-built |
| t4 | merged | `colleague/agents/state/ledger.py` (43 tests) |
| t5 | merged | #410 — `colleague/salvage.py` + the 2-line loop seam (d1); live-proven twice this session (t9 and t20 SIGTERM salvages wrote the artifact and the WIP commit) |
| t6 | merged | #400 — `colleague/stallguard.py`; floor 5400 s (d2/d4) |
| t7 | merged | `agents` opt-in, three-way mutual exclusion, `doctor` `agents` group, `config show` line |
| t8 | merged | truncated-turn lane (`context.TruncatedTurn`) |
| t9 | merged | `colleague/agents/runtime.py` — colleague-built; its synthesis turn was cut by SIGTERM after 60 min and integrated from the salvaged WIP |
| t10 | merged | `colleague/agents/state/context.py` |
| t11 | merged | `colleague/agents/delegation.py` — colleague-built |
| t12 | merged | `colleague/agents/guidance.py` — colleague-built |
| t13 | merged | `TaskResult.agents` + `agents/artifact_block.py` + engine floor + mock parity |
| t14 | merged | cross-role subagents, `context_mode`, delegate/return events, `LobesRoles.associate` |
| t15 | merged | loop wiring (seam calls; bodies in `runtime.AgentsRun`) |
| t16 | merged | talker records (`agents/talker.py`), `guide_cortex` → `operator_input`, talker surface refusal |
| t17 | merged | continuation rehydrates from the ledger |
| t18 | merged | `tests/test_agents_boundary.py` + `tests/test_file_length_ratchet.py` + baseline (d6) — colleague-built |
| t19 | merged | ledger at the operator repo + `clean` reaps ok-only ledgers (resumable runs keep theirs) |
| t20 | pending | fallback proof on the saved advert — colleague run cut at 50 min, **resumed** with `work --continue` |
| t21 | merged | `tests/test_agents_continuity.py` + `tests/_agents_audit.py` |
| t22 | merged | `docs/features/model-bound-agents.md`, CLAUDE.md eleventh increment, CHANGELOG, v1.61.0 |
| t23 | live proof DONE; experiment pending | two live armed runs on the Spark rig (`216d1110b1bc`, `0ff226c60ebe` — `docs/live-testing.md` row 37): 100 % attribution, manifest ratio ≤ 0.0054, ledger at the operator repo, child bound via `profile: associate` with the recorded `fallback_from_role`, delegate/return events; run 1 exposed and run 2 confirmed the fix for the missing model-facing `profile`/`context_mode` tool params; matched experiment arms (row 38) pending rig hours |

## Mid-work Decisions

Quoted from the delivery ledger (`devague deviate --list`): d1 (t5 loop seam,
approved), d2 + d4 (stall floor 3600 → 5400 s, approved), d3 (operator:
worker dormant, `associate` reserved — approved), d5 (t2 Claude-built in
parallel, approved), d6 (operator: file-length ratchet in t18, approved).
Integration fixes outside the plan text: t19's reap narrowed to ok-only
(resumable runs keep their ledger, c35); t13's parity pin updated once t15
made the block loop-authored.

## Evidence

- Full suite on the integrated tip: green (≈8.8k tests); the only failures seen
  were three lobes tests that read the MAIN checkout's local operator
  `.colleague/config.json` (environmental — pass in every worktree).
- Live SIGTERM salvage (#410) exercised for real twice (t9, t20 runs).
- Live runs: `docs/live-testing.md` row 37 (two armed runs, both `ok`; run 1 found the missing `profile`/`context_mode` tool params, fixed before run 2). Experiment: row 38 (pre-registered, pending).

## Delivery Claims

- Unarmed = byte-identical (pinned key set; `tests/test_e2e_mock.py` unchanged) — **verified**.
- Worker-absent / associate-absent fallback recorded on identity, artifact and doctor — **verified** (tests + live run 2: `fallback_from_role: associate`).
- Model switching only by ledgered delegation (AST guard) — **verified**.
- Matched-experiment promotion — **unverified** (bars above; arms pending).

## Remaining Work / Follow-up

- t20 resume (in flight); the matched experiment arms (rig hours, row 38).
- #412 / #413 — the big-file extraction (loop.py 5132+ lines, three seat builders to fold).
- Per-role API key source for cross-origin child dials (same-origin hygiene sends none today).
- The dormant `worker` / reserved `associate` become live when lobes-cli#187 lands a ready role.
