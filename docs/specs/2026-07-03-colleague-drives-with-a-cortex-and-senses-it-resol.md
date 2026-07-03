# Colleague drives with a cortex and senses: it resolves its minds by role from lobes — cortex (Qwen 3.6 27B @128K) the authoritative tool-calling mind working behind the scenes, senses (Gemma 4 12B @32K) the multimodal front door the operator talks to and hears back from — with the raw request preserved verbatim across the boundary, a senses layer that structurally cannot act, and the split architecture measurable against cortex-only.

> Colleague drives with a cortex and senses: it resolves its minds by role from lobes — cortex (Qwen 3.6 27B @128K) the authoritative tool-calling mind working behind the scenes, senses (Gemma 4 12B @32K) the multimodal front door the operator talks to and hears back from — with the raw request preserved verbatim across the boundary, a senses layer that structurally cannot act, and the split architecture measurable against cortex-only.

## Audience

- The operator running colleague on a lobes rig (the GB10 spark duo) and mesh peers talking to a resident colleague; secondary: Claude-driven callers via ask-colleague. Colleague is the consuming client of lobes' role contract (lobes-cli#81).

## Before → After

- Before: Today colleague's config carries concrete model ids and endpoints; the second model is framed as 'deepthink' (a stronger reasoner escalated to at judgment moments) even though the target rig's second model is Gemma — a perceiver, not a stronger mind; media understanding rides the c24 bridge bolted onto deepthink.multimodal; there is no role vocabulary, no intake/speak-back layer in front of the operator surface, and no way to measure a split architecture against single-model.
- After: colleague resolves cortex and senses BY ROLE from lobes' machine-readable contract (zero hardcoded model ids in colleague config), drives the bounded tool loop on cortex, fronts the operator-facing surfaces (session, mesh residency) with senses for intake + media perception + speak-back, carries a debuggable ContextPacket that preserves the raw request verbatim, and records runtime measurements that let the operator compare split vs cortex-only.

## Why it matters

- The split maps each mind to what it is actually good at on this rig: Qwen 27B is the only lobe that can tool-call (Gemma4's serving-side parser gap makes it structurally unable to drive the loop), and Gemma is the only multimodal + MTP-fast lobe — so cortex-owns-actions / senses-owns-perception is the honest division, and measurement answers whether the split makes colleague feel faster and more natural WITHOUT reducing correctness (the #274 question), instead of hardcoding one monolithic endpoint.

## Requirements

- ROLE RESOLUTION FROM LOBES: colleague gains an opt-in lobes discovery source in its config resolution — when armed (e.g. COLLEAGUE_LOBES_URL / config.json lobes section), colleague resolves cortex and senses to {endpoint, model, context, ready, responsibilities} from the lobes contract (gateway GET /capabilities and/or 'lobes capabilities --json'), feeding the existing EngineConfig precedence as a defaults source: explicit flag > env > config.json > lobes discovery > builtin. Zero model ids needed in colleague's own config; an unreachable lobes degrades to the next precedence rung with a visible stderr notice, never a hard-fail.
  - honesty: A colleague config containing zero model ids resolves cortex+senses live from the lobes contract and completes a real work item; with lobes unreachable the same run degrades to the next precedence rung with a stderr notice and still runs (h7); a test pins the precedence order including the new lobes rung.
- ROLE VOCABULARY, NOT MORE DEEPTHINK: the second-model plumbing (DeepthinkConfig, tools-off completions, per-endpoint token windowing, degrade-never-raise) generalizes to role-based two-model config — cortex is the main loop model, senses is a declared front/perception role. The 'deepthink' config keys keep working as back-compat aliases; the c24 media bridge becomes a native senses responsibility rather than a deepthink.multimodal bolt-on. 'brain' is forbidden as a name anywhere.
  - honesty: Absent lobes/senses config is byte-identical to today (existing tests + artifact shape unchanged); existing deepthink config keys and TaskResult.deepthink records keep working; grep shows no 'brain' vocabulary anywhere in code or docs.
- SENSES STRUCTURALLY CANNOT ACT: every senses invocation is a tools-off completion (no tool schema on the wire — the same structural guarantee the deepthink/acceptance-self-check surface already has), senses output is always advisory (a packet or a phrasing, never a decision the runtime enforces), and no senses code path can reach ToolExecutor writes, run_command, or the git handoff. Mirrors lobes' forbidden_responsibilities = [final_decision, repo_action, security_decision].
  - honesty: No senses request ever carries a tool schema on the wire (structural, like the acceptance self-check), and a test proves a senses code path cannot invoke ToolExecutor writes, run_command, or handoff even if the model emits tool-call-shaped output.
- CONTEXT PACKET WITH RAW-INTENT PRESERVATION: when senses does intake, it produces a ContextPacket {original text verbatim, interpretation, confidence, task_type, omissions-if-known} that rides ALONGSIDE the original — cortex's prompt always contains the operator's original words verbatim; the packet is advisory context, never a replacement. A debug mode surfaces the packet.
  - honesty: A test asserts cortex's prompt contains the operator's original text verbatim whenever a packet is present; the packet is inspectable via the debug flag and recorded in the artifact; a lossy or failed senses intake degrades to passing the raw text through untouched — intake can never lose the request.
- DECISION MODES: v1 ships cortex-only (the default — byte-identical to today when senses/lobes config is absent) and split mode (senses intake + optional speak-back on the operator-facing surfaces, cortex driving the loop), plus a debug-show-senses-packet flag. The senses layer is bypassable per run (a flag forces cortex-only for a high-value task).
  - honesty: cortex-only is the shipped default and byte-identical when nothing is configured; split mode is opt-in; a per-run bypass flag forces cortex-only; each mode is visible in the artifact (TaskResult.mode or sibling), never silent.
- MEASUREMENT HOOKS: TaskResult records the active mode and per-invocation senses runtime numbers (point, latency, tokens, degraded) the way deepthink escalations are recorded today — omit-when-None — plus session-level intake/speak-back timings, so the operator can run the same task in both modes and compare wall-clock, senses overhead, and cortex calls avoided; task QUALITY judgment stays with the feedback/ROI loop and the operator, never a synthesized score.
  - honesty: Senses runtime numbers (latency/tokens/degraded per point) are recorded omit-when-None and comparable across modes; NO field anywhere asserts answer correctness or task quality — quality stays with the operator feedback loop (mirrors lobes' runtime-only measurement line).

## Honesty conditions

- This is a role generalization of machinery colleague already has (dual-model tools-off completions, media bridge, mode profiles, TaskResult records) — not a rewrite: absent config stays byte-identical, all-engines rule holds, no new base dep/socket/daemon; and the live GB10 proof (senses intake + cortex tool loop end-to-end, split vs cortex-only numbers) is recorded in docs/live-testing.md or honestly marked PENDING, never claimed unproven.
- lobes-cli#81's committed spec names Colleague as the primary client of the role contract (verifiable in lobes-cli docs/specs 2026-07-03), and every audience surface — session, mesh residency, ask-colleague callers — is explicitly addressed by the intake-scope decision (c19).
- Verifiable today by grep: colleague's config resolution has no lobes/role rung; the second-model config section is named 'deepthink'; the media bridge keys off deepthink.multimodal; no cortex/senses vocabulary exists in colleague code.
- Demonstrable end-to-end, not aspirational: a real run's artifact JSON carries the mode, the packet, and senses runtime fields; the live rebalanced-rig proof is recorded in docs/live-testing.md or honestly marked PENDING (the deepthink convention).
- The hardware claims cite the recorded 2026-07 rig probes (27B tool-calls OK; Gemma4 image-capable but NO structured tool calls; Gemma MTP fast) — and if a serving-side parser fix later gives Gemma tool calling, the cortex-owns-actions division is re-documented as a design choice, never left standing as a stale hardware claim.
- The spec and CLAUDE.md scope line document this as the second landed increment at the router-exclusion boundary (after deepthink): two declared roles, fixed responsibilities, no automatic routing — and senses-direct stays out with its rationale written down.
- The signal is proven through the real surfaces (--attach, a real session or mesh run) — not a synthetic harness; the same task run cortex-only and split yields directly comparable artifact numbers; SKIP/PENDING is recorded honestly if the rebalanced stack is not yet serving.

## Success signals

- A from-scratch .colleague config with zero model ids, pointed at lobes, runs a real work item: senses (Gemma@32K) does intake on the operator's message + screenshot and shapes the speak-back, cortex (Qwen@128K) drives every tool call — and the artifact shows the mode, the packet, verbatim raw intent, and comparable runtime numbers vs the same task run cortex-only.

## Scope / boundaries

- This is the sanctioned re-spec at the router exclusion line, and it stays behind it: TWO operator-declared roles with a FIXED responsibility boundary (cortex acts, senses perceives/presents), resolved by name from lobes — no automatic task-to-model routing policy, no N-model generalization, no senses-decides-to-answer-itself. Senses sits only on operator-facing surfaces; the bounded tool loop, gates, and handoff are cortex territory untouched.

## Non-goals

- senses-direct-for-cheap-tasks mode (senses answering without cortex) is NOT in v1 — a model deciding per-input whether cortex is needed is the start of the excluded routing policy; parked as an explicit follow-up pending split-mode measurements.
- No voice loop in v1: colleague discovers stt/tts in the lobes contract but does not consume them (no audio capture/playback surface); embedder/reranker consumption also stays out (colleague's memory is the eidetic CLI's business). Gemma is NOT a Qwen replacement and is never measured as one.

## Decisions

- Senses reaches the wire through the SAME enumerated tools-off completion machinery as deepthink (Engine.make_complete, per-endpoint windowing via make_count_tokens, degrade-never-raise) — extended with the intake and speak-back points on the operator surfaces; no new wire protocol, no daemon, no new base dep. The senses window is 32K: intake sees the fresh input + a bounded context slice, never the whole history.
- Runtime-owned under the all-engines rule: role resolution, the ContextPacket, modes, and measurement live in the runtime/config/loop — identical for mock and vllm-openai; mock records degraded no-ops exactly as it does for deepthink today.
- q1 resolved (user-endorsed): senses intake covers the interactive surfaces only in v1 — colleague session free-text and mesh-resident inbound messages. One-shot 'colleague work' text is deliberate CLI input and bypasses text intake (no Gemma TTFT on scripted runs); work items still get senses MEDIA perception for attachments. Split-vs-cortex-only measurement therefore reads from interactive runs plus media-bearing work items.

## Hard questions

- Does one-shot 'colleague work' text go through senses intake at all in v1, or is intake session/mesh-only? Deliberate CLI text arguably needs no perception layer — but skipping it means work items get no packet and the measurement story covers only interactive surfaces.

## Open questions

- Where exactly does senses intake hook in v1 — session free-text only, or also mesh-resident inbound messages, or also one-shot 'colleague work' instructions? Session + mesh are the natural operator-facing surfaces; a one-shot work instruction is already deliberate text and may not need intake.

## Open / follow-up

- senses-direct-for-cheap-tasks: revisit after split-mode measurements exist; requires its own re-spec against the router exclusion. Tracked: [#276](https://github.com/agentculture/colleague/issues/276).
- Voice loop (stt/tts consumption) and embedder/reranker consumption: discoverable in the contract from day one, consumed in a later arc. Tracked: [#277](https://github.com/agentculture/colleague/issues/277).

## Accepted plan risks / parked unknowns (non-blocking)

> These `unknown_nonblocking` items are retained in the frame JSON but dropped by the
> spec-md exporter; re-attached here by hand so `/spec-to-plan` sees the full picture.
> None block convergence — they are plan-time or live-measurement calls, not fabrications.

- **Lobes contract transport for colleague.** Gateway `GET /capabilities` over
  urllib vs a `lobes` CLI shell-out (which would need boundary-test sanctioning)
  vs both — and whether resolved roles are cached to disk between runs or
  re-resolved each run. Behavior is fixed (resolve by role, degrade gracefully);
  the transport is a plan-time call, and lobes-cli#81 is itself spec-only today
  (no plan/impl yet), so the contract shape could still shift.
- **Speak-back placement.** Whether senses shapes the final summary on ALL
  surfaces (session, mesh, work stderr) or only conversational ones, and whether
  the raw cortex summary is always retained alongside the shaped one in the
  artifact. Presentation-layer call, decidable at plan time.
- **Intake latency budget.** Whether senses intake runs synchronously before
  cortex (adds Gemma TTFT to every turn) or in parallel with a fast
  acknowledgement — depends on live MTP latency numbers lobes#81's per-role
  measurement profiles will provide (not built yet).

## Source

Specced from [agentculture/colleague#274](https://github.com/agentculture/colleague/issues/274)
and the lobes side contract
([agentculture/lobes-cli#81](https://github.com/agentculture/lobes-cli/issues/81),
`lobes-cli/docs/specs/2026-07-03-lobes-exposes-the-full-colleague-runtime-stack-as.md`)
via the `/think` (devague) operator chain.
