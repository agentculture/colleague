# Build Plan — Convertible gains an 'oilcheck' command — one read-only health check that verifies the CLI is functional, the engine wheels are discoverable, and the repo config is sound, with rubric-shaped pass/fail and remediation hints, so you catch a broken install or misconfig before a drive fails mysteriously.

slug: `convertible-gains-an-oilcheck-command-one-read-onl` · status: `exported` · from frame: `convertible-gains-an-oilcheck-command-one-read-onl`

> Convertible gains an 'oilcheck' command — one read-only health check that verifies the CLI is functional, the engine wheels are discoverable, and the repo config is sound, with rubric-shaped pass/fail and remediation hints, so you catch a broken install or misconfig before a drive fails mysteriously.

## Tasks

### t1 — oilcheck core: build the check-group registry + diagnose() aggregator in a new convertible/oilcheck/ package, rewire cli/_commands/doctor.py as the thin verb, port existing identity checks, and scaffold the other group modules as stubs

- covers: c11, h3, c15, h14, c16, h15, c6, h10, c2, h6, c5, h9, c1, h13
- acceptance:
  - convertible/oilcheck/__init__.py exposes a CHECK_GROUPS registry and diagnose()-> {healthy, checks:[{id,passed,severity,message,remediation}]}; healthy is False iff any check has severity 'error' and passed=False (warning/info never flip it)
  - cli/_commands/doctor.py calls convertible.oilcheck.diagnose(), preserves text + --json rendering via emit_result, and exits 1 on unhealthy / 0 otherwise; existing tests/test_cli_introspection.py doctor tests still pass and no 'oilcheck' subparser is registered
  - identity checks (today's _diagnose) are ported verbatim into convertible/oilcheck/identity.py as the first registered group; convertible/oilcheck/{provider,engines,otel,environment}.py exist as stubs returning [] and are pre-registered in the registry (so group tasks fill one disjoint file each)
  - tests/test_oilcheck_core.py asserts the rubric shape matches doctor's, exit-code semantics, that a stubbed error-severity failure flips healthy+exit, and that diagnose() writes no files and opens no socket (read-only)

### t2 — provider-config check group: resolve EngineConfig and report base_url/model (api_key redacted), warn on unset 3rd-party credentials, and add the advisory provider_budget warning

- depends on: t1
- covers: c17, h16
- acceptance:
  - convertible/oilcheck/provider.py resolves EngineConfig.resolve() and emits an info check reporting base_url+model with api_key REDACTED (never printed)
  - a 'provider_credentials' warning fires when base_url is non-default (3rd-party) while api_key is still the 'EMPTY' default; silent on the default localhost rig
  - a 'provider_budget' warning fires when base_url is non-default and no CONVERTIBLE_BUDGET env is set, with a remediation hint; both checks are severity=warning and never flip healthy=False; no budget field is added to EngineConfig
  - tests/test_oilcheck_provider.py injects each condition and asserts exactly the expected check + severity + non-empty remediation

### t3 — engine-wheels check group: probe every discovered engine uniformly and assert the two bundled engines are present/loadable (all-engines rule)

- depends on: t1
- covers: c9, h1, c17, h16
- acceptance:
  - convertible/oilcheck/engines.py uses registry.catalog()/load() to probe EVERY entry-point in convertible.engines uniformly (loads/instantiates each), never special-casing one engine
  - an error fires if <1 engine is discovered or if either bundled engine (mock, vllm-openai) is missing or fails to load; the report changes symmetrically when a bundled engine is added/removed
  - tests/test_oilcheck_engines.py monkeypatches the entry-point seam to simulate a missing/extra/broken wheel and asserts the engine check responds with no oilcheck code change

### t4 — otel-readiness check group: report telemetry config state and flag enabled-but-SDK-missing, without breaking the zero-deps guard

- depends on: t1
- covers: c10, h2, c17, h16
- acceptance:
  - convertible/oilcheck/otel.py reports whether CONVERTIBLE_OTEL_ENABLED is set, whether the [otel] extra imports (lazy import, confined to a try/except), and whether OTEL_EXPORTER_OTLP_ENDPOINT is set
  - severity is error when telemetry is enabled but the SDK is not importable; info otherwise; the module imports no third-party package at import time
  - tests/test_zero_deps.py still passes (importing convertible.oilcheck pulls in no third-party package); tests/test_oilcheck_otel.py covers the enabled-but-missing-SDK and default-off paths

### t5 — environment check group: repo config (.convertible + hooks.json + command templates), AGENTS/skills layering, handoff prereqs (git/gh), and CLI integrity

- depends on: t1
- covers: c3, h7, c17, h16
- acceptance:
  - convertible/oilcheck/environment.py checks: .convertible/ resolves (configdir), hooks.json is valid JSON if present (error on parse failure), command templates parse if present, AGENTS/skills layering (layers.py) resolves without raising (warning on failure)
  - handoff prereqs: git on PATH via shutil.which (error if absent), gh on PATH (warning, PR-only); CLI integrity: package imports + __version__ resolves + the argparse parser builds
  - tests/test_oilcheck_environment.py injects a malformed .convertible/hooks.json and an absent git/gh (PATH monkeypatch) and asserts exactly the expected check + severity + remediation

### t6 — docs + introspection surfaces: update explain catalog, learn, overview verb description, README and CLAUDE.md to describe the broadened doctor and the 'oilcheck' wording

- depends on: t1
- covers: c1, h13, c3, h7
- acceptance:
  - convertible/explain/catalog.py doctor entry, learn.py doctor summary, and overview.py verb line describe the configuration-readiness battery; 'convertible doctor' + 'convertible doctor --json' appear in overview/learn/explain
  - README.md doctor row and CLAUDE.md describe doctor as convertible's 'oilcheck' health check (wording only — no new verb); no doc mentions a non-existent 'oilcheck' command or a '--fix'/'--no-hooks' flag
  - teken cli doctor . --strict still passes (the rubric still finds the 'doctor' verb)

### t7 — bump version + CHANGELOG entry for the doctor configuration-readiness battery (#28)

- depends on: t2, t3, t4, t5, t6
- acceptance:
  - pyproject.toml + convertible/__init__.py version bumped (minor) and a Keep-a-Changelog entry prepended to CHANGELOG.md describing the broadened doctor; the version-check CI job passes

## Risks

- [out_of_scope] A --fix/--apply auto-remediation mode is out of scope for this plan (diagnose-only); parked as a follow-up spec.
- [out_of_scope] A real budget/spend-cap config field + enforcement (CONVERTIBLE_BUDGET respected by the loop/driver) is out of scope; v1 ships only the advisory provider_budget warning.
- [unknown_nonblocking] Naming: code package is convertible/oilcheck/ while the CLI verb stays 'doctor' (oilcheck = metaphor in code/docs, not a verb). A reviewer may read the package name as implying a verb; mitigated by t1 asserting no 'oilcheck' subparser exists. (task t1)
