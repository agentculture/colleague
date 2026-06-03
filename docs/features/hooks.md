# Lifecycle hooks

> Operator-authored shell commands that fire at lifecycle events; a `pre_tool`
> hook can allow, deny, or rewrite a tool call before it runs.

Hooks are operator-authored shell commands registered in
`.colleague/hooks.json` (repo-level, falling back to user-level at
`~/.colleague/hooks.json`; repo wins). They fire at four lifecycle events
during a drive. Crucially, hook firing lives in the **runtime**
(`colleague/loop.py`), not in any backend — so a hook config that fires on
`mock` fires identically on `vllm-openai` (the all-engines rule). New backend
plugins inherit the full lifecycle layer for free.

## Config format

```json
{
  "hooks": {
    "pre_tool":  [{ "matcher": "run_command", "command": "my-policy-gate.sh" }],
    "post_tool": [{ "matcher": "write_file",  "command": "black $file 2>/dev/null; true" }],
    "task_start":[{ "command": "echo task starting" }],
    "finish":    [{ "command": "echo done" }]
  }
}
```

| Field | Meaning |
|-------|---------|
| `matcher` | Regex (`re.fullmatch`) tested against the tool name. Absent/empty matches every tool. Ignored for `task_start` / `finish`. |
| `command` | Shell command run (via `subprocess`, `shell=True`) in the target repo directory. |

## Lifecycle events

| Event | When it fires | Effect |
|-------|--------------|--------|
| `task_start` | Once, before the loop starts | Observe only |
| `pre_tool` | Before each tool call | **Can allow, deny, or rewrite** |
| `post_tool` | After each tool call (incl. after a tool error) | Observe only (side-effects OK) |
| `finish` | Once, on any loop exit | Observe only |

Only `pre_tool` is control-bearing — the first decisive decision wins.
`task_start` / `post_tool` / `finish` are observe-only this increment: a deny
from them is recorded but does not halt the loop.

## I/O contract

Each hook receives a JSON payload on **stdin**:

```json
{
  "event": "pre_tool",
  "tool": "run_command",
  "arguments": { "command": "pytest" },
  "task_id": "<uuid>",
  "repo_path": "/path/to/repo"
}
```

It signals its decision via **exit code** and optional **structured stdout**:

| Exit code | Stdout | Decision |
|-----------|--------|----------|
| non-zero | any | **deny** — stderr (fallback: stdout) is fed back to the model as the tool result |
| 0 | empty or non-JSON | **allow** — tool runs as-is |
| 0 | `{"decision":"allow", ...}` | **allow** |
| 0 | `{"decision":"deny", "reason":"..."}` | **deny** — reason fed back to the model |
| 0 | `{"decision":"rewrite","arguments":{...}}` | **rewrite** — tool runs with the replacement arguments |

Any response may carry an `"additionalContext"` string. Every firing (event,
matched command, decision, exit code, reason) is recorded in
`TaskResult.hook_firings` and appears in the [artifact](artifact.md).

## Fail-closed, never fatal

A hook must never abort the drive. A subprocess timeout, a launch failure, an
invalid matcher regex, or any unexpected error maps to a structured fail-closed
**deny** firing rather than crashing the loop.

## Usage

```bash
colleague hooks list --repo .
colleague hooks list --repo . --json
colleague hooks overview
```

## ⚠ Security: repo-shipped hooks run by default

When you drive a repo that contains `.colleague/hooks.json`, **those hooks
execute automatically** with your OS privileges — no confirmation prompt, no
sandbox. This is intentional under colleague's **trusted-operator-env model
(D2)**, the same tradeoff Claude Code and Codex make for their hook configs.

There is **no `--no-hooks` flag and no per-repo trust gate today** — that
hardening is a tracked follow-up, not yet built. Until it ships: only drive
repos you own or have audited, review `.colleague/hooks.json` before driving an
unfamiliar repo, and prefer user-level (`~/.colleague/hooks.json`) hooks if you
want hooks without trusting any repo's config.

## Key files

- `colleague/hooks.py` — config loading + the `run_hook` I/O contract.
- `colleague/loop.py` — `_fire_hooks`; the runtime owns lifecycle firing.
- `colleague/cli/_commands/hooks.py` — the `hooks list`/`overview` verb.

## See also

- [per-model-configuration.md](per-model-configuration.md) — per-model hooks
  overlay: add model-specific entries that fire ahead of the base hooks for one
  targeted model only.
- [command-templates.md](command-templates.md) — the other half of the
  extensibility layer.
- [drive-and-loop.md](drive-and-loop.md) — the tool-loop that fires hooks.
