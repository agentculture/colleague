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

## Related

- [model-selection.md](model-selection.md) — the `--model` / `--base-url` surface.
- [layered-config.md](layered-config.md) — AGENTS + skills composition.
- [per-model-configuration.md](per-model-configuration.md) — per-model overlays.

## Key files

- `colleague/configdir.py` — config-dir precedence + legacy fallback.
- `colleague/config.py` — `load_config_file`, `EngineConfig.resolve`.
- `colleague/cli/_commands/config.py` — the `config show` / `overview` verb.
