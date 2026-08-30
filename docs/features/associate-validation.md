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
- **`ready:false` on a live proxied role:** the flag describes the local host;
  the lane may still answer (probe it, step 0).

Ship the associate-by-default change (plan t19) only after this ladder has a
green live-testing row; until then the decision rule in #459 chooses the seat
per lane by measurement (cortex Qwen at `off`/`low` vs the associate at
`off`/`low`).
