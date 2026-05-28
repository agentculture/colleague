# GPS: OpenTelemetry observability

> Opt-in OpenTelemetry traces + metrics for a drive — observable against an OTLP
> collector, not just the per-run artifact.

GPS makes a drive observable: it emits **OpenTelemetry traces + metrics** over
OTLP so a run shows up in a collector, complementing the per-run JSON
[artifact](artifact.md). Telemetry lives in the **chassis** — instrumented once
in the loop (`convertible/loop.py`, per tool call) and the shared drive path
(root + handoff spans) — so *every* engine emits identical signals (the
all-engines rule), exactly like lifecycle hooks. No engine module touches the
`telemetry` package.

## Off by default; a strict no-op

Telemetry is **off by default** and a strict no-op when off: no spans, no SDK
import, the `TaskResult` unchanged. That property is protected so the e2e shape
test and the zero-deps guard keep passing.

The OpenTelemetry SDK is an **optional `[otel]` extra**, never a base
dependency — the base install keeps zero runtime dependencies. It is imported
**lazily** inside `convertible/telemetry/_otel.py`, only when telemetry is
enabled. Requested *without* the extra installed, convertible degrades to a no-op
with a one-line stderr notice — it never fails the drive.

```bash
pip install 'convertible-cli[otel]'                        # or: uv sync --extra otel
export CONVERTIBLE_OTEL_ENABLED=1
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318   # OTLP/HTTP collector
convertible drive "<task>" --repo . --engine mock --no-pr
#   -> stderr prints "trace: <id>"; the collector receives the spans + metrics
```

## Signals

**Spans:** `convertible.drive` (root) → `convertible.tool.*` (one per tool call)
→ `convertible.handoff`.

**Metrics:** `convertible.steps`, `convertible.tokens` (attr `kind`),
`convertible.tool.latency`, `convertible.tool.calls`, `convertible.hook.denials`,
`convertible.drive.duration` (attr `status`).

## Configuration

Precedence (highest first): explicit > `CONVERTIBLE_OTEL_*` > standard `OTEL_*` >
default. `OTEL_SDK_DISABLED=true` is honored as a kill-switch.

| Variable | Meaning |
|----------|---------|
| `CONVERTIBLE_OTEL_ENABLED` | Turn telemetry on (default: off). |
| `CONVERTIBLE_OTEL_ENDPOINT` / `OTEL_EXPORTER_OTLP_ENDPOINT` | Collector URL. |
| `CONVERTIBLE_OTEL_SERVICE_NAME` / `OTEL_SERVICE_NAME` | Resource `service.name`. |
| `CONVERTIBLE_OTEL_METRICS_ENABLED` | Toggle metric emission (default: on). |

## Usage

```bash
convertible telemetry status      # resolved config + whether the SDK is installed
convertible telemetry status --json
convertible telemetry overview
```

## Key files

- `convertible/telemetry/__init__.py` — `TelemetryConfig`, `load_telemetry`,
  `sdk_available`, the no-op `Telemetry`.
- `convertible/telemetry/_otel.py` — the **only** module that imports
  `opentelemetry` (lazily).
- `convertible/loop.py` — per-tool spans + metrics.

## See also

- [doctor.md](doctor.md) — the `otel` check-group reports GPS readiness without
  enabling telemetry or importing the SDK.
- [artifact.md](artifact.md) — the per-run record GPS complements.
