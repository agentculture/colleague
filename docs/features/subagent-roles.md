# Subagent roles — a typed workforce, with read-only roles that cannot write

Colleague delegates a scoped sub-task to a **typed subagent** — a *role* that
gives the child a tailored system prompt, a **curated subset** of the tool
surface, and a curated skill subset. Roles nest recursively (agents of agents of
agents) under a single global budget, and a **read-only role provably cannot
mutate the tree**.

Roles are **purely additive**: with no `.colleague/agents` config and no role
requested, a work item runs byte-identically to before — one full-surface role.

## Built-in roles

| Role | read-only | Offered tools | Use |
|------|-----------|---------------|-----|
| `explorer` | ✅ | `read_file`, `list_dir`, `check_test_integrity`, `finish` | investigate the repo |
| `planner`  | ✅ | same as explorer | reason about an approach |
| `reviewer` | ✅ | same as explorer | critique code |
| `validator`| ✅ | explorer + `run_tests` | run the suite, report pass/fail |
| `writer`   | ❌ | the full surface (today's default) | implement a change |

A **read-only** role withholds `write_file`, `edit_file`, **and** `run_command`
— the three write/exec vectors — so it cannot mutate the tree by any offered
tool. The validator additionally gets a dedicated read-only **`run_tests`** loop
tool (a fixed `python -m pytest` runner, never arbitrary shell), so it can
validate without any write/exec surface.

The read-only built-ins are intentionally **pure-read**: `culture`/`devague` are
excluded because they shell out to write-capable CLIs, which would contradict the
"cannot mutate the tree" guarantee.

## Requesting a role

Selecting a role is **backend-judged and optional** — never automatic routing.
Omitting it is byte-identical to today's full-surface delegation.

- **Loop tools** — the `subagent` and `subagents` tools take an optional `role`
  parameter; a batch can set one `role` for all children, or per-item `"role"`.
- **CLI** — `colleague work --role <name>`.
- **ask-colleague** — `ask-colleague explore|review|write --role <name>`.
- **Plan workforce** — `build_workforce_items(..., role=...)` assigns a role per
  fanned-out child (reusing `make_batch_spawn`, no new fan-out/merge code).

Inspect the resolved roles with **`colleague roles list`** (`--json`,
`roles overview`, `explain roles`). (This is a distinct noun from `agents`, which
inspects the AGENTS *instruction-file* cascade.)

## How it works

The role is a NAME on `EngineConfig.role`. The engine (`mock` and `vllm-openai`
identically — the all-engines rule) resolves it once in `work()`:

- the **offered tool schema** = `curate_schemas(role)` (a subset of `SCHEMAS`),
- a **role-aware `ToolExecutor`** (`allowlist=role`) that *refuses* any withheld
  tool even if the model hallucinates the call,
- the **system prompt** = `compose_role_prompt(role, …)` (base + AGENTS layers +
  the role's `prompt_fragment` + the role's curated skill subset), composed
  through the one existing layered-config path (no second assembly path).

The applied role is recorded on `TaskResult.role` / `SubResult.role`
(omit-when-None, so a role-less run serializes byte-identically).

### Recursion + the global agent budget

Recursion goes deeper than before — `MAX_SUBAGENT_DEPTH` is **4** (was 2) — and a
single **`MAX_SUBAGENT_TOTAL` = 24** global budget bounds the TOTAL agents spawned
under one top-level work item, *regardless of nesting shape*. The budget is a
thread-safe counter created once and threaded down every level; each child is
charged once **before any work** (no engine load, no worktree), so every nesting
shape terminates. Nested batches are now permitted (a child gets its own depth+1
batch-spawn sharing the budget). Caps are env-tunable
(`COLLEAGUE_SUBAGENT_DEPTH` / `COLLEAGUE_SUBAGENT_TOTAL`).

## Operator config

Per-role prompt overlays live at `.colleague/agents/<name>.md`, with a per-model
overlay at `.colleague/<model>/agents/<name>.md` (exact path via
`sanitize_model`, no sibling globbing — the established skills/hooks convention).
An overlay overrides a built-in role's **prompt**; absent → the built-in default.

## Honest limits

- **`run_command` (writer) is arbitrary shell by design** (the trusted-operator
  D2 model — bypassable by `sh -c`). The confinement guarantee covers the
  *file-write* tools (`write_file`/`edit_file`, confined to the repo root by
  `_safe_path`) and the absence of a cross-repo write *mode* — not an OS sandbox.
- **No cross-repo "free-run" write mode.** Writes are confined to the repo + the
  agent's own throwaway worktree. Writing BEYOND a single repo is a separate,
  gated mode that requires an issue and explicit thinking — **parked, out of
  scope** here. There is no code path that enables an out-of-repo write.
- **v1 operator config overrides the prompt only**, not a role's tool-allowlist
  (custom-allow-list roles need frontmatter parsing — a follow-up). Role files
  are **not** approval-gated by checksum yet (unlike hooks/commands).
- **Speed:** depth-4 nesting buys real wall-clock speedup only on a
  concurrent-serving model; on a serializing server, gain is bounded by
  overlapped I/O, not model compute.

## Spec + plan

- Spec: [`docs/specs/2026-06-17-colleague-orchestrates-a-workforce-of-typed-subage.md`](../specs/2026-06-17-colleague-orchestrates-a-workforce-of-typed-subage.md)
- Plan: [`docs/plans/2026-06-17-colleague-orchestrates-a-workforce-of-typed-subage.md`](../plans/2026-06-17-colleague-orchestrates-a-workforce-of-typed-subage.md)
