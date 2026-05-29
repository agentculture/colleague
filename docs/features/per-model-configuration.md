# Per-model configuration

> The harness adjusts the seat and mirrors for whoever is driving — same car,
> tuned to the specific model behind the wheel.

Convertible's car metaphor extends to how operator-declared fixes apply to
specific models. The **chassis** (loop, hooks, config resolution) is shared
across every engine. But different models have different biases — quirks in how
they write files, what they assume about paths, or how they structure output.
Per-model configuration lets operators declare those fixes precisely, applying
them only to the targeted model and leaving all other drives untouched.

Two per-model configuration surfaces ship in v0:

- **Per-model AGENTS instructions and skills** — a system-prompt overlay
  (`AGENTS.convertible.<model>.md` + `.convertible/<model>/skills/*.md`) that
  tunes the model's guiding instructions. See [layered-config.md](layered-config.md).
- **Per-model hooks overlay** — a separate `hooks.json` whose entries fire
  **ahead of** the base hooks for that model only. This page documents the hooks
  overlay.

## The per-model hooks overlay

### Config path

Place a `hooks.json` at:

```text
.convertible/<model>/hooks.json
```

where `<model>` is the sanitized model token (see [Model token
sanitization](#model-token-sanitization) below). For example, for a model id
`mmangkad/Qwen3.6-27B-NVFP4`:

```text
.convertible/mmangkad-Qwen3.6-27B-NVFP4/hooks.json
```

The file format is identical to the base `.convertible/hooks.json` — same
`{"hooks": {"pre_tool": [...], ...}}` schema. See
[hooks.md](hooks.md) for the full format reference.

### Per-model-first precedence

When the loop loads hooks for a drive, per-model entries are **prepended ahead
of** the base entries for each lifecycle event. The loop's existing
**first-deny/rewrite-wins** rule then gives the per-model fix priority: if a
per-model `pre_tool` entry denies or rewrites a tool call, the base entries for
the same tool never run.

```text
Composed order for each event:
  [per-model entry 1, per-model entry 2, …, base entry 1, base entry 2, …]
```

A base hook that runs for every model still fires — the per-model overlay only
adds entries at the front, never removes the base ones.

### Exact-path isolation

The overlay path is built by **exact construction** through
`convertible.layers.sanitize_model`. The loader never globs
`.convertible/*/hooks.json` or iterates sibling directories. Model X therefore
can never load model Y's overlay: isolation is structural, not filtered.

### Strict no-op

With no `--model` passed (or for a model whose overlay file is absent), the
returned hook config is **byte-identical** to a base-only load. Existing drives
against models with no overlay see no behavior change.

### No new dependency, socket, or daemon

The overlay is a file read — the same `subprocess`-based hook runner used for
the base config. No new runtime dep, no socket, no daemon; it reuses the exact
hook machinery already in `convertible/hooks.py` and `convertible/loop.py`.

### Model token sanitization

The `<model>` directory name is produced by `convertible.layers.sanitize_model`:
every run of characters outside `[A-Za-z0-9._-]` collapses to a single `-`,
leading/trailing `-`/`.` are stripped, and an empty id yields `default`. Dots
are preserved (`Qwen3.6`, `NVFP4` carry meaning).

| Model id | Sanitized token |
|----------|----------------|
| `Qwen/Qwen3-32B` | `Qwen-Qwen3-32B` |
| `mmangkad/Qwen3.6-27B-NVFP4` | `mmangkad-Qwen3.6-27B-NVFP4` |
| `meta-llama/Llama-3-8B` | `meta-llama-Llama-3-8B` |

## Operator-declared, not auto-detected

Convertible does **not** auto-detect model biases. The operator names the
failure mode, writes the hook fix, and places it under the model's directory.
This is intentional: auto-detection would require heuristic guessing across
every run; an explicit hook is auditable, repeatable, and applies only when
the operator has confirmed the bias is real.

## Worked example: the F9 footer bias

### The bias

During a `drive-evaluation` experiment (commit log `0.11.1`), a model was asked
to author a static-site documentation page. The model produced an HTML footer
anchor pointing **outside** the served `site/` docroot:

```html
<a href="../README.md">Back to README</a>
```

That relative `../README.md` path escapes the docroot on every `site/`-rooted
HTTP server and produces a 404. The model repeated this pattern reliably — it
"knew" the repo's top-level `README.md` existed and used a relative parent-dir
reference rather than a docroot-relative path. The fix is docroot-relative:
`/README.md` (or an in-`site/` copy).

### Why a per-model hook

The base hooks do not block this pattern — it is not a universal policy, and
other models do not exhibit it. A per-model `pre_tool` hook on `write_file`
applies the fix **only** for the targeted model, leaving the base config
untouched for every other drive.

### Hook config

Place the following at `.convertible/mmangkad-Qwen3.6-27B-NVFP4/hooks.json`:

```json
{
  "hooks": {
    "pre_tool": [
      {
        "matcher": "write_file",
        "command": "python3 .convertible/hooks/fix-footer-escape.py"
      }
    ]
  }
}
```

### Hook script

`.convertible/hooks/fix-footer-escape.py`:

```python
#!/usr/bin/env python3
"""pre_tool hook: deny write_file when the content escapes the site/ docroot
via a '../README.md' footer anchor, and suggest the docroot-relative fix.

Reads the JSON payload from stdin (keys: event, tool, arguments, task_id,
repo_path). Exits 0 with a rewrite decision when the pattern is found;
otherwise allows (exit 0, empty stdout).
"""
import json
import re
import sys

payload = json.load(sys.stdin)
content = payload.get("arguments", {}).get("content", "")

# Pattern: href="../README.md" (with optional whitespace)
ESCAPE_PAT = re.compile(r'href=["\']\.\.\/README\.md["\']', re.IGNORECASE)

if ESCAPE_PAT.search(content):
    fixed_content = ESCAPE_PAT.sub('href="/README.md"', content)
    print(json.dumps({
        "decision": "rewrite",
        "arguments": {
            **payload["arguments"],
            "content": fixed_content,
        },
        "additionalContext": (
            "Footer anchor '../README.md' escapes the site/ docroot. "
            "Rewrote to '/README.md' (docroot-relative)."
        ),
    }))
else:
    # No match — allow as-is (exit 0, empty stdout).
    pass
```

### Before and after

**Before** (without the hook): the model writes a file containing:

```html
<footer><a href="../README.md">Back to README</a></footer>
```

This path resolves outside the `site/` docroot and returns a 404 over HTTP.

**After** (with the hook): the hook intercepts the `write_file` call, rewrites
the `content` argument in place, and the file is written as:

```html
<footer><a href="/README.md">Back to README</a></footer>
```

The drive completes normally. The rewrite is recorded in `TaskResult.hook_firings`
and appears in the result artifact. The model receives the `additionalContext`
string as context, so it can incorporate the correction on subsequent writes
without re-triggering the hook.

### Inspecting the composed hook set

```bash
convertible hooks list --repo . --model mmangkad/Qwen3.6-27B-NVFP4
```

Output (human-readable):

```text
[per-model]  pre_tool   write_file   python3 .convertible/hooks/fix-footer-escape.py
[base]       pre_tool   run_command  my-policy-gate.sh
```

Per-model entries appear first, tagged `per-model`; base entries follow, tagged
`base`. With `--json`:

```bash
convertible hooks list --repo . --model mmangkad/Qwen3.6-27B-NVFP4 --json
```

```json
{
  "hooks": [
    {
      "event": "pre_tool",
      "matcher": "write_file",
      "command": "python3 .convertible/hooks/fix-footer-escape.py",
      "scope": "per-model"
    },
    {
      "event": "pre_tool",
      "matcher": "run_command",
      "command": "my-policy-gate.sh",
      "scope": "base"
    }
  ]
}
```

## The all-engines rule

Per-model hooks load in `convertible/loop.py` via `load_hooks(repo_path,
model=config.model)`. Both bundled engines (`mock` and `vllm-openai`) pass
`model=config.model` — so a per-model overlay that fires on `mock` fires
identically on `vllm-openai`. New engine wheels inherit this for free because
hook firing is chassis-owned, not engine-owned.

## Key files

- `convertible/hooks.py` — `load_hooks(repo_path, *, model=None)`: per-model
  overlay load + composition.
- `convertible/layers.py` — `sanitize_model`: model-id → filename-safe token.
- `convertible/loop.py` — passes `model=config.model` to `load_hooks`; the
  chassis owns all hook firing.
- `convertible/cli/_commands/hooks.py` — `hooks list --model <m>` shows the
  composed set with `scope` tags.

## See also

- [hooks.md](hooks.md) — full hook format, I/O contract, and security note.
- [layered-config.md](layered-config.md) — per-model AGENTS instructions and
  skills (the system-prompt sibling to this hooks overlay).
