# Layered per-model config

> A model-specific system prompt composed from AGENTS instructions and skills,
> with strict per-model isolation.

Colleague composes a model-specific **system prompt** for every drive from two
layered families, resolved *relative to the model currently driving*
(`colleague/layers.py`). It is injected once on the `Engine` base class
(`system_prompt()`), so every engine inherits it — the all-engines rule, exactly
like hooks and telemetry.

**Per-model isolation is structural.** When driving model X, the loader builds
X's exact filenames/dirnames and reads only those plus the shared base. It never
globs `AGENTS.colleague.*.md` or iterates sibling `.colleague/*/skills/`
directories — so model X can never load model Y's files. Isolation is built from
exact-path construction, not filtering.

## AGENTS instructions

A cascade read from the **repo root** (the cross-tool standard location —
sibling agent tools read `AGENTS.md` there too), general → specific, with a
`~/.colleague/` user-level fallback:

```text
AGENTS.md                       # shared base
AGENTS.colleague.md           # colleague overlay
AGENTS.colleague.<model>.md   # model overlay
```

The layers are concatenated general → specific, so model-specific guidance lands
last. Note the asymmetry: the repo-level layer lives at the repo root, but the
user-level fallback lives under `~/.colleague/`.

## Skills

Markdown capability docs under `.colleague/`, folded into the prompt as a
compact **name + one-line-summary catalog** (never the full bodies — it stays
token-cheap):

```text
.colleague/skills/*.md            # base
.colleague/<model>/skills/*.md    # model overlay (shadows base by stem)
```

Repo-level `.colleague/` also shadows user-level `~/.colleague/` underneath —
two orthogonal precedence axes, both structural. A skill is **instructional text
only**; there is no skill *execution* in v0 (an execution sandbox is out of
scope) — invokable skills are a tracked follow-up.

## Model token sanitization

`<model>` is sanitized to a filename-safe token: every run of characters outside
`[A-Za-z0-9._-]` collapses to a single `-`, leading/trailing `-`/`.` are
stripped, and an empty id yields `default`. Dots are preserved (`Qwen3.6`,
`NVFP4` carry meaning). For example, `Qwen/Qwen3-32B` → `Qwen-Qwen3-32B`.

## Symlink confinement

Layer files are confined just like tool reads: a candidate whose resolved target
escapes the root it was found under (e.g. a symlink pointing outside the repo or
config dir) is skipped — so a repo can't smuggle `/etc/passwd` or `~/.ssh/…` into
a system prompt that is then sent verbatim to a remote engine.

## Behavior when no layers exist

When no AGENTS layers and no skills resolve for the model, the composer returns
`None` and the loop keeps its own default system prompt — behavior is
byte-identical to a layer-free run.

## Usage

```bash
colleague agents list --model Qwen/Qwen3-32B --repo .
colleague agents overview
colleague skills list --model Qwen/Qwen3-32B --repo .
colleague skills overview
```

## MCP layering is not built

Colleague does **not** read `mcp.json` or connect to any MCP server today, and
there is **no `mcp` verb**. A live MCP client (transport, tool discovery,
dynamic tool registration) needs its own spec — don't rely on a non-existent
surface.

## Key files

- `colleague/layers.py` — `resolve_agents`, `resolve_skills`, `system_prompt_for`.
- `colleague/engine.py` — `Engine.system_prompt()` injects it for every engine.
- `colleague/configdir.py` — repo-over-user `.colleague/` resolution.

## See also

- [per-model-configuration.md](per-model-configuration.md) — per-model hooks
  overlay: the same per-model isolation principle applied to the hooks layer
  (`.colleague/<model>/hooks.json`).
- [engines.md](engines.md) — every engine inherits the layered prompt.
- [command-templates.md](command-templates.md) — also resolved via `.colleague/`.
