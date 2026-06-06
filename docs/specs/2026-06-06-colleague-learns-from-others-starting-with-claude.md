# colleague learns from others, starting with Claude: a learn-from capability reads Claude Code skills from .claude/skills/ and adapts them into colleague's own .colleague/skills/ format — deterministic copy first, then an optional colleague-driven LLM adapt pass — so colleague grows its skill set by absorbing a peer's, on the same repo/root

> colleague learns from others, starting with Claude: `colleague learn-from claude` reads the repo's `.claude/skills/` and adapts each into a flat `.colleague/skills/<name>.md` colleague loads into every backend's system prompt — a deterministic copy first, then an optional colleague-driven review-and-adapt pass — with the lineage recorded, invokable both from the CLI and the interactive session

## Audience

- an operator (or an agent via the ask-colleague skill) who wants colleague to pick up the skills another agent already has — beginning with Claude Code's `.claude/skills/` — without hand-porting each one

## Before → After

- Before: colleague reads `.colleague/skills/*.md` into its system prompt, but that directory is empty in a fresh repo; the only skills present live in `.claude/skills/` in Claude's directory-per-skill + YAML-frontmatter format, which colleague does not read. Colleague's skill set cannot grow by learning from a peer.
- After: a single command — `colleague learn-from claude` (and a `/learn-from` slash in `colleague session`) — adapts each `.claude/skills/<name>/SKILL.md` into a flat `.colleague/skills/<name>.md`, stamped with a `learned-from` provenance marker, that `colleague skills list` resolves and every backend loads. A deterministic copy lands first; an optional colleague-driven LLM pass then adapts paths/locations and Claude-isms to colleague's own tool surface.

## Why it matters

- "learn from others" is the point: colleague should be able to absorb a peer agent's accumulated skills rather than have every skill re-authored for it. Claude is the first source; the source is a registry so future minds (codex, a mesh peer) slot in without a CLI change.

## Requirements

- `learn-from <source>` adapts `.claude/skills/<name>/SKILL.md` → `.colleague/skills/<name>.md`: strip the YAML frontmatter, fold the `description` (a YAML block scalar in every real SKILL.md) to a single leading summary line, stamp a `<!-- learned-from: ... -->` provenance marker, and preserve the body — deterministically (same input ⇒ byte-identical output).
  - honesty: the adapted doc's first non-empty non-heading line equals the source `description`, so `colleague/layers.py` `_first_summary_line` (the catalog summariser) yields the description, not the provenance comment — asserted against the real `_first_summary_line` in a test.
- the deterministic copy is stdlib-only (no pyyaml, a minimal `---`-fenced parser that handles `>`/`|` block scalars) and imports no `subprocess`/`threading`/`concurrent.futures`, so `dependencies = []` and `tests/test_boundary.py` stay green.
  - honesty: the zero-deps guard (`tests/test_zero_deps.py`) and boundary test pass unchanged; `colleague/learn_from.py` appears in no subprocess/thread allow-list.
- after the copy, unless `--copy-only`, colleague itself drives an LLM review-and-adapt pass over the just-copied skills in the working tree (fix paths/locations, replace Claude-specific machinery — the Skill tool, slash commands — with colleague's tool surface), flipping the marker to `adapt: claude->colleague`; it degrades to copy-only with a clear notice when no backend is reachable.
  - honesty: with the `mock` backend (offline, the contract reference) the stage-2 pass is invoked and the `TaskResult`/artifact shape is unchanged; with no backend reachable, `learn-from` still completes the copy and prints a copy-only-degrade notice rather than failing.
- the capability is invokable in both modes: a top-level `colleague learn-from` CLI verb (agent/markdown/scripted) and a `/learn-from` slash command in `colleague session` (interactive), both reaching the same `adapt_skills` core.
  - honesty: the slash command appears in the single `_SLASH_COMMANDS` catalog (so `/help`, the autocomplete popup, and the drift test all pick it up) and runs the deterministic copy in-session via the real CLI verb (`--copy-only`), refreshing the skills panel.

## Honesty conditions

- colleague loads skills as instructional text and does NOT execute them; "run them on the same repo/root" means the backend model reads the adapted doc and acts via its own tools (`read_file`/`write_file`/`list_dir`/`run_command`/`culture`/`devague`/`subagent(s)`/`finish`). A skill leaning on Claude's Skill tool, slash commands, or `scripts/` maps only partially — surfaced per skill as a `runnable_estimate` (full | partial | instructional-only), never overstated as fully runnable.
- the adaptation is idempotent: re-running reports `skipped` for unchanged skills and never rewrites them; a colleague-owned dest (carrying the provenance marker) is updated only under `--force`; a hand-authored dest (no marker) is `protected` and never silently clobbered.
- the deterministic copy is faithful and offline; the LLM adapt is non-deterministic and needs the live reference rig — both facts are documented, and the absence of a reachable backend degrades to copy-only, it does not error.
- `--dry-run` previews every action (would-create / would-update / would-skip / protected / not-found) and writes nothing.
- the source is a registry currently holding only `claude`; an unknown source is a clean user error listing the known sources, not a crash.

## Success signals

- on this repo, `colleague learn-from claude --copy-only` populates `.colleague/skills/` from the 13 `.claude/skills/`, `colleague skills list` then resolves them, a re-run reports all `skipped`, `--dry-run` reports the same plan while writing nothing, and `/learn-from claude --dry-run` works inside `colleague session`.

## Scope / boundaries

- scoped to reading `.claude/skills/` (repo, or `~/.claude/skills/` with `--user`) and writing `.colleague/skills/` in the same repo/root; it never copies skill `scripts/` binaries (they already live in `.claude/skills/<name>/scripts/` in the same root — the provenance marker records where) and never writes outside `.colleague/skills/`.
- one source (`claude`) behind a registry; no cross-repo learning, no network fetch of skills.

## Non-goals

- not a skill execution runtime (colleague still loads, never runs, skills — invokable skills remain a tracked follow-up), not a multi-backend router, not an MCP client, no daemon/socket, no new runtime dep.
- not an automatic/continuous sync — `learn-from` is operator/agent-invoked; it does not watch `.claude/skills/` for changes.

## Decisions

- the verb is top-level `learn-from` (a distinct action like `work`/`clean`), kept off the read-only `skills` noun (which only lists/overviews); the interactive surface is a `/learn-from` slash that runs the deterministic copy (`--copy-only`) so an in-session invocation never blocks on a model call.
- stage 2 reuses the existing bounded tool loop over the working tree without a git handoff/branch, so `learn-from` yields working-tree edits the operator reviews, not a `colleague/<id>` branch.

## Open / follow-up

- a second source (`codex`, a mesh peer) — the registry is ready; only a discoverer + format adapter is needed.
- repeated/continuous learning (a `--watch` or sync mode) is deferred; v1 is single-shot, invoked.
- whether the LLM adapt pass should run as a full recorded work item (with artifact + feedback) rather than an in-place loop pass is deferred to the feedback-loop follow-up.
