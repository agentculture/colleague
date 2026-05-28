# Build Plan — Convertible gains GPS: opt-in OpenTelemetry observability (traces + metrics) emitted from the shared chassis, with the SDK as an optional extra that keeps the base install at zero runtime dependencies.

slug: `convertible-gains-otel-gps-observability` · status: `exported` · from frame: `convertible-gains-otel-gps-observability`

> Issue #22 "Install GPS: OTeL support". Telemetry belongs to the chassis (the loop + the shared drive path), so every engine emits it identically — like lifecycle hooks. The OpenTelemetry SDK ships as an optional `[otel]` extra, lazily imported, so the base install keeps `dependencies = []`.

## Tasks

### t1 — Telemetry facade: stdlib-only config + no-op (no SDK import)

- acceptance:
  - `convertible/telemetry/__init__.py` defines `TelemetryConfig` (+ `resolve()`), the `Telemetry` no-op base, `load_telemetry()`, and `sdk_available()` — importing none of `opentelemetry`.
  - `TelemetryConfig.resolve()` honors precedence (explicit > `CONVERTIBLE_OTEL_*` > `OTEL_*` > default) and `OTEL_SDK_DISABLED`; off by default.

### t2 — SDK-backed implementation (lazily imported)

- depends on: t1
- acceptance:
  - `convertible/telemetry/_otel.py` imports `opentelemetry` at top level but is imported **only** from inside `load_telemetry()`.
  - builds TracerProvider + MeterProvider with OTLP/HTTP exporters; emits the `convertible.drive`/`convertible.tool.*`/`convertible.handoff` spans and the `convertible.steps`/`tokens`/`tool.calls`/`tool.latency`/`hook.denials`/`drive.duration` instruments; `flush()` force-flushes; an atexit hook shuts the providers down.
  - accepts in-memory exporter test seams; `reset_for_tests()` drops cached providers.

### t3 — Loop instrumentation (the all-engines seam)

- depends on: t1, t2
- acceptance:
  - `loop.run()` gains a `telemetry=None` kwarg defaulting to `load_telemetry()` (mirrors `hooks`); each tool call is wrapped in a `tool_span`; tokens recorded per completion; hook denials recorded.
  - with telemetry off, the loop result is byte-identical to today's (no new fields, no drift).

### t4 — Shared drive path: root + handoff spans

- depends on: t2, t3
- acceptance:
  - `execute_drive` opens the `convertible.drive` root span around `engine.drive()` + `handoff()` + the artifact write, opens a `convertible.handoff` child, emits a `trace: <id>` stderr diagnostic, and `flush()`es in a `finally`.
  - both `drive` and `session` are instrumented (both route through `execute_drive`); the engine-failure path still writes the error artifact and raises `CliError`.

### t5 — CLI noun + explain

- depends on: t1
- acceptance:
  - `convertible telemetry status [--json]` reports the resolved config + `sdk_installed` (probed without importing the SDK); `telemetry overview` describes the noun; bare `telemetry` falls back to overview.
  - registered in `cli/__init__.py`; explain entries added; `teken cli doctor . --strict` passes.

### t6 — Packaging: optional extra + dev/CI install

- depends on: t2
- acceptance:
  - `[project.optional-dependencies] otel` lists the SDK packages; `dependencies = []` unchanged; the same packages added to the `dev` group so `uv sync` installs them and the telemetry tests run in CI.

### t7 — Tests + guards

- depends on: t1, t2, t3, t4, t5
- acceptance:
  - `tests/test_telemetry.py`: config precedence, disabled→no-op (no import), enabled-but-missing-SDK→graceful no-op + notice, and (SDK-gated, in-memory) tool spans + drive-span nesting + metrics.
  - `tests/test_telemetry_cli.py`: status/overview/explain.
  - `tests/test_zero_deps.py` extended to import `convertible.telemetry` + `convertible.cli` and assert no third-party leak (the deferral guard).
  - full suite + lint + `teken` gates green.

### t8 — Docs + version

- depends on: t1–t7
- acceptance:
  - `CLAUDE.md` adds GPS/telemetry to the car metaphor and documents the optional-extra exception honestly; `README.md` gains a telemetry section; this spec/plan pair committed.
  - version bumped (0.6.0 → 0.7.0, minor) with a CHANGELOG entry.

## Dependency order

t1 → (t2, t3, t5, t6) → t4 → t7 → t8.

## Risks

- The OTLP exporter logs transient errors when no collector is reachable; the drive still completes (verified). Operators must point `OTEL_EXPORTER_OTLP_ENDPOINT` at a live collector. Not a correctness risk.
- Keeping the SDK import deferred is load-bearing for the zero-deps guard; the extended `test_zero_deps` is the regression guard.
