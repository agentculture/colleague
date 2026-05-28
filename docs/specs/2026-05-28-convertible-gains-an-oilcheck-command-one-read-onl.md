# Convertible gains an 'oilcheck' command — one read-only health check that verifies the CLI is functional, the engine wheels are discoverable, and the repo config is sound, with rubric-shaped pass/fail and remediation hints, so you catch a broken install or misconfig before a drive fails mysteriously.

> Convertible gains an 'oilcheck' command — one read-only health check that verifies the CLI is functional, the engine wheels are discoverable, and the repo config is sound, with rubric-shaped pass/fail and remediation hints, so you catch a broken install or misconfig before a drive fails mysteriously.

## Audience

- convertible operators setting up the CLI in a repo, and agents verifying their environment is sound before issuing a 'drive'.

## Before → After

- Before: to know if convertible is correctly installed and configured you must run several separate introspection verbs (wheels list, hooks list, telemetry status, doctor) and eyeball each; a broken engine wheel, malformed hooks.json, or missing git/gh only surfaces as a confusing failure mid-drive.
- After: one command — 'convertible doctor' (convertible's 'oilcheck') — runs a battery of read-only checks across CLI integrity, engine-wheel discovery, repo config, layering, handoff prereqs and telemetry, and prints a single rubric-shaped report ({healthy, checks:[{id,passed,severity,message,remediation}]}) with per-check remediation hints, exiting non-zero if anything is unhealthy.

## Why it matters

- fail-fast: catching a broken install or misconfig in one explicit health check is far cheaper than debugging a mid-drive failure, and gives agents a single machine-readable gate to assert their environment before working.

## Requirements

- engine-wheel checks honor the all-engines rule: oilcheck probes EVERY discovered engine uniformly (each entry-point in convertible.engines loads/instantiates), and asserts the two bundled engines (mock, vllm-openai) are present; it never special-cases one engine.
  - honesty: an out-of-tree engine wheel registered under convertible.engines is probed by oilcheck with no change to oilcheck code; adding/removing a bundled engine changes the report symmetrically (the e2e shape test stays the guard).
- oilcheck adds zero runtime dependencies: every check uses only stdlib (importlib.metadata for wheels, shutil.which for git/gh, json for hooks.json, pathlib for config/layers), matching the project's dependencies=[] convention.
  - honesty: the zero-deps guard test (tests/test_zero_deps.py) still passes after oilcheck lands — importing the oilcheck module pulls in no third-party package.
- oilcheck emits the exact established rubric shape {healthy, checks:[{id,passed,severity(error|warning|info),message,remediation}]}, supports --json, writes results to stdout and diagnostics to stderr, and is registered as a global verb with an explain catalog entry + learn entry (agent-first CLI convention).
  - honesty: oilcheck --json round-trips through the same emit_result path as doctor and validates against the identical rubric schema; a test asserts the shape matches doctor's.
- v1 doctor battery, CONFIGURATION-READINESS focused (the issue's emphasis): (a) PROVIDER CONFIG — resolve EngineConfig (base_url/api_key/model via CONVERTIBLE_*/OPENAI_* env + defaults) and report it with api_key redacted; warn when an engine is pointed at a non-default/3rd-party base_url while api_key is still the 'EMPTY' default (credentials likely unset); (b) OTEL — when telemetry is enabled (CONVERTIBLE_OTEL_ENABLED) report whether the [otel] extra imports and whether OTEL_EXPORTER_OTLP_ENDPOINT is set (error if enabled-but-SDK-missing; info otherwise); (c) ENGINE WHEELS — >=1 discovered, mock + vllm-openai loadable (all-engines, uniform); (d) REPO CONFIG — .convertible/ resolves, hooks.json valid JSON if present, command templates parse if present; (e) LAYERING — AGENTS/skills resolution does not raise; (f) HANDOFF PREREQS — git on PATH (error), gh on PATH (warning, PR-only); (g) CLI INTEGRITY — package imports, __version__ resolves, parser builds; (h) IDENTITY — reuse doctor's existing checks.
  - honesty: each check is independently verifiable: a test injects a fault (a non-default base_url with the EMPTY api_key; CONVERTIBLE_OTEL_ENABLED with the [otel] extra absent; malformed hooks.json; absent git) and asserts exactly that check flips to its expected severity with a non-empty remediation.

## Honesty conditions

- the health-check capability (the 'oilcheck' in docs) is invoked via 'convertible doctor' (+ --json), is listed in overview/learn/explain, and runs without error on a clean clone.
- both audiences are served by one invocation: an operator reads the text report; an agent parses the --json payload and branches on 'healthy'.
- the gap is real today: there is no single command that rolls up wheels/hooks/telemetry/config health — confirmed by the current verb list.
- a failing check returns before a drive would start, so the operator/agent sees the problem from oilcheck rather than from a mid-drive traceback.
- oilcheck performs no writes and no network I/O on the default path; a test asserts it mutates no files and opens no socket.
- after the change 'convertible doctor' and 'convertible doctor --json' run the full battery; the existing test_cli_introspection doctor tests still pass, the agent-first rubric (teken cli doctor --strict) still finds the 'doctor' verb, and no 'oilcheck' subparser is registered.
- the report aggregates at least the CLI-integrity, engine-wheel, and repo-config check groups into one {healthy, checks[]} payload from a single 'convertible doctor' run.
- an injected-fault test (bad hooks.json or removed bundled wheel) makes 'convertible doctor' exit non-zero with the offending check failed; the clean-clone test makes it exit 0.
- the provider_budget check is warning-only and never flips 'healthy' to false: with a non-default base_url and no budget env it emits a warning + hint; with the default localhost vLLM rig (or no provider configured) it stays silent/passes; no budget field is added to EngineConfig.

## Success signals

- on a clean convertible clone 'convertible doctor' exits 0 and reports healthy; with an injected fault (e.g. malformed .convertible/hooks.json or a missing bundled engine wheel) it exits non-zero and the failing check names the problem + a remediation hint; the --json payload matches the established doctor rubric shape.

## Scope / boundaries

- oilcheck is read-only diagnosis: it reports problems and prints remediation hints, but does NOT mutate anything (no auto-fix / --fix / --apply) and opens no socket/daemon. Network reachability probes (vLLM endpoint, gh auth) are not run by default.

## Decisions

- exit code on unhealthy = 1, mirroring the existing 'doctor' verb (errors fail; warnings/info do not), rather than the '2 environment error' code, for cross-verb consistency.
- The health check ships as the EXISTING 'doctor' verb, broadened from identity-only to the full battery — there is NO new 'oilcheck' CLI verb. 'oilcheck' is the car-metaphor name used only in docs/README/wording (e.g. 'doctor is convertible's oilcheck'). Identity invariants remain one check-group inside doctor; the existing doctor tests and the agent-first rubric's 'doctor' requirement keep passing.
- doctor's provider-config group includes an ADVISORY 'provider_budget' check (severity=warning, never error): when an engine resolves to a non-default/3rd-party base_url and no spend-guard env (e.g. CONVERTIBLE_BUDGET) is set, doctor warns with a remediation hint to set a cap / confirm provider quota. v1 adds NO budget config field to EngineConfig and enforces NO budget — purely advisory, read-only.

## Open / follow-up

- Whether oilcheck should auto-RESOLVE issues (a --fix/--apply mode) — the issue body says 'system issue resolutions'. Stronger reading = mutate/repair. Convertible is heavily read-only; auto-fix is a side-effecting re-spec (cf. steward 'doctor --apply'). Proposed: v1 = diagnose + remediation hints only; --fix is a separate follow-up spec.
- A real budget/spend-cap config field + enforcement (e.g. CONVERTIBLE_BUDGET or a .convertible budget setting that the loop/driver respects) — beyond v1's advisory warning; needs its own spec leg (new config surface + enforcement semantics).
