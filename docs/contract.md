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

### Always-on top-level keys (15)

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
| `artifacts_path` | string \| null | Absolute path to this artifact's own JSON file. |
| `error` | string \| null | Set only when `status == "error"`. |
| `branch` | string \| null | The git handoff branch, or `null` when the run stayed local. |
| `pr_url` | string \| null | The opened PR URL, or `null` (`--no-pr` / no remote / no PR requested). |
| `hook_firings` | HookFiring[] | Every lifecycle-hook invocation — see [`hook_firing`](#hookfiring-hook_firings-item). |
| `command` | string \| null | The command-template name that originated this task, or `null` for an ad-hoc instruction. |
| `not_finished` | boolean | `true` iff the step budget was exhausted without a `finish` call (and without an abort). |
| `stopped_without_finish` | boolean | `true` iff the run ended on a no-tool-call turn and never called `finish`, even after the nudge. |

### Optional (omit-when-absent) top-level keys (16)

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
| `finish_recovered` | string | A `finish` transport failure was recovered (`"literal-markup"` \| `"thin-finish-synthesis"` \| `"meta-finish-synthesis"`). |
| `memory` | dict | The eidetic memory recall/remember cycle ran — see [`memory`](#memory-dict). |
| `media` | dict | The task carried attachments and their delivery was classified — see [`media`](#media-dict). |
| `senses` | SensesBlock | A cortex/senses split (or live-presence talk lane) ran — see [`senses`](#sensesblock-senses). |

### The maximal key set (drift-tested)

Every key above, together — the set a caller sees from an artifact where
**every** optional feature fired at least once. `tests/test_contract_doc.py`
builds exactly this `TaskResult` in code and asserts its `to_dict()` key set
equals this block.

<!-- contract:keys:top-level -->
```text
acceptance_outcomes
affected_tests_report
announcement
artifacts_path
branch
capacity_decision
capacity_warning
changed_files
command
coherence_report
deepthink
destination
error
finish_recovered
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
```

`tool_counts` is a `{tool_name: count}` map, not a fixed key set.

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
role
status
summary
task_id
usage
```

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

#### `SensesBlock` (`senses`)

The cortex/senses front-door record. `injections` and `chat` are
omit-when-**empty** within this block (a split run with no live-presence talk
lane carries neither key) — the block below is the maximal shape (both
present).

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

A consumer that shells out to `colleague` and parses its JSON should pin a
package version and re-validate this document on upgrade — exactly the
discipline `data-refinery-cli`'s consumers already follow.
