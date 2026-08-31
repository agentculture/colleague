# colleague published-artifact contract

This is the surface a caller (an operator's own tooling, a sibling agent, the
`ask-colleague` skill, or anything else that shells out to `colleague work`)
may **pin against**: the run-report artifact JSON, the feedback record, the
artifact naming/layout on disk, and the process exit-code semantics. Follows
the spirit of
[data-refinery-cli's `docs/contract.md`](https://github.com/agentculture/data-refinery-cli/blob/main/docs/contract.md):
frozen shapes, a drift test (`tests/test_contract_doc.py`) that fails the
build the moment code and doc disagree, and a semver-bump policy for any
breaking change.

- **Contract version:** `1` (first frozen edition; enumerates the shape as of
  colleague `1.37.0`).
- **Package version pinned by a consumer:** see `pyproject.toml` `version`.

Every fenced block below tagged `<!-- contract:keys:NAME -->` is read
verbatim by the drift test — one JSON key per line, alphabetically sorted.
Don't hand-edit a block without also updating (or, better, regenerating from)
the dataclass it documents; the test fails loudly the moment the two disagree.

## The run-report artifact JSON

Every `colleague work` / `drive` invocation writes one result artifact: the
full `colleague.contract.TaskResult` as JSON via `TaskResult.to_dict()`
(`colleague/artifact.py` `write()`). The shape is **additive-optional**: a
fixed set of keys is always present, and a larger set of feature-specific keys
is emitted **only when that feature actually fired** during the run (the
"omit-when-None" convention used throughout `colleague/contract.py`) — so an
artifact from a plain `colleague work "<task>"` with none of the optional
features active is byte-for-byte the same shape it always was, no matter how
many optional features colleague has grown.

### Always-on top-level keys (16)

Present on every artifact, regardless of which features fired.

| Key | Type | Meaning |
|-----|------|---------|
| `task_id` | string | The work item's id (also the artifact filename's leading segment). |
| `status` | string | `"ok"` \| `"error"` \| `"incomplete"` — see [exit codes](#exit-code-semantics). |
| `summary` | string | The model's final report text (or the `NO_RESULT_PRODUCED` sentinel on a truly empty run). |
| `changed_files` | string[] | Repo-relative paths the work item wrote. |
| `steps` | Step[] | The full tool-call trace — see [`step`](#step-steps-item). |
| `usage` | Usage | Exact API-reported token accounting — see [`usage`](#usage-usage--sub_resultsusage). |
| `stats` | WorkStats | Always-on cost/shape statistics — see [`stats`](#workstats-stats). |
| `finish_states` | FinishRecord[] | Always-on per-seat finish/truncation state (decision c30) — see [`finish_record`](#finishrecord-finish_states-item). |
| `artifacts_path` | string \| null | Absolute path to this artifact's own JSON file. |
| `error` | string \| null | Set only when `status == "error"`. |
| `branch` | string \| null | The git handoff branch, or `null` when the run stayed local. |
| `pr_url` | string \| null | The opened PR URL, or `null` (`--no-pr` / no remote / no PR requested). |
| `hook_firings` | HookFiring[] | Every lifecycle-hook invocation — see [`hook_firing`](#hookfiring-hook_firings-item). |
| `command` | string \| null | The command-template name that originated this task, or `null` for an ad-hoc instruction. |
| `not_finished` | boolean | `true` iff the step budget was exhausted without a `finish` call (and without an abort). |
| `stopped_without_finish` | boolean | `true` iff the run ended on a no-tool-call turn and never called `finish`, even after the nudge. |

### Optional (omit-when-absent) top-level keys (20)

Each key below is **entirely absent** from the JSON — not present as `null` —
when the corresponding feature never fired for this work item. `sub_results`
is additionally omit-when-**empty** (an empty list is still omitted, not
serialized as `[]`).

| Key | Type | Fires when |
|-----|------|------------|
| `destination` | string | A devague goal-frame slug was set (`--destination`). |
| `announcement` | string | An announcement was declared on arrival at a destination. |
| `capacity_decision` | CapacityDecision | The fill-line threshold was crossed — see [`capacity_decision`](#capacitydecision-capacity_decision). |
| `capacity_warning` | string | The up-front complexity assessment exceeded in-repo split capacity. |
| `lint_report` | LintReport | The lint pre-finish gate ran — see [`lint_report`](#lintreport-lint_report). |
| `coherence_report` | CoherenceReport | The coherence pre-finish gate ran on changed docs — see [`coherence_report`](#coherencereport-coherence_report). |
| `test_integrity_report` | TestIntegrityReport | The mirror-detection gate found something — see [`test_integrity_report`](#testintegrityreport-test_integrity_report). |
| `role` | string | The work item ran as a typed subagent role (e.g. `"writer"`, `"explorer"`). |
| `sub_results` | SubResult[] | At least one `subagent`/`subagents` delegation completed — see [`sub_result`](#subresult-sub_results-item). |
| `mode` | string | A driving mode (`work`\|`plan`\|`explore`\|`review`) was selected by the CLI/session entry door. |
| `affected_tests_report` | AffectedTestsReport | The affected-tests gate ran — see [`affected_tests_report`](#affectedtestsreport-affected_tests_report). |
| `acceptance_outcomes` | dict[] | `Task.acceptance` criteria were set, so the pre-finish self-check ran — see [`acceptance_outcome`](#acceptance-outcome-acceptance_outcomes-item). |
| `deepthink` | DeepthinkCall[] | The dual-model deepthink escalation fired at least once — see [`deepthink_call`](#deepthinkcall-deepthink-item). |
| `effort` | dict | At least one seat's thinking-effort rung resolved (effort-v4 t5) — `{seat: rung}` for every seat BUILT during the run: `"main"` always (when resolved), `"senses"` when the senses lane ran, delegated children by role (a scout/purpose child included), `"distill"` when the rung-2 pass launched. `"off"` is recorded; a never-resolved seat is absent. |
| `finish_recovered` | string | A `finish` transport failure was recovered (`"literal-markup"` \| `"thin-finish-synthesis"` \| `"meta-finish-synthesis"`). |
| `memory` | dict | The eidetic memory recall/remember cycle ran — see [`memory`](#memory-dict). |
| `media` | dict | The task carried attachments and their delivery was classified — see [`media`](#media-dict). |
| `senses` | SensesBlock | A cortex/senses split (or live-presence talk lane) ran — see [`senses`](#sensesblock-senses). |
| `agents` | dict | The model-bound-agents increment (#411) was armed — see [`agents`](#agents-dict). |
| `config_events` | ConfigEvent[] | At least one config event (baseline/proposed/refused/verified/applied/reverted) was recorded — see [`config_event`](#configevent-config_events-item). |
| `config_digest` | string | `config_events` is non-empty — the deterministic digest over that replayed sequence, see [`config_event`](#configevent-config_events-item). |

### The maximal key set (drift-tested)

Every key above, together — the set a caller sees from an artifact where
**every** optional feature fired at least once. `tests/test_contract_doc.py`
builds exactly this `TaskResult` in code and asserts its `to_dict()` key set
equals this block.

<!-- contract:keys:top-level -->
```text
acceptance_outcomes
affected_tests_report
agents
announcement
artifacts_path
branch
capacity_decision
capacity_warning
changed_files
command
coherence_report
config_digest
config_events
deepthink
destination
effort
error
finish_recovered
finish_states
hook_firings
lint_report
media
memory
mode
not_finished
pr_url
role
senses
stats
status
steps
stopped_without_finish
sub_results
summary
task_id
test_integrity_report
usage
```

### Nested shapes

#### `WorkStats` (`stats`)

Always-on per-work-item cost/shape statistics (`colleague/contract.py`
`WorkStats`). Tokens live on `usage` (exact, API-reported); `stats` covers
everything else — timing, tool usage, and chars/bytes generated (there is no
tokenizer, so "thought vs written" is measured in chars/bytes, never
estimated tokens).

<!-- contract:keys:stats -->
```text
answer_bytes
answer_chars
bytes_written
duration_seconds
engine
files_changed
model
model_turns
reasoning_bytes
reasoning_chars
request
started_at
step_count
tool_counts
web_calls
web_failed
```

Optional — emitted only when at least one is non-zero, so an untouched run
keeps the shape above (plan t20, `colleague/runcounts.py`): `counts`, a
dict of exact harness counters `batches_run` (parallel read-only tool
batches), `calls_parallelised` (tool calls executed inside them),
`results_blanked` (old tool results the microcompaction floor blanked),
`outputs_spilled` (tool outputs spilled to `.colleague/tool-output/`) and
`guard_trips` (always-on loop-guard halts).

`tool_counts` is a `{tool_name: count}` map, not a fixed key set.

#### `FinishRecord` (`finish_states[]` item)

Always-on, per-seat finish-state + truncation record (`colleague/contract.py`
`FinishRecord`; plan task t1, decision c30 — the one sanctioned unconditional
artifact addition since this contract froze, exactly like `stats`/WorkStats
itself: never omit-when-empty, present on every artifact including an
unconfigured run). `seat` is a free-form string, not a closed enum — today
always `"main"` (the acting mind's own turns), plus `"senses"` when a
cortex/senses split ran.

<!-- contract:keys:finish_record -->
```text
finish_reason
reasoning_effort
seat
state
truncated
```

`state` is one of `"deliberate"` \| `"truncated"` \| `"stopped"` \|
`"timeout"` \| `"empty"` (`colleague.contract.FINISH_STATES`) —
`colleague/finishstate.py`'s `classify_finish_state` maps the loop's own
terminal outcome plus the raw backend `finish_reason` onto these five states;
`"empty"` is the state guaranteed whenever the work item's `summary` is the
`NO_RESULT_PRODUCED` sentinel — it never reports `"deliberate"`. `truncated`
is `true` iff `state == "truncated"`. `finish_reason` is the raw
backend-reported value for the seat's LAST completion (e.g. `"stop"` \|
`"tool_calls"` \| `"length"`), or `""` when the backend/engine never reports
one (e.g. the `"senses"` seat, which has no raw wire value of its own).
`reasoning_effort` records the thinking-effort rung the seat ran at, or `""`
(the stable sentinel) when it was never resolved — including artifacts written
before the field existed, which load back as `""`.

#### `Usage` (`usage` / `sub_results[].usage`)

Exact, verbatim-from-the-model-response token accounting. The same shape is
used both on `TaskResult.usage` and nested inside each `SubResult.usage` —
cost attribution is nested-only (a parent's `usage` is never summed with its
children's).

<!-- contract:keys:usage -->
```text
completion_tokens
prompt_tokens
total_tokens
```

#### `Step` (`steps[]` item)

One tool-call iteration of the bounded loop. The same shape is written, one
per line, to the sibling `<task_id>.<slug>.trace.jsonl` file.

<!-- contract:keys:step -->
```text
arguments
index
ok
result
tool
```

#### `HookFiring` (`hook_firings[]` item)

One lifecycle-hook invocation (`task_start` / `pre_tool` / `post_tool` /
`finish`).

<!-- contract:keys:hook_firing -->
```text
command
decision
event
exit_code
reason
tool
```

`decision` is one of `"allow"` \| `"deny"` \| `"rewrite"` \| `"observe"`.

#### `SubResult` (`sub_results[]` item)

One delegated child work item's result. `role` and `parent` are themselves
omit-when-`None` **within** each entry (a role-less / parent-less child omits
those two keys) — the block below is the maximal shape (both present).

<!-- contract:keys:sub_result -->
```text
changed_files
engine
model
parent
reasoning_effort
role
status
summary
task_id
usage
```

`reasoning_effort` (omit-when-None, effort-v4 t5) is the child seat's resolved
thinking-effort rung, read off the built child config at spawn — the same
value the parent folds into its top-level `effort` block under the child's
role.

#### `CapacityDecision` (`capacity_decision`)

The one declared fill-line move (`"compact"` \| `"split"` \|
`"finish-with-handoff"`), recorded at most once per work item.

<!-- contract:keys:capacity_decision -->
```text
kind
reason
```

#### `LintReport` (`lint_report`)

<!-- contract:keys:lint_report -->
```text
fixed
residual
skipped
```

Each list holds human-readable notes (e.g. `"black reformatted 2 file(s)"`),
not structured findings.

#### `CoherenceReport` (`coherence_report`)

<!-- contract:keys:coherence_report -->
```text
status
reason
embed_url
embed_model
files
```

`status` is `"scored"` or `"skipped"` (`reason` says why). `embed_url` /
`embed_model` record the measurement's frame provenance (coherence-cli#10):
the embedding endpoint + model the scorer used — a meaning score is a
model-relative, anchor-defined measurement, never universal meaning. `files`
is a list of per-file records: `path` plus either the coherence CLI's payload
(`meaning_score`, `subdimensions`, `diagnostics`, and any future keys
verbatim) or an `error` string. `reason`/`embed_url`/`embed_model`/`files`
are omit-when-absent inside the report. Advisory only — never blocks the
handoff (#294).

#### `TestIntegrityReport` (`test_integrity_report`)

<!-- contract:keys:test_integrity_report -->
```text
findings
```

##### `MirrorFinding` (`test_integrity_report.findings[]` item)

<!-- contract:keys:mirror_finding -->
```text
impl_file
kind
symbol
test_file
```

`kind` is `"attribute"` \| `"dict_key"`.

#### `AffectedTestsReport` (`affected_tests_report`)

<!-- contract:keys:affected_tests_report -->
```text
capped
failed
passed
reason
selected
status
total
```

`status` is `"passed"` \| `"failed"` \| `"skipped"`.

#### Acceptance outcome (`acceptance_outcomes[]` item)

A plain dict, not a dataclass — one per `Task.acceptance` criterion.

<!-- contract:keys:acceptance_outcome -->
```text
criterion
evidence
met
```

Advisory only: `met: false` never flips `TaskResult.status`.

#### `DeepthinkCall` (`deepthink[]` item)

<!-- contract:keys:deepthink_call -->
```text
degraded
duration
point
tokens
```

`tokens` / `duration` are `null` when not measured (e.g. a degraded call that
never reached the wire).

#### `ConfigEvent` (`config_events[]` item)

One entry in the append-only config event stream (plan task t7, covers
c9/h9; `colleague/configevents.py`) — the audit trail a three-tier cortex
configurator (a later task) proposes/refuses/verifies/applies/reverts
changes onto. `kind` is one of `"baseline"` \| `"proposed"` \| `"refused"` \|
`"verified"` \| `"applied"` \| `"reverted"`. **`"baseline"` is itself an event
kind** — a seeded starting config must be recorded as an ordinary event, not
an invisible constructor default, because `config_digest` is a deterministic
sha256 computed from the REPLAYED `config_events` sequence **alone** (no
ambient state); a starting config that never became an explicit `baseline`
event can never be reconstructed from, or verified against, the digest (the
"T8 trap" the acceptance criteria name). `target`/`origin` are free-form
strings (e.g. `target="worker.tools"`, `origin="cortex"` — matching
`colleague.lattice.Target`/`Origin` string values when a configurator
populates them, though this stream is not itself coupled to that enum).
`reason` is populated for a `"refused"` event and empty otherwise by
convention. `seq` is a monotonically increasing position in the stream,
assigned by `colleague.configevents.ConfigEventStream.append`.

<!-- contract:keys:config_event -->
```text
kind
origin
reason
seq
target
```

`config_events` is `[]`/omitted when a work item recorded no config-event
activity — today's common case, since the stream is populated by
`colleague.configevents` but nothing in the runtime writes to it yet this
wave. `config_digest` is `null`/omitted alongside it.

#### `memory` (dict)

A plain dict, not a dataclass, populated by the memory-informed-runtime cycle
(recall-before / remember-after).

<!-- contract:keys:memory -->
```text
injected_chars
lesson_recorded
query
recalled
```

#### `media` (dict)

<!-- contract:keys:media -->
```text
attachments
```

##### `media.attachments[]` item

<!-- contract:keys:media_attachment -->
```text
path
status
```

`status` is `"delivered"` \| `"dropped"` \| `"unknown"` \| `"bridged"` — a
token-contribution verdict (the attachment reached the prompt), never a claim
that the model *understood* it.

#### `agents` (dict)

The model-bound-agents block (#411; spec c17/h24), built by
`colleague.agents.artifact_block.build_agents_block` — present only when the
`agents` increment is armed (`COLLEAGUE_AGENTS` / config.json `agents`). Kept
small: the task ledger is the authority, this is the read-side mirror the
ROI/feedback readers consume. An armed run always carries the key with the
SAME shape on every backend (the engine-side fold supplies the empty-lists
floor when the loop authored nothing); unarmed, the key is omitted.

<!-- contract:keys:agents -->
```text
fallbacks
invocations
ledger_digest
ledger_path
messages
version
```

`version` is `1`. `invocations[]` items are `InvocationRecord.to_dict()`
(identity + context manifest: refs and digests, never payloads);
`messages[]` items are `AgentMessage.to_dict()` (no rationale field, ever);
`ledger_path` / `ledger_digest` are the task-ledger pointer and its state
digest (`null` when no ledger was written).

##### `agents.fallbacks[]` item

<!-- contract:keys:agents_fallback -->
```text
from_role
purpose
resolved_model
```

One entry per invocation whose purpose ran on a fallback seat (its
`fallback_from_role` names the role it was carried *from*); `resolved_model`
is the served model id — trace data, never a constant.

#### `SensesBlock` (`senses`)

The cortex/senses front-door record. `injections` and `chat` are
omit-when-**empty** within this block (a split run with no live-presence talk
lane carries neither key) — the block below is the maximal shape (both
present).

**One shared shape serves every front** (presence-default-everywhere arc):
the interactive session, the `colleague talk` attach, a background run, the
mesh resident, and one-shot `colleague work` all record their middle-manager
beats (ack, proactive updates, clarify, guidance relay, the senses
coordination loop's turns) into this SAME `SensesBlock` shape — the same
fields below, the same `chat[].kind` vocabulary, the same `records[].point`
convention. No front defines its own record schema.

<!-- contract:keys:senses -->
```text
chat
injections
mode
packet
records
```

`mode` is e.g. `"split"` \| `"cortex-only"`. `injections[]` items are a
conventional (not dataclass-enforced) `{text, at, source}` shape — one per
applied operator-to-cortex guidance injection. `chat[]` items are a
conventional `{message, answer, relay, relay_text, latency, degraded, at}`
shape — one per live-presence talk-lane exchange.

##### `chat[]` entry `kind` values (`senses.chat[].kind`)

Every `chat[]` entry MAY carry an optional `kind` key; when it is **absent**
the entry is a `"talk"` exchange (today's pre-arc shape, unchanged — `kind`
is never injected by serialization, only ever implied). This is the ONE
closed vocabulary (`colleague.contract.SENSES_CHAT_KINDS`) every front draws
from:

<!-- contract:keys:senses_chat_kind -->
```text
ack
clarify
talk
update
```

- `"ack"` — the intake acknowledgment, rendered before cortex's first step.
- `"update"` — a cadence-gated proactive progress narration, grounded in the
  live flight-feed tail.
- `"clarify"` — a clarifying question/answer exchange before dispatch.
- `"talk"` — a reactive operator-initiated exchange (implied when `kind` is
  absent).

The senses coordination loop's operator-facing moves reuse this SAME
vocabulary rather than inventing a fifth kind: `reply_to_operator` folds as
`"talk"`, `dispatch_to_cortex` as `"ack"`, `clarify` as `"clarify"`. Its
`guide_cortex` move (a guidance relay) is **not** a `chat` entry at all — it
folds into `injections` instead, exactly like the live-presence talk lane's
own applied guidance. Its `read_flight` / `wait` moves are internal
bookkeeping only: a `records[]` entry (below), no `chat` entry.

`records[].point` stays free-form (e.g. `"senses-intake"`, `"senses-update"`,
`"senses-talk"`); the senses coordination loop's turns are additionally
recorded with the `"senses-loop:<move>"` prefix
(`colleague.contract.SENSES_LOOP_POINT_PREFIX`, e.g.
`"senses-loop:dispatch_to_cortex"`) so per-move loop turns stay
distinguishable from the fixed-beat points above — no new field, no new
record shape.

##### `ContextPacket` (`senses.packet`)

<!-- contract:keys:context_packet -->
```text
confidence
interpretation
omissions
original
task_type
```

`original` round-trips **verbatim** — never derived, trimmed, or normalized.

##### `SensesRecord` (`senses.records[]` item)

<!-- contract:keys:senses_record -->
```text
degraded
latency
point
tokens
```

## The feedback record + `last_work` pointer

`colleague feedback record <id|last> --rating N [--notes …] [--by …]`
(`colleague/feedback.py`) writes a **single record per work item** —
re-grading overwrites, it never appends a history.

<!-- contract:keys:feedback -->
```text
at
by
notes
rating
task_id
```

`rating` is an integer in `1..5` inclusive. `by` is the resolved identity (or
`""` when none resolves — rendered as `(unknown)` in text mode, never
guessed). `at` is an ISO-8601 UTC timestamp of when the grade was recorded.

The per-repo `last_work` pointer (a one-line text file, not JSON) names the
most recent work item's `task_id` so `feedback ... last` can resolve it
without the caller quoting an id.

## Artifact naming/layout on disk

Every write targets `.colleague/` in the repo (`colleague/artifact.py`
`DEFAULT_ARTIFACT_DIRNAME`); reads additionally fall back to the legacy
`.convertible/` dir for artifacts recorded before the rename.

| File | Contents |
|------|----------|
| `.colleague/<task_id>.<slug>.json` | The `TaskResult` artifact (bare `<task_id>.json` when no slug is derivable from the request). |
| `.colleague/<task_id>.<slug>.trace.jsonl` | One `Step` JSON object per line — the same stem as the result JSON. |
| `.colleague/<task_id>.feedback.json` | The feedback record — **never slugged**, always the bare `task_id`. |
| `.colleague/last_work` | A one-line pointer naming the most recent work item's `task_id` (legacy fallback: `last_drive`). |

The slug is a lossy, human-recognisable label (`colleague/slug.py`
`slugify(request)`); `task_id` stays the authoritative key throughout —
`colleague/artifact.py`'s `find_artifact` / `read_request` resolve **both**
the bare and the slugged filename, so a caller never needs to know which
scheme a given work item used.

## Exit-code semantics

`colleague work` / `colleague drive` translate `TaskResult.status` into the
process exit code:

| `status` | Exit code | Meaning |
|----------|-----------|---------|
| `"ok"` | `0` | Clean finish. |
| `"incomplete"` | `2` | The run ended without an explicit clean `finish` (step-budget exhaustion, a stop with no re-nudge success, etc.) — the artifact still carries a best-effort `summary`, but a caller MUST treat it as a partial, not an authoritative result. |
| `"error"` | `1` | The engine raised; `TaskResult.error` carries the message. |

## `colleague feedback export` — the ROI ledger line

`colleague feedback export [--min-rating N] [--since ISO-DATE] [--format
jsonl] --repo PATH` emits one JSON line **per graded work item** (an ungraded
work item — no feedback record — is excluded entirely; this is the "how good
was it" ledger, not `feedback list`'s full work-item inventory). `jsonl` is
the only supported `--format` value in v1 (also the default); an unrecognised
value is a clean CLI error, never a silent fallback. `--since` filters on the
work item's `stats.started_at` (the run's start time, not the grading time);
`--min-rating` keeps rows whose `rating >= N`. An empty/all-ungraded store
produces zero output lines and exits `0`.

<!-- contract:keys:export_line -->
```text
at
notes
rating
request
stats
status
summary
task_id
```

`at` is the feedback record's grading timestamp (not the work item's
`started_at`). `stats` is a slim summary, not the full `WorkStats` block:

<!-- contract:keys:export_line_stats -->
```text
bytes_written
files_changed
steps
```

## Versioning policy

| Change | Requires |
|--------|----------|
| New optional (omit-when-absent) key in the artifact/feedback/export shape | minor bump |
| Removed/renamed key, changed type, changed exit-code meaning | major bump (this contract's version, above) |
| New `colleague feedback` verb / new export flag | minor bump |
| New always-on (never omit-when-absent) top-level key | minor bump — a rare, deliberately RECORDED convention change (the same class of change as `stats`/WorkStats becoming always-on, and #313's `incompletion`); `finish_states` (decision c30) is the first since this contract froze at version `1`. |

A consumer that shells out to `colleague` and parses its JSON should pin a
package version and re-validate this document on upgrade — exactly the
discipline `data-refinery-cli`'s consumers already follow.
