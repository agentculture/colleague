# Build Plan — Colleague owns the model-gear boundary: when the model server crashes on a tool-calling request (e.g. a vLLM EngineCore 500), Colleague surfaces an actionable error that names the likely cause and points at config + doctor --probe; doctor --probe proactively catches a server that can't actually serve Colleague's tool-calling requests (not just one that answers /v1/models); and an operator can dump the exact outgoing request — so a caller of ask-colleague / colleague work never has to debug the model server directly.

slug: `colleague-owns-the-model-gear-boundary-when-the-mo` · status: `exported` · from frame: `colleague-owns-the-model-gear-boundary-when-the-mo`

> Colleague owns the model-gear boundary: when the model server crashes on a tool-calling request (e.g. a vLLM EngineCore 500), Colleague surfaces an actionable error that names the likely cause and points at config + doctor --probe; doctor --probe proactively catches a server that can't actually serve Colleague's tool-calling requests (not just one that answers /v1/models); and an operator can dump the exact outgoing request — so a caller of ask-colleague / colleague work never has to debug the model server directly.

## Tasks

### t1 — vLLM engine: map a server-crash 500 to an actionable Colleague error

- covers: c3, h3, c11, h10
- acceptance:
  - A stubbed HTTP 500 whose body contains 'EngineCore'/'InternalServerError' on a tools-bearing request yields a Colleague error naming the likely cause (tool-calling + speculative-decoding/FP4) and pointing at 'colleague doctor --probe', with the original upstream body preserved
  - A 400 (validation) or a 500 with an unrecognized body degrades to a generic 'the model server returned <code>' message and is NOT attributed to a server crash (no mis-blame of Colleague-side faults)
  - Stdlib-only status+body inspection in vllm_openai.py (or a shared wrap); no new dependency

### t2 — doctor --probe: real tool-calling round-trip (works / unsupported / crashed)

- covers: c4, h4
- acceptance:
  - A new opt-in check under 'doctor --probe' POSTs ONE minimal tools+tool_choice chat/completions request and classifies WORKS / TOOL-CALLS-UNSUPPORTED / SERVER-CRASHED, each with a distinct remediation line
  - Stub: a tool_call reply -> WORKS; a 400/tool-parser error -> TOOL-CALLS-UNSUPPORTED ('--enable-auto-tool-choice + --tool-call-parser'); a 500-EngineCore -> SERVER-CRASHED ('check speculative-decoding/FP4')
  - The check runs ONLY under --probe (never on the no-network doctor path), and doctor itself never raises on a probe failure — a crash is reported as a check result

### t3 — --dump-request: surface the exact outgoing payload

- depends on: t1
- covers: c5, h5
- acceptance:
  - With the dump enabled (flag and/or COLLEAGUE_* env) the exact payload (model/messages/tools/tool_choice/temperature) is emitted (stderr or file); disabled, output is byte-identical to today
  - The api_key never appears in the dump (it is an Authorization header, not in the payload)
  - Enabling the dump does not change the request actually POSTed (same bytes on the wire)

### t4 — Integration + boundary verification (close the #182 path; hold the non-goals)

- depends on: t1, t2, t3
- covers: c1, h1, c8, h8, c9, h9
- acceptance:
  - End-to-end stub: against a crashing-server stub, 'doctor --probe' reports an actionable failure (not green) AND a work item surfaces the legible error — the #182 path is closed without touching the model server
  - tests/test_zero_deps.py still passes — none of the three features adds a third-party import (zero-dep honesty)
  - The final diff adds no server-side change, no model-router, and no retry-of-a-crashed-engine path (boundary held)

### t5 — Docs + version bump: frame the #182 ownership correction

- depends on: t1, t2, t3
- covers: c2, h2, c6, h6, c7, h7
- acceptance:
  - CHANGELOG.md + pyproject.toml bumped (patch); the entry frames the before (cryptic 500 / green-but-blind probe) -> after (legible error + real tool-calling probe + --dump-request) and names the caller-vs-operator audience (#182)
  - A short note (feature doc and/or 'colleague explain doctor' text) states Colleague owns the model-gear boundary and a caller never debugs the server
  - version-check CI passes (PR version > main)

## Risks

- [unknown_nonblocking] The --probe tool-calling check sends the SAME class of request that crashed the engine, so it may itself trip the crash or disturb a shared server; mitigated by a minimal request + opt-in --probe, but cannot be eliminated. (task t2)
