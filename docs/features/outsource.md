# `outsource` — use colleague as a different mind

> Hand a scoped repo task to colleague — a *different* backend/model than the
> calling agent. The point isn't a stronger model; it's a **different mind**, and
> diversity helps.

`outsource` is a **first-party Claude Code skill** (`.claude/skills/outsource/`)
that drives the `colleague` CLI so another agent can delegate a scoped task to
a different engine (default: a local vLLM `sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP` on
`:8001`). Colleague's model is **not assumed to be stronger** than the caller —
a second, independent perspective catches what the author's mind glides past,
which is why **review** is the headline verb.

Unlike the other skills under `.claude/skills/` (which colleague *vendors*),
this one is **authored here** — colleague is its origin (see
[`docs/skill-sources.md`](../skill-sources.md)).

## The three verbs

| Verb | What it does | Side effects |
|------|--------------|--------------|
| `explore "<question or area>"` | Read-only investigation; the model reads and reports findings. | **None** — runs in a throwaway `git worktree` at HEAD. |
| `review "<focus>" [--base main]` | A diverse second opinion on the **committed** diff (`<base>...HEAD`). | **None** — throwaway worktree; committed changes only. |
| `write "<task>" [--apply\|--pr]` | Implement a change. **Previews by default**; `--apply` lands it, `--pr` opens a PR. | **None** by default (preview in a throwaway worktree); a `colleague/<id>` drive branch with `--apply` (or a PR with `--pr`). |

Each verb builds an instruction from a prompt template
(`prompts/{explore,review,write}.md`), runs `colleague drive --json`, and
prints the drive's `TaskResult.summary` to stdout. Per-step progress streams to
stderr while it runs.

## The reflex — reach for it *unprompted*

The skill is meant to fire **proactively**, not only when a user says "outsource
this." The two read-only verbs have zero side effects (throwaway worktree), so
the reflex is always safe:

- **`review` is the standing reflex** — before presenting or opening a PR on a
  non-trivial *committed* diff, get a diverse second opinion. A different mind
  catches what the author's mind glides past, at the cost of ~20s.
- **`explore`** when you need a fresh read of an unfamiliar area whose answer is
  independent of your current context.
- **Don't** outsource work that needs your accumulated context or the user's
  intent, anything outward-facing/destructive without a nod (`write --apply` /
  `--pr`), trivial edits, or output you can't verify cheaply.
- **Guardrails:** check readiness in one glance (`colleague whoami` names the live
  drive engine + model; `doctor --probe` if unsure); treat output as a second
  opinion to verify and own, never authority; close the loop with `feedback` so
  the ROI is measurable.

See the [skill](../../.claude/skills/outsource/SKILL.md) for the full GO/NO-GO rule.

## How to run

```bash
bash .claude/skills/outsource/scripts/outsource.sh <verb> "<text>" [options]
```

Common options: `--repo PATH` (default `.`), `--base BRANCH` (review base,
default `main`), `--engine` / `--model` / `--base-url` (default the local 27B,
overridable via flags or `COLLEAGUE_*` env), `--max-steps N` (default 20),
`--timeout N` (per-request seconds, default 300 — a local model can be slow on a
growing context), `--apply` / `--allow-dirty` / `--pr` (write only — `write`
previews unless `--apply` or `--pr` is given).

### explore (read-only)

```text
$ outsource explore "report the top-level markdown title of README.md"
status: ok
task: 7f3a91c0b2e4

**Top-level markdown title of `README.md` (line 1):**
# colleague

artifact: /repo/.colleague/7f3a91c0b2e4.report-the-top-level-markdown-title.json
grade: outsource feedback 7f3a91c0b2e4 --rating <1-5>
```

The drive ran entirely in a throwaway worktree — `git status`, the current
branch, and the worktree list are byte-for-byte identical before and after. A
read-only probe **preserves** its artifact (so you can grade it by the printed
`task_id`) but does **not** move the `last` pointer (#132), so a probe can never
steal a grade meant for a write. Grade it by its id, or find it later with
`outsource feedback list`.

### write (previews by default)

Without `--apply`, `write` runs the change in a throwaway worktree and prints the
would-be diff — nothing touches your working tree:

```text
$ outsource write "create greet.py with greet(name) returning 'hi, ' + name" --repo /tmp/demo
status: ok

Created greet.py with a single function greet(name) that returns 'hi, ' + name.

changed files: greet.py

--- preview diff (NOT applied — pass --apply to land it) ---
diff --git a/greet.py b/greet.py
new file mode 100644
+++ b/greet.py
+def greet(name):
+    return "hi, " + name
```

Pass `--apply` to land it on a `colleague/<id>` drive branch you can inspect,
merge, or discard (or `--pr` to push + open a PR):

```text
$ outsource write "create greet.py with greet(name) …" --repo /tmp/demo --apply
status: ok

Created greet.py with a single function greet(name) that returns 'hi, ' + name.

changed files: greet.py
drive branch: colleague/3acc192d27e1-create-greet-py-with-greet-name
grade: outsource feedback 3acc192d27e1 --rating <1-5>
```

The drive branch and artifact carry a slug of the request, so the drive is
recognisable in a `git branch` / `ls .colleague/` listing.

### feedback — close the ROI loop

```text
$ outsource feedback list                          # find a drive by its request
ID            WHEN              STATUS  GRADE  REQUEST
3acc192d27e1  2026-06-05 14:02  ok      --     create greet.py with greet(name) …
7f3a91c0b2e4  2026-06-05 13:55  ok      --     report the top-level markdown title …

$ outsource feedback 3acc192d27e1 --rating 4 --notes "clean"   # grade by id
```

`outsource feedback last` grades the most recent **write** (read-only probes
don't move `last`). Grade a probe by the `task_id` it printed, or use
`outsource feedback list`.

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
- **`write` previews by default** (isolated worktree, safe even on a dirty tree).
  **Applying** (`--apply` / `--pr`) **refuses a dirty tree** unless `--allow-dirty`
  — this guards the dirty-tree hazard (`colleague drive --no-pr` commits
  *uncommitted* edits onto the drive branch and leaves you there). Commit or stash
  first before applying.

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
