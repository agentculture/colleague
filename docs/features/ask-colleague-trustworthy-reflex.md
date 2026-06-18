# ask-colleague — trustworthy reflex

> The standing reflex is "review before every PR." It only pays off if the
> review is **fast**, **honest**, and **side-effect-safe**. Four shipped fixes
> (#217–#220b) close the gaps that made the reflex break on first real use
> (issue #220, filed from discord-bot-cli: zero findings at step 8 / ~8 min on
> a medium diff).

The fixes are **non-breaking**: they tighten existing behaviour without changing
the public interface. The wrapper (`ask-colleague.sh`) and `SKILL.md` are
vendored verbatim to consumers, so these fixes re-vendor automatically
(tracked in rollout-cli#11).

## #217 — `write --apply` dirty guard is tracked-only

The `write --apply` dirty guard now uses
`git status --porcelain --untracked-files=no`, so a prior `explore` or `review`
probe's untracked `.colleague/` artifacts no longer block an apply. This
matches the runtime `working_tree_dirty` guard in `colleague/handoff.py`.

Before this fix, any untracked file (including the `.colleague/` cache left by
a preceding read-only probe) would cause the guard to refuse the apply,
forcing the user to manually clean the working tree.

## #218 — SKILL.md provenance paragraph corrected

The `SKILL.md` provenance paragraph no longer claims the consumer's sibling
skills are "vendored from guildmaster." It states only that `ask-colleague` is
first-party from `colleague` under cite-don't-import, and defers
sibling-skill provenance to the consumer's own `docs/skill-sources.md` ledger.

This prevents the skill from making claims about the consumer's repo that it
cannot verify.

## #219 — `flight status --follow` streams live

The command `colleague flight status --follow` streams the flight feed live
using a stdlib poll loop over the `.colleague/flight/<id>.feed.jsonl` file. It
exits cleanly on flight-finish (feed reap), EOF, or Ctrl-C. The `--json` flag
emits JSONL.

The `ask-colleague monitor` subcommand now invokes it, so "watch the live feed"
is finally accurate. The one-shot `flight status` (without `--follow`) is
byte-identical to before.

**No daemon, no socket, no new dependency.** The poll loop is pure stdlib.

## #220a — `review` front-loads a filtered, capped diff

The `ask-colleague review` instruction now includes a filtered, capped diff:

- `git diff --stat` (always emitted)
- The diff body with lockfile and vendored noise excluded (`uv.lock`,
  `package-lock.json`, `*.min.js`)
- Capped to `COLLEAGUE_MAX_OUTPUT_CHARS` with an explicit truncation note

The model receives the whole change in **~1 turn** instead of **~8 sequential
read turns**. The review prompt now states that the diff is provided.

This is the speedup that holds on the reference rig (single serializing GPU).

## #220b — advisory review fan-out

When a review reads across more than `COLLEAGUE_REVIEW_FANOUT_FOLDERS` distinct
folders, the runtime injects **one recommendation** to delegate per-folder
read-only `reviewer` subagents via the `subagents` tool, reusing the existing
fan-out/merge machinery. **No new worktree or merge code** is introduced.

The feature is **dormant by default** (`review_fanout_folders=None`), making it
byte-identical when off. The recommendation is advisory and backend-judged.

## Honest limits

1. **Parallel fan-out gives ~no wall-clock speedup on a single serializing
   GPU.** On a vLLM instance with `--max-num-seqs=2`, the parallel review
   fan-out is bound by overlapped I/O, not model compute. The front-loaded
   diff (#220a) is the speedup that holds on the reference rig.

2. **Zero new runtime dependencies, daemons, or sockets.** None of these fixes
   adds a runtime dependency, daemon, or socket. The zero-deps / no-daemon
   conventions hold.

3. **Wall-clock `--deadline` flag and GPU-contention auto-detection are
   deferred.** These are follow-ups, not built.

4. **Forced-synthesis (#191/#197) is unchanged.** The already-shipped
   forced-synthesis mechanism is unaffected; these fixes complement it.

## See also

- [`docs/features/ask-colleague.md`](ask-colleague.md) — the `ask-colleague` skill overview
- [`docs/features/agent-cli.md`](agent-cli.md) — `colleague work` and `colleague drive` entry points
