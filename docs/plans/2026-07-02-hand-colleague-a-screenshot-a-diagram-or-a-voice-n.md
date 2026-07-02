# Build Plan — Hand colleague a screenshot, a diagram, or a voice note along with your task - in the interactive session, from the CLI, or over the mesh - and it works from the media directly: attachments ride the task contract to a multimodal main model, and colleague verifies the model actually saw them instead of trusting a 200.

slug: `hand-colleague-a-screenshot-a-diagram-or-a-voice-n` · status: `exported` · from frame: `hand-colleague-a-screenshot-a-diagram-or-a-voice-n`

> Hand colleague a screenshot, a diagram, or a voice note along with your task - in the interactive session, from the CLI, or over the mesh - and it works from the media directly: attachments ride the task contract to a multimodal main model, and colleague verifies the model actually saw them instead of trusting a 200.

## Tasks

### t1 — Task.attachments on the contract: optional attachments list ({path, media_type}) on Task, omit-when-None, to_dict/from_dict round-trip, malformed payload degrades to None. Files: colleague/contract.py + tests/test_contract_attachments.py

- covers: c9, h7
- acceptance:
  - Task without attachments serializes byte-identically to today (existing artifact fixtures re-parse unchanged; to_dict has no attachments key when None)
  - round-trip test: Task with attachments -> to_dict -> from_dict -> equal; malformed attachments payload (string, dict) degrades to None without raising

### t2 — Media helpers module (NEW colleague/media.py, pure stdlib): attachment validation (exists/readable/media-type inference from extension), data-URI encoding, OpenAI content-part builders (image_url + input_audio shapes), per-image token estimate constant from the live probe, part-aware flatten helper (parts -> text placeholder). No I/O beyond reading the attachment file; no third-party dep.

- covers: c10
- acceptance:
  - unit tests: a png path becomes a valid image_url data-URI part; a wav path becomes an input_audio part; unknown extension raises a clear error; flatten(parts) yields text with a placeholder per media part
  - test_zero_deps still passes (module imports cleanly with no third-party import)

### t3 — Loop wiring for initial parts: when task.attachments is non-empty, loop.py builds the initial user message as content parts (text + one part per attachment) via colleague.media; with no attachments the message stays a plain string. Files: colleague/loop.py + tests/test_loop_media.py

- depends on: t1, t2
- covers: c10, h8
- acceptance:
  - with attachments absent the initial message content is type str (not a one-part list) - pinned by test; e2e mock shape test unchanged
  - with one image attachment the first user message is a 2-element parts list (text part + image part) on both mock and vllm-openai message builders (all-engines)

### t4 — Engine wire pass-through: vllm-openai serializes content-parts messages verbatim over the standard OpenAI wire (no vLLM-only fields); mock engine accepts parts-shaped messages. Files: colleague/engines/vllm_openai.py + colleague/engines/mock.py + tests/test_engine_parts.py

- depends on: t2
- covers: c11, h9
- acceptance:
  - a captured request body for a parts message contains only standard OpenAI content-part keys (type, text, image_url, input_audio) - asserted by test
  - mock engine round-trips a parts message without error and the e2e shape test still passes

### t5 — view_media loop tool: read-only tool loading an image file from the repo into the conversation as a content part mid-work. Schema + role-aware executor dispatch in colleague/tools.py (structured outcome carrying the part), loop.py folds a media tool outcome into a parts user message, curated into read-only roles in colleague/roles.py. Files: tools.py + roles.py + loop.py + tests/test_view_media.py

- depends on: t3
- covers: c12, h10
- acceptance:
  - view_media on a path outside the repo is refused via the same _safe_path check (test); oversize file (over the size cap) refused with a clear error naming the cap
  - a role withholding view_media refuses the call even when the model emits it (role-aware executor test); explorer/reviewer roles include it (pure read)
  - after a successful view_media call the next model turn sees a parts user message containing the image part (loop fold test on mock)

### t6 — Budget accounting + part-safe windowing: media parts counted against the context budget (exact via /tokenize when it accepts parts - probe and adapt; else the colleague.media per-image estimate); windowing and fill-line compaction drop a media part WHOLE with a placeholder note, never truncating mid-part. Files: colleague/context.py + colleague/loop.py + tests/test_context_media.py

- depends on: t5
- covers: c13, h11
- acceptance:
  - count_tokens on a parts message returns text tokens + per-media estimate when /tokenize cannot count parts (char-fallback path test); the estimate is the colleague.media constant, not zero
  - windowing a history containing a parts message either keeps the message intact or replaces it with the placeholder note - a test asserts no output message ever contains a truncated/partial parts list

### t7 — Deepthink digest flattening: every deepthink escalation digest flattens media parts to text placeholders/descriptions before the wire - parts structurally never reach a text-only endpoint. Files: colleague/deepthink.py + tests/test_deepthink_media.py

- depends on: t2
- covers: c14, h12
- acceptance:
  - a test pins that run_deepthink never sends a list-typed content field: digest built from a parts-bearing history contains only string content (uses colleague.media flatten helper)
  - a media-bearing dual-model run still escalates successfully on mock (no crash, degraded=False path intact)

### t8 — Media-comprehension bridge (operator decision c24): when the MAIN model is text-only and the task carries media, escalate a media-bearing digest tools-off to the declared multimodal second model and fold the returned description back into the main loop as one advisory message; recorded on TaskResult.deepthink ({point: media-bridge}). Strict no-op when main is multimodal, no media attached, or no second model declared; bridge failure degrades (media recorded undelivered), never raises. Files: colleague/deepthink.py + colleague/loop.py + tests/test_media_bridge.py

- depends on: t6, t7
- covers: c24, h18
- acceptance:
  - single-model config with attachments: bridge does not fire and the run is byte-identical except the delivered/dropped record (no-op test)
  - dual config + text-only main + image attachment on mock: exactly one tools-off bridge escalation fires, its description is injected as one advisory message, and TaskResult.deepthink records point=media-bridge
  - bridge endpoint unreachable: run completes with media recorded undelivered and a degraded bridge record - no exception escapes

### t9 — Delivered-vs-dropped verification (decision c25): after a media-bearing completion the runtime compares usage.prompt_tokens against the text-only estimate + per-tile floor to classify each attachment DELIVERED or DROPPED (zero extra model turns); recorded on an omit-when-None TaskResult.media field ({attachments: [{path, status}]}, never the word understood) + stderr warning on a drop. Files: colleague/loop.py + colleague/contract.py + tests/test_media_delivery.py

- depends on: t1, t8
- covers: c15, h13, h5
- acceptance:
  - a mock run replaying the LIVE silent-drop usage numbers (prompt_tokens ~= text-only estimate) classifies the image DROPPED and records it on TaskResult.media + stderr - the reproduced-probe test
  - threshold uses the per-tile token floor: a run whose prompt_tokens exceed the text estimate by at least the floor classifies DELIVERED; no false-positive on a tiny image (boundary test at the floor)
  - a run with no attachments has no media key in the artifact (omit-when-None, byte-identical)

### t10 — CLI surface: colleague work --attach PATH (repeatable) feeds Task.attachments after colleague.media validation (exists/type inferable); clean choices-shaped error on a missing/unsupported file. Files: colleague/cli/_commands/work.py + tests/test_cli_attach.py

- depends on: t1, t2
- covers: c16, h14
- acceptance:
  - work --attach img.png --attach diagram.jpg produces a Task whose attachments field lists both, in order, with inferred media types (test via execute_work seam on mock)
  - work --attach missing.png exits with a structured CliError naming the path (no traceback); bare work without --attach builds a Task with attachments=None

### t11 — Session surface (in chat): the interactive session accepts attachments on a work line and threads them into the same Task.attachments (ergonomics decided at build: /attach slash or inline path token - drift-tested against the SlashSpec catalog if a slash). Files: colleague/cli/_commands/session.py + tests/test_session_attach.py

- depends on: t1, t2
- covers: c16, h14
- acceptance:
  - a session work line with an attachment produces a Task whose attachments match the CLI-built shape exactly (same-shape test vs the t10 path)
  - a session line with no attachment routes byte-identically to today (intent routing and palette selection untouched - existing session tests unchanged)

### t12 — Resident/mesh surface (as service) + media trust: a mesh request may reference media by path; OPERATOR identity may attach arbitrary operator-local paths, a non-operator request only paths inside the target repo working tree (anti-exfiltration), still read-only under explorer. Files: colleague/resident/appserver.py + colleague/resident/trust.py + tests/test_resident_media.py

- depends on: t1, t2
- covers: c16, c17, h15, h2, h14
- acceptance:
  - a crafted non-operator request referencing /home/user/.ssh/id_rsa is refused with a recorded reason (test); the same path from the operator identity is accepted
  - a non-operator media request still resolves to the explorer role (read-only) - reuses the existing c19 trust seam, no new trust decision path (asserted by test on the existing trust functions)
  - the accepted request produces the same Task.attachments shape as the CLI path (same-shape test)

### t13 — Livecheck live proofs: image end-to-end (generate a red-pixel png, colleague work --attach through the real surface on live Gemma4, assert the ANSWER contains red + DELIVERED recorded) and audio honest-skip (input_audio attachment on the live rig records DROPPED -> livecheck reports SKIP with the silent-drop reason, never green). Ledger rows in docs/live-testing.md. Files: colleague/livecheck.py + docs/live-testing.md + tests/test_livecheck_media.py

- depends on: t9, t10
- covers: c19, h17, h1, h6, c7, h19
- acceptance:
  - the image livecheck asserts answer content (red) and TaskResult.media DELIVERED - a 200 with a dropped image FAILS the check (asserted via a simulated-drop unit test)
  - the audio livecheck records SKIP with the silent-drop reason on today's rig and never reports pass while the drop persists (unit test on the classification logic)
  - both entries appear in docs/live-testing.md with their gating condition; offline runs of the livecheck verb degrade to skipped, never a traceback

### t14 — Gemma4-as-main STAGED per-model config: a documented, test-proven per-model overlay recipe (.colleague/<sanitized-gemma-model>/ config: 96000 budget @ 128K window) that activates ONLY by explicit operator config; defaults unchanged (bare run resolves 27B-as-main at 48000); the flip prerequisite (serving-side Gemma tool parser) documented as external. Files: docs/features/media-input.md (staging section) + tests/test_gemma_staged_config.py (+ example config in docs, no default change in colleague/config.py)

- covers: c18, h16
- acceptance:
  - a repo with the documented Gemma per-model overlay resolves context_budget_tokens=96000 for that model and 48000 for the default model (existing per-model overlay seam, exact-path, test)
  - a bare EngineConfig.resolve() still yields the 27B default at 48000 (no default drift test); no colleague code special-cases Gemma (grep-level assertion in test)

### t15 — Byte-identical + all-engines pin sweep: the no-attachments baseline is pinned across the whole runtime (e2e mock shape test unchanged, artifact bytes identical, boundary/zero-deps guards pass with colleague/media.py sanctioned read-only) and the three surfaces produce one Task.attachments shape (cross-surface parity test). Files: tests/test_e2e_mock.py + tests/test_boundary.py + tests/test_zero_deps.py + tests/test_media_parity.py

- depends on: t4, t9
- covers: h3, h4, c3, c4
- acceptance:
  - full suite green with an attachment-less run producing an artifact byte-identical to pre-arc (fixture comparison test)
  - cross-surface parity test asserts CLI/session/resident all build the identical attachments shape; boundary test confirms media.py imports no subprocess and no third-party module

### t16 — Docs + honest limits: docs/features/media-input.md (three surfaces, bridge, delivered-vs-comprehended, budget accounting), CLAUDE.md architecture part, boundary honesty everywhere - audio is shaped-but-parked (livecheck SKIP, no doc claims working audio), input-only non-goals (no media output/video/OCR/URL fetch/lobes routing), why-it-matters framing. Files: docs/features/media-input.md + CLAUDE.md + CHANGELOG.md

- depends on: t13, t15
- covers: c1, c2, c5, c6, h6
- acceptance:
  - doc-test alignment check passes: every documented behavior names its pinning test; no doc, changelog, or help text claims working audio (grep for audio claims returns only shaped/parked/SKIP wording)
  - CLAUDE.md gains the media-input architecture part with the honest-limits block (audio gate, comprehension vs delivery, flip prerequisite) mirroring the spec boundary

## Risks

- [unknown_nonblocking] /tokenize content-parts capability unknown: probe at t6 build time; the per-image estimate fallback works either way (accounting exact-or-estimated, never zero) (task t6)
- [unknown_nonblocking] Serving-side Gemma tool parser is external (lobes serving change): the Gemma4-as-main default flip stays staged regardless of this plan; t14 documents the prerequisite, never works around it (task t14)
- [follow_up] Audio live proof gated on the rig actually consuming input_audio: the audio livecheck records SKIP until the rig changes; no plan task claims working audio (task t13)
- [unknown_nonblocking] Session attach ergonomics (slash command vs inline path token) decided at t11 build time against the SlashSpec drift-test - either shape satisfies the acceptance criteria (task t11)
- [unknown_nonblocking] Per-image token cost varies with image size/tiling: the t9 threshold uses the per-tile FLOOR so variance can only widen the DELIVERED margin, never false-positive a drop (task t9)
- [follow_up] Real bridge quality on live Gemma (description fidelity for diagrams/screenshots) unmeasured until the t13 live proof - bounded by the one-completion budget, degrades recorded (task t8)
