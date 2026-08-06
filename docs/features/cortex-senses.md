# Cortex + senses — colleague resolves its minds by role, from lobes

> Spec:
> [`docs/specs/2026-07-03-colleague-drives-with-a-cortex-and-senses-it-resol.md`](../specs/2026-07-03-colleague-drives-with-a-cortex-and-senses-it-resol.md)
> · plan:
> [`docs/plans/2026-07-03-colleague-drives-with-a-cortex-and-senses-it-resol.md`](../plans/2026-07-03-colleague-drives-with-a-cortex-and-senses-it-resol.md)

colleague can drive with **two roles**: a **cortex** — the fast, wide-window,
authoritative tool-calling mind that drives the bounded tool loop — and a
**senses** — a tools-off multimodal front door that reads the operator's raw
request before cortex acts on it and shapes cortex's raw summary back into a
conversational reply. Both are resolved **by role**, not by a hardcoded model
id: an operator running colleague against a `lobes` gateway can ship a config
with **zero model ids** and still get a live, correctly-routed cortex/senses
pair.

This is the *second* sanctioned increment at the router-exclusion boundary,
after [deepthink](deepthink.md) — see "The honest line" below.

> For the **component map, data-flow diagrams, the model table, and what the
> split enables**, see the companion
> [architecture doc](cortex-senses-architecture.md). This doc covers config,
> modes, and honest limits in prose.

## Architecture

Role resolution happens once, at `EngineConfig.resolve()` time, as one more
rung in the existing precedence chain (`colleague/config.py`):

```text
explicit flag  >  COLLEAGUE_* env  >  .colleague/config.json  >  lobes discovery  >  builtin default
```

- **cortex** is the *main* model — the same `EngineConfig.model`/`base_url`
  that has always driven the tool loop. Nothing about the loop, the gates, or
  the git handoff changes: cortex territory is untouched.
- **senses** is a *second*, optional, declared endpoint
  (`EngineConfig.senses: SensesConfig | None`) — present only when a model
  resolves for it (env, config.json, or the lobes rung). Absent senses is
  byte-identical to pre-arc colleague.
- **lobes** (`colleague/lobes.py`) is the discovery client: a single
  stdlib-`urllib` `GET {gateway}/capabilities` that returns a superset payload
  per role (`role, model, runtime, endpoint, path, context, quant, mtp,
  responsibilities, forbidden_responsibilities, ready, loaded`). This doc's
  arc originally consumed only `cortex` and `senses`; later re-specs grew the
  consumed set — `stt`/`tts` (voice), the `embedder` (env relay), and `muse`
  (the deepthink discovery rung, [deepthink.md](deepthink.md)) — while
  `reranker` stays read-and-discarded (#277's parked retrieval lane; see
  [Honest limits](#honest-limits) and the [#276/#277](#the-honest-line-this-is-not-a-router)
  follow-ups). `resolve_roles` degrades to `None` on **any** failure
  (unreachable gateway, timeout, non-200, malformed JSON, a missing role) and
  **never raises** — an armed-but-unreachable lobes gateway prints ONE stderr
  notice and resolution falls through to the next precedence rung.

Zero model ids are required in colleague's own config when lobes is armed:
`cortex`'s model id becomes the main `model` default, and `senses`'s model id
and context window become a `SensesConfig` default — both read live off the
wire, never hardcoded in colleague source (a boundary test pins this: no
`"gemma"`/no vendor model string appears in `colleague/` code).

## Config

### Declaring senses directly

`SensesConfig` mirrors `DeepthinkConfig` field-for-field
(`colleague/config.py`): `model`, `base_url`, `api_key`, `context_budget`,
`multimodal`. Presence is keyed **solely** on a resolved senses *model* — no
model, no senses, regardless of other keys (the same rule deepthink uses).

```jsonc
// .colleague/config.json
{
  "senses": {
    "model": "coolthor/gemma-4-12B-it-NVFP4A16",
    "base_url": "http://localhost:8001/v1",  // defaults to the MAIN base_url
    "api_key": "…",                           // defaults to the MAIN api_key
    "context_budget": 24000,                  // tokens; default 24000 (32K-sized)
    "multimodal": true                        // arms the media-comprehension bridge
  }
}
```

Env equivalents: `COLLEAGUE_SENSES_MODEL`, `COLLEAGUE_SENSES_BASE_URL`,
`COLLEAGUE_SENSES_API_KEY`, `COLLEAGUE_SENSES_CONTEXT_BUDGET`,
`COLLEAGUE_SENSES_MULTIMODAL`. The resolved block is visible (api_key
redacted) via `colleague config show`.

### The lobes discovery rung

```jsonc
// .colleague/config.json — either shape works
{ "lobes": "http://localhost:8001" }
// or
{ "lobes": { "url": "http://localhost:8001" } }
```

Env equivalent: `COLLEAGUE_LOBES_URL`. When armed, `EngineConfig.resolve()`
makes ONE `GET /capabilities` call and:

- feeds `cortex`'s model id as the default `model` (below config.json, above
  the builtin default),
- feeds `senses`'s model id + window as a default `SensesConfig` **only when
  senses is not already declared** via env/config.json (env/config.json
  always win),
- **each role dials its OWN advertised endpoint** (colleague#292/291 S1+S2,
  closing lobes-cli#87 end-to-end) — `EngineConfig.resolve()` calls
  `colleague/lobes.py`'s per-role `resolve_role_base_url` independently for
  cortex, senses, and voice (stt/tts); the gateway origin
  (`COLLEAGUE_LOBES_URL` itself) survives only as the documented fallback for
  an unwired role (empty `endpoint`) or a disallowed scheme — the pre-0.38
  "every role dials the gateway origin" workaround is gone. See
  [Honest limits](#honest-limits) for what this does and doesn't cover.

**api_key hygiene:** the main `api_key` is inherited only when the discovered
senses role's dial target shares the main endpoint's origin (the reference
rig: everything proxied at one gateway). A cross-origin senses gets the
no-auth default instead — the main Bearer token is never forwarded to a host
a wire payload advertised. To arm a cross-origin senses, declare the key
explicitly (`COLLEAGUE_SENSES_API_KEY`, or a `config.json` `senses.api_key` —
which works even without a declared model); a wrong or absent key degrades
visibly at the next senses invocation, never fails the run. A unified
withheld-key stderr notice across all three discovery rungs
(deepthink/senses/voice) is a follow-up, tracked as
[#349](https://github.com/agentculture/colleague/issues/349).

Inspect the armed state, the resolved roles, and the degradation rung with
**`colleague lobes show`** (`not_configured` / `armed_reachable` /
`armed_unreachable`).

### Per-run flags

- **`--cortex-only`** (on `work`/`session`) bypasses the senses front door for
  one run: no intake, no speak-back shaping, no senses media bridge. The
  artifact records `mode: "cortex-only"`. A strict no-op when no senses model
  is resolved (there is nothing to bypass).
- **`--debug-senses`** (session) prints the perceived `ContextPacket` to
  stderr after every intake — the fast way to see what senses actually read
  without digging through the artifact.

## Modes

| Mode | When | Behavior |
|---|---|---|
| **cortex-only** (default) | no senses/lobes config anywhere, or `--cortex-only` | byte-identical to pre-arc colleague: one model, no packet, no shaping |
| **split** | senses resolved and not bypassed, on an interactive surface | senses intake produces a `ContextPacket`; cortex drives the loop with the packet as advisory context; the final summary is speak-back-shaped for **display only** |

The raw cortex summary is **always** retained in `TaskResult.summary` — speak-back
shaping is a presentation-layer transform applied to what the operator/mesh
peer *sees*, never a replacement of the artifact's summary of record. `mode`
is recorded on `TaskResult` (`"cortex-only"` / `"split"`) — the split is never
silent.

### Where intake actually runs (q1)

Text intake covers the **interactive, operator-facing surfaces only**:

- `colleague session` free-text lines (`colleague/cli/_commands/session.py`
  `_prepare_senses`),
- mesh-resident inbound messages (`colleague/resident/appserver.py`).

**One-shot `colleague work "<instruction>"` text deliberately bypasses text
intake** — it is already deliberate CLI input, and running Gemma's TTFT on
every scripted/CI invocation would be pure overhead with no operator-facing
"raw ↔ interpreted" gap to bridge. Work items still get **senses MEDIA
perception**: when the task carries attachments and the senses model is
declared multimodal, the media-comprehension bridge (below) **prefers
senses over deepthink** — `_maybe_run_senses_media_bridge` runs first and,
when armed, the deepthink media-bridge path is a strict no-op. So a one-shot
work item with `--attach` still exercises senses; a one-shot work item with
plain text does not.

## The packet

```python
ContextPacket(
    original="fix the flaky test in test_foo.py",  # verbatim — sacrosanct
    interpretation="Investigate and fix a non-deterministic test failure in test_foo.py",
    confidence=0.8,
    task_type="bugfix",
    omissions=["which specific test function", "whether CI or local repro"],
)
```

`original` is **never** derived from the model's output — the caller's exact
text is copied onto the packet before the completion is even issued, and it
rides the loop as-is: when a task carries a `context_packet`, the loop injects
the **original text verbatim** as the user message and appends the senses
interpretation as ONE **advisory companion message**
(`colleague/loop.py` `_maybe_inject_context_packet`). The packet augments,
never replaces — a test pins that cortex's prompt always contains the
operator's original words byte-for-byte whenever a packet is present.

A failed or lossy intake (dead endpoint, timeout, unparseable JSON) returns
`(None, degraded SensesRecord)` — the caller passes the raw text through
untouched. **Intake can never lose the request.**

`--debug-senses` surfaces the packet on stderr; it is always inspectable in
the artifact via `TaskResult.senses.packet`.

## The cannot-act guarantee

Every senses invocation — intake, speak-back, and the media bridge — is
issued through the **same enumerated tools-off completion machinery as
deepthink**: `Engine.make_complete(senses_config, tools=[])`. An explicit
empty tool list is on the wire, never `None` — a senses request *structurally
cannot carry a tool schema*, the same invariant class as the acceptance
self-check. This mirrors what the live lobes contract itself reports for the
`senses` role:

```json
"forbidden_responsibilities": ["final_decision", "repo_action", "security_decision"]
```

A dedicated structural proof (`colleague/senses.py` imports neither
`colleague.tools.ToolExecutor` nor `subprocess`; a stub senses response
carrying literal tool-call markup or an OpenAI `tool_calls` payload produces
only a plain advisory packet or a degraded record — zero `ToolExecutor`
invocations, repo tree provably untouched) pins this even against a
misbehaving/hallucinating senses model.

## Measurement story

`TaskResult.senses` is an omit-when-None block, `{mode, packet, records}`,
where `records` is the ordered list of `SensesRecord {point, latency, tokens,
degraded}` entries — one per senses invocation (`senses-intake`,
`senses-speakback`, `media-bridge`). This is the senses-side sibling of
`TaskResult.deepthink`'s `{point, tokens, duration, degraded}` records. Tokens
are read verbatim from the response `usage` (never estimated) exactly like
every other token-honesty surface in colleague.

The same task run **cortex-only** and **split** yields two artifacts whose
`stats`/`senses` fields are directly comparable side-by-side: wall-clock,
senses overhead (intake + speak-back latency/tokens), and — implicitly —
whether split mode changed the number of cortex calls. **No field anywhere
asserts answer correctness or task quality** — that stays with the operator
feedback/ROI loop (`colleague feedback`), mirroring the lobes contract's own
runtime-only measurement line. The live per-mode comparison is the
`cortex-senses` livecheck scenario's job (task t13); see
[`docs/live-testing.md`](../live-testing.md).

## Why it matters — hardware

The split maps each mind to what it is actually good at on the reference
"lobes" rig (probed live 2026-07-03, `LOBES_LIVE_FINDINGS.md`, gateway at
`http://localhost:8001`):

| Role | Model | Context | Notes |
|---|---|---|---|
| **cortex** | `unsloth/Qwen3.6-27B-NVFP4` | **131072** (128K) | `ready`+`loaded` true, `forbidden_responsibilities: []` — the only lobe that can tool-call |
| **senses** | `coolthor/gemma-4-12B-it-NVFP4A16` | **32768** (32K) | `ready`+`loaded` true, `mtp: true` (multimodal, MTP-fast), `responsibilities: [intake, normalize_input, classify_intent, prepare_context_packet, speak_back]`, `forbidden_responsibilities: [final_decision, repo_action, security_decision]` |

Qwen 27B is the only rig lobe that can drive the bounded tool loop — Gemma4's
serving-side tool-call parser gap makes it structurally unable to (the same
finding [`deepthink.md`](deepthink.md) and [`media-input.md`](media-input.md)
already record: a Gemma-as-main run finishes via pseudo-markup,
`status: incomplete`). Gemma4 is the only multimodal + MTP-fast lobe. So
**cortex-owns-actions / senses-owns-perception is the honest division on this
rig** — not an arbitrary design preference. If a later serving-side parser fix
gives Gemma tool-calling, this division becomes a *design choice*, documented
as such, never left standing as a stale hardware claim.

## The honest line: this is not a router

The historically out-of-scope **multi-model router / routing policy** is
still out of scope. Cortex/senses is the **second** sanctioned, re-specced
increment at that boundary (the first was [deepthink](deepthink.md)) — and it
moves the line exactly this far and no further:

- **TWO** operator-declared roles with a **fixed** responsibility boundary —
  cortex acts (drives the loop, tools, gates, handoff), senses perceives and
  presents (intake, speak-back, media description) — no N-role
  generalization;
- roles are **resolved by name** from the lobes contract, never selected
  per-task by a heuristic;
- **no automatic task→model routing policy** — the model never decides
  per-input whether cortex is needed; there is no "senses answers cheap
  questions on its own" path;
- senses sits **only** on operator-facing surfaces (session, mesh residency);
  the bounded tool loop, the pre-handoff gates, and the git handoff are cortex
  territory, untouched;
- absent config = **byte-identical** single-model colleague, exactly like
  deepthink's absent-config guarantee.

Two explicit follow-ups are parked, not built, each needing its own
router-boundary re-spec before it can land:

- **[#276](https://github.com/agentculture/colleague/issues/276)** —
  senses-direct-for-cheap-tasks (senses answering without cortex at all). A
  model deciding per-input whether cortex is needed *is* the start of the
  excluded routing policy — this is explicitly parked pending real
  split-mode measurements, not built here.
- **[#277](https://github.com/agentculture/colleague/issues/277)** — the
  voice loop (`stt`/`tts` consumption: audio capture/playback) and
  embedder/reranker consumption (colleague's memory stays the eidetic CLI's
  business). Both roles are discoverable in the `/capabilities` contract from
  day one (`colleague lobes show` reports all resolved roles the gateway
  exposes) but colleague consumes only `cortex`/`senses`; `stt`/`tts`/
  `embedder`/`reranker` are read and discarded.

## Three-tier mode — legacy vs three-tier distinction

In **legacy mode** (no `three_tier` config), the cortex-only semantics are
unchanged: the cortex drives the tool loop, senses operates as the
tools-off front door, and deepthink is available for judgment escalation.
The `--cortex-only` flag keeps its meaning — it bypasses the senses front
door for one run.

In **three-tier mode** (opt-in via `config.json` `three_tier` or
`COLLEAGUE_THREE_TIER`), the worker role resolves as the acting dial — the
model that drives the tool loop. Senses carries structural fidelity clauses
(verbatim worker-answer containment, raw-answer fallback). The cortex is
available for the opt-in configurator (default off). Deepthink is absent
in three-tier mode. See [three-tier.md](three-tier.md) for the full
feature doc.

## Honest limits

- **The senses intake window is 32K, and it is windowed — `original` never
  is.** `run_senses_intake`/`run_senses_speakback` window the PROMPT sent to
  the senses model to the senses model's own `context_budget` (default 24000,
  ~73% of a 32768 window — the default 27B/64K-window ratio deepthink uses,
  applied to senses' own window); a prompt that overflows is binary-searched
  down with a visible `[senses digest truncated to fit budget]` marker. This
  windowing affects only what senses itself *reads* — `ContextPacket.original`
  is set to the caller's text before any windowing and is never touched by
  it, so a long request is always preserved verbatim on the packet and in the
  cortex prompt, even when senses' own interpretation of it was formed from a
  truncated view.
- **The lobes `endpoint` field is now client-reachable (lobes-cli 0.38.0,
  closing lobes-cli#87) — and `EngineConfig.resolve()` now dials it (colleague#292,
  S1+S2 of the #291 lobes-0.38 re-sync, task t19).** The arc's original probe
  found each role's `endpoint` reporting an internal host
  (`http://localhost:8000`) that 404s from outside the gateway's own network —
  only the gateway origin (`:8001` on the reference rig) actually answered.
  Since lobes-cli 0.38.0, `/capabilities` advertises each role's `endpoint` as
  a genuinely dialable, Host-derived origin (overridable via the gateway's
  `GATEWAY_PUBLIC_URL`), empty when a role is unwired. `colleague/lobes.py`
  exposes `resolve_role_base_url(role, gateway_url)`: dial the role's own
  `endpoint` when it is a non-empty `http`/`https` URL (the same scheme guard
  `resolve_roles` applies to the gateway URL itself), falling back to the
  gateway origin only when `endpoint` is empty/missing. **Now wired into
  `EngineConfig.resolve()` end-to-end**: `colleague/config.py`'s
  `_role_dial_base_url`/`_resolve_lobes_rung` dial cortex's, senses', and
  voice's (stt/tts, via two independent `VoiceConfig` fields
  `stt_base_url`/`tts_base_url`) OWN advertised endpoints — the
  gateway-origin-for-all workaround is gone; the gateway origin survives only
  as the documented per-role fallback (unwired role or disallowed scheme).
  This closes the S1 follow-on that this section previously tracked. The
  `embedder` role is ALSO now resolved (S2): `colleague/lobes.py`'s `embed_env`
  relays its dial target + model id as `EIDETIC_EMBED_URL`/`_MODEL` and
  `COHERENCE_EMBED_URL`/`_MODEL` env vars into the eidetic-CLI shell-out
  (`colleague/memory.py`) — colleague itself never issues an embeddings
  request (spec boundary c9/h18); `reranker` stays ignored (#277's parked
  retrieval lane).
- **`ready` means two different things depending on the role.** For
  `cortex`/`senses`/`embedder`/`reranker`, the gateway's `ready` is a CONFIG
  PROXY — `ready == loaded` (the model is loaded into the serving process),
  never an actual request-level liveness probe. For `stt`/`tts`, lobes-cli
  0.38.0 (closing lobes-cli#89) made `ready` LIVE-PROBE-BACKED via the
  realtime bridge's own health check; a warming audio backend now answers
  HTTP 503 with `Retry-After` (never a bare 502) while it warms up.
  `colleague/lobes.py`'s `ready_kind(role_name)` classifies which is which,
  and `colleague lobes show` labels each role accordingly
  (`config-proxy`/`live-probed`) so an operator never conflates the two.
  `colleague/voice.py`'s `transcribe`/`synthesize` treat a 503+`Retry-After`
  as "warming": wait `min(Retry-After, 10s)` and retry ONCE, then degrade
  exactly as before (a 502 or any other failure is unaffected).
- **A lobes-discovered senses is `multimodal=False`.** `RoleInfo` (the t1
  parsed shape) carries no `mtp`-to-`multimodal` mapping, so discovering
  senses off the wire never auto-arms the media-comprehension bridge — an
  operator arms it explicitly via `COLLEAGUE_SENSES_MULTIMODAL=1` (or
  `config.json` `{"senses": {"multimodal": true}}`), the same "declaration,
  never a probe" rule deepthink's `multimodal` flag already follows. This is
  deliberate, not a gap: the live rig's senses role IS multimodal
  (`mtp: true`), but colleague never infers capability from a model name or
  a wire hint.
- **Intake is synchronous in v1.** `_prepare_senses` blocks on the senses
  completion before the work item starts — every split-mode turn pays the
  senses model's TTFT. A parallel-with-acknowledgement intake path was an
  explicit plan-time unknown, deferred pending live MTP latency numbers.
- **Deepthink and senses can coexist, but their surfaces are disjoint.** An
  operator declaring both gets deepthink's judgment-escalation points
  (unchanged) plus senses' perception/presentation points; when BOTH are
  declared multimodal, the media bridge **prefers senses** (the media bridge
  point is recorded under `TaskResult.senses`, and the deepthink media-bridge
  path is skipped as a strict no-op) — pinned by task t6's tests.
- **The live rebalanced-stack proof.** The 2026-07-03 rig probe
  (`LOBES_LIVE_FINDINGS.md`) confirms the stack described above —
  cortex@128K and senses@32K — is now actually serving (previously PENDING
  on an unrebalanced rig). The end-to-end split-vs-cortex-only measurement itself
  is the `cortex-senses` livecheck scenario's job (task t13); see
  [`docs/live-testing.md`](../live-testing.md) for its current status —
  recorded honestly as PENDING until that scenario runs, never claimed
  proven ahead of the evidence.
