# Hand colleague a screenshot, a diagram, or a voice note along with your task - in the interactive session, from the CLI, or over the mesh - and it works from the media directly: attachments ride the task contract to a multimodal main model, and colleague verifies the model actually saw them instead of trusting a 200.

> Hand colleague a screenshot, a diagram, or a voice note along with your task - in the interactive session, from the CLI, or over the mesh - and it works from the media directly: attachments ride the task contract to a multimodal main model, and colleague verifies the model actually saw them instead of trusting a 200.

## Audience

- Operators delegating repo work that hinges on visual context (a failing-UI screenshot, an architecture diagram, a whiteboard photo) or spoken context (a voice note), plus mesh peers handing colleague media-bearing requests as a service.

## Before → After

- Before: colleague is text-only on every surface: Task carries only instruction strings, the loop builds string-content messages, the engine reads content as a string - and the one multimodal model on the rig (Gemma4 at 128K, image input proven live) cannot be exercised; media context must be hand-transcribed into prose, losing exactly the detail that matters.
- After: A Task can carry media attachments end-to-end: colleague work --attach on the CLI, an attach affordance in the interactive session, and a path-reference convention on the resident/mesh surface all land as standard OpenAI content parts on the task prompt; runtime comprehension verification detects a model that silently dropped the media and records it honestly on the TaskResult.

## Why it matters

- The rig already serves a 128K multimodal model going unused; visual context is the highest-bandwidth task context there is, and the silent-drop probe result proves a 200 OK means nothing - honest media support needs runtime verification, which only the harness can own.

## Requirements

- Task.attachments: the task contract gains optional media attachments (path + media type per entry), omit-when-None so an attachment-less task serializes byte-identically; round-trips to_dict/from_dict; all-engines (mock and vllm-openai see the same shape).
  - honesty: A Task without attachments serializes byte-identically to today (omit-when-None) and a legacy artifact round-trips through from_dict unchanged; a malformed attachments payload degrades to None, never a crash.
- Parts plumbing in the loop: when attachments are present the runtime builds the initial user message as OpenAI content parts (text part + one part per attachment); with no attachments the message stays a plain string - byte-identical shapes, pinned by the e2e mock test.
  - honesty: With attachments absent the initial message stays a plain STRING (not a one-part list) - pinned by test, so downstream string-assuming code (windowing, markup re-parse, fill-line) never meets a surprise list.
- Engine wire pass-through: vllm-openai forwards content-parts messages verbatim over the standard OpenAI wire format (image_url data-URI for images; input_audio shape for audio); no vLLM-only fields, so retargeting another OpenAI-compatible server stays a config change.
  - honesty: Parts are standard OpenAI content parts only - no vLLM-only wire fields enter the engine; mock accepts the identical shape (all-engines rule holds end-to-end).
- view_media loop tool: a read-only tool that loads an image file from the repo into the conversation as a content part mid-work (the media sibling of read_file), repo-confined via the same safe-path check, size-capped, curated into read-only roles (pure read).
  - honesty: view_media refuses a path outside the repo (same _safe_path confinement) and oversize files with a clear error; a role withholding it refuses the call even when the model hallucinates it.
- Budget accounting for media: media parts are counted against the context budget (exact via /tokenize if it accepts parts - unknown, probe during build - else a fixed per-image estimate from the live probe, ~260-300 tokens per tile); windowing and compaction drop a media part WHOLE with a placeholder note, never truncating mid-part.
  - honesty: A media part is never sliced mid-part by windowing or compaction - dropped whole with a placeholder note - and its token cost is counted (exact or estimated) inside the same budget windowing enforces, never ignored.
- Deepthink digest flattening: every deepthink escalation digest flattens media to a text placeholder or description before hitting the wire - the second model may be text-only (today's 27B is), so media parts must structurally never reach a text-only endpoint; pinned by a test.
  - honesty: A test pins that no content-part list ever reaches the deepthink wire - the digest builder structurally flattens media; a media-bearing dual-model run still escalates successfully.
- Comprehension verification: after a media-bearing completion the runtime checks the model actually consumed the media using the token-contribution signal (an image contributes ~hundreds of prompt tokens; a silent drop contributes ~0 - the exact signal the live probe exposed), needs no extra model turn, and records a detected drop honestly on the TaskResult - never a silent OK.
  - honesty: Drop detection costs no extra model turn, thresholds against the known per-tile token floor so a genuinely tiny image cannot false-positive, and a detected drop lands on the TaskResult + stderr - never silently ignored.
- Three surfaces, one plumbing: (in chat) colleague session accepts attachments on a work line; (out of chat) colleague work --attach PATH, repeatable, feeds Task.attachments; (as service) the resident accepts a media path reference in a mesh request under the c19 trust model. All three converge on the same Task.attachments - no per-surface media code paths.
  - honesty: Each surface is driven by its own test (work --attach, session attach, resident media reference) and all three produce the same Task.attachments shape - proven, not asserted.
- Mesh media trust: over the resident surface, only the OPERATOR identity may attach arbitrary operator-local paths; a non-operator request may reference media only inside the target repo working tree (no reaching into the wider filesystem - a mesh peer must not be able to exfiltrate ~/.ssh by asking colleague to look at it as an image), and still runs read-only under the explorer role.
  - honesty: A crafted non-operator mesh request referencing a path outside the repo is refused with a recorded reason (test-proven); operator authority reuses the existing c19 trust seam - no new trust code path to audit.
- Gemma4-as-main staged, not flipped: the Gemma profile (128K window, 96000 budget) ships as ready per-model config, but the DEFAULT main-model flip stays gated on the serving-side Gemma tool parser (Gemma4 emits no structured tool_calls today, so it cannot drive the tool loop); the default remains 27B-as-main at 48000.
  - honesty: Defaults unchanged: a bare run still resolves 27B-as-main at 48000 budget; the Gemma profile activates only by explicit operator config; the flip prerequisite (serving-side parser) is documented as external, never worked around in colleague code.
- Live proofs via livecheck: the image end-to-end proof (red-pixel through colleague work --attach on live Gemma4) and the audio honest-skip (rig silently drops input_audio - recorded as SKIP with reason, never a pass) both land as livecheck entries in docs/live-testing.md.
  - honesty: The audio livecheck records SKIP with the silent-drop reason and never reports green; the image livecheck asserts the ANSWER content (red), not merely a 200 response.
- Media-comprehension bridge (operator decision 2026-07-02): when the MAIN model is text-only and the task carries media, the runtime escalates a media-bearing digest tools-off to the declared multimodal second model (the inverse deepthink direction - reusing the run_deepthink one-bounded-completion machinery and the enumerated-escalation-surface convention, adding media comprehension as one enumerated point) and folds the returned description back into the main loop - so attachments are useful on today's rig (27B main + Gemma vision) before the Gemma-as-main flip.
  - honesty: The bridge escalation is a strict no-op when the main model is multimodal, when no media is attached, or when no second model is declared (single-model config stays byte-identical); a bridge failure degrades - the run continues with the media recorded as undelivered, never a crash; and no media part reaches a text-only wire even in the bridge path (the digest carries the parts to the MULTIMODAL endpoint only).

## Honesty conditions

- A media-bearing task works end-to-end through at least one real surface on the live rig (image), and 'colleague verified the model saw it' is backed by the recorded token-contribution check on the TaskResult; the announcement never claims audio works while the rig drops it.
- The mesh-peer audience is honestly constrained: a non-operator peer gets read-only execution and repo-confined media only, so 'as a service' never implies arbitrary file access for strangers.
- The text-only baseline is pinned: with no attachments, message shapes, artifact bytes, and surface behavior are byte-identical to pre-arc (e2e mock shape test unchanged).
- All three surfaces converge on Task.attachments with no per-surface media plumbing - one contract field, one parts builder, each surface driven by a test.
- The verification story is grounded in the reproduced live silent-drop (recorded usage numbers in a test), not a hypothetical - the token-contribution signal demonstrably separates consumed from dropped media.
- Audio ships wire-shape + tests + an honest livecheck SKIP only; no doc, changelog, or announcement claims working audio until the live gate passes.
- The success signal is measured through the shipped surface (colleague work --attach on the live rig + the mock shape test), not through curl or a test harness bypass; the degradation half (text-only main, attachment present) is itself test-proven, and byte-identical means byte-identical - pinned by the existing e2e shape test, not eyeballed.

## Success signals

- The red-pixel probe runs through the real surface, not curl: colleague work --attach red.png 'what color is this?' answers red with comprehension verified, on both a live Gemma4 run and the mock shape test; a text-only main model with an attachment degrades to a recorded honest limitation (never a silent drop); an attachment-less run stays byte-identical on every surface.

## Scope / boundaries

- Input only, still one runtime: no media OUTPUT or generation, no video, no OCR preprocessing pipeline, no lobes-side routing (#250 stays excluded), no N-model media router (the dual-model deepthink line holds - one declared second model, enumerated surface). Audio is SHAPED but its live proof is GATED: the rig today silently drops input_audio, so audio ships as wire-shape + tests + an honest livecheck skip, never claimed working.

## Non-goals

- Media output/generation, video input, OCR or any preprocessing pipeline, URL fetching for attachments (network action - attachments are operator-local files), lobes routing (#250), and automatic task-to-model media routing are all out of scope this arc.

## Assumptions

- The per-image token cost measured on live Gemma4 (~260 prompt tokens per image tile) is a stable enough estimate for the char-fallback budget accounting when /tokenize cannot count parts.
- Mesh media arrives as a filesystem path reference (IRC-based mesh text cannot carry binaries); the resident and the requester share a machine or a shared filesystem for media handoff this arc.

## Decisions

- Audio is shaped-but-parked (restates the operator's prior-session call): the input_audio content-part shape, Task.attachments support, and tests all ship, but no audio capability is claimed - the live proof is gated on the rig actually consuming audio, and the gate failing today is recorded as the honest limit.
- Attachments are operator-local file paths, resolved and encoded at task-build time (data-URI on the wire); no URL fetching - fetching a URL is a network action outside the trust surface this arc.
- Delivered vs comprehended (operator decision 2026-07-02): the runtime's token-contribution check claims DELIVERED (media entered the prompt) or DROPPED - the TaskResult field never says understood; COMPREHENSION is claimed only where the live red-pixel probe proves it (livecheck). Zero extra model turns for the runtime check.

## Hard questions

- Can prompt-token accounting distinguish 'model consumed the image' from 'server tokenized it but the model ignored it'? The signal proves tokens entered the prompt, not comprehension - is token-contribution the honest claim, with the livecheck red-pixel answer as the only true comprehension proof?

## Open / follow-up

- Session attach ergonomics (slash command vs path auto-detection on a work line) - a plan-level UI choice, not spec-blocking.
- Audio transcription semantics (what colleague DOES with consumed audio beyond passing it to the model) - moot until the rig consumes audio at all.
