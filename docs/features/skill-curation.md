# Skill curation — role-aware subsets + a token-capped composed catalog

> Tracking: [colleague#257](https://github.com/agentculture/colleague/issues/257) ·
> spec R4 in
> [`docs/specs/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md`](../specs/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md).

Before this feature every built-in role's `skill_subset` field was `None` —
the field existed (`docs/features/subagent-roles.md`) but every role composed
the **full** skills catalog regardless of shape. And the catalog itself
composed unconditionally: however many skill docs a repo accumulated, all of
them landed in the system prompt every time. This feature does two things:
gives the read-and-report built-in roles a real, glob-based skill subset, and
lets the composed catalog be **token-capped** with a priority order so a
growing skills directory degrades gracefully instead of unboundedly.

## Role skill subsets (`colleague/roles.py`)

`explorer` / `planner` / `reviewer` share `_INVESTIGATION_SKILL_PATTERNS`;
`validator` gets that plus `"run-tests*"`; `writer` keeps `skill_subset=None`
(the full catalog — the "no silent skill loss" floor, see below):

```python
_INVESTIGATION_SKILL_PATTERNS: tuple[str, ...] = (
    "recall*", "explore*", "review*", "agent-config*",
    "doc-test-alignment*", "sonarclaude*",
)
_VALIDATOR_SKILL_PATTERNS = _INVESTIGATION_SKILL_PATTERNS + ("run-tests*",)
```

Each pattern is an **include** for a class of skill that is itself
investigation/reporting-shaped (reads state, writes nothing). Everything not
matched is excluded by omission — this repo's release/side-effect-shaped
skills (`cicd`, `version-bump`, `pypi-maintainer`, `assign-to-workforce`,
`communicate`, `ask-colleague`, `promote`) are deliberately left out of the
read-only roles' composed prompt, since a read-only child has no business
knowing how to open a PR or cut a release.

`BUILTIN_ROLES` is a **single module-level constant shared by every repo**
colleague drives — it can't hardcode this repo's current `.colleague/skills/*.md`
filenames, so each pattern travels by naming convention (an `fnmatch`-style
glob) rather than an exact list. A pattern matching nothing in a given repo's
catalog just composes an empty skills section — never an error.

## Glob-aware filtering (`colleague/layers.py` `_filter_skills`)

```python
def _filter_skills(skills, subset):
    if subset is None:
        return skills  # no silent skill loss
    return {name: skill for name, skill in skills.items()
            if any(fnmatch.fnmatchcase(name, pattern) for pattern in subset)}
```

`subset=None` passes every skill through unfiltered — the invariant a curated
role/mode must never breach: an **uncurated** role or mode (or `writer`) keeps
today's full catalog, byte-identical. `subset=()` (an empty tuple) matches
nothing. Matching is `fnmatch.fnmatchcase` so casing behavior doesn't vary by
platform, and a plain literal name (no wildcard characters) still matches
only that exact skill — a strict superset of the old exact-name-only
semantics, so every pre-existing exact-name subset keeps matching exactly
what it matched before.

## The `<!-- skill-priority: N -->` marker

An optional single-line HTML-comment marker in a skill doc (the same idiom as
learn-from's `<!-- learned-from: ... -->` provenance marker):

```markdown
<!-- skill-priority: 5 -->
```

Lower `N` means higher priority (survives longest under a cap). A missing or
malformed marker defaults to `SKILL_PRIORITY_DEFAULT = 100` — a neutral middle
value, so an explicitly high-priority skill (`N < 100`) always outranks an
unmarked one, and an explicitly low-priority skill (`N > 100`) is dropped
before an unmarked one. `parse_skill_priority(text)` parses it;
`skill_priority(skill)` reads + parses a `Skill`'s doc text, degrading to the
default on any read error. The marker line itself is skipped by
`_first_summary_line` so it never leaks into the composed catalog as if it
were the skill's summary.

## Token-capped composition (`select_skills_within_budget` / `compose_skills`)

`COLLEAGUE_SKILLS_TOKEN_CAP` (legacy `CONVERTIBLE_SKILLS_TOKEN_CAP` honored as
a fallback) — resolved by `resolve_skills_token_cap(explicit=None)` —
defaults to **`0`, meaning uncapped**: with no explicit cap parameter and no
env var set, composition is byte-identical to a cap-unaware call (the h4
honesty-condition floor: no explicit cap means no silent skill loss).

When a positive cap would be exceeded, `select_skills_within_budget`:

1. Checks whether the full catalog (rendered the same way `compose_skills`
   renders it) already fits — if so, nothing is dropped.
2. Otherwise **drops whole skills, lowest-priority first** — never a
   mid-skill truncation. Drop order is `sorted(names, key=lambda n:
   (priorities[n], n), reverse=True)`: the highest priority *number* (lowest
   priority) goes first; **ties are broken by reverse name order** (the
   alphabetically *later* name is dropped first) — deterministic and
   documented, not an implementation accident.
3. Stops as soon as the remaining catalog fits.

`compose_skills` appends one explicit note when anything was dropped:

```text
omitted 2 skill(s) over the token cap: pypi-maintainer, version-bump
```

never a bare truncation. `count_tokens` defaults to
`count_skill_tokens_chars` — the same zero-dependency char heuristic
(`chars // 4`, minimum 1 for non-empty text) `colleague.context.count_tokens_chars`
uses elsewhere, adapted for the flat-markdown catalog text rather than the
chat-message-list shape — so a caller can plug in an exact tokenizer via the
same `count_tokens` seam used throughout the context-budget feature, but none
is bundled.

`compose_role_prompt` composes the role's subset **first**, then applies the
(optional) token cap to that already-filtered catalog — a role's curated
subset and a token budget compose together, never independently. Composition
order stays fixed: `base` (engine default) → AGENTS layers → role
`prompt_fragment` → skills catalog (filtered, then capped).

**Wiring note:** `colleague/engine.py`'s `compose_role_prompt(role,
task.repo_path, config.model, base=_DEFAULT_SYSTEM)` call does not pass an
explicit `skills_token_cap` — so in practice the cap resolves purely from the
`COLLEAGUE_SKILLS_TOKEN_CAP` env var (via `resolve_skills_token_cap()`'s
`None`-parameter fallback), not from any per-repo/per-model config file. There
is no `.colleague/config.json` knob for this cap today — only the env var.

## Inspection: `colleague skills list --role/--budget`

`colleague/cli/_commands/skills.py`'s `skills list` verb mirrors exactly what
gets composed at drive time (never a separate, driftable code path):

- `--role NAME` filters the catalog to that role's `skill_subset` via the same
  `_filter_skills` the runtime composition uses — an unknown role name raises
  a clean `CliError` naming `colleague roles list`, never a silent no-op.
- `--budget TOKENS` (positive) switches the output from a plain list to a
  **composed vs. omitted** breakdown at that cap, via the exact
  `select_skills_within_budget` helper `compose_skills` calls, each entry
  annotated with its declared `<!-- skill-priority: N -->` value (or the
  default 100).

```text
$ colleague skills list --role explorer --budget 400
budget: 400 tokens
role: explorer
composed (3):
  agent-config (priority 100)
  explore (priority 100)
  recall (priority 100)
omitted (2):
  doc-test-alignment (priority 100)
  sonarclaude (priority 100)
```

## Honest limits

- **Static curation, not dynamic relevance ranking.** A role's `skill_subset`
  is a fixed, hand-authored pattern list; the token cap's priority order is a
  fixed per-skill marker. Neither considers the actual task at hand — a
  per-task dynamic relevance ranking (choosing which skills matter for *this*
  instruction) is the documented **#7** follow-up, not built here.
- **The cap is global per composition call, not per-role-tunable via config
  file** — only `COLLEAGUE_SKILLS_TOKEN_CAP` (env) or an explicit
  `skills_token_cap=` parameter (currently unused by the engine's own call
  site) set it; there is no `.colleague/config.json` key.
- **Whole-skill granularity only** — a skill that alone exceeds the cap is
  simply omitted; there is no mid-skill summarization or truncation (by
  design — a truncated skill doc could read as a *different*, wrong
  instruction).
- **`writer`'s `skill_subset=None` is deliberate**, not a placeholder pending
  future curation — the writer role is today's full-surface default and must
  never silently lose a skill.

## Spec + plan

- Spec: [`docs/specs/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md`](../specs/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md)
- Plan: [`docs/plans/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md`](../plans/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md)
  (tasks t10-t11)

## See also

- [`docs/features/subagent-roles.md`](subagent-roles.md) — the role model
  (`skill_subset` is one of its fields) this feature populates
- [`docs/features/layered-config.md`](layered-config.md) — the AGENTS +
  skills layering this feature's token cap sits inside
