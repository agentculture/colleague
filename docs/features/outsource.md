# `outsource` — use convertible as a different mind

> Hand a scoped repo task to convertible — a *different* engine/model than the
> calling agent. The point isn't a stronger model; it's a **different mind**, and
> diversity helps.

`outsource` is a **first-party Claude Code skill** (`.claude/skills/outsource/`)
that drives the `convertible` CLI so another agent can delegate a scoped task to
a different engine (default: a local vLLM `mmangkad/Qwen3.6-27B-NVFP4` on
`:8001`). Convertible's model is **not assumed to be stronger** than the caller —
a second, independent perspective catches what the author's mind glides past,
which is why **review** is the headline verb.

Unlike the other skills under `.claude/skills/` (which convertible *vendors*),
this one is **authored here** — convertible is its origin (see
[`docs/skill-sources.md`](../skill-sources.md)).

## The three verbs

| Verb | What it does | Side effects |
|------|--------------|--------------|
| `explore "<question or area>"` | Read-only investigation; the model reads and reports findings. | **None** — runs in a throwaway `git worktree` at HEAD. |
| `review "<focus>" [--base main]` | A diverse second opinion on the **committed** diff (`<base>...HEAD`). | **None** — throwaway worktree; committed changes only. |
| `write "<task>" [--pr]` | Implement a change. | A `convertible/<id>` drive branch (or a PR with `--pr`). |

Each verb builds an instruction from a prompt template
(`prompts/{explore,review,write}.md`), runs `convertible drive --json`, and
prints the drive's `TaskResult.summary` to stdout. Per-step progress streams to
stderr while it runs.

## How to run

```bash
bash .claude/skills/outsource/scripts/outsource.sh <verb> "<text>" [options]
```

Common options: `--repo PATH` (default `.`), `--base BRANCH` (review base,
default `main`), `--engine` / `--model` / `--base-url` (default the local 27B,
overridable via flags or `CONVERTIBLE_*` env), `--max-steps N` (default 20),
`--timeout N` (per-request seconds, default 300 — a local model can be slow on a
growing context), `--allow-dirty` / `--pr` (write only).

### explore (read-only)

```text
$ outsource explore "report the top-level markdown title of README.md"
status: ok

**Top-level markdown title of `README.md` (line 1):**
# convertible
```

The drive ran entirely in a throwaway worktree — `git status`, the current
branch, and the worktree list are byte-for-byte identical before and after.

### write

```text
$ outsource write "create greet.py with a function greet(name) returning 'hi, ' + name" --repo /tmp/demo
status: ok

Created greet.py with a single function greet(name) that returns 'hi, ' + name.

changed files: greet.py
drive branch: convertible/3acc192d27e1
```

The change landed on a drive branch you can inspect, merge, or discard.

### review — the headline verb

`review` gets an independent second opinion on the committed diff. This skill
was itself reviewed this way — `outsource review` was pointed at the wrapper's
own diff, and the 27B (a different mind) flagged a real gap the author had
missed:

```text
$ outsource review "the print_result and worktree-cleanup changes" --base <prev>
status: ok

## Review of outsource.sh changes
### 1. Correctness risks / likely bugs
No bugs found. The changes are correct.
- print_result heredoc→-c fix: a real bug fix …
### 2. Design, clarity, or maintainability concerns
- Untested worktree path: the new test exercises write → run_write, NOT
  explore/review → run_readonly, so the worktree-cleanup logic is untested.
### 3. Actionable suggestions
1. Add a test for run_readonly …
```

That finding was acted on: `test_readonly_verb_isolates_in_a_worktree_and_cleans_up`
now covers exactly that path. A different mind earned its keep.

## Safety

- **explore and review are read-only.** They run in a throwaway `git worktree` at
  HEAD, so a stray write can't reach your working tree or branch, and the worktree
  (plus any drive branch) is removed afterwards. The prompts also instruct the
  model not to modify anything.
- **`write` refuses a dirty tree** unless `--allow-dirty` — this guards the
  dirty-tree hazard (`convertible drive --no-pr` commits *uncommitted* edits onto
  the drive branch and leaves you there). Commit or stash first.

## Honest limits

- Read-only is enforced by **worktree isolation + a prompt constraint**, not a
  sandbox — the loop always exposes `write_file`/`run_command`, so the model can
  still run arbitrary *read-only* commands.
- `review` covers **committed** changes only (`<base>...HEAD`); commit work first.
- A small **local model can be slow** on a large diff: reviewing a whole feature
  branch in one shot can exceed the per-request timeout. Keep the review scope
  tight (a focused `--base`, a specific file/area), raise `--timeout`, or point
  `--model` / `--base-url` at a bigger engine.
- The default engine is whatever single model is running locally; a multi-model
  fleet (a different model per verb) is separate infrastructure.

See the skill itself for the full contract:
[`.claude/skills/outsource/SKILL.md`](../../.claude/skills/outsource/SKILL.md).
