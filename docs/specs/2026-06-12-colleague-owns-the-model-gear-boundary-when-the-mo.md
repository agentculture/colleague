# Colleague owns the model-gear boundary: when the model server crashes on a tool-calling request (e.g. a vLLM EngineCore 500), Colleague surfaces an actionable error that names the likely cause and points at config + doctor --probe; doctor --probe proactively catches a server that can't actually serve Colleague's tool-calling requests (not just one that answers /v1/models); and an operator can dump the exact outgoing request — so a caller of ask-colleague / colleague work never has to debug the model server directly.

> Colleague owns the model-gear boundary: when the model server crashes on a tool-calling request (e.g. a vLLM EngineCore 500), Colleague surfaces an actionable error that names the likely cause and points at config + doctor --probe; doctor --probe proactively catches a server that can't actually serve Colleague's tool-calling requests (not just one that answers /v1/models); and an operator can dump the exact outgoing request — so a caller of ask-colleague / colleague work never has to debug the model server directly.

## Audience

- Callers of Colleague's contract (agents using ask-colleague / colleague work — e.g. culture in #182) who must NEVER have to operate model-gear directly; and the operator who runs Colleague + the model server, who needs an actionable diagnostic instead of a raw upstream 500.

## Before → After

- Before: Today 'doctor --probe' only GETs {base_url}/models (reachability.py) so it goes GREEN even on a server that crashes on tool calls; a tool-calling EngineCore crash bubbles up via vllm_openai._post_json + work.py as a bare 'engine X failed: HTTP Error 500 ... EngineCore' after ~199s; and there is no way to see the outgoing payload — so the caller (culture, #182) was pushed to curl the server and reconfigure vLLM themselves.
- After: A model-server crash on a tool-calling request (a 500 whose body names EngineCore / InternalServerError) surfaces as an actionable Colleague error that names the likely cause (tool-calling + speculative-decoding/FP4) and points at the server config + 'colleague doctor --probe' — not a bare 'HTTP Error 500' after ~3 minutes.
- After: 'colleague doctor --probe' does a real tool-calling round-trip (one minimal tools+tool_choice chat/completions request) and reports whether the server can actually SERVE Colleague's requests — catching a tool-calling-incapable / crashing server up front, distinct from the existing 'GET /v1/models is reachable' check.
- After: An operator can dump the exact outgoing request payload Colleague sends to the model (a --dump-request switch or COLLEAGUE_* env), to inspect/diff it without a logging proxy or hand-curling :8001; the api_key (a header, never in the payload) is never exposed.

## Why it matters

- Colleague is the harness BETWEEN the agent and the model; it owns that boundary. A cryptic upstream crash reaching the caller as 'go debug your vLLM' is a Colleague UX defect regardless of where the crash physically lives. A consumer of ask-colleague must never have to operate model-gear directly (the ownership correction on #182).

## Requirements

- Error legibility: vllm_openai._post_json (or the shared work-failure wrap) maps a 500 whose body contains 'EngineCore'/'InternalServerError' on a tools-bearing request to an actionable Colleague error that names the likely cause and points at 'colleague doctor --probe' + the server config — while PRESERVING the original upstream body and degrading to a generic 'server error' for a non-vLLM 500, so a real Colleague-side fault is never mis-attributed to the server.
  - honesty: The mapping keys off the OpenAI-standard 500 status + a body-substring match, so it works for vLLM ('EngineCore') and degrades to a generic 'the model server returned a 500' for any other OpenAI-compatible server — a config retarget, never a code change, consistent with the engine's config-not-code rule.

## Honesty conditions

- All three capabilities are runtime/engine-side and zero-dep (stdlib urllib, mirroring vllm_openai.py + reachability.py); nothing opens a socket/daemon or adds a dependency; the 'EngineCore' string is vLLM-specific, so heuristics key off the OpenAI-standard 500 status + body text and degrade to a generic message on a non-vLLM server.
- The audience split is real: the CALLER (an agent, via ask-colleague) gets a clean Colleague error; the OPERATOR (who runs the server) gets the actionable remediation. #182 is the concrete instance — culture called 'ask-colleague review', never touched the server.
- The error mapping is a heuristic INFERENCE ('likely cause'), not a claim about the server's internals; it preserves the original upstream body, fires only on a 500 whose body matches the server-crash markers (never a 400 validation), so a genuine Colleague-side fault is never re-attributed to the server.
- The probe sends exactly ONE minimal tools+tool_choice request, stays behind --probe (it opens a connection and costs a small generation), and classifies WORKS / TOOL-CALLS-UNSUPPORTED / SERVER-CRASHED — a tool-unsupported server yields an actionable 'enable tool calling' message, not a false-green and not a crash of doctor itself.
- The dump is a faithful copy of the exact payload sent (model/messages/tools/tool_choice/temperature); the api_key (an Authorization header) is never part of it; toggling the dump does not change the request actually sent.
- Verified on current main: reachability.py only GETs {base_url}/models; vllm_openai._post_json re-raises the HTTPError with the body folded in but adds no diagnosis; work.py wraps an engine failure as 'engine X failed: <err>' (EXIT_ENV_ERROR) — none test tool calling or expose the payload.
- This is the recorded ownership correction on #182: the caller used ask-colleague's contract, not the server; therefore the fix is Colleague-side legibility + catchability, never asking the caller to operate model-gear.
- The out-of-scope items genuinely hold: no server-side change, no blind retry of a possibly-dead engine, no model router; zero new deps (stdlib urllib only); the vLLM-specificity of 'EngineCore' is handled by a documented degrade-to-generic path, not pretended away.
- The three checks are provable with stubs (a monkeypatched _post_json returning a 500-EngineCore body; a fake probe target classifying works/unsupported/crashed) — no live model — exactly how the oilcheck + ask-colleague tests already stub the wire.

## Success signals

- 'doctor --probe' against a tool-calling-incapable / crashing server reports an actionable FAILURE (not green); a work item that hits a 500-EngineCore prints an error naming the likely cause + the 'doctor --probe' next step; '--dump-request' emits the exact outgoing payload. All three are covered by stub-based tests (no live model). Net: the #182 reporter learns what's wrong from Colleague, never by curling :8001.

## Scope / boundaries

- Out of scope: Colleague does NOT fix or work around the server crash (the FP4/MTP/spec-decode crash is the operator's / model-gear's to resolve) — it makes the failure LEGIBLE + CATCHABLE, never silenced or auto-retried against a possibly-dead engine; NOT a multi-model router/fallback; stays within the zero-deps / no-socket / no-daemon conventions (probe + dump use stdlib urllib like the engine). The EngineCore string is vLLM-specific, so the heuristics key off the OpenAI-standard 500 + body text and degrade to a generic message on a non-vLLM server.

## Decisions

- Probe design: add an opt-in tool-calling check under 'doctor --probe' (beside provider_reachable) that POSTs ONE minimal tools+tool_choice chat/completions request and classifies the outcome: WORKS (a tool_call or clean completion) / TOOL-CALLS-UNSUPPORTED (400 / tool-parser error -> 'start vLLM with --enable-auto-tool-choice + --tool-call-parser') / SERVER-CRASHED (500 EngineCore -> 'the server crashed on a tool-calling request; check speculative-decoding/FP4'). Each outcome carries a distinct actionable remediation.
- Introspection: a '--dump-request' switch (and/or COLLEAGUE_* env) writes the exact outgoing request payload (model/messages/tools/tool_choice/temperature) to stderr or a file; the api_key is an Authorization header and is NEVER part of the dump; enabling the dump does not alter the request actually sent.

## Hard questions

- risk: The probe's tool-calling request is the SAME class of request that crashed the EngineCore — so on a genuinely fragile server the probe itself may trip the crash (and could disturb other clients sharing that server). The probe must use a minimal request to limit blast radius and treat the crash as the diagnostic signal; it cannot avoid poking the server, which is partly why it stays opt-in behind --probe.
