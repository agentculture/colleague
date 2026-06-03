---
name: outsource
type: command
description: >
  Hand a scoped repo task to colleague — a *different* backend/model than you
  (e.g. a local vLLM Qwen) — and fold its answer back. The point isn't a stronger
  model; it's a different mind, and diversity helps: `outsource review` gets an
  independent second opinion on a diff, `outsource explore` gets a fresh read of
  an area, `outsource write` delegates a small implementation, and `outsource
  feedback` grades a finished drive (the ROI loop). Reach for it PROACTIVELY, not
  only when asked: before you present or open a PR on a non-trivial committed
  diff, run `review` for a diverse second opinion; for a fresh read of an
  unfamiliar area whose answer is independent of your current context, run
  `explore`. Both are read-only — isolated in a throwaway git worktree, zero side
  effects — so the reflex is always safe; the side-effecting `write --apply` /
  `write --pr` still needs the user's go-ahead. Also triggers when the user says
  "outsource this", "get a second opinion", "have colleague review/explore/
  write", "ask the other model", or "rate that drive". Outsourced output is a
  second opinion to verify and own, never authority.
---

# outsource — use colleague as a different mind

`outsource` drives the **`colleague`** CLI so a Claude agent can hand a scoped
task to a *different* backend (default: a local vLLM `Qwen3.6-27B` on
`:8001`). Colleague's model is **not** assumed to be stronger than you — its
value is **diversity**. A second, independent mind catches things the author's
mind glides past, which is why **review** is the headline verb.

This skill is the operator: a portable wrapper that resolves the CLI and turns
each verb into a `colleague drive`, then prints the drive's result summary.

## The reflex — when to reach for colleague *unprompted*

Don't wait to be told "outsource this." The two read-only verbs have **zero side
effects** (throwaway worktree, can't touch your tree), so reaching for them is
always safe — make it a habit on tasks that fit:

**GO** (reach out on your own — default to the read-only verbs):

- **`review` — the standing reflex.** You (or a subagent) just produced a
  non-trivial *committed* diff and are about to present it or open a PR. Get a
  diverse second opinion *first*. A different mind catches what the author's mind
  glides past — that's the whole point, and it costs you nothing but ~20s.
- **`explore`** — you need to understand an unfamiliar area whose answer is
  **independent of your current context**, and you could be doing something else
  meanwhile. Fan it out, fold the findings back.
- A scoped, **verifiable** subtask where a fresh pass raises your confidence and
  you can cheaply check the result.

**NO-GO** (just do it yourself):

- Work that needs *your* accumulated context, the user's intent, or cross-cutting
  design judgment — a context-free second mind will drift, not help.
- Anything **outward-facing or destructive** without a user nod: `write --apply` /
  `write --pr`, posting, deleting. The read-only verbs are the unprompted reflex;
  side-effecting ones are not.
- Trivial work that's faster to just do (a one-line edit) — the drive + fold-back
  costs more than the edit.
- Output you can't verify cheaply — if you can't check it, diversity is just noise.

**Guardrails (always):**

- **One-glance readiness.** `colleague whoami` names the live drive engine +
  model; if it reports `mock` or you're unsure the server is up, run `colleague
  doctor --probe`. Don't burn time on a dead or no-op backend.
- **Second opinion, not authority.** colleague is a *different* mind, not a
  stronger one. Weigh its findings, verify its claims, own the decision. Diversity
  is the value; verification is the price.
- **Close the loop.** Occasionally `outsource feedback last --rating N` so the ROI
  of outsourcing this *kind* of task is measurable — and you learn when to stop.

## How to run

The entry point is `scripts/outsource.sh`. Invoke it from the repo you want
colleague to work on:

```bash
bash .claude/skills/outsource/scripts/outsource.sh <verb> "<text>" [options]
```

It resolves the CLI portably — an installed `colleague` on `PATH` (the normal
case), falling back to `uv run colleague` when inside the colleague checkout,
else an install hint.

### Verbs

| Verb | What it does | Side effects |
|------|--------------|--------------|
| `explore "<question or area>"` | Read-only investigation of the repo; the model reads and reports findings. | **None** — runs in a throwaway worktree at HEAD. |
| `review "<what to focus on>" [--base main]` | A diverse second opinion on the **committed** diff (`<base>...HEAD`). | **None** — throwaway worktree; reviews committed changes only. |
| `write "<task>" [--apply\|--pr]` | Implement a change. **Previews by default** (throwaway worktree, prints the would-be diff); `--apply` lands a drive branch in place; `--pr` pushes + opens a PR. | **None** by default (preview); a `colleague/<id>` drive branch / PR only with `--apply` / `--pr`. |
| `feedback <id\|last> [--rating N]` | **Grade a finished drive** (the ROI loop). With `--rating N` (1–5, plus `--notes`) it records feedback; without, it shows the drive's existing feedback. `last` resolves the most recent drive in `--repo`. | Writes `.colleague/<id>.feedback.json` only when `--rating` is given; read-only otherwise. |

### Options

| Option | Meaning |
|--------|---------|
| `--repo PATH` | Target repo (default: `.`). |
| `--base BRANCH` | Base for the `review` diff (default: `main`). |
| `--engine NAME` | Backend plugin (default: `$COLLEAGUE_ENGINE` or `vllm-openai`). |
| `--model NAME` | Model (default: `$COLLEAGUE_MODEL` or `sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP`). |
| `--base-url URL` | OpenAI base URL (default: `$COLLEAGUE_BASE_URL` or `http://localhost:8001/v1`). |
| `--max-steps N` | Loop step budget (default: 20). |
| `--apply` | (`write`) apply the change in place (drive branch) instead of previewing. |
| `--allow-dirty` | (`write`) allow running on a dirty tree (only matters with `--apply` / `--pr`). |
| `--pr` | (`write`) push + open a PR instead of a local drive branch (implies `--apply`). |
| `--rating N` | (`feedback`) record a 1–5 quality rating for the drive. |
| `--notes "..."` | (`feedback`) free-text notes stored with the rating. |
| `--by NAME` | (`feedback`) who is grading (default: colleague's resolved identity). |

The result printed to stdout is the drive's `TaskResult.summary` (plus
`changed_files` / drive branch for `write`), parsed from `colleague drive
--json`. Per-step progress streams to stderr while it runs.

## When to reach for which verb

- **review** — the standing use. You wrote (or an agent wrote) a change and you
  want a candid, independent pass over the *committed* diff before you trust it.
  Treat the output as a second opinion to weigh, not a verdict.
- **explore** — you want a fresh, unbiased read of an unfamiliar area ("how does
  X work here?") without anchoring on your own assumptions.
- **write** — a small, well-scoped implementation you're happy to delegate. It
  **previews by default** (runs in a throwaway worktree and prints the would-be
  diff without touching your tree); pass `--apply` to land it on a
  `colleague/<id>` drive branch you can inspect, merge, or discard, or `--pr` to
  open a PR.
- **feedback** — *after* an outsourced drive, close the loop: record how good it
  was. Every drive's artifact already carries always-on **stats** (elapsed time,
  tokens read/generated, tools used, bytes written, reasoning-vs-answer sizes);
  `feedback` adds a 1–5 quality grade. Stats say what it *cost*, feedback says how
  *good* it was — together they let you compute the **ROI of outsourcing** and
  decide whether to outsource again (and to which backend). Grade the most recent
  drive with `outsource feedback last --rating 4 --notes "…"`.

## Hard rules (do not violate)

- **explore and review are read-only.** They run in a throwaway `git worktree`
  at HEAD, so a stray write can't reach your working tree or branch; the prompts
  also tell the model not to modify anything. Don't route a change-making task
  through them — use `write`.
- **`write` previews by default; applying refuses a dirty tree.** A preview runs
  in an isolated worktree and never touches your tree, so it is safe even when
  dirty. `--apply` / `--pr` (the in-place path) refuses a dirty tree unless you
  pass `--allow-dirty` — this guards the dirty-tree hazard: `colleague drive
  --no-pr` commits *uncommitted* edits onto the drive branch and leaves you there.
  Commit or stash first before applying.
- **Outsourced output is a second opinion, not authority.** The backend may be a
  smaller/different model; weigh its findings, verify its claims, and own the
  decision yourself.

## Honest limits

- Read-only is enforced by **worktree isolation + prompt constraint**, not a
  sandbox — the loop always exposes `write_file`/`run_command`, so the model can
  still run arbitrary *read-only* commands.
- `review` covers **committed** changes only (`<base>...HEAD`). To review
  uncommitted work, commit it first.
- The default backend is whatever single model is running locally; a multi-model
  fleet (different model per verb) is separate infrastructure.

## Provenance

This is a **first-party** colleague skill — colleague is its origin. It is
the inverse of the other skills under `.claude/skills/`, which colleague
vendors *from* guildmaster. See `docs/skill-sources.md`. The `cite, don't import`
policy holds: downstream repos copy it, they don't symlink or depend on it.
