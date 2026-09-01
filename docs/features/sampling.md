# Per-model sampling defaults + the repetition guard (#479)

> Every seat's completion carries the **model card's** sampling values for the
> half its already-resolved effort rung selects — thinking when a rung is armed,
> non-thinking when effort is `off` — instead of the hard-coded greedy
> `temperature 0.0` colleague sent before. A model colleague holds no card for
> sends **no sampling keys at all**. A model-independent guard cuts a turn whose
> reasoning has started repeating itself verbatim instead of riding it into the
> output budget.

Two halves, independently falsifiable: the sampling table
(`colleague/sampling.py`, `colleague/samplingwire.py`,
`colleague/samplingfile.py`) and the repetition guard
(`colleague/repetitionguard.py`). The kill switch `COLLEAGUE_SAMPLING=0`
restores the pre-#479 payload.

**Every number on this page is pinned by `tests/test_sampling_docs.py`** — a
value here that diverges from the shipped constant fails the suite. Read a
figure here as checkable, not as prose.

## Audience

The colleague **operator** running work items on a Qwen3.8 vLLM rig, and every
**seat** colleague builds (cortex, worker, deepthink, senses, evaluator, scout,
subagent children, the distill child) — each of which previously inherited one
hard-coded `temperature 0.0` regardless of whether its thinking was on or off.

## The builtin table (`BUILTIN_SAMPLING_ROWS`)

The FIXED builtin table holds the Qwen3.8-27B card values recorded in
issue #479, both halves. `—` means the field is **not set** by that row, and an
un-set field is never sent.

| key | thinking | non-thinking |
|-----|----------|--------------|
| `temperature` | `1.0` | `0.7` |
| `top_p` | `0.95` | `0.8` |
| `top_k` | `20` | `20` |
| `min_p` | `0.0` | — |
| `presence_penalty` | `0.0` | `1.5` |
| `repetition_penalty` | `1.0` | — |

The recognised keys are exactly those six (`SamplingProfile`'s fields, and
`samplingwire.SAMPLING_COERCERS`' key set). `role` on both builtin rows is
`None`: a card is a property of the **checkpoint**, not of the seat that dials
it. A per-seat row is an operator override, never a builtin.

**The half is derived from the rung, never re-resolved.** Under the #416 ladder
(see [thinking-effort.md](thinking-effort.md)) `off` **is** the model's
non-thinking mode and every other rung is the thinking half.
`sampling.half_for_rung` consumes the rung `vllm_payload._effort_for` already
computed; `None`, the `default` kill-switch sentinel, and any value off the
ladder each select **no half**, and therefore no sampling keys.

## The row is the card; the wire is the row minus the server's own defaults

`colleague/samplingwire.py` is the one module in the tree that names the vLLM
extension keys. It drops any key whose value already equals the server default,
because sending it changes nothing while widening colleague's non-OpenAI
surface:

| key | value treated as the server default |
|-----|-------------------------------------|
| `top_p` | `1.0` |
| `min_p` | `0.0` |
| `presence_penalty` | `0.0` |
| `repetition_penalty` | `1.0` |

`temperature` is deliberately **absent** from that table: a payload builder
always writes a temperature, so a row's temperature is an *override* of an
existing key — filtering it would leave the pre-#479 greedy `0.0` on the wire,
the exact bug this arc fixes. `top_k` is absent too, because vLLM spells
"disabled" as `-1` or `0` depending on version, so there is no single
unambiguous default to compare against.

What actually reaches `/chat/completions` for the builtin rows:

| key | thinking | non-thinking |
|-----|----------|--------------|
| `temperature` | `1.0` | `0.7` |
| `top_p` | `0.95` | `0.8` |
| `top_k` | `20` | `20` |
| `min_p` | — | — |
| `presence_penalty` | — | `1.5` |
| `repetition_penalty` | — | — |

## The fourth carve-out

`temperature`, `top_p` and `presence_penalty` are plain OpenAI keys and need no
carve-out at all. On the builtin table **`top_k` is the only vLLM extension key
that reaches the wire** — which is why the fourth carve-out to "the vLLM adapter
only touches the OpenAI surface" (CLAUDE.md conventions, beside `/tokenize`, the
armed-lobes stale-pin refresh and the `chat_template_kwargs` ladder key) is
narrow: **the sampling keys a matched row explicitly sets**. `min_p` and
`repetition_penalty` remain RECOGNISED fields an operator may set, and are sent
only when a row sets them to something other than the server default.

**No retry-without-sampling-keys path ships**, and that asymmetry with the
ladder-400 retry is deliberate, not an omission: exposure is already bounded,
because a model id matching no profile row sends no sampling keys at all. Only
an operator who explicitly matched or declared a profile can present the
extension keys to a server that refuses them, and that 400 surfaces exactly as
it does today. If a future server makes this a real degrade case it earns its
own retry path and its own measurement — never a speculative one.

## The match rule (`normalize_model_id`)

Three strings name one model in this repo's own evidence: the rig serves
`unsloth/Qwen3.8-27B-NVFP4`, the card the values come from is
`Qwen/Qwen3.8-27B`, and the probe record names `Qwen3.8-27B-NVFP4`. An
exact-match rule would match none of them — and combined with
"unmatched sends nothing" a keying miss would ship as a green feature over an
unchanged greedy payload. So matching normalises: drop the organisation prefix,
strip quantisation suffixes repeatedly (longest first), lowercase.

| served id | normalises to | matches a builtin row |
|-----------|---------------|-----------------------|
| `unsloth/Qwen3.8-27B-NVFP4` | `qwen3.8-27b` | yes |
| `Qwen/Qwen3.8-27B` | `qwen3.8-27b` | yes |
| `qwen3.8-27B-W8A8-INT8` | `qwen3.8-27b` | yes |
| `Qwen/Qwen3.8-4B` | `qwen3.8-4b` | no |

Ids are **enumerated per row, never a loose prefix**: `Qwen3.8-4B` is not
`Qwen3.8-27B` and must not inherit the 27B card just because the names share a
prefix. A checkpoint colleague has no card for gets no sampling keys — the
honest degrade, and the reason the live served id is pinned as a test fixture:
a rig rename cannot silently disarm the profile.

## Resolution

`sampling.resolve_sampling(model, role, rung, rows)` is most-specific-wins:

```text
model + role + half  >  model + half  >  role + half  >  half
```

At **equal** specificity the LAST matching row wins, which is how an operator
table layered after `BUILTIN_SAMPLING_ROWS` overrides a builtin row rather than
being shadowed by it. It returns `None` — meaning *no sampling keys at all* —
when the rung yields no half, or when no row claims the model.

**Two statements that sit uneasily together, reconciled explicitly.**
`BUILTIN_SAMPLING_ROWS` deliberately contains **no `models=()` any-model row**,
and that absence is *why* an unmatched model sends nothing. But the ladder does
support a `models=()` row, so an operator any-model row placed in
`.colleague/models.json` would override that guarantee. Today it cannot: the
`models.json` consumer builds every row as `models=(model_key,)` from the file's
model-id key, so the file has no way to express an any-model row. If a later arc
adds one, the "unmatched sends nothing" guarantee holds only for operators who
declined it — say so there rather than leaving this page's guarantee to rot.

## `.colleague/models.json` — the operator table

### Schema

One JSON object keyed by **model id**; each model's value is keyed by **half**;
each half is a flat object of sampling key/value pairs:

```json
{
  "unsloth/Qwen3.8-27B-NVFP4": {
    "thinking": {"temperature": 0.9, "top_p": 0.95, "top_k": 20},
    "non_thinking": {"temperature": 0.7, "top_p": 0.8, "top_k": 20}
  },
  "some-other-model": {
    "instruct": {"temperature": 0.6}
  }
}
```

Accepted half labels, lowercased with `-` folded to `_` before lookup:

| label | half |
|-------|------|
| `thinking` | thinking |
| `non_thinking` | non-thinking |
| `nonthinking` | non-thinking |
| `instruct` | non-thinking |

An unrecognised label contributes no row. Recognised value keys are the six in
the builtin table; an unrecognised key or an unparseable value is dropped
**individually** (booleans included), so one typo never costs an operator the
rest of the row — and never refuses a run. A missing file, invalid JSON, a
non-object top level, or a non-object model entry are all silently skipped.

### Merge granularity — per model key

Every `models.json` across `configdir.config_roots` is read (repo before user)
and folded lowest-precedence-first, so a repo file's model entries overwrite
same-named user entries. Worked example: a user-level
`~/.colleague/models.json` declaring `model-a` and a repo-level
`.colleague/models.json` declaring `model-b` resolve to **both** rows — the
repo file naming one model does not erase a rig-wide row for a *different*
model. Within one model id the entry is taken **wholesale** from the
highest-precedence file that supplies it: there is no deep merge inside a
model's halves. That is `config_files`' top-level-key merge, one level deeper
(model id instead of a config.json section name).

### Tracked at HEAD — and what that costs mid-measurement

`models.json` is the one thing under `.colleague/` that is **not** gitignored
(`artifact._SELF_IGNORE` allow-lists `!models.json` beside `commands/` and
`skills/`). That is the whole point: `work`/`drive` run in a throwaway git
worktree checked out at HEAD ([write-isolation.md](write-isolation.md)), and a
gitignored file simply does not exist inside that worktree — an operator's rows
would silently vanish the moment a run went isolated.

The consequence, which will surprise someone mid-arm: **an uncommitted edit to
`models.json` does not reach a dispatched work item.** The worktree is created
at HEAD on `colleague/<id>`, so tuning sampling mid-measurement means
*committing* the change. This is the same rule every tracked file follows; it is
stated here because the failure is silent.

It also settles the file format by constraint rather than preference: JSON, not
YAML, because PyYAML is forbidden here and `tests/test_zero_deps.py` allow-lists
exactly `agentfront`.

### Why `models.json` and not `agents.json` — the four recorded reasons

So a later arc proposing to rename or fold this file finds the argument it has
to answer rather than re-deriving it:

1. **`agents` is already a live key with a different meaning.** It is a boolean
   inside `config.json` arming the #411 execution mode (`config_seats.py`), so
   the word has a settled and different meaning in this config directory.
2. **Sampling is default-on; #411 is opt-in and byte-identical when unarmed.**
   A default-on path must not read an opt-in mode's file.
3. **Card values are facts about a MODEL, and many roles share one model.**
   Keying by agent would duplicate one published fact across every seat that
   uses it, and let the copies drift.
4. **#411 discovers models, it does not declare them.**
   `AgentProfile.resolved_model` is explicitly trace data filled from
   `RoleInfo`.

If an agents definition file is ever built, it **references** `models.json`
rather than absorbing it.

### Two limits of the file format

- **No role dimension.** The shape is model → half → keys, with no role level,
  so every operator row resolves with `role=None` and claims **any seat**. The
  builtin ladder supports `model + role + half`; the file format does not. A
  per-seat operator row needs a file-format change; the consumer deliberately
  does not invent a role nesting.
- **The override is ROW-level, not key-level.** `resolve_sampling` returns one
  row's whole profile, so an operator row naming only `temperature` also drops
  the builtin's `top_p` and `top_k` for that half. Restate the whole half, not
  the one key you meant to change.

## Knobs

| variable | status | effect |
|----------|--------|--------|
| `COLLEAGUE_SAMPLING` | permanent kill switch | `0`, `false`, `no`, `off` (case-insensitive) — send no sampling keys at all; the pre-#479 payload, key for key |
| `COLLEAGUE_TEMPERATURE` | deprecated for one release | still read, still applied, plus a warning naming `.colleague/models.json`; removed the release after |
| `CONVERTIBLE_TEMPERATURE` | removed | ignored, and a run that sets it gets a loud warning |

The kill switch is **per-process, and carries no value**, both deliberately.
Per-process because `models.json` is tracked and therefore shared by every
colleague process on the checkout — only an environment variable lets two
concurrent arms (an A/B, or a byte-identical control) differ on one working
tree, and file-absence is not an off-state for a model the builtin table
matches. Value-free because, unlike a global temperature, it cannot flatten a
model's two halves into one number.

There is **no value-carrying environment rung for sampling**, which is what
stops a single scalar collapsing a model's two halves. The deprecated
`COLLEAGUE_TEMPERATURE` still can during its grace period — and it is set to
`1.0` in this operator's environment today, matching the card's thinking value
while silently overriding the non-thinking `0.7`. The deprecation warning is
what makes that visible; the trap closes for good when the variable does.

## `config show`

`config show` states the sampling match **positively**, beside the effort lines
it derives its half from: the row that matched and the model it matched for,
what goes on the wire, and what was dropped as already the server default — or
an explicit `no row matched` line. A deliberately misspelt model id renders as
no-row-matched rather than resolving quietly to a default.

Two honest limits, both real today:

- **It renders the BUILTIN table only.** `_sampling_section` resolves with
  `rows=None`, so the operator `models.json` rows the adapter *does* apply are
  not reflected. An operator who overrides a builtin row therefore sees one
  thing in `config show` and sends another. Small follow-up: pass the same rows
  `vllm_payload._operator_sampling_rows` builds.
- **Its kill-switch line fires only on the literal `0`.** The adapter disables
  sampling on `0`, `false`, `no` or `off`; `config show` reports the switch
  armed only for `== "0"`. So `COLLEAGUE_SAMPLING=off` sends no sampling keys
  while `config show` still prints the match with no kill-switch line.

## The repetition guard

`colleague/repetitionguard.py` ports **only** the verbatim-tail tier of
qwen-code's repetition detector. The entropy/content tier is off upstream for
false positives and is explicitly NOT ported. This reverses a decision
`loopguards.py`'s docstring recorded — declining the repetition tier — on the
evidence below, accepting the false-positive story below.

| constant | value |
|----------|-------|
| `TAIL_REPEAT_MIN_LENGTH` | `48` |
| `TAIL_REPEAT_MIN_COUNT` | `8` |
| `MAX_BUFFER_CHARS` | `8192` |
| `ESCALATION_TRIP_LIMIT` | `3` |

A trip fires only when a substring of at least `TAIL_REPEAT_MIN_LENGTH`
characters — the *fundamental* repeating unit, not an accidental multiple of a
shorter one — recurs verbatim and immediately adjacent at least
`TAIL_REPEAT_MIN_COUNT` times at the very end of the buffer.

**Trip semantics differ from `loopguards`.** `loopguards.check` drops the turn's
pending calls and ENDS the run; a repetition trip cuts only the **turn** and
hands it to the tighter-window retry path that already exists — the path that
recovered the incident run. A false positive therefore costs one turn, not one
work item. To stay bounded, trips escalate: the `ESCALATION_TRIP_LIMIT`-th trip
in one run ends the run with the warning, so the guard can never cycle forever.
Detector state is a plain dict threaded through `check`, never module-global, so
concurrent children (`subagents_batch`' thread pool) never share a detector.

### A reproduced false POSITIVE

An 84-character boilerplate narration line repeated **8 times back-to-back**
inside one turn trips the guard. Seven repeats do not, and interleaving any
varying text between the repeats does not. Found by an `ask-colleague` review
(task `4754361a0229`) and reproduced independently; `tests/test_sampling_docs.py`
reproduces it again on every run, so this page cannot claim a threshold the
detector does not have. The arc records the limit rather than weakening the
detector, because the cost is bounded: one turn into the existing retry, never
the run.

### A false NEGATIVE

The detector keeps only the trailing `MAX_BUFFER_CHARS` (8192) characters, so a
runaway that **recovers within the last 8 KB** never trips. The guard catches a
turn that is still repeating when it is looked at, not one that repeated and
stopped.

### A cut turn's tokens are unrecorded, not zero

Aborting the SSE read discards the final usage frame (`include_usage` delivers
usage on the LAST chunk), and CLAUDE.md pins that tokens are exactly what
`usage` reports and are never estimated. So a guard-cut turn's tokens are
**unrecorded**. They are not free, and nobody should read the artifact as if
they were: the guard's warning carries `reasoning_chars` the way the
truncated-turn warning already does.

## Recorded evidence

Everything in this section is also recorded as **row 66b** of
[live-testing.md](../live-testing.md), beside row 66 (the greedy `low` run it
comes from), so the ledger and this page cannot tell two stories.

### The incident this arc exists for

Run `2bd306a6916a` (`low` effort, greedy `temperature 0.0`, thinking armed;
artifact and reasoning sidecar under
`.colleague/2bd306a6916a.*` in the `rerun-low-arm` worktree). Read off the
artifact, not the issue text:

- `status: error`, 31 steps, 22 model turns, **651,679 reasoning characters
  total**;
- one warning: `{kind: truncated-turn, finish_reason: length,
  reasoning_chars: 271486, step_index: 20}` — a single turn of 271,486
  characters, killed by the output budget before any answer;
- the per-turn sidecar profile (`turn: characters`) is
  1: 320, 2: 227, 3: 34, 4: 34, **5: 46,998**, 6: 364, 7: 151, 8: 21,997,
  9: 35,149, 10: 60,747, 11: 99,658, 12: 1,326, 13: 78,049, **14: 271,486**,
  15: 2,811, 16: 50, 17: 236, 18: 76, 19: 9,769, 20: 7,087, 21: 14,936,
  22: 174.

**Correction to the spec's paraphrase, recorded rather than smoothed.** The spec
says "turns 1 through 11 reasoned sharply"; the sidecar says the escalation
begins at **turn 5** (46,998 characters) and turn 11 is already 99,658. What the
sidecar does support is the second half of the claim: after the harness retried
with a tighter window the model returned to short turns (16: 50, 17: 236,
18: 76, 22: 174), with three mid-sized turns (19–21, 7k–15k) in between. The
model was looping, not failing — but the loop starts earlier than the spec's
sentence implies.

Run `4b74a1bd5a9b` (artifact in this repo's `.colleague/`) is the second half of
the evidence: `status: incomplete`, one warning
`{kind: loop-guard, guard: identical-calls, tool: write_file, repeats: 5,
limit: 5, dropped: 1}` — five identical `write_file` calls.

### Four live probes, 2026-09-01, with their limits

Run against the operator's own lobes gateway at `localhost:8001` serving
`Qwen3.8-27B-NVFP4`, during the spec pass. These are **recorded probe results,
not tests**: nothing in the suite re-runs them.

1. **The gateway forwards and vLLM honours the extension keys.** `top_k: 1` at
   `temperature 2.0` returned three **byte-identical** completions; the same
   request without `top_k` returned three different ones (one containing the
   garbled token "Reykitanjör"). *Limit:* this proves the key reached the
   sampler on THAT rig at THAT time; it is not a guarantee for another server.
2. **A 200 proves nothing.** An invented body key `colleague_bogus_key` also
   returned HTTP 200 — unknown body keys are silently ignored. So **no test may
   treat a status code as proof that a profile applied**, which is exactly why
   probe 1 had to be a determinism experiment. It is also the property that
   makes the degrade story safe. *Limit:* one gateway at one version — a
   different server may instead *reject* an unknown key with a 400, which is
   the case the "unmatched model sends nothing" bound covers rather than a
   retry path.
3. **`presence_penalty 1.5` is harmless to tool calling and to bulk code
   emission.** Tool calling: 3/3 well-formed parallel calls, same as the 0.0
   control. Code emission: 154 lines against a 158-line control, with **zero**
   non-ASCII characters — no language mixing, the specific degradation the card
   warns about. *Limit:* one model, one rig, a small sample and structural
   metrics only; it rules out the obvious catastrophic failure, not subtle
   quality loss, and the generated code's correctness was not evaluated.
4. **Aborting the SSE read does stop generation.** GPU utilisation fell from 95%
   to 3% within about six seconds and stayed there, so the guard's cut saves
   real GPU time on a shared rig, not merely colleague's wall-clock. *Limit:*
   observed via GPU utilisation, not a server-side confirmation, and
   utilisation was already 95% from a prior killed request — what is measured is
   that closing every client connection returns the origin to idle.

The definitive sampling arm — the preserved brief rerun at the full Qwen3.8
thinking profile — is a **separate** task and is **not** recorded here. Until it
lands in [live-testing.md](../live-testing.md), nothing on this page claims the
sampling change made a run complete that greedy decoding did not.

## Honest limits

- The four probes above are **recorded observations, not tests**. A rig change
  that stops honouring `top_k` is not caught by this suite.
- `config show` renders the builtin table only, and its kill-switch line fires
  only on the literal `0` (see [`config show`](#config-show)).
- Operator rows carry no role dimension and override at row granularity, not key
  granularity (see [Two limits of the file format](#two-limits-of-the-file-format)).
- The guard's reproduced false positive and its 8 KB false negative are above,
  unweakened.
- Only the two Qwen3.8-27B rows ship. Every other checkpoint sends nothing, by
  design — colleague never guesses a profile for a model it has not measured.
- The associate seat is **out of this system**: `_apply_associate_profile`
  already replaces `temperature`/`top_p` and sends an `enable_thinking` boolean
  on its own lane, selected by profile NAME rather than by the effort rung. An
  armed associate payload is byte-identical before and after this arc. The arc
  therefore ends with **two** sampling surfaces, documented honestly as two; the
  fold-in is a deferred follow-up.
- The two diagnostic probes in `colleague/oilcheck/` keep their hard-coded
  `temperature 0.0`: they are determinism probes, not reasoning work.

## Key files

- `colleague/sampling.py` — the frozen profile, the builtin table, the match
  rule, the resolution ladder.
- `colleague/samplingwire.py` — the server-default filter and the recognised-key
  coercers; the ONE module that names the vLLM extension keys.
- `colleague/samplingfile.py` — the `.colleague/models.json` loader and its
  per-model merge.
- `colleague/engines/vllm_payload.py` — the single write site
  (`_sampling_fragment`) and the kill switch.
- `colleague/distill.py` — the second completion site, resolving the same
  profile through the same two modules.
- `colleague/repetitionguard.py` — the detector; `colleague/loop_transport.py`
  holds the trip semantics.
- `tests/test_sampling_docs.py` — the doc-agreement gate for this page.

## See also

- [thinking-effort.md](thinking-effort.md) — the rung this table's half is
  derived from, and the third carve-out.
- [config-resolution.md](config-resolution.md) — where `models.json` sits beside
  `config.json`.
- [model-selection.md](model-selection.md) — how the model id this table matches
  on is resolved.
- [engines.md](engines.md) — the vLLM adapter and its OpenAI-surface convention.
- [write-isolation.md](write-isolation.md) — why a tracked file is what reaches a
  dispatched run.
