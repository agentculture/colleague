# Thinking effort — a per-seat reasoning ladder

> Spec:
> [`docs/specs/2026-08-21-per-seat-thinking-effort-416.md`](../specs/2026-08-21-per-seat-thinking-effort-416.md)
> · plan:
> [`docs/plans/2026-08-21-per-seat-thinking-effort-416.md`](../plans/2026-08-21-per-seat-thinking-effort-416.md)

colleague sends a **per-seat thinking setting** to a thinking checkpoint: the
deepthink and design seats keep the checkpoint's full effort while the shallow
seats (the senses front door, the Talker, the read-only scouts) turn thinking
**off** — resolved **where each seat is built**, never per turn **from content**
(amended #484: *per enumerated point from a fixed table* — the effort-spike
surface, `colleague/effortspikes.py`, keys a rung by POINT NAME, never by
inspecting a turn or accepting a model-supplied value; amended again by the
effort-decay arc, convention change (8): *per enumerated point, **or per
fixed OFFSET from such a point**, from a fixed table* — `colleague/effortdecay.py`
keys the acting turns AFTER a spike by their offset from it, `1 → low`, then
`off` until the next spike, opt-in `COLLEAGUE_EFFORT_DECAY=1`; see
[`effort-spikes.md`](effort-spikes.md)), and
**byte-identical when unset**. The knob is a closed ladder, not a free number:

```text
LADDER = ("off", "low", "medium", "high", "xhigh")
```

plus the sentinel `default`, which is the **kill switch** (see below), not a
sixth rung.

## Audience

Two readers, one surface:

- **The operator** edits `config.json` / env vars (the config surface — see
  [config-resolution.md](config-resolution.md) for the new knobs) and reads the
  resolved table via `colleague config show`.
- **The runtime** reads the *same* resolved table to build each seat (the seat
  table below). There is no second config format — both readers are served by
  one surface.

## The v4 default table

This is the single source of truth for the default rung of every seat, role,
and design call-site. It is pinned row-for-row by
`tests/test_effort.py::test_default_table` and `::test_table_sizes_exact` —
**every row below is asserted by one parametrized test**, and the set of rows is
exactly the set the test pins (no stray rows). The other docs
([engines.md](engines.md), [deepthink.md](deepthink.md),
[config-resolution.md](config-resolution.md),
[subagent-roles.md](subagent-roles.md)) reference this table; they do not
duplicate it.

### Persistent seats (`SEAT_TABLE`)

| Seat | Default rung |
|------|--------------|
| `cortex` | `low` |
| `worker` | `low` |
| `deepthink` | `xhigh` |
| `evaluator` | `low` |
| `senses` | `off` |
| `design` | `xhigh` |
| `associate` | `low` |

The `associate` row is the armed seat's floor (Nemotron needs `low`); the
unreachable fallback to cortex runs at `off` (`associate_seats.FALLBACK_EFFORT`)
— two models, one seat (#475).

### Subagent children (`ROLE_TABLE`)

| Role | Default rung |
|------|--------------|
| `writer` | `low` |
| `planner` | `low` |
| `reviewer` | `low` |
| `validator` | `low` |
| `explorer` | `off` |
| `scout` | `off` |

### Associate sub-seats (`ASSOCIATE_SEAT_TABLE`, `colleague/efforttables.py`)

The five enumerated associate seats (`ASSOCIATE_SEATS`) each carry their own
rung; the `associate` row above is the whole-seat override. Precedence:
`default` kill-switch > explicit per-child override >
`COLLEAGUE_ASSOCIATE_REASONING_EFFORT_<SEAT>` / `reasoning_effort_seats["associate.<seat>"]`
> `COLLEAGUE_ASSOCIATE_REASONING_EFFORT` (the whole-seat row) > this table.
Unset, every seat resolves to its `low` row (v4 #475 — the four `off` rows
moved to join `distill`).

| Associate seat | Default rung |
|----------------|--------------|
| `scout` | `low` |
| `compact` | `low` |
| `synthesis` | `low` |
| `digest` | `low` |
| `distill` | `low` |

### Purpose tools (`PURPOSE_TABLE` + `PURPOSE_STEPS`, `colleague/efforttables.py`)

A purpose tool's child gets its OWN rung, passed to the spawn as the explicit
override — never the parent's rung, the parent's seat override, or the global
rung (decision q7 of the purpose-tools spec). Operator knob:
`COLLEAGUE_<PURPOSE>_REASONING_EFFORT` / `reasoning_effort_purposes[<purpose>]`;
the `default` kill-switch still yields no fragment. The step cap is the child's
`max_steps` (`None` = the parent's default).

| Purpose tool | Child role | Default rung | Step cap |
|--------------|------------|--------------|----------|
| `web_survey` | `scout` (associate when armed) | `low` | 12 |
| `code_survey` | `scout` (associate when armed) | `low` | 12 |
| `review` | `reviewer` | `low` | 16 |
| `validate` | `validator` | `low` | 16 |
| `plan` | `planner` | `low` | 10 |
| `handover_to_colleague` | `writer` | `low` | parent default |

Honest limit (follow-up v5 of the purpose-tools spec): a **manual**
`subagent`/`subagents` child still resolves the parent's cortex seat override
above its own `ROLE_TABLE` row (`colleague/subagents.py`, the child rung
resolution) — so `COLLEAGUE_CORTEX_REASONING_EFFORT=high` reaches a manual
reviewer child; a purpose child does not inherit it.

### Top-level role overrides (`TOP_LEVEL_ROLE_TABLE`)

A typed role is *also* a top-level `colleague work --role` flag, not only a
subagent child. The role table above applies to **children**; at the top level
two roles are overridden — the ask-colleague explore path and the diff review:

| Role | Top-level rung |
|------|----------------|
| `explorer` | `low` |
| `reviewer` | `low` |

(off is selectable via a per-seat / parent override.)

### Read-only mode overrides (`TOP_LEVEL_MODE_TABLE`)

When no top-level role is given, the run's `--mode` applies the same rung to
the acting seat for the two read-only modes (`colleague work --mode
explore|review`, the mode the ask-colleague verbs select). The operator's rule
(2026-08-30): the associate seat is the fast reviewer, and whenever it is not
taken, cortex at the v3 `medium` default is slow — a 20 KB diff review overflowed its
synthesis turn at 274k reasoning chars and closed `incomplete`. Consulted only
when no explicit override exists: the kill-switch, every per-seat / global
knob, and a `--role` with its own top-level rung still win, so an unset run
is byte-identical.

| Mode | Acting-seat rung |
|------|------------------|
| `explore` | `low` |
| `review` | `low` |

Every other top-level role and mode keeps the **acting seat's** rung (low).

### Design call-sites (`DESIGN_SITE_TABLE`)

One-shot design/planning decisions reason about *structure* rather than write
code, so they run on the `design` seat at heavier effort than the steady-state
seats — even when the acting seat is set lower. This is a **fixed, enumerated**
table of call-sites, not a task→effort decision (adding a call-site means
editing the constant, never a runtime choice):

| Call-site | Default rung |
|-----------|--------------|
| `plan.spec_stage` | `xhigh` |
| `plan.plan_stage` | `high` |
| `plan.workforce` | `xhigh` |
| `autosplit` | `xhigh` |
| `fillline.split` | `xhigh` |
| `subagents.decompose` | `xhigh` |

## Precedence

`colleague.effort.resolve_effort` is the **only** place precedence is computed;
every seat builder calls it, and a table test covers each adjacent pair.
Highest first:

1. **kill-switch** (`COLLEAGUE_REASONING_EFFORT=default`, or `config.json`
   `reasoning_effort: "default"`) — beats everything, including an explicit
   parent override;
2. **explicit per-delegation parent override** (a parent delegating to a child
   with a named rung);
3. **per-seat env/config override** (`COLLEAGUE_<SEAT>_REASONING_EFFORT`, or
   `config.json` `reasoning_effort_seats`);
4. **role table** (the child's own role row);
5. **seat table** (the seat's row);
6. **unset** (`None` — no key on the wire).

The first non-`None` input wins. The `default` sentinel at *any* rung
short-circuits to `None` immediately — the kill switch fires from wherever it is
set, not only from the dedicated flag.

## The kill switch

ONE global switch forces every seat, role, and design call-site to **unset** —
the byte-identical pre-increment wire — in one env var, no redeploy, no code
change:

```bash
COLLEAGUE_REASONING_EFFORT=default colleague work "..."   # or config.json "reasoning_effort": "default"
```

With the kill switch set, **no payload from any seat carries
`chat_template_kwargs`** regardless of per-seat / role / env overrides, and
`config show` prints the switch as the winning layer.

## The wire

`vllm_openai._build_chat_payload` is the single payload builder every seat's
`_make_complete` passes through. It emits `chat_template_kwargs` **only** when
the seat's resolved setting is non-unset:

- `off` → `{"enable_thinking": false}` (the vLLM/Qwen3 toggle — the real OFF);
- any rung → `{"reasoning_effort": <rung>}` sent **verbatim** (`"high"` is sent
  as `"high"`, never silently upgraded to `"xhigh"`);
- unset / `default` → no key at all (byte-identical body).

Never both keys, and never any other key **inside `chat_template_kwargs`**
(`preserve_thinking` is never sent — vLLM merges request kwargs per key, so
lobes' `preserve_thinking: true` is never clobbered). `chat_template_kwargs` is
a **vLLM extension**, so this is the **third** graceful-degrade carve-out to
"the vLLM adapter only touches the OpenAI surface" (after `/tokenize` and the
armed-lobes stale-pin refresh — see CLAUDE.md conventions): a server that
ignores the key behaves exactly as today.

**`chat_template_kwargs` is no longer the only per-seat body key.** Since #479
the same payload also carries the resolved **per-model sampling profile**, and
the rung this page resolves is exactly what selects its half — `off` is the
model's non-thinking half, any live rung the thinking half, and unset /
`default` selects no half and therefore no sampling key. On the builtin Qwen3.8
table that adds `temperature`, `top_p` and `top_k` (plus `presence_penalty` on
the non-thinking half); `top_k` is the only vLLM extension among them, and it
is the **fourth** carve-out. The table, the wire filter, the operator
`.colleague/models.json` and the honest limits live in
[sampling.md](sampling.md) — this page owns the rung, not the values.

## Ladder-400 degrade

A seat call that carried `chat_template_kwargs` and gets an **HTTP 400 whose
body names the ladder** (probe 2026-08-21: `Unexpected reasoning effort bogus.
Supported types are xhigh (default), medium, and low.`) is **retried ONCE
without the key**, and a `TaskResult` warning names the seat + the server's
supported ladder. The run never fails on the knob. The retry fires at most
once, only on a 400 whose body names the reasoning ladder, only for a request
that carried the key; any other 400 surfaces exactly as today. This retry is
**disjoint** from the existing same-role stale-pin 404 refresh retry (by status
code, each single-shot) — a scripted 404→400→200 yields exactly two distinct
retries, the refreshed model id persists, the key is dropped, and both warnings
land.

## Observability

The effort each invocation ran at is **trace data**: on the #411 task-ledger
invocation record (`InvocationRecord.reasoning_effort`, beside `model`) and on
the OTel work span (beside `model`/`max_steps`) — so per-seat attribution
answers "what effort did this call run at" without re-deriving the table. It is
recorded **only when set** (absent = unset), keeping the unset artifact/ledger
byte-identical.

## Honest limits

- **`high` == `xhigh` on Qwen3.8.** Probe 2026-08-22: on the pinned Qwen3.8
  checkpoint, `high` and `xhigh` produce indistinguishable reasoning behavior —
  the model does not expose a fifth distinct rung. colleague sends `high`
  **verbatim** anyway rather than silently upgrading it: the five-rung
  vocabulary is a contract with the *backend*, and a future backend (or a
  future Qwen revision) may yet honor the distinction. Consequence, stated
  plainly: an operator choosing `high` over `xhigh` on this checkpoint gets
  **no saving** — the `plan.plan_stage = high` tier buys nothing here; it is
  kept as operator intent for checkpoints with a real `high` rung.
- **The probe is n=1 per cell, one checkpoint, one box, one day.** It lowers
  the odds of a surprise; it does **not** replace the live arm.
- **Effort × tool-calling rests on the t11 arm.** A scout/worker loop *with*
  tools at `enable_thinking: false` may degrade tool-call formation on the
  `qwen3_coder_thinking` parser. This is **unmeasured** by the probe; the
  read-only roles ship `off`/`low` now and the effort×tool-calling proof runs
  live in-session on explorer/reviewer/validator/planner children before merge
  (plan task t11). If any read-only child fails to form tool calls at its
  default, the role's default is reverted to unset in the same PR (c25) and
  this doc says so.
- **#417 scope limits.** The measured evidence (colleague#417 / lobes-cli#192)
  is n=1/cell over 4 prompts: the Qwen3.8-27B template ladder is
  low/medium/xhigh (default xhigh, `high` = alias, unknown value → HTTP 400);
  `enable_thinking: false` is the real OFF; **low/medium are not monotonic
  cheaper** and degrade instruction-following (one flipped a decision); OFF
  scored 4/4 on shallow prompts. The saving is **seat-shaped**, so the knob is
  seat-shaped — the doc cites the measured rig evidence and states its limits
  rather than asserting a universal saving.
- **The default now sends `low` for the acting seat by design** (spec
  decisions c35/c36/c38/c39; v4 #475 dropped the v3 `medium` default).
  "Byte-identical" holds **under the kill-switch**,
  not under "nothing configured": with the default table armed, the acting
  cortex/worker seat sends `reasoning_effort: low` on the wire. Say it
  plainly — the increment is *not* invisible until armed; it is invisible only
  when the operator opts out via the kill switch.
- **Thor / 35B ladder unknown.** The served checkpoint's ladder is not
  discoverable from the lobes `/capabilities` contract; validation is a static
  client-side enum. Thor's no-MTP cortex and the 35B worker template may expose
  a different or no ladder — the ladder-400 retry-once is the runtime guard,
  unmeasured until a Thor run.
- **The distill child's `max_tokens` is not window-clamped** (colleague#448).
  `distilleffort.max_tokens_for_rung` returns a fixed 4096 / 12288 rather than
  clamping against the served window via `outputclamp.clamp_output_tokens`,
  because the detached distill child has neither input the clamp needs: the
  context window and prompt-token count come from the one run-start
  `/tokenize` probe in the vLLM adapter, and the child is a raw `urllib` POST
  that never builds an adapter. Stated plainly: there is nothing to clamp
  against today, and a guessed window would look like a clamp while encoding
  an assumption the child cannot verify. Not a live risk on the pinned rig
  (12288 against a 131072 window), and a length-cut completion already fails
  legibly via `reasoning_exhausted_reason`, which names the cap. Raised by the
  Qodo review on #447; a real fix needs window discovery in the child, which
  is its own re-spec.
- **Exact reasoning-token accounting is adjacent, parked.** The rig now reports
  `usage.completion_tokens_details.reasoning_tokens` (#417) while
  `vllm_openai.py` still carries a stale comment that the server reports none;
  exact reasoning-token accounting on `WorkStats` is a separate increment.

## Why it matters

- **colleague#415:** small requests finish in ~2 min while module briefs stall
  23–75 min on a `--max-num-seqs=2` rig.
- **colleague#417:** cortex is at `xhigh` on every turn by default, and lower
  rungs are **not** reliably cheaper and degrade parsed output, while
  thinking-off is −75% total tokens on shallow calls with equal correctness —
  the saving is seat-shaped, so the knob must be seat-shaped.

## Key files

- `colleague/effort.py` — the ladder, the v4 tables, `resolve_effort`,
  `to_chat_template_kwargs`, `validate_effort` (pure stdlib; `config` imports
  `effort`, never the reverse).
- `colleague/design.py` — `DESIGN_CALL_SITES`, `design_effort`,
  `design_seat_config` (the design call-site, landing in parallel).
- `colleague/engines/vllm_openai.py` — `_build_chat_payload` emits
  `chat_template_kwargs`; the ladder-400 retry-once.
- `colleague/config.py` — `EngineConfig.reasoning_effort` /
  `reasoning_effort_seats` / `too_long_min` knobs + the acting seat's effort.
- `colleague/roles.py` — `Role.effort` (the per-role home for effort).

## See also

- [config-resolution.md](config-resolution.md) — the new knobs and their
  precedence.
- [deepthink.md](deepthink.md) — the deepthink seat's `xhigh` default on the
  four-point escalation surface.
- [subagent-roles.md](subagent-roles.md) — `Role.effort` and the child rows.
- [engines.md](engines.md) — the third carve-out on the vLLM adapter.
- [sampling.md](sampling.md) — the per-model sampling profile the same rung
  selects the half of, and the fourth carve-out.
