# capacity-standard — colleague holds an opinion about its own context capacity

> When a turn's prompt crosses a tunable fraction of the context budget, colleague
> injects ONE decision prompt naming three moves — **compact**, **split**, or
> **finish-with-handoff** — and the model declares one by its next action. A
> separate warn-only signal fires when an assignment is too big for even an
> in-repo split.

The capacity standard (v1, #156) is colleague's **proactive** capacity decision.
It sits above the reactive [graceful-degradation](graceful-degradation.md) floor:
where degradation reacts to an overflow/timeout *after* it happens, the fill-line
decision acts *before* the window fills.

## The fill-line decision (`colleague/fillline.py` + `colleague/loop.py`)

When prompt tokens cross `COLLEAGUE_FILLLINE_THRESHOLD` (on
`EngineConfig.fillline_threshold`, default `0.8`) of the budget, the loop injects
one structured decision prompt with the capacity numbers. The model's next action
declares the move, recorded on `TaskResult.capacity_decision` (`{kind, reason}`,
omit-when-None; the singular field records the most recent crossing's decision):

- **compact** — a bounded model-authored summary turn replaces the working
  history, preserving the head `messages[:2]`. The summary is **validated**
  before it replaces history (`validate_compaction`, deterministic: goal +
  changed-file evidence appended when missing; an empty note is rejected —
  see [indefinite-run](indefinite-run.md)). On its own overflow it falls back
  to lossy windowing (the documented floor). This is the deliberate v0→v1
  graduation: it supersedes the old "no LLM-generated summary in v0" rule,
  recorded honestly.
- **split** — a `subagents` call routes through the existing
  [auto-split](auto-split.md) fan-out machinery, unchanged.
- **finish-with-handoff** — a `finish` records the continuation summary via the
  existing preserve-partial path.

The fill-line fires **per crossing of the line** (the indefinite-run arc
superseded v1's "at most once per work item"): a resolved offer re-arms once
the run drops back under the line, so a long run can compact repeatedly. Total
compaction turns are bounded by the compaction cap (`COLLEAGUE_COMPACTION_CAP`
env > `config.json` top-level `compaction_cap` > default
`DEFAULT_COMPACTION_CAP = 4`; `0` = unlimited); the cap reached suppresses
further offers, recorded once on
`TaskResult.capacity_warning` plus a phase notice, never silent. Lossy
windowing remains the floor. Detail:
[indefinite-run.md](indefinite-run.md).

## The "too big for one repo" warning (`colleague/capacity.py`)

A coarse up-front complexity assessment (deps / folders / files + an instruction
token estimate) sets `TaskResult.capacity_warning` when an assignment exceeds even
the in-repo split capacity. The `work` CLI emits it to stderr and records it in
the artifact. colleague performs **no cross-repo write** — the operator splits
across repos/instances.

## Honest limits

- Advisory, never forced; zero-dep; a strict no-op (byte-identical `TaskResult`)
  when no fill-line event occurs.
- The token budget is best-effort exact (exact via the vLLM `/tokenize` endpoint,
  char-approximate fallback otherwise); no third-party tokenizer is bundled.
- Runtime-owned (all-engines): fires identically for `mock` and `vllm-openai`.

## Key files

- `colleague/fillline.py` — the pure decision helpers + `apply_compaction` +
  `validate_compaction` + `DEFAULT_COMPACTION_CAP` (operator-tunable via
  `COLLEAGUE_COMPACTION_CAP` env > `config.json` top-level `compaction_cap`;
  `0` = unlimited; default `4`).
- `colleague/capacity.py` — the coarse complexity assessment.
- `colleague/loop.py` — injection + `_compact_history` + the decision wiring.

## Spec + plan

- [`docs/specs/2026-06-06-colleague-holds-a-standard-for-its-own-capacity-it.md`](../specs/2026-06-06-colleague-holds-a-standard-for-its-own-capacity-it.md)
- [`docs/plans/2026-06-06-colleague-holds-a-standard-for-its-own-capacity-it.md`](../plans/2026-06-06-colleague-holds-a-standard-for-its-own-capacity-it.md)
- Superseding arc (per-crossing re-arm + validation + episode chaining):
  [`docs/features/indefinite-run.md`](indefinite-run.md)
