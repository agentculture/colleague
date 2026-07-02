# Media Input

Hand colleague a screenshot, a diagram, or a voice note along with your task —
in the interactive session, from the CLI, or over the mesh — and it works from
the media directly. Attachments ride the task contract to a multimodal main
model, and colleague **verifies the model actually received them** instead of
trusting a 200.

Spec + plan: `docs/specs/2026-07-02-hand-colleague-a-screenshot-a-diagram-or-a-voice-n.md`
and the matching `docs/plans/` file.

## Three surfaces, one plumbing

All three entry points converge on the same `Task.attachments` field
(`{path, media_type}` entries, validated by `colleague.media.validate_attachment`,
omit-when-None — an attachment-less task serializes byte-identically; pinned by
`tests/test_media_parity.py`):

- **Out of chat (CLI):** `colleague work "<task>" --attach shot.png` —
  repeatable, validated at parse time (a missing file or unknown extension is a
  clean structured error naming the path). Composes with `--command`
  (`tests/test_cli_attach.py`).
- **In chat (session):** `/attach <path>` stages an attachment for the NEXT
  work line (repeatable, in order; `/attach` alone lists what's staged). The
  staging list clears one-shot after the work line consumes it
  (`tests/test_session_attach.py`).
- **As a service (resident/mesh):** a request body may carry line-anchored
  `attach: <path>` references (capped at 4; extras noted, never silent). See
  the trust rule below (`tests/test_resident_media.py`).

The loop builds the initial user message as OpenAI content parts (one text
part + one part per attachment) only when attachments are present; without
them the message stays a plain string — the byte-identical baseline
(`tests/test_loop_media.py`). Parts are standard OpenAI shapes only
(`image_url` data-URI, `input_audio`), so retargeting another
OpenAI-compatible server stays a config change (`tests/test_engine_parts.py`).

## Mesh media trust (anti-exfiltration)

Only the **operator identity** may attach arbitrary operator-local paths. A
non-operator's `attach:` reference must resolve **inside the target repo
working tree** — resolve-then-contain, so a symlink living inside the repo but
pointing outside it is refused too — and the request still runs read-only
under the explorer role (the existing c19 trust seam; media adds no new trust
decision path). A refusal is recorded with a reason naming the path and the
rule; it never crashes the request. A mesh peer cannot exfiltrate `~/.ssh` by
asking colleague to look at it as an image.

## `view_media` — the media sibling of `read_file`

A read-only loop tool that loads a repo image into the conversation as a
content part mid-work: same `_safe_path` confinement, a 4 MB size cap named in
its refusal, images only. Curated into every read-only role (pure read); the
role-aware executor refuses a withheld call. The tool message stays a plain
string — the image rides a follow-up user parts message (the wire-safe
convention every OpenAI-compatible server accepts). `tests/test_view_media.py`.

## Delivery verification — delivered vs comprehended (decision c25)

After the first media-bearing completion the runtime compares the server's
reported `prompt_tokens` against a locally-counted text-only baseline. An
image contributes ~hundreds of prompt tokens (~260/tile, live-probed); a
silent drop contributes ~0 — the exact signal the live probe exposed. Zero
extra model turns. Recorded on the omit-when-None `TaskResult.media`:

- `delivered` — contribution cleared the per-part floor (half a tile), so the
  media **entered the prompt**. This never claims the model *understood* it —
  comprehension is claimed only by the livecheck red-pixel proof.
- `dropped` — a 200-OK response whose media contributed nothing (the rig's
  historical audio behavior), warned on stderr.
- `unknown` — the server reported no usage; a drop is never claimed without
  evidence.
- `bridged` — the media bridge delivered a description via the second model
  (below).

`tests/test_media_delivery.py`.

## Graceful degradation on a media-refusing endpoint

A text-only served model does not silently drop an image part — it **rejects
the request** (live-probed: `HTTP 400: At most 0 image(s) may be provided in
one prompt`). The loop classifies that refusal
(`colleague.context.is_media_rejection`), flattens every parts message to text
placeholders, retries once (structurally bounded — no parts remain), records
the media `dropped`, and the run continues instead of hard-failing.
Live-verified end-to-end: the same `--attach` run that 400-failed completes
`status: ok` with the model honestly reporting it sees no image.

## The media-comprehension bridge (operator decision c24)

When the **main model is text-only** and the task carries media, the runtime
escalates a media-bearing digest **tools-off to the declared multimodal second
model** (the inverse of the deepthink flattening rule) and folds the returned
description back as ONE advisory message — so attachments are useful on
today's rig (27B main + Gemma4 vision) before the Gemma-as-main flip.

- Armed only by operator declaration: `COLLEAGUE_DEEPTHINK_MULTIMODAL=1` (or
  `config.json` `{"deepthink": {"multimodal": true}}`) on top of a dual-model
  config — never probed or inferred from a model name.
- The declared-text-only main wire carries **no parts at all** (it would 400):
  it gets the flattened placeholders; the real parts travel only on the bridge
  escalation, windowed to the second model's own budget minus a per-part
  reserve.
- Recorded as `TaskResult.deepthink` `{point: "media-bridge"}` + media status
  `bridged`; a bridge failure degrades (verifier records honestly), never
  raises. Strict no-op single-model / no-media / undeclared.

`tests/test_media_bridge.py`.

## Budget accounting

Media parts are counted against the context budget: the exact `/tokenize`
counter receives a text-flattened copy plus `IMAGE_TOKEN_ESTIMATE` (260) per
media part — deliberately additive-conservative — and the char fallback
charges the same estimate directly. Windowing and compaction drop a parts
message **whole** (with the placeholder note), never slicing mid-part; the
head attachment message is always preserved. Deepthink digests flatten media
to placeholders so a parts list structurally never reaches a text-only wire
(`tests/test_context_media.py`, `tests/test_deepthink_media.py`).

## Live proofs (livecheck)

Ledger: `docs/live-testing.md` (rows 15–16). Both checks degrade to `skipped`
offline, never a traceback. **Never trust a 200:** the image check passes only
on `delivered` AND the answer naming the color — a dropped record fails even
if the answer happens to say "red" (`tests/test_livecheck_media.py`).

Live results (2026-07-02, `coolthor/gemma-4-12B-it-NVFP4A16`):

- **Image end-to-end: PASSED** — red-pixel PNG through the real
  `colleague work --attach` surface; answer named "Red"; artifact recorded
  `delivered` from real usage (the image's tiles cleared the floor).
- **Text-only degradation: VERIFIED** — the same run against the text-only
  27B completes `ok` with media `dropped` (was a hard 400 before the
  degradation landed).
- **Audio delivery: PASSED (rig-dependent)** — the earlier same-day probe saw
  `input_audio` silently dropped (~0 tokens); the serving side has since
  started consuming it (real token contribution). The check grades delivery
  from evidence and will honestly SKIP again if the rig regresses. See the
  honest limits below for the comprehension caveat.

## Honest limits

- **Delivery is aggregate, not per-part:** the token-contribution signal
  cannot distinguish which of several attachments dropped; all entries in one
  run share a status.
- **Audio comprehension is UNPROVEN:** the image proof pins the answer
  content (red); audio has only the delivery evidence (token contribution on
  a short clip). A tone-identification comprehension probe (1 s, 16 kHz)
  timed out at 300 s — the rig strains on audio compute — so no doc claims
  the model *understands* audio; treat audio as rig-dependent
  delivery-only until a comprehension probe completes.
- **`view_media` is images-only** and capped at 4 MB.
- **`Task.attachments` is size-capped too** — `colleague.media.validate_attachment`
  (the single funnel for CLI `--attach`, session `/attach`, and mesh `attach:`
  references) rejects a non-regular-file path and enforces
  `MAX_ATTACHMENT_BYTES` (16 MB), the same protection `view_media` already had,
  so a mesh request can no longer reference an oversize in-repo file to
  exhaust memory or bloat the prompt.
- **The bridge trigger is an operator declaration**, not a capability probe —
  colleague never special-cases a model name (pinned by the no-gemma-in-source
  test).
- **The Gemma4-as-main flip stays gated** on the serving-side Gemma tool
  parser (below) — media input works today via Gemma-as-main for pure
  vision-answer tasks (no tool loop) and via the bridge for tool-driving
  tasks.
- **No media output, no video, no OCR pipeline, no URL fetching** (attachments
  are operator-local files), no automatic task→model media routing.

## Gemma4-as-main: staged, not flipped

The Gemma4 model is **staged** as a potential future main model but is **not
flipped** (not the default). The default main model remains the 27B Qwen model
at the default 48 000 context budget.

### Per-model overlay recipe

To run colleague against the served Gemma4 model with its correct 128K window
budget, create a per-model profiles overlay:

**File path:**

```text
.colleague/coolthor-gemma-4-12B-it-NVFP4A16/profiles.json
```

**Contents** (keyed by the REAL mode names — the profile layer is consulted
only when a mode is selected, and it looks the overlay up by that mode name):

```json
{
  "work": {"context_budget_tokens": 96000},
  "plan": {"context_budget_tokens": 96000},
  "explore": {"context_budget_tokens": 72000},
  "review": {"context_budget_tokens": 72000}
}
```

The directory name `coolthor-gemma-4-12B-it-NVFP4A16` is the output of
`colleague.layers.sanitize_model("coolthor/gemma-4-12B-it-NVFP4A16")` —
slashes become hyphens, the rest is preserved verbatim.

When the resolved model id matches `coolthor/gemma-4-12B-it-NVFP4A16` **and a
mode is selected** (`colleague work --mode work`, or the interactive session's
mode), the `apply_mode_profile` layer reads this overlay and sets
`context_budget_tokens` to 96 000 (matching the 128K serving window at ~0.75
fill; explore/review carry 72 000, preserving those modes' 0.75-of-window
intent).

**Honest limit — a bare modeless run keeps 48 000.** `apply_mode_profile` is a
strict no-op with no mode selected, so this overlay cannot drift a bare
`colleague work` (that is the *staged, not flipped* guarantee, pinned by
`test_modeless_run_ignores_overlay`). To right-size a modeless run against
Gemma4, set `COLLEAGUE_CONTEXT_BUDGET=96000` in the environment — there is no
per-model budget seam outside the mode-profile overlay today.

### Default stays at 48 000

The built-in default context budget remains **48 000 tokens** for the 27B main
model (`sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP`). No source code change is
required — the default is a constant in `colleague/config.py` and the per-model
overlay seam is purely data-driven (JSON files in `.colleague/`).

### Flip prerequisite: serving-side Gemma tool parser

Flipping Gemma4 to the default main model requires a **serving-side change**:
the lobes serving rig must grow a Gemma-format tool-call parser. The current
Gemma4 model emits no structured tool calls yet (probed and confirmed live —
a media run on Gemma-as-main finishes via pseudo-markup, `status:
incomplete`). This is an **external prerequisite** — it is never worked around
in colleague code. Until the serving-side parser lands, Gemma4 remains staged
(configurable via the per-model overlay above) but not the default.
