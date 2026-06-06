# learn-from — colleague learns skills from a peer agent

`colleague learn-from <source>` lets colleague **grow its skill set by absorbing
another mind's** — starting with Claude. It reads an external agent's skills and
adapts them into colleague's own flat `.colleague/skills/*.md` format, which
colleague folds into every backend's system prompt (`colleague/layers.py`) on the
**same repo/root**.

> Why it exists: colleague already *reads* `.colleague/skills/*.md`, but a fresh
> repo's only skills live in `.claude/skills/` in Claude Code's directory-per-skill,
> YAML-frontmatter form. `learn-from` is the bridge that populates colleague's
> skill layer from a peer — the *write* side of the read-only `skills list`/`overview`.

## The two stages

### Stage 1 — deterministic copy (`colleague/learn_from.py`, stdlib only)

Turns `.claude/skills/<name>/SKILL.md` → `.colleague/skills/<name>.md`:

- strip the SKILL.md YAML frontmatter — a minimal `---`-fenced parser that
  handles **block scalars** (`description: >` / `|`), since every real SKILL.md
  writes its description as `>`;
- fold the `description` into a **leading summary line** so colleague's catalog
  (`compose_skills` → `_first_summary_line`) shows it;
- stamp a provenance marker:
  `<!-- learned-from: claude; source: <path>; scripts: <path|->; adapt: pending -->`;
- keep the body verbatim.

It is **deterministic and idempotent** (same input ⇒ byte-identical output; an
unchanged skill reads back `skipped`) and **zero-dep** (stdlib only — no pyyaml,
no subprocess/threads, so `tests/test_boundary.py` and `tests/test_zero_deps.py`
hold).

A skill's `scripts/` are **not copied** — they already live at
`.claude/skills/<name>/scripts/` in the same repo/root, and the marker records
where. (Copying binaries would duplicate bytes and imply colleague executes
them — it does not; see the honest limit below.)

### Stage 2 — LLM review-and-adapt (optional; colleague drives)

By default, after the copy, colleague itself drives the configured backend over
each freshly written skill **in the working tree, with NO git handoff/branch**, to:

- fix file paths / locations that referred to the source repo or to `.claude/`;
- replace Claude-specific machinery (the Skill tool, slash commands like
  `/think`) with colleague's own tool surface
  (`read_file`/`write_file`/`list_dir`/`run_command`/`culture`/`devague`/`subagent`);
- preserve the skill's intent and leading summary, then flip the marker to
  `adapt: claude->colleague`.

Skip it with `--copy-only`. It is **best-effort and isolated**: an unreachable
backend (or any per-skill failure) **degrades to copy-only** with a clear stderr
notice — the stage-1 file stays on disk, marker `adapt: pending`. Stage 2 reuses
the existing bounded tool loop (`engine.work`), so it inherits hooks, telemetry,
and the all-engines contract; it runs one scoped work item per written skill.

## Safety

- An existing **colleague-owned** skill (carrying the provenance marker) that
  differs is updated only with `--force`.
- A **hand-authored** skill doc (no marker) is `protected` and never silently
  clobbered — `--force` to overwrite.
- `--dry-run` previews every action (`would-create` / `would-skip` /
  `would-update` / `protected` / `not-found`) and writes nothing.

## Honest limit — load, not execute

colleague **loads** skills as instructional text; it does **not execute** them.
"Run them on the same repo/root" means the backend model *reads* the adapted doc
and acts via its own tools. A skill leaning on scripts / the Skill tool / slash
commands maps only **partially** — surfaced per skill as `runnable_estimate`:

- `full` — pure instructional prose;
- `partial` — mentions running commands generally;
- `instructional-only` — references scripts / the Skill tool / slash commands.

This is a documented heuristic, not a guarantee.

## Invocation — both modes

`learn-from` is an internal capability reachable two ways (it is **not** a
`.colleague/skills/` doc — it does not live "in the context"):

- **markdown / scripted / agent mode** — the CLI verb:

  ```bash
  colleague learn-from claude --repo .
  colleague learn-from claude --copy-only          # deterministic copy only
  colleague learn-from claude run-tests think      # only these skills
  colleague learn-from claude --dry-run --json     # preview, machine-readable
  colleague learn-from claude --user               # read ~/.claude/skills/
  colleague learn-from claude --force              # re-learn / overwrite
  ```

- **interactive mode** — the `/learn-from` session slash (runs the deterministic
  copy with `--copy-only` so it never blocks on a model call):

  ```text
  /learn-from claude
  /learn-from claude run-tests --dry-run
  ```

## The source registry

The source is a tiny registry (`colleague/learn_from.py` `_SOURCES`), currently
holding only `claude`. A future mind (a `codex`, a mesh peer) is a new entry —
a discoverer + format adapter — with no CLI change. An unknown source is a clean
user error that lists the known sources.

## See also

- `colleague explain learn-from`
- [`docs/features/layered-config.md`](layered-config.md) — how `.colleague/skills/`
  resolve and compose into the system prompt
- [`docs/skill-sources.md`](../skill-sources.md) — skill provenance (vendored vs
  first-party vs learn-from-generated)
- spec/plan: `docs/specs/2026-06-06-colleague-learns-from-others-starting-with-claude.md`,
  `docs/plans/2026-06-06-colleague-learns-from-others-starting-with-claude.md`
