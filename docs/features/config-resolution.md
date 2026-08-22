# config-resolution — how colleague resolves its endpoint, model, and config dir

> Repo-level `.colleague/` overrides user-level `~/.colleague/`. The engine
> endpoint (`base_url` / `api_key` / `model`) resolves with an explicit
> precedence: **flag > `COLLEAGUE_*`/`OPENAI_*` env > `.colleague/config.json` >
> built-in default**. View the resolved config (with the api_key redacted) via
> `colleague config show`.

This is the durable way to point colleague at another OpenAI-compatible provider
without re-passing flags or env vars each run.

## The config dir (`colleague/configdir.py`)

Repo-level `.colleague/` takes precedence over user-level `~/.colleague/`. The
legacy `.convertible/` dir is honored as a **read-only** fallback (writes always
go to `.colleague/`).

## The endpoint override (`colleague/config.py`)

`.colleague/config.json` keys `base_url` / `api_key` / `model` feed into
`EngineConfig.resolve(repo_path=…)` as the resolution **default**, so the
precedence is:

```text
explicit flag  >  COLLEAGUE_*/OPENAI_* env  >  .colleague/config.json  >  built-in default
```

Stdlib `json` only; a malformed/absent file is a strict no-op. Wired into the
`work` / `session` / `learn-from` paths (each passes `repo_path`).

## Viewing the resolved config

```bash
colleague config show [--repo PATH] [--json]   # api_key is redacted
colleague config overview
```

`config show` reuses `EngineConfig.resolve(repo_path=…).to_dict()`.
`colleague doctor --repo <path>` (and `--probe`) also **reflect**
`.colleague/config.json` in the provider + reachability check-groups.

## Honest limit

The `--repo` default is the cwd, so a bare `colleague doctor` outside a repo (or
in one without `.colleague/config.json`) is unchanged — env + defaults only.

## The thinking-effort knobs (#416)

The per-seat thinking-effort ladder resolves through the same knob contract
(flag > env > `config.json` > default), beside `temperature`:

- **`COLLEAGUE_REASONING_EFFORT`** / `config.json` `reasoning_effort` — the
  global knob. The value `default` is the **kill switch**: it forces every
  seat, role, and design call-site to unset (the byte-identical pre-increment
  wire) in one env var, no redeploy.
- **`COLLEAGUE_<SEAT>_REASONING_EFFORT`** (SEAT ∈ `CORTEX` | `WORKER` |
  `DEEPTHINK` | `SENSES` | `EVALUATOR` | `DESIGN`) / `config.json`
  `reasoning_effort_seats` — per-seat overrides.
- **`COLLEAGUE_TOO_LONG_MIN`** / `config.json` `too_long_min` (default 20) —
  the wall-clock signal for the retroactive split-next-time record.

`EngineConfig.to_dict()` carries `reasoning_effort` and `reasoning_effort_seats`
on `mock` and `vllm-openai` identically (the all-engines rule holds on the
result shape); with nothing set both are `None`/`{}`. `colleague config show`
prints the resolved table (one line per seat) and names the winning layer when
the kill switch is set. An unknown value in env or `config.json` raises
`CliError` at `resolve()` naming the ladder. The ladder, the v3 default table,
the precedence order, and the honest limits live in
[thinking-effort.md](thinking-effort.md) — this doc points at them, it does not
duplicate the table.

## Per-key merge for all override loaders (#339)

All `config.json` override loaders now read via the per-key merge: user-level
defaults survive when a repo file omits their keys. This applies to lint,
testintegrity, watch, coherence, memory, affected-tests, presence, and icons
(eight loaders total). The #338 chain-overrides fix extended the per-key merge
to all eight.

## Rename back-compat (`convertible` → `colleague`)

The project was renamed from *convertible*. The import package, the
`colleague`/`clg` commands, the `.colleague/` config dir, and the `COLLEAGUE_*`
env vars are the canonical names; the PyPI distribution is `colleague` (no longer
`convertible-cli`). The legacy names are still honored as **deprecated read
fallbacks**:

- `.convertible/` config/artifact dirs are read-only fallbacks (writes always go
  to `.colleague/`; see `configdir.LEGACY_CONFIG_DIR_NAME`,
  `artifact.artifact_read_dirs`, `layers._LEGACY_USER_CONFIG_SUBDIR`).
- `CONVERTIBLE_*` env vars — each read prefers `COLLEAGUE_*` then falls back to
  `CONVERTIBLE_*`.
- `identity_env` emits **both** `COLLEAGUE_IDENTITY` and `CONVERTIBLE_IDENTITY`
  so sibling CLIs that only know the old name keep working.

Historical artifacts (`CHANGELOG.md`, `docs/specs/`, `docs/plans/`, `.devague/`,
dated drive-notes) intentionally keep the old name. The SonarCloud `projectKey`
in `sonar-project.properties` is `agentculture_colleague`; that is an EXTERNAL
identity, so the SonarCloud project itself must be re-keyed/recreated to match or
coverage uploads 404 until it is.

## Related

- [thinking-effort.md](thinking-effort.md) — the per-seat thinking-effort
  ladder and its knobs.
- [model-selection.md](model-selection.md) — the `--model` / `--base-url` surface.
- [layered-config.md](layered-config.md) — AGENTS + skills composition.
- [per-model-configuration.md](per-model-configuration.md) — per-model overlays.

## Key files

- `colleague/configdir.py` — config-dir precedence + legacy fallback.
- `colleague/config.py` — `load_config_file`, `EngineConfig.resolve`.
- `colleague/cli/_commands/config.py` — the `config show` / `overview` verb.
