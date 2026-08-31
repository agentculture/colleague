"""Feedback/telemetry/organism catalog entries (feedback, telemetry, lobes, organs, coherence).

Split out of ``colleague/explain/catalog.py`` (docstring constants only, one
per ``colleague explain <path>`` topic group); see that module for ``ENTRIES``.
"""

from __future__ import annotations

_FEEDBACK = """\
# colleague feedback

Grade a work item **after the fact** — the second half of the outsourcing-ROI loop.
A work item's artifact already records what it *cost* (the always-on `stats` block:
elapsed time, tokens read/generated, tools used, bytes written, reasoning-vs-answer
sizes); `feedback` records how *good* it was. Together they let a caller — human
or agent — decide whether outsourcing that task to colleague (and to which
backend) paid off.

A work item is named by its `task_id`, or the literal `last` for the most recent
work item in the repo. Feedback is a **single record per work item** (re-grading
overwrites), stored as `.colleague/<task_id>.feedback.json` beside the artifact.

`last` resolves to the most recent **consequential** work item: `ask-colleague explore`
/ `review` run read-only in a throwaway worktree and **do not move** `last` (they
preserve their artifact and are graded by their printed `task_id`). When you ask
for `last`, the resolved work item's id + request is echoed to stderr, so a
mis-resolve is never silent. Forgotten the id? `feedback list` shows every work item
by request.

## Verbs

- `feedback record <id|last> --rating N [--notes ...] [--by ...] [--repo P]` —
  write a 1-5 quality rating + notes. `--by` defaults to the resolved identity.
- `feedback show <id|last> [--repo P] [--json]` — read a work item's feedback. An
  ungraded work item reads back as `no feedback yet` (a clean state, exit 0 — not an error).
- `feedback list [--repo P] [--json]` — list every recorded work item in the repo,
  newest-first, with its request, status, and grade (`--` when ungraded). The
  durable way to find the right work item when the order is forgotten.
- `feedback overview` — describe this surface.

## Usage

    colleague feedback record last --rating 4 --notes "correct but verbose"
    colleague feedback record 9f2c1ab0 --rating 5 --repo . --json
    colleague feedback show last --repo .
    colleague feedback list --repo .

## Record shape

    {"task_id": "...", "rating": 4, "notes": "...", "by": "...", "at": "<ISO-8601>"}

`rating` must be an integer 1-5. There is no tokenizer, so the artifact's
reasoning/written sizes are exact chars/bytes, never estimated tokens — see
`colleague explain work` for the stats block.

## See also

- `colleague explain work`
- `colleague explain ask-colleague`
"""

_TELEMETRY = """\
# colleague telemetry

Telemetry for a work item: opt-in OpenTelemetry **traces + metrics** over OTLP. Telemetry
belongs to the runtime — it is instrumented once in the loop and the shared work
path, so *every* backend emits identical signals (the all-engines rule), exactly
like lifecycle hooks.

Off by default. The OpenTelemetry SDK is an **optional extra** (the base install
keeps zero runtime dependencies); enable it with the env var and install the
extra:

    pip install 'colleague[otel]'
    export COLLEAGUE_OTEL_ENABLED=1
    export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318   # OTLP/HTTP collector

When requested without the extra installed, colleague degrades to a no-op with
a one-line stderr notice — it never fails the work item.

## Signals

- spans: `colleague.work` (root) -> `colleague.tool.*` (per tool call) plus
  `colleague.handoff`.
- metrics: `colleague.steps`, `colleague.tokens` (attr `kind`),
  `colleague.generated.chars` (attr `kind`=reasoning|answer), `colleague.bytes_written`,
  `colleague.tool.latency`, `colleague.tool.calls`, `colleague.hook.denials`,
  `colleague.work.duration` (attr `status`).

## Configuration

Precedence (highest first): explicit > `COLLEAGUE_OTEL_*` > standard `OTEL_*` >
default. `OTEL_SDK_DISABLED=true` is honored as a kill-switch.

- `COLLEAGUE_OTEL_ENABLED` — turn telemetry on (default: off).
- `COLLEAGUE_OTEL_ENDPOINT` / `OTEL_EXPORTER_OTLP_ENDPOINT` — collector URL.
- `COLLEAGUE_OTEL_SERVICE_NAME` / `OTEL_SERVICE_NAME` — resource `service.name`.
- `COLLEAGUE_OTEL_METRICS_ENABLED` — toggle metric emission (default: on).

## Usage

    colleague telemetry status
    colleague telemetry status --json
    colleague telemetry overview

## See also

- `colleague explain work`
- `colleague explain hooks`
"""

_LOBES = """\
# colleague lobes

Inspect colleague's connection to a **lobes gateway** — the cortex/senses arc's
single upstream that serves multiple typed model roles behind one
`/capabilities` endpoint. Colleague resolves exactly two of those roles:

    cortex   the fast, wide-window reasoning mind that drives the tool loop
    senses   the tools-off multimodal front door (intake / normalize /
             classify_intent / prepare_context_packet / speak_back)

The gateway may serve more roles (`embedder`, `reranker`, `stt`, `tts`); this
noun reports only `cortex` + `senses` — colleague resolves nothing else today.

## Armed state + degradation rung

`lobes show` is read-only (one `GET /capabilities`, stdlib `urllib`, never
raises) and reports exactly one of three rungs:

- `not_configured` — `COLLEAGUE_LOBES_URL` is unset; a clean, honest message,
  exit 0 (not an error).
- `armed_reachable` — the gateway answered; the resolved `cortex`/`senses`
  metadata is shown (model, context window, endpoint, ready flag,
  responsibilities, forbidden_responsibilities).
- `armed_unreachable` — a URL is set but the gateway did not answer (down,
  timed out, non-200, or a malformed response); reported honestly, exit 0.

**Scope note:** this noun's ONLY armed signal is `COLLEAGUE_LOBES_URL` env. It
does not (yet) consult a `lobes` section in `.colleague/config.json` — that
fuller precedence chain (explicit flag > env > config.json > builtin) is a
separate, later config-resolution concern (the runtime's own lobes discovery
rung), not this introspection noun's job.

## Usage

    colleague lobes show
    colleague lobes show --json
    colleague lobes overview

## See also

- `colleague explain roles`
- `colleague explain config`
- `colleague explain organs`
"""

_ORGANS = """\
# colleague organs

colleague is the operator front for a small **organism** of sibling CLIs — each
an independent repo, each behind its own published contract
(issue #291, requirement R10). `organs list` shows what is wired in, and
whether it is actually here, with **zero network calls**.

## The curated table

A hand-maintained table (`colleague/oilcheck/organs.py`'s `ORGANS`) — NOT a
dynamically discovered plugin registry:

    lobes           discovery rung (colleague/lobes.py + config.py precedence)
    eidetic         memory shell-out (colleague/memory.py)
    coherence       gate — planned colleague#294 (S3); not yet built
    sloth           experiment noun (colleague/experiment.py; allow-list sloth,
                    colleague#295 S5)
    data-refinery   dataset pipeline — planned data-refinery-cli#14 (S6); not
                    yet built colleague-side
    agtag           culture tool (colleague/culture.py allow-list)
    devex           culture tool (colleague/culture.py allow-list)
    devague         destination tool (colleague/devague.py allow-list)

For each organ this reports **presence** (`shutil.which` on its binary),
**version** (`importlib.metadata.version` on a curated binary→distribution
mapping — many organs are installed as isolated CLI tools, e.g.
`uv tool install`, so a present binary very often still reads `"unknown"`; that
is the expected honest case, not a bug), and **armed** (read from colleague's
own config resolution — env vars, `.colleague/config.json`, and for the memory
organ a plain filesystem check for `.eidetic/`; never a network call).

The full per-organ writeup — what it owns, its contract artifact, and its own
respected non-goals — lives in [`docs/organs.md`](../../docs/organs.md).

## One resolver, two views

`colleague doctor`'s organs check-group and `colleague organs list` render the
SAME resolver (`resolve_organs`), so they can never disagree: `doctor` turns
each entry into a pass/fail health check (a missing/not-yet-wired organ is
always a `warning` with a `uv tool install <distribution>` remediation hint,
**never** unhealthy); `organs list` shows the full table.

`doctor --probe` additionally probes the lobes gateway's live
`GET /capabilities` reachability (reusing `colleague.lobes.resolve_roles`) —
probe-only, never part of the zero-network registered group.

## Usage

    colleague organs list
    colleague organs list --repo PATH
    colleague organs list --json
    colleague organs overview
    colleague doctor              # organs appear as organ_<name> checks
    colleague doctor --probe      # + lobes gateway reachability

## See also

- `colleague explain doctor`
- `colleague explain lobes`
- `colleague explain config`
"""

_COHERENCE = """\
# colleague coherence

On-demand coherence measurement of colleague's work artifacts. Coherence scores
measure the semantic quality of documentation (``*.md`` files) via the
operator-installed ``coherence`` CLI (Meaning Gradient). The measurement is
**advisory** and **never a gate**: it informs but never blocks the work item
handoff.

## Verbs

- ``coherence overview`` — describe the coherence surface (what it is, that it is
  advisory and never a gate). Always exits 0.
- ``coherence score PATH [PATH...]`` — score one or more markdown files directly
  by reusing the existing scoring machinery in ``colleague/coherence.py``.
  Supports ``--json`` for structured output including embedding-frame provenance.
- ``coherence show TASK_ID|last`` — resolve a finished work item's artifact,
  score its recorded changed ``.md`` files if any, and report the artifact's
  existing ``coherence_report`` block when present.

## Degradation

When the ``coherence`` CLI is not installed (``shutil.which`` returns ``None``):
``overview`` still exits 0; ``score``/``show`` raise a structured ``CliError``
with a remediation hint (``uv tool install coherence-cli``).

## Usage

    colleague coherence overview
    colleague coherence score README.md
    colleague coherence score --json CHANGELOG.md docs/guide.md
    colleague coherence show last
    colleague coherence show abc123 --repo /path/to/repo

## See also

- `colleague explain feedback` — grade a finished work item
- `colleague explain organs` — the coherence organ in the organism map
"""
