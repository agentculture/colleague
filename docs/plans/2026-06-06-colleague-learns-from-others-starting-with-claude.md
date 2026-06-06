# Build Plan — colleague learns from others, starting with Claude: a learn-from capability reads Claude Code skills from .claude/skills/ and adapts them into colleague's own .colleague/skills/ format — deterministic copy first, then an optional colleague-driven LLM adapt pass

slug: `colleague-learns-from-others-starting-with-claude` · status: `exported` · from frame: `colleague-learns-from-others-starting-with-claude`

> colleague learns from others, starting with Claude: `colleague learn-from claude` reads the repo's `.claude/skills/` and adapts each into a flat `.colleague/skills/<name>.md` colleague loads into every backend's system prompt — a deterministic copy first, then an optional colleague-driven review-and-adapt pass — with the lineage recorded, invokable both from the CLI and the interactive session

## Tasks

### t1 — NEW colleague/learn_from.py: the deterministic, stdlib-only adapter core (stage 1) + a source registry

- covers: r1, r2, h1, h2, h-idempotent, h-runnable
- acceptance:
  - parse_frontmatter handles a `---`-fenced block with `key: value` lines AND YAML block scalars (`>`/`>-` folded to one space-joined line, `|`/`|-` newline-preserving); no leading `---` or an unterminated fence ⇒ `({}, text)`
  - render_colleague_skill is deterministic (byte-identical on re-render) and leads with the description so `colleague.layers._first_summary_line(rendered) == description`; the `<!-- learned-from: ... -->` marker and the `# <name>` body survive
  - estimate_runnable returns full | partial | instructional-only from a documented heuristic
  - adapt_skills(repo, source=..., names, dry_run, force, user) resolves source via `_SOURCES` (only `claude`; unknown ⇒ ValueError), writes `.colleague/skills/<name>.md`, and reports created/updated/skipped/protected/not-found (would-* under dry_run); idempotent; a marker-less dest is protected unless force
  - colleague/learn_from.py imports no subprocess/threading/concurrent.futures (tests/test_boundary.py green) and adds no runtime dep (tests/test_zero_deps.py green)

### t2 — NEW tests/test_learn_from.py: adapter unit tests

- depends on: t1
- covers: r1, r2, h1
- acceptance:
  - tests cover block-scalar folding, the `_first_summary_line == description` contract (importing the real function), idempotency, name fallback to dir name, estimate_runnable, and adapt_skills created/skipped/dry-run/filter/not-found/unknown-source/protected
  - `uv run pytest tests/test_learn_from.py` passes

### t3 — NEW colleague/cli/_commands/learn_from.py (thin verb) + register in cli/__init__.py + _LEARN_FROM in explain/catalog.py

- depends on: t1
- covers: r4 (CLI half), h-explain
- acceptance:
  - `colleague learn-from <source> [name ...] [--repo] [--user] [--dry-run] [--force] [--copy-only] [--json]`: results→stdout, errors→stderr, `--json` payload {source, repo, dry_run, skills:[{name,source,dest,action,runnable_estimate,note}]}
  - unknown source / missing-or-non-existent `--repo` ⇒ CliError(EXIT_USER_ERROR=1) with a remediation hint
  - `colleague explain learn-from` resolves; the verb is registered and appears in `colleague --help`

### t4 — Stage-2 LLM adapt: in learn_from.py / the CLI verb, after the copy and unless --copy-only, drive the configured backend over the copied skills in the working tree (no handoff), flipping the marker to `adapt: claude->colleague`; degrade to copy-only when no backend is reachable

- depends on: t1, t3
- covers: r3, h3
- acceptance:
  - with `--copy-only` only stage 1 runs (deterministic, offline)
  - default runs stage 2 via the bounded loop over `.colleague/skills/` editing in place (no `colleague/<id>` branch); with the `mock` backend the pass is invoked and TaskResult/artifact shape is unchanged
  - an unreachable backend degrades to copy-only with a clear stderr notice, exit 0

### t5 — /learn-from session slash: SlashSpec in _SLASH_COMMANDS + a _CONFIG_ACTIONS handler in colleague/cli/_commands/session.py routing to the real verb with --copy-only

- depends on: t3
- covers: r4 (interactive half), h4
- acceptance:
  - `/learn-from [source] [--dry-run]` runs in-session via the real CLI verb (`--copy-only`), folds output into the cockpit, and refreshes the skills/context panels
  - the command appears in `_SLASH_COMMANDS` so `/help`, the autocomplete popup, and tests/test_session_autocomplete.py drift test pick it up

### t6 — NEW tests/test_learn_from_cli.py: CLI + session slash + mock-engine stage-2 tests

- depends on: t3, t4, t5
- covers: r3, r4
- acceptance:
  - learn-from claude on a fabricated tmp `.claude/skills/foo/SKILL.md`: created → skipped (idempotent) → --force update; --dry-run writes nothing; name filter; unknown source rc 1; missing `.claude/skills/` ⇒ empty list rc 0
  - a round-trip: after learn-from, `colleague skills list --repo <tmp>` shows the adapted skill
  - the `/learn-from` slash dispatches; a mock-engine stage-2 run leaves the artifact/result shape intact
  - `uv run pytest tests/test_learn_from_cli.py` passes

### t7 — Docs + scope + release: docs/features/learn-from.md, a docs/skill-sources.md note, the CLAUDE.md architecture bullet, /version-bump minor (1.0.0→1.1.0) + CHANGELOG; run full gates

- depends on: t1, t2, t3, t4, t5, t6
- covers: h-explain, process
- acceptance:
  - docs/features/learn-from.md documents the transform, the source registry, both invocation modes, and the honest load-not-execute limit; docs/skill-sources.md notes learn-from-generated (derived, marker-stamped) skills vs vendored ones; CLAUDE.md gains a learn-from bullet near the layered-config/skills section
  - version + CHANGELOG bumped; `pytest -n auto`, black/isort/flake8/bandit, the zero-deps + boundary + e2e-mock guards, and `teken cli doctor . --strict` all pass
