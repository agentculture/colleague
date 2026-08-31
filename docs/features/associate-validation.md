# Validating the associate seat (Nemotron) with colleague on real cases

Operator-facing, runnable. Written from the delegation-follow-ups arc
(2026-08-30, `docs/live-testing.md` rows 62 and 64, issues #458/#459/#460 and
lobes-cli#234). The associate seat — the lobes `associate` role, Nemotron 3.5
Lightning on the reference rig, proxied from the Jetson AGX Orin — is meant to
serve every **non-writer** lane: `code_survey`/`web_survey` scouts, the
review/validate/plan children, and the memory distill child. Until this guide
has been run once with the results pasted as a live-testing row, those lanes
stay on cortex (Qwen) at thinking `off`/`low` and the associate is opt-in.

## 0. Preconditions — read them off the rig, never assume

```bash
# the advert: role, model, flags (ready/loaded/feasible describe the LOCAL host for a proxied role)
uv run colleague lobes show --json | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['roles']['associate'])"

# does colleague resolve the seat? (t19 makes this the default; until then use the sentinel)
COLLEAGUE_ASSOCIATE_MODEL=lobes uv run colleague config show --json \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['lobes'].get('associate'), d['lobes'].get('not_consumed'))"
# expect: {'served_model': 'nvidia/NVIDIA-Nemotron-…', 'wire_model': 'associate', 'addressed_as_role': True}

# the SERVED window — the advert's `context` is the model's nominal window, not the deployment's
GK=$(grep -E '^GATEWAY_API_KEY=' ~/.lobes/.env | head -1 | cut -d= -f2)
curl -s -H "Authorization: Bearer $GK" -H 'Content-Type: application/json' \
  http://localhost:8001/tokenize -d '{"model":"associate","prompt":"hello world"}'
# expect: {"count":2,"max_model_len":<served window>}  — 128000 on the reference rig vs 1048576 advertised

# one completion through the alias, and its served model
curl -s -H "Authorization: Bearer $GK" -H 'Content-Type: application/json' \
  http://localhost:8001/v1/chat/completions \
  -d '{"model":"associate","messages":[{"role":"user","content":"Reply OK."}],"max_tokens":8}' | python3 -c "import sys,json; print(json.load(sys.stdin)['model'])"
```

Since plan t22 (#460 fixed, v1.69.0) colleague clamps the associate child's
budget to the SERVED window itself (one `/tokenize` probe per seat per process)
and the alias retry no longer hides a context-length 400; the operator override
still wins when smaller:

```bash
export COLLEAGUE_ASSOCIATE_MODEL=lobes            # opt-in until the ladder below is green
# optional, tighter than the served window: COLLEAGUE_ASSOCIATE_CONTEXT_BUDGET=100000
```

**Record the deployment's serving parameters, not only its window.** The
Orin side is tuned deliberately (operator, 2026-08-30): temperature, output
token budget, sampling defaults. Note what colleague sends: every completion
carries `temperature: config.temperature` (`colleague/engines/vllm_openai.py`,
the payload builder), and the associate seat is a `dataclasses.replace` of the
parent config, so **the associate child runs at cortex's configured
temperature (`COLLEAGUE_TEMPERATURE`), not at the Orin's server default** —
the deployment's temperature only applies if colleague's value matches it (plan
t23, shipped in v1.69.0, replaces this with the seat profile below).
`max_tokens` is colleague's window clamp. Paste the deployment's parameters
(the Orin's vLLM launch flags / `lobes status` there) AND colleague's
`temperature` into the row beside the served window, and re-run the ladder
whenever either changes; a result measured under one tuning is not evidence
for another.

## 0b. How to address the lane — the operator's measured contract (2026-08-30)

Two profiles, because one setting does not serve both jobs:

**Depth pass — research, survey, code location** (what `code_survey`/
`web_survey`/memory extraction need):

```json
{"model": "associate", "messages": ["…"],
 "temperature": 0.6, "top_p": 0.95,
 "chat_template_kwargs": {"enable_thinking": true}}
```

Omit `max_tokens` entirely — the single most important line. There is no
server-side cap, and a low one is the failure mode: `max_tokens: 4096` with
thinking on returned an EMPTY string with HTTP 200 and `finish_reason: length`
on 8 of 12 tasks (it looks like success). If a client insists on a cap, use
≥ 8192; the depth arm consumed up to 9,730 output tokens on a 23K-token prompt.

**Fast triage — classification, routing, a bounded answer:**

```json
{"model": "associate", "messages": ["…"],
 "temperature": 0.2, "top_p": 0.95, "max_tokens": 2048,
 "chat_template_kwargs": {"enable_thinking": false}}
```

(Operator correction 2026-08-30: triage runs at temperature **0.2**. And for
colleague's use case every associate lane needs reasoning, so **depth is the
profile for all associate sub-seats**; triage is an explicit operator override
only.)

~4× faster and never truncates, at a real cost: terse and shallower — 11
durable facts where depth got 25, 3/5 relevant files where depth found 5/5,
missed the decisive line depth quoted verbatim, and it ignores output-format
instructions more often (`answer with one line: COUNT: <integer>`, `quote the
document`).

Rules for any caller: address the lane as `model: "associate"` — the role
name, never the raw checkpoint id (it resolves to a different local backend
and 404s `role_infeasible` on a box that proxies the role); served window
128,000; `/v1/*` needs the bearer key, `/capabilities` is open.

**The corrected evidence (#461, lobes' second comment of 2026-08-30 correcting
its first — the first was measured with thinking OFF, the configuration that
is "worst at everything except speed"):**

- **Reasoning budget is the lever, not the model.** Three of the four
  "escalate to cortex" items — trace a cross-module branch, understand an
  unfamiliar architecture, diagnose a bug from code semantics — FAIL with
  thinking off and PASS with thinking on at an adequate budget.
  **Design/implement a change fails at every budget** (4K/16K/32K, always
  well-typed code solving an adjacent problem) and stays an unconditional
  escalation. So the `code_survey` escalation rule is conditional on the
  seat's configured reasoning budget; colleague's `depth` profile IS the
  thinking-on configuration.
- **Paths: verify, do not assume broken.** Thinking on (n=12): exact path
  75 %, basename 92 %, definition line 100 % (thinking off, n=36: 56 / 78 /
  92 %). One misattribution reproduced in all four configurations —
  `tests/test_plan_plan_stage.py` returned as
  `culture-nodes/tests/test_plan_plan_stage.py` while the correct prefix sat
  in the `FILE:` header it had just read: correctly retrieved content with a
  fabricated provenance, invisible to a reviewer. Treat `file` in any digest
  as unverified until re-resolved; the ranged-read validation is load-bearing.
- **Counting / inventory: reduce first, then count with thinking on.**
  Thinking OFF cannot aggregate at any size (over-counts 6 files in 167
  tokens; wrong in 36/36 real-block samples). Thinking ON counted exactly on
  every trap-free corpus tested (6…40 items, up to 42,826 tokens — a
  demonstrated floor, the next size hit the 128K window) and matched a
  defensible reading in 7/12 real blocks, falling from 3/3 at 46k to 1/3 at
  91k and 99k. Define the predicate exactly (`path starts with X`, never
  "comes from X"). The operator's measured caution: *"Aggregation gets worse
  at ≥91K, but a 64K cap doesn't make counting correct at 91K — it makes 91K
  requests impossible. The actual fix is reducing the working set before
  counting, which is caller-side policy, not a server constraint."* So
  colleague keeps the seat at the served 128K window (`served_window_budget`)
  and owns the reduction itself: never ask for a count over raw ~100K
  material, and never ask a thinking-off lane for a count at any size.
- **Cost of depth (same 12 tasks, identical prompts):** thinking on / 4K
  budget 678 s with 9/12 truncated (the dead zone); off / 8K 174 s, 0
  truncated; on / 32K 1,220 s, 0 truncated, 11/12 pass. Decode 54–85 tok/s
  (52–58 at 30–40K prompts), prefill ~1,612 tok/s; definition-line recall
  12/12 at every block size, 88 % deep into 99,674 tokens — the 16K–64K
  working band is about prefill cost and aggregation correctness, not
  retrieval degradation.
- **Two client hazards:** `thinking_budget` is accepted and silently ignored
  by vLLM (lobes-cli#235) — the only levers are `enable_thinking` and
  `max_tokens`; and an empty-content `finish_reason: length` turn is already a
  NAMED truncation in colleague's loop (`colleague/loop.py`, #411 t8), never
  an empty success.

**What colleague sends since plan t23 (v1.69.0):** exactly this contract —
the `depth` profile on every associate lane (temperature 0.6, top_p 0.95,
`enable_thinking: true`, `max_tokens` omitted), `triage` only via
`COLLEAGUE_ASSOCIATE_PROFILE=triage` (or per-value overrides
`COLLEAGUE_ASSOCIATE_TEMPERATURE` / `_TOP_P` / `_MAX_TOKENS` / `_THINKING`);
`config show` prints the profile beside the seat. Cortex still sends its own
`COLLEAGUE_TEMPERATURE` and window clamp, byte-identical to before.

## 1. The case ladder — smallest first, each on a throwaway repo

Run each case with `uv run colleague work "<brief>" --repo <tmp-repo> --no-pr --json`
from the colleague checkout (so the artifact carries `offered_tools` and the
child records), and keep the artifact (`<tmp-repo>/.colleague/<id>.*.json`).

| # | Case | Brief shape | What it tests |
|---|------|-------------|---------------|
| 1 | single-file `code_survey` | "Survey `src/x.py` (≈300 lines) via `code_survey`; report its public functions with `path:line` citations." | the lane routes, the child finishes inside its cap, paths are repo-relative (the `/repo` quirk, row 62) |
| 2 | 4-module survey | the large-surface brief (`docs/live-testing/briefs/arm-large-surface-requested.md`), fixture from `scripts/make_large_surface_fixture.py` | context growth vs the served window; digest correctness against the fixture's four planted pairs |
| 3 | `web_survey` | "Survey these 3 URLs via `web_survey` and report … with `evidence_refs`" (WebGlass installed, `COLLEAGUE_WEB` unset) | the web lane on the seat; `urls fetched:` block; failed fetches |
| 4 | `review` child | a committed 2-file diff; "review HEAD~1 via `review`" | a non-scout purpose on the seat (`PURPOSE_ROLE['review']`) |
| 5 | memory distill | any case with an `.eidetic/memory` store in the repo; then `colleague feedback show last` | the distill child rides the associate (`ASSOCIATE_SEAT_TABLE['distill']`); `TaskResult.memory` counters increment |

## 2. What to read off each artifact (never off prose)

```bash
python3 - <<'PY'
import json,sys,collections
d=json.load(open(sys.argv[1]))
P=('code_survey','web_survey','review','validate','plan')
calls=[s for s in d['steps'] if s.get('tool') in P]
print('status', d['status'], 'turns', d['stats']['model_turns'], 'wall', round(d['stats']['duration_seconds']))
for s in calls:
    r=str(s.get('result') or '')
    print(' ', s['tool'], 'step', s['index'], 'REFUSED' if 'refused' in r[:40] else 'ran', '| served', s['arguments'].get('served_model'), '|', r[:90].replace('\n',' '))
for c in d.get('sub_results',[]):
    print('  child', c['task_id'], c['model'], c['status'], 'tokens', (c.get('usage') or {}).get('total_tokens'))
last=max((s['index'] for s in calls), default=-1)
tail=[s for s in d['steps'] if s['index']>last]
print('after children:', len(tail), 'steps; full read_file:', dict(collections.Counter(str(s['arguments'].get('path')) for s in tail if s.get('tool')=='read_file')))
print('warnings', [w.get('kind') for w in d.get('warnings') or []], '| memory', d.get('memory'))
PY
```

Per case, record: served model per child (`sub_results[].model` is the wire
alias today — the served id comes from the config block; #460 asks for the
served id on the child record), child status + tokens, refusals (with the
error body — a `role_infeasible` 404 after an alias retry means a 400 hid
behind it), post-digest reads (full-module `read_file` = the caller re-did the
work; ranged reads of cited lines = it re-validated), task success, and for
case 5 the `memory` counters.

## 3. Pass bar per case (a miss is written as a miss)

- Case 1: 1/1 child `ok`, ≤ 12 steps (the `PURPOSE_STEPS` cap — #458 until
  fixed), every claim cited `path:line`, zero absolute-path errors.
- Case 2: ≥ 3 of 4 planted pairs named, 0 false pairs, 0 refusals, each child
  inside the served window (no 400), parent post-digest reads ranged, not full.
- Case 3: the `urls fetched:` block lists every requested url; claims carry
  `evidence_refs`; failed fetches annotated `(failed)`.
- Case 4: the review names file paths + line numbers for each finding on the
  real diff.
- Case 5: `distill_attempts` and `distill_validated` both increment on the
  artifact; the lesson names a constant from the case, not a process platitude.

## 4. Known failure shapes (as of 2026-08-30)

- **Budget vs served window (#460, lobes-cli#234) — FIXED in v1.69.0 (plan t22):**
  before it, a 768k child budget from a 1,048,576 advert against a served
  128,000 window → `400 maximum context length` → the alias→served-id retry →
  `404 role_infeasible` with the original 400 lost. Now the seat is clamped to
  the served window and a failed retry reports both bodies; lobes-cli#234 asks
  the advert to carry the served window too.
- **Unapplied child cap (#458):** children run 23–37 steps against a 12-step
  cap and 150k–1.1M tokens.
- **`/repo` paths:** Nemotron opened a child with `read_file /repo/src/…`
  (four errors) before recovering with `list_dir .` — the scout brief should
  say "paths are repo-relative".
- **Empty HTTP 200 (`finish_reason: length`, empty content):** a low
  `max_tokens` with thinking on — 8/12 tasks at 4,096 on 20K+ prompts. The
  loop names it a truncation; the `depth` profile omits the cap.
- **Provenance fabrication for correctly retrieved content:** the
  reproducible `culture-nodes/…` misattribution in §0b — only a ranged
  re-resolution catches it.
- **Aggregation off thinking:** any count or exhaustive list from a
  thinking-off lane is wrong; from a thinking-on lane it is reliable only over
  a reduced, cleanly separable working set (§0b).
- **A failed `/tokenize` probe keeps the advert-derived budget (a recorded
  limit of the t22 clamp):** `served_window_budget` leaves the configured
  budget untouched when the probe returns nothing (a server without
  `/tokenize`, a network error) — on a 1,048,576 advert that is the 768k
  budget that produced #460. Step 0's probe is what proves the clamp is
  live; the gateway proxies the ROOT `/tokenize` (a `/v1/tokenize` request
  is `Not Found`).
- **`ready:false` on a live proxied role:** the flag describes the local host;
  the lane may still answer (probe it, step 0).

Ship the associate-by-default change (plan t19) only after this ladder has a
green live-testing row; until then the decision rule in #459 chooses the seat
per lane by measurement (cortex Qwen at `off`/`low` vs the associate at
`off`/`low`).
