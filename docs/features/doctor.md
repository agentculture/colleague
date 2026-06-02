# `doctor` — configuration-readiness (oilcheck)

> Colleague's oilcheck: a read-only health check across identity, provider,
> engines, otel-readiness, and environment. Exits 1 when unhealthy.

`colleague doctor` is colleague's **oilcheck** — a configuration-readiness
health check that answers "is this install actually ready to drive?" before you
hand it work. It is **read-only** and **diagnose-only** (no `--fix`), with **zero
new runtime dependencies**.

The diagnostic logic lives in a chassis-level package, `colleague/oilcheck/`
(the same way telemetry lives in `colleague/telemetry/`). The `doctor` CLI verb
is a thin presentation layer that renders the report and maps it to an exit code.

## The check-group contract

oilcheck aggregates many small, independent **check-groups** into one report.
Each check is a dict with exactly five keys: `id`, `passed`, `severity`
(`error` / `warning` / `info`), `message`, and `remediation`. The report is the
rubric shape `{healthy, checks: [...]}`.

**Only a failed `error` check flips the report unhealthy.** Warnings and info are
advisory and never change health, even when they fail. `doctor` exits `1` when
unhealthy, else `0`. Every check-group is contractually read-only and must never
raise — a group that hits an error turns it into a failed check, so one broken
group can't take down the whole report.

## The five check-groups (in report order)

### 1. identity — `colleague/oilcheck/identity.py`

The agent-identity invariants (mirrors `steward doctor`). When run from a source
checkout with a `culture.yaml`:

- `prompt_file_present` / `backend_consistency` (**error**) — the declared
  backend has its prompt file on disk (`claude` → `CLAUDE.md`, `acp` →
  `AGENTS.md`, `gemini` → `GEMINI.md`).
- `skills_present` (**warning**) — the vendored `.claude/skills/` kit is present.

From a wheel install (no `culture.yaml` beside the package) it reports a single
`source_checkout` info check and nothing else.

### 2. provider — `colleague/oilcheck/provider.py`

Reports the resolved engine provider config (read-only, no network):

- `provider_config` (**info**, always) — effective `base_url` and `model`; the
  `api_key` is **redacted**.
- `provider_credentials` (**warning**, non-default `base_url` only) — fires when
  pointing at a third-party host while `api_key` is still the placeholder
  `EMPTY`.
- `provider_budget` (**warning**, non-default `base_url` only) — advisory: fires
  when no `COLLEAGUE_BUDGET` spend cap is set.

Silent on the default localhost rig (a local vLLM server needs no key/budget).
No `error` is ever emitted here.

### 3. engines — `colleague/oilcheck/engines.py`

Engine-wheel discovery and loadability, probed uniformly (all-engines rule):

- `engines_discovered` (**error**) — at least one engine is registered.
- `bundled_engines_present` (**error**) — both `mock` and `vllm-openai` are in
  the catalog.
- one `engine_load_<name>` (**error**) per discovered engine — instantiating it
  doesn't raise.

### 4. otel — `colleague/oilcheck/otel.py`

GPS readiness, **without** enabling telemetry or importing the SDK eagerly
(`importlib.util.find_spec` only — the zero-deps guard must keep passing):

- `otel_enabled` (**info**) — whether telemetry is enabled (notes the
  `OTEL_SDK_DISABLED` kill-switch if set).
- `otel_sdk` (**info** | **error**) — whether the `[otel]` extra is importable;
  **error only** when telemetry is enabled *and* the SDK is absent.
- `otel_endpoint` (**info**) — whether an OTLP endpoint is configured (userinfo
  redacted).

### 5. environment — `colleague/oilcheck/environment.py`

The broader operating environment (repo = cwd):

- `config_dir` (**info**/warning) — whether a `.colleague/` config dir resolves.
- `hooks_valid` (**info**/error) — `.colleague/hooks.json`, if present, parses.
- `commands_parse` (**info**/error) — all command templates parse.
- `layering` (**info**/warning) — AGENTS/skills resolution doesn't raise.
- `git_present` (**error**) — `git` is on `PATH` (required for handoff).
- `gh_present` (**warning**) — `gh` is on `PATH` (PR-creation handoff; `--no-pr`
  works without it).
- `cli_integrity` (**error**) — the package imports, `__version__` resolves, and
  the argument parser builds.

## Usage

```bash
colleague doctor              # human-readable rubric; exit 1 if unhealthy
colleague doctor --json       # structured {healthy, checks[]}
colleague explain doctor      # the catalog entry
```

## Extending it

Add a check-group by writing a module that exposes `checks() -> list[dict]`
(read-only, never raising, building checks with `make_check`), then append its
`checks` callable to `CHECK_GROUPS` in `colleague/oilcheck/__init__.py`. List
order is report order. Read the module docstring there — it is the group spec.

## Key files

- `colleague/oilcheck/__init__.py` — `make_check`, `diagnose`, `CHECK_GROUPS`.
- `colleague/oilcheck/{identity,provider,engines,otel,environment}.py` — the groups.
- `colleague/cli/_commands/doctor.py` — the presentation layer.

## See also

- [engines.md](engines.md), [telemetry.md](telemetry.md), [handoff.md](handoff.md)
  — the subsystems doctor probes.
- [agent-cli.md](agent-cli.md) — the other read-only introspection verbs.
