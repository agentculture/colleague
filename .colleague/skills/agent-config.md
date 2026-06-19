Show a Culture agent's full configuration in one read-only view: its system-prompt file (CLAUDE.md / AGENTS.colleague.md), the parallel culture.yaml, and the agent's local .colleague/skills index. Use when an operator says "show agent <name>", "what does <agent> look like", or before teaching/onboarding an agent and you need to see its current kit + config. Inventory only — it reports, it does not judge alignment or drift.

<!-- learned-from: claude; source: .claude/skills/agent-config/SKILL.md; scripts: .claude/skills/agent-config/scripts; adapt: claude->colleague -->

# agent-config

# agent-config — surface a Culture agent's config in one view

This skill answers "what kit + config does this agent have?" for a single agent,
showing the three artifacts that together define it:

1. **System-prompt file** (`CLAUDE.md` / `AGENTS.colleague.md`) — the
   prompt-side guidance for the agent's backend. Detect which file is present
   by checking the repo root.
2. **`culture.yaml`** — the runtime-side config (`agents:` list with `suffix`,
   `backend`, `model`, `system_prompt`, `channels`, `tags`, `acp_command`,
   `extras`). Lives at the project root.
3. **`.colleague/skills/*.md`** — the per-project skills the agent can
   invoke, one line each (name + truncated description).

This is an **inventory** surface: it reports the config, it does **not**
interpret drift or judge alignment.

## When to use

- Before onboarding or teaching an agent — see its current kit + config.
- When an operator asks "show me agent `<name>`" or "what does `<agent>` run".
- Read it, don't guess — before answering a question about what an agent does.

## How to run

Use colleague's built-in tools to gather the three sections. There is no
external script; follow these steps:

1. **System-prompt file** — read the prompt file at the repo root:
   ```
   read_file CLAUDE.md
   # or
   read_file AGENTS.colleague.md
   ```
   Show whichever exists (or both if present).

2. **`culture.yaml`** — read the runtime config:
   ```
   read_file culture.yaml
   ```
   If missing, note `(missing)`.

3. **Skills index** — list the available skills:
   ```
   list_dir .colleague/skills
   ```
   For each `.md` file, read the first line (the one-line summary) to produce
   a one-line summary per skill (name + description, truncated to 120 chars):
   ```
   read_file .colleague/skills/<skill>.md
   ```

Output is three sections: the detected system-prompt file, `culture.yaml` (or
`(missing)`), and a one-line summary per local skill.

## What to look at in `culture.yaml`

| Field | Why it matters |
|-------|----------------|
| `suffix` | Identifies the agent on the mesh. |
| `backend` | One of `mock` / `vllm-openai`. The all-backends rule means a feature in one must hold identically for all. |
| `model` | Drift here changes behavior silently. |
| `system_prompt` | Should not contradict the prompt file. |
| `channels` | Where the agent listens. |
| `tags`, `extras`, `acp_command` | Backend-specific. |

## Notes

- **Read-only.** Never edit agent files. Report; do not flag or fix drift —
  that judgment is outside this skill's scope.
- **Backend-aware.** Prompt-file detection checks for `CLAUDE.md` and
  `AGENTS.colleague.md` at the repo root.
- **Vendored from steward** (`agent-config`). Reframed for colleague's
  inventory role; re-sync from steward's canonical copy when it changes.
