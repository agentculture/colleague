# Convertible gains GPS: opt-in OpenTelemetry observability — traces and metrics for a drive, emitted from the shared chassis so every engine is instrumented identically, with the OpenTelemetry SDK shipped as an optional extra that keeps the base install at zero runtime dependencies.

> Convertible gains GPS: opt-in OpenTelemetry observability — traces and metrics for a drive, emitted from the shared chassis so every engine is instrumented identically, with the OpenTelemetry SDK shipped as an optional extra that keeps the base install at zero runtime dependencies.

Issue: https://github.com/agentculture/convertible/issues/22 — *"Install GPS: OTeL support"*

## Audience

- Convertible operators who run drives across machines and want them traced and measured against the same OpenTelemetry collector the sibling AgentCulture repos (e.g. `../culture`) already feed, plus engine-wheel developers who need observability to live in the chassis (not per-engine).

## Before → After

- Before: A drive's only record is the per-run JSON artifact + step trace (the "dashboard"). It is blind across runs — no spans, no metrics, nothing a collector can aggregate. There is no way to watch a fleet of drives or measure tool latency / token spend over time.
- After: With `CONVERTIBLE_OTEL_ENABLED=1` and the `[otel]` extra installed, every drive emits an OpenTelemetry trace (`convertible.drive` root → `convertible.tool.*` children → `convertible.handoff`) and metrics (steps, tokens, tool latency, tool calls, hook denials, drive duration) over OTLP to a configured collector. Off by default it is a strict no-op: no spans, no SDK import, the result artifact unchanged.

## Why it matters

- Running models against repos at fleet scale needs cross-run observability, and the AgentCulture mesh already standardises on OpenTelemetry (`culture/telemetry/`). Putting the instrumentation in the loop + the shared drive path means it binds every engine under the all-engines rule — exactly like lifecycle hooks — instead of each wheel reinventing it.

## Requirements

- R1 Chassis instrumentation: spans + metrics are emitted from `convertible/loop.py` (per tool call) and the shared `execute_drive` path (root + handoff), so they apply to every engine identically; a drive on `mock` and on `vllm-openai` is instrumented the same way (all-engines rule).
  - honesty: The loop and `execute_drive` are the only places telemetry is wired; no engine module imports the telemetry package. A `mock` drive and a `vllm-openai` drive produce the same span tree shape.
- R2 Opt-in, no-op by default: telemetry is off unless explicitly enabled; when off, no span is created, no metric recorded, no SDK imported, and `TaskResult` is byte-identical to today's.
  - honesty: With telemetry off, `tests/test_e2e_mock.py` (artifact shape) and the existing loop/drive tests pass unchanged, and `convertible.loop` imports no third-party module.
- R3 Zero runtime deps preserved: the OpenTelemetry SDK is an optional extra (`pip install 'convertible-cli[otel]'`); `pyproject.toml` keeps `dependencies = []`. The SDK is imported lazily, only when telemetry is enabled.
  - honesty: `tests/test_zero_deps.py` asserts `[project].dependencies == []` and that importing `convertible.telemetry` / `convertible.loop` / `convertible.cli` pulls in no third-party top-level module — and it passes even with the `[otel]` extra installed (dev/CI).
- R4 Graceful degradation: telemetry requested without the extra installed degrades to a no-op with a one-time stderr notice; it never fails the drive.
  - honesty: A test forces the lazy SDK import to raise and asserts `load_telemetry` returns the no-op and prints the `[otel] extra` notice to stderr; the drive still completes.
- R5 Config from the environment: telemetry config resolves with the convertible precedence (explicit > `CONVERTIBLE_OTEL_*` > standard `OTEL_*` > default); `OTEL_SDK_DISABLED=true` is honored as a kill-switch. Field names mirror `agentirc`/`culture`'s `TelemetryConfig`.
  - honesty: Table-driven tests cover each precedence rung and the kill-switch; defaults are off, `service.name=convertible`, OTLP/HTTP `:4318`.
- R6 Agent-first CLI surface: a `telemetry` noun (`telemetry status`, `telemetry overview`) follows the conventions (register(sub), `--json`, noun exposes `overview`, an explain catalog entry) and passes `teken cli doctor . --strict`. `telemetry status` reports the resolved config and whether the SDK is installed (without importing it).
  - honesty: `convertible telemetry status --json` emits the resolved config + `sdk_installed`; the noun exposes `overview`; `explain telemetry` exists; `teken cli doctor . --strict` passes.
- R7 Signal fidelity: spans carry the drive's facts (task id, engine, model, tool, ok, changed file, status, pr_url); metrics follow culture's `convertible.<area>.<metric>` naming.
  - honesty: An SDK-backed test (in-memory exporter, no network) drives the loop and asserts the `convertible.tool.*` spans and the `convertible.steps`/`tokens`/`tool.calls`/`tool.latency` instruments are emitted.

## Honesty conditions

- A single drive with telemetry enabled emits one `convertible.drive` trace whose tool spans nest under the root and whose handoff is a child — observable via an in-memory exporter in tests and a real collector in the manual proof.
- On main today there is no telemetry of any kind (zero mentions of otel/telemetry/spans/metrics in the repo) and `dependencies = []`; both are verifiable by inspection.
- The base install never gains a runtime dependency: the SDK lives in `[project.optional-dependencies] otel`, the import is deferred, and the zero-deps guard proves the deferral.
- No code path opens a listening socket or forks a daemon; OTLP export is outbound HTTP via the SDK exporter (the same category as the vLLM driver's outbound `urllib` POST).
- Telemetry off is a true no-op: identical artifact shape, no SDK import, no behavior drift — guarded by the existing e2e shape test.

## Scope / boundaries

- In scope: traces + metrics over OTLP, the optional `[otel]` extra, env-driven config, the `telemetry` introspection noun, instrumentation of the loop + shared drive path.
- Out of scope (re-spec if wanted): logs signal export, W3C trace-context propagation across mesh hops, an audit JSONL sink (culture has one), a grpc exporter in the default extra (HTTP only; grpc is operator-addable), and changing `TaskResult` to carry trace ids.

## Decisions

- D1 OTeL is an accepted, documented exception to the no-deps rule — but only as an optional extra; the base package stays dep-free and the SDK import is deferred.
- D2 Default exporter is OTLP/HTTP on `:4318` (lean extra); culture's gRPC `:4317` collectors also accept HTTP, and `otlp_protocol` is selectable.
- D3 Telemetry off is the default and a strict no-op, to protect the all-engines shape invariant and the zero-deps guard.
