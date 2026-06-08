# Changelog

All notable changes to this project will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/). This project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.0] - 2026-06-08

### Added

- ``colleague config show`` / ``config overview`` verb: prints the resolved provider
  configuration (base_url, model, max_steps, temperature, timeout,
  context_budget_tokens) with api_key redacted. Reflects .colleague/config.json
  when --repo is given.
- ``colleague doctor --repo`` now reflects .colleague/config.json: provider and
  reachability groups accept an optional repo_path, so doctor diagnoses the
  current repo's persistent config-file override.

### Changed

- Documented the .colleague/config.json provider override in
  docs/features/model-selection.md (worked OpenAI/OpenRouter examples; corrected
  default-model table).

## [1.2.0] - 2026-06-08

### Added

- Persistent config-file override for the engine endpoint: .colleague/config.json (repo-level, falling back to user-level ~/.colleague/config.json) feeds base_url/api_key/model into EngineConfig.resolve as the resolution default, so colleague can be pointed at any OpenAI-compatible provider (replacing the local vLLM) without re-passing CLI flags or env vars. Precedence: explicit flag > COLLEAGUE_*/OPENAI_* env > .colleague/config.json > built-in default. Wired into the work/session/learn-from paths; stdlib json only; absent/malformed file is a strict no-op (colleague/config.py load_config_file).

### Changed

- EngineConfig.resolve gains an optional repo_path keyword; when omitted, behavior is byte-identical to before.

## [1.1.0] - 2026-06-06

### Added

- colleague `learn-from <source>`: learn skills from a peer agent (first source: claude) — read `.claude/skills/<name>/SKILL.md` and adapt each into colleague's own `.colleague/skills/<name>.md` (deterministic, stdlib-only copy: frontmatter strip incl. block scalars, description-first summary line, learned-from provenance marker; idempotent create/skip/update/protect).
- Optional stage-2 LLM review-and-adapt pass driven by the configured backend over each written skill in the working tree (no git handoff); --copy-only skips it and it degrades to copy-only when no backend is reachable.
- /learn-from session slash command (deterministic copy, --copy-only).
- colleague explain learn-from + docs/features/learn-from.md.

## [1.0.0] - 2026-06-06

### Added

- Capacity standard (#156): proactive fill-line decision (compact | split | finish-with-handoff) recorded on TaskResult.capacity_decision; self-compaction summarizes the working history to itself with lossy windowing as the fallback floor; coarse complexity assessment in colleague/capacity.py; warn-only "too big for one repo" caller warning (TaskResult.capacity_warning). Tunable via COLLEAGUE_FILLLINE_THRESHOLD (default 0.8).

### Changed

- v0 -> v1 graduation: the v0 "no LLM-generated summary" convention is intentionally superseded by self-compaction; lossy windowing remains the documented fallback floor.

## [0.42.0] - 2026-06-06

### Added

- `colleague clean` verb + `ask-colleague clean`: reap stale/corrupt `colleague/*` branches and orphaned 0-byte `.colleague/` artifacts left by a crashed work item (which can wedge `git fetch`), scoped strictly to `colleague/*` and conservative with `.git/objects` (#162)
- Advisory doctor stale-ref check (`colleague_stale_refs`, warning severity) that flags a wedged repo and points at `colleague clean` (#162)

### Changed

- Handoff is crash-resilient: a catchable interruption (`HandoffError` / `KeyboardInterrupt`) before the commit lands restores the operator ref and reaps the orphan `colleague/<id>` branch; the success path is byte-identical (#162)
- `ask-colleague.sh`: user-input errors (bad/missing verb, flag, arg, path; dirty-tree guard) now exit 1 not 2, matching the CLI 0/1/2 contract; environment errors stay 2 (#161)
- `ask-colleague` SKILL.md: explore/review side-effect cells no longer claim unqualified None (they write a gradable `.colleague/` artifact); added a consumer gitignore note for `.colleague/` (#161)

## [0.41.0] - 2026-06-06

### Added

- Slash dropdown grouped tree with tag badges (#160): the colleague session / autocomplete popup is now a borderless (frameless) grouped tree — commands sit under one icon per intent group (📁 Controls / Inspect / Session) with compact capability/risk tag badges ([read-only], [git], [pr], [writes], …) next to each command; filtering preserves group context and the selected command shows its summary.
- New SlashSpec.tags metadata feeds the popup, /help, and the cockpit tiers from one source; a shared tag/group formatter (colleague/tui/widgets/slash_autocomplete.py) keeps them from drifting.
- /help compact renders the emoji tag form; COLLEAGUE_SLASH_TAG_STYLE=icons switches the live popup to icon badges.
- PanelItem.tags so the slash-command tree (slash.* panels, one per group) reaches the agent-facing Markdown and TAUI/JSON cockpit tiers; the borderless live session view skips them (the / popup covers that).

### Changed

- /help and /help verbose now render group icons and tag badges; the compact help lists each command on its own line under its group instead of a dense name row.
- TAUI mirror schema bumped to 0.2 (panel items gained an optional tags list).

## [0.40.0] - 2026-06-06

### Added

- Session delegation cockpit (#158): a Run policy panel (run_command gating, file edits, push/PR) and a Context panel (repo, branch, working-tree state, AGENTS-layer and skill counts, telemetry, /feedback availability) on the first session screen, plus a suggested next action that always answers "what now?".
- Borderless, Markdown-feel interactive ANSI cockpit renderer (colleague/tui/render/ansi_flat.py) with an animated emoji state glyph (moon-phase while a work item runs, steady severity glyph at idle); derived from taui.serialize so it cannot drift from the Markdown view.
- Grouped compact /help (Controls / Inspect / Session) plus a richer /help verbose.

### Changed

- The session work-templates palette is retitled "Work templates" (panel id unchanged); the policy + context panels flow into the Markdown and TAUI tiers for free.
- Promoted handoff._current_ref to public handoff.current_ref (read-only branch accessor) so the cockpit can surface the current branch.

### Fixed

- The Session panel's suggested next action no longer goes stale (#159 review): `_refresh_context()` now recomputes and replaces the leading suggestion in place after `/pr`, `/base`, `/model`, `/engine`, and a completed work item, so the cockpit keeps its "always answer what now?" promise (it previously rebuilt only the policy + context panels).
- The Run policy panel labels `run_command` honestly (#159 review): an empty allow-list paired with a deny-list now reads `deny-list: … (all others allowed)` and a section with no rules reads `present, no rules (effectively ungated)`, instead of misleadingly claiming `gated (deny unlisted)` — matching what `Policy.check_run_command` actually enforces (an allow-list only gates when non-empty).
- The Run policy panel no longer crashes on a malformed `approvals.json` (#159 review): allow/deny values are coerced through a string-list sanitizer mirroring `policy._str_list`, so an `allow` given as a dict or a list with non-string members degrades gracefully instead of raising `TypeError` during render.

## [0.39.2] - 2026-06-05

### Added

- `colleague/context.py` `is_request_timeout` + `classify_degradable` — sibling detectors that drive the loops degradation and auto-split gates for both overflow and request-timeout signals (all-engines rule).

### Changed

- The `doc-review` command template is now self-scoping: it audits a few surfaces per pass and recommends a per-surface split early, so a large doc set no longer blows the request timeout. CLAUDE.md and `docs/features/graceful-degradation.md` document the timeout-degradation path and its honest limit (a dead/stuck server still wastes the bounded timeout retries).

### Fixed

- A request timeout mid-completion now degrades gracefully like a context-overflow instead of hard-failing with no deliverable (#154): the loop trims history and retries (capped lower, `_MAX_TIMEOUT_RETRIES=1`, since each timeout costs a full `COLLEAGUE_TIMEOUT` window), and on an exhausted give-up injects the auto-split/INCOMPLETE recommendation against a carried-forward floored window so the model can still produce an INCOMPLETE report. The vLLM `_post_json` now wraps a read-phase `TimeoutError` legibly (keeps "timed out" for the detector, surfaces the `COLLEAGUE_TIMEOUT` knob).
- `_complete_with_degradation` now honours `classify_degradable`'s overflow-takes-precedence rule across a mixed sequence (#157 review): an overflow seen *after* an earlier timeout restores the higher `_MAX_OVERFLOW_RETRIES` cap instead of staying pinned to the lower timeout cap, so the cheap overflow retries are no longer starved by the earlier timeout. The reactive shrink-and-retry was refactored into focused helpers (`_open_degradation_window`, `_shrink_for_retry`, `_plan_degraded_retry`, `_final_degraded_attempt`) to drop its cognitive complexity below the SonarCloud threshold, and the new `# noqa` suppression comments were normalised to a parsable form.

## [0.39.1] - 2026-06-05

### Changed

- Docs terminology cleanup to match the `drive`->`work` rename and align "outsource" wording to "delegate": `drive` (noun)->`work item`, `drive branch`->`work branch`, `colleague drive`->`colleague work`, and outsource(d)->delegate(d) across the ask-colleague SKILL.md, stats-and-feedback, and escalation docs; back-compat/rename-history lines intentionally preserved.
- CLAUDE.md: added a Prefer Colleague over spawning a sub-agent guidance paragraph to the division-of-labor section.

## [0.39.0] - 2026-06-05

### Added

- Auto-split (#151): when an assignment is too large for one context window, colleague now recommends splitting it into up to ~4 hand-over child assignments via the existing `subagents` tool instead of degrading lossily or failing. Advisory and backend-judged: the reactive trigger fires at the degradation-exhaustion point (when bounded overflow retries are exhausted) and is sequenced BEFORE escalation; the model decides whether to split. A coarse up-front instruction estimate adds an early advisory hint. The fan-out + merge reuse `colleague.subagents.make_batch_spawn`/`batch_spawn` verbatim. Capacity is a tunable `COLLEAGUE_AUTOSPLIT_TARGET` knob (default ~1M tokens), structurally clamped to `MAX_SUBAGENT_FANOUT - 1`. Runtime-owned (all-engines rule); zero new deps; a strict no-op when no trigger fires.

## [0.38.0] - 2026-06-05

### Added

- `--allow-dirty` flag on `colleague work`/`drive` and `colleague session` to opt into running against a dirty working tree.

### Fixed

- Dirty-tree guard (#149): a bare `colleague work`/`drive`/`session` against a repo with uncommitted *tracked* changes now refuses up front instead of silently sweeping those edits onto the work branch. The check is tracked-changes-only (pre-existing untracked WIP is already protected by the handoff baseline); pass `--allow-dirty` to opt in. The `ask-colleague` skill propagates `--allow-dirty` through to the runtime.

## [0.37.0] - 2026-06-05

### Changed

- **Renamed the core operation `drive` → `work`** — the last car-themed term, now
  aligned with colleague's work-partner framing. The CLI verb is **`colleague work`**;
  the run/record noun is a **"work item"** (`WorkStats`, `WorkItem`, `WorkStep`,
  `WorkSummary`, `WorkAborted`, `execute_work`, `_work_loop`). `Engine.drive()` →
  **`Engine.work()`** (every backend). Back-compat: **`colleague drive` is a deprecated
  alias** (still resolves; `--help` row labelled deprecated), so existing invocations,
  scripts, and the `ask-colleague` wrapper keep working. `colleague explain drive`
  still resolves. Reflected in `colleague learn`, `colleague explain`, and all docs.
- `Engine.drive()` → **`Engine.work()`** carries a **back-compat bridge** for
  out-of-tree plugins: a legacy backend that still implements `drive()` (not
  `work()`) is bridged automatically (`Engine.__init_subclass__` aliases its
  `work` to `drive` with a `DeprecationWarning`), and the base `Engine.drive()`
  delegates to `work()` so callers using the old method name still work — so a
  pre-rename plugin keeps instantiating and running via `registry.load`.
- The `feedback` "last" pointer file is now `.colleague/last_work`; the legacy
  `.colleague/last_drive` is still **read** as a fallback (old repos resolve `last`).
- TUI/TAUI: the cockpit `Drive` snapshot class → `WorkItem`; the snapshot JSON key
  `"drive"` → `"work"` and the Markdown section `## Drive` → `## Work`; the trace event
  type `"drive_step"` → `"work_step"`. Old snapshots/traces (carrying `"drive"` /
  `"drive_step"`) are still **read** (back-compat fallbacks), so `tui replay`/`diagnose`
  on pre-rename artifacts keep working.

### Breaking

- **OTel span/metric renamed** `colleague.drive` → `colleague.work` and
  `colleague.drive.duration` → `colleague.work.duration`. A span name cannot be
  aliased transparently, so existing dashboards/queries on `colleague.drive` must be
  updated.
- **`whoami` / `overview` JSON keys renamed** `drive_engine`/`drive_model` →
  `work_engine`/`work_model` (text labels: "work engine:" / "work model:"). Consumers
  parsing these keys must update.

## [0.36.0] - 2026-06-05

### Changed

- **Renamed the first-party `outsource` skill to `ask-colleague`** — a peer-framed name (you *ask a colleague*; you don't *outsource* to a vendor) that fits colleague as a daily work partner and lowers the bar to reach for it. The four verbs are unchanged: `ask-colleague explore | review | write | feedback`. Back-compat: the "outsource this" trigger phrase still fires the skill, and `colleague explain outsource` still resolves. The wrapper is now `.claude/skills/ask-colleague/scripts/ask-colleague.sh`; the feature doc is `docs/features/ask-colleague.md`. Reflected in `colleague learn` and `colleague explain`.
- **Renamed the `wheels` CLI noun to `backends`** (`colleague backends list | overview`) — retiring the old *convertible*-era car-themed name in favour of colleague's "one runtime, many minds" vocabulary. `wheels` is kept as a **deprecated alias** (it still resolves; its `--help` row is labelled deprecated, and `colleague explain wheels` resolves to the `backends` entry). `registry.WheelInfo` → `registry.BackendInfo`.

### Removed

- Retired the trucking-themed `convoy` alias for `colleague explain subagent` (the `subagent` / `subagents` names are unchanged).

## [0.35.2] - 2026-06-05

### Fixed

- Bare `colleague drive` now echoes a `grade: colleague feedback record <task_id> --rating N` hint in its result block (#144) — the ROI-loop nudge was previously emitted only by the `outsource` wrapper. The placeholder is shell-safe (`N`, not `<1-5>`) so the line is copy-pasteable; JSON output is unaffected.
- `colleague feedback record` now emits a stderr advisory when no identity resolves (no `--by`, no `culture.yaml` nick / `.colleague/identity.json`), instead of silently leaving `by` empty (rendered as `(unknown)` in text) (#145). The record still writes; `--json` stdout is untouched.

## [0.35.1] - 2026-06-05

### Added

- docs/cli-experience-evaluation.md — a hands-on, live-rig evaluation of the agent-facing CLI/DX experience (companion to the TUI-rendering evaluation).

### Fixed

- `overview` Identity now mirrors `whoami` — it surfaces the live-resolved `drive engine` + `drive model` instead of a bare `model:` (the mesh model, often `unknown`) that silently disagreed with `whoami`.

## [0.35.0] - 2026-06-05

### Added

- TaskResult.stopped_without_finish — flags a drive that ended on a no-tool-call turn without ever calling finish (colleague#142); serialized in the artifact and surfaced by the outsource wrapper

### Fixed

- Loop no longer treats a no-tool-call turn as a clean finish: it nudges the model once to call finish (recovering the common mid-task trail-off), and a stubborn stop is flagged via stopped_without_finish instead of silently returning trailing narration as an authoritative result (colleague#142)

## [0.34.2] - 2026-06-05

### Added

- tools/tui_sim: deterministic asciinema .cast simulations of the TUI (palette + slash autocomplete, drive cockpit, skill/error popups, full end-to-end ride) built from the real pure render seams — dev-only, zero new runtime deps
- docs/tui-experience-evaluation.md: a frame-by-frame human-experience evaluation of the TUI drawn from the recordings
- `_Session.__init__` gains an optional `user_home` (default `None` = current behavior) plumbed to `discover_commands`, so a caller can scope palette command discovery hermetically

### Fixed

- tools/tui_sim recordings are now hermetic: `build_session` pins `user_home` to the repo so a contributor's personal `~/.colleague/commands` can't leak into the palette and break byte-identical regeneration (PR #141 review)
- tools.tui_sim progress log moved to stderr, keeping stdout clean (agent-first results/diagnostics separation)

## [0.34.1] - 2026-06-05

### Changed

- Live-testing ledger: field-audited the always-on DriveStats block against a real drive (drive a6c5f0c1fd13) — flipped the Drive stats row from partial to validated and added a re-checkable §0 procedure. bytes_written verified exact (101) against the committed file; tool_counts/step_count/files_changed mirror the live step trace; usage tokens verbatim. No code change; closes out epic #128.

## [0.34.0] - 2026-06-05

### Added

- `colleague feedback list` (and `outsource feedback list`) — list every recorded drive newest-first by request, status, and grade; the durable way to find a drive when the order is forgotten. Reads the authoritative task_id from each artifact's contents, so the filename scheme does not matter (#132).
- `feedback record last` / `feedback show last` now echo the resolved drive's id + request to stderr, so a `last` mis-resolve is never silent; every `outsource` drive digest prints `task:` and a copy-paste `grade:` hint (#132).
- Request-slugged artifact filenames (`<task_id>.<slug>.json`) and drive branches (`colleague/<task_id>-<slug>`) so a drive is recognisable in an `ls` / `git branch` listing; `colleague/slug.py` + `artifact.find_artifact`/`read_request` resolve both bare and slugged names (back-compat) (#132).

### Changed

- `last` is now writes-only across the outsource flow (#132): `outsource explore`/`review` preserve their artifact but no longer move the `last_drive` pointer (the skill's `_preserve_artifact` stopped writing it), so a read-only probe can never steal a grade meant for a consequential write. A probe is graded by its printed task_id or via `feedback list`. The skill now preserves the artifact by the basename the drive reports (robust to bare or slugged names).
- Refactored `feedback.list_drives` — extracted `_load_drive_artifact` / `_drive_rating` / `_drive_summary` helpers to cut its cognitive complexity from 27 to ~12 (SonarCloud ≤15), with no behavior change (PR #139 review).

### Fixed

- Early-failure drives keep their request (PR #139 qodo): `failed_result` now records `stats.request` + `started_at` when given the instruction, and `execute_drive` passes `task.instruction` on the no-partial path — so an artifact written before the loop runs is still slugged, discoverable-by-request, and sortable in `feedback list` instead of a blank row.
- `outsource`'s `print_result` grade hint no longer requires `status == ok` (PR #139 qodo): a failed-but-gradable drive (colleague writes an artifact on failure, and a failure rated 1/5 is the ROI signal) now emits the copy-paste `grade:` command on the failure digest (stderr).

## [0.33.9] - 2026-06-05

### Added

- Live-validation test `tests/test_vllm_live_context_budget.py` (gated by `COLLEAGUE_VLLM_E2E`) proving context-overflow graceful degradation end-to-end against a real served model: proactive history windowing (a small budget + a chained read task drops oldest turns and inserts the placeholder in real model requests) and reactive trim+retry recovery (an induced overflow shrinks the budget and the retry recovers against the live model) (#127).

### Changed

- Live-testing ledger (`docs/live-testing.md`) row 7 (Context-overflow graceful degradation) marked validated with the §7 result block (proactive drive `36b022abc7f0`, reactive drive `0323db53b1dd`); every matrix row + epic #128 is now validated live.

## [0.33.8] - 2026-06-05

### Added

- End-to-end telemetry validation through the production `execute_drive` path: `tests/test_telemetry_e2e.py` (engine-agnostic, runs in CI when the `[otel]` extra is installed) asserts the full root + per-tool + handoff span tree (nested in one trace) and all metrics, and covers the previously-untested `colleague.handoff` span, `colleague.drive.duration`, and `colleague.hook.denials`. `tests/test_vllm_live_telemetry.py` (gated by `COLLEAGUE_VLLM_E2E`) adds a live-model composition stamp (#126).

### Changed

- Live-testing ledger (`docs/live-testing.md`) row 6 (Telemetry end-to-end) marked validated with the §6 result block (live drives `eff14af763d4`, `02c811085cb6`).

## [0.33.7] - 2026-06-05

### Added

- Live-validation test `tests/test_vllm_live_neighbours.py` (gated by `COLLEAGUE_VLLM_E2E`) proving operator-configured neighbour read-only clones fire end-to-end against a real served model: clone-on-start + read, cleanup-on-finish, and gitignored (#125).

### Changed

- Live-testing ledger (`docs/live-testing.md`) row 5 (Neighbours read-only clones) marked validated with the §5 result block (drives `711505cb4c3f`, `09d31abcf160`).

## [0.33.6] - 2026-06-05

### Added

- docs/live-testing.md §4 marked ✅: loop tools `culture` + `devague` validated live (#124). 4a — drive `2395f7d5d9b9` called `culture(cli='devex', args=['--version'])` and it shelled out (`exit=0`, identity injected). 4b — drive `80cb15c5f9cd` called `devague` `new` + `status` (both `exit=0`; `new` wrote only a self-contained `.devague/`), and the model declared a `destination` on finish as a live bonus. Allow-lists / `confirm`/`reject`/`export` exclusions / identity injection / destination-in-artifact stay DETERMINISTIC (schema `enum` makes a forbidden value unreachable live) — cited, not re-proven.
- tests/test_vllm_live_loop_tools.py — gated (`COLLEAGUE_VLLM_E2E=1`) live proof that a real model reaches the `culture` + `devague` tools and they shell out to the operator-installed CLIs; tasks constrained to zero-side-effect subcommands.

### Changed

- `_DEFAULT_SYSTEM` (colleague/loop.py) now names the `culture` tool and its `agtag`/`devex` CLIs — the same #122-style gap (an unnamed loop tool is invisible to the live model). Advisory, runtime-owned (all-engines). Pinned by `tests/test_destination_loop.py::test_default_system_advertises_culture_tools`.

## [0.33.5] - 2026-06-04

### Added

- docs/live-testing.md §3 marked ✅: gated configs enforcement validated (#123). 3a/3c/3d proven LIVE against the reference rig (drives `324819918d83`/`21dff9b0fb93` run_command deny/allow, `a30324e89aa3`/`23fa581fc19a` hook deny/rewrite, `5a590ffb360f` per-model overlay); 3b (checksum-void + command-expand-refused) and 3e (per-model AGENTS/skills composition) proven DETERMINISTICALLY (engine-agnostic — a live model adds no signal).
- tests/test_vllm_live_gated_configs.py — gated (`COLLEAGUE_VLLM_E2E=1`) live proof that a real model's run_command/write_file call hits the approval gate / pre_tool hooks, and that the per-model hooks overlay loads via `load_hooks(model=config.model)`.
- tests/test_gated_configs_enforcement.py — fast deterministic proof of 3b (checksum drift voids a hook approval → skipped; a drifted command template is refused at expand time) and 3e (`system_prompt_for` folds per-model AGENTS/skills into the prompt; a sibling model sees neither). All config lives in throwaway tmp_path — the repo still ships none.

## [0.33.4] - 2026-06-04

### Added

- docs/live-testing.md §2 marked ✅: subagents validated live (#122). Live drive `6c27147eb917` against the reference rig delegated via the parallel `subagents` tool (`COLLEAGUE_SUBAGENT_CONCURRENCY=2`) — two children in isolated `sub/<id>` worktrees, a merge child integrated both branches cleanly, worktrees torn down, `sub_results` folded into the artifact.
- tests/test_vllm_live_subagents.py — gated (`COLLEAGUE_VLLM_E2E=1`) end-to-end proof that a real model reaches the `subagents` tool and the worktree create→merge→cleanup lifecycle runs; asserts on structural facts (`sub_results` populated, worktrees cleaned) robust to model-text variance.

### Changed

- `_DEFAULT_SYSTEM` subagents guidance (colleague/loop.py) now names the parallel `subagents` batch tool and its isolated-worktree/merge-child/conflict-surfacing nature, and invites delegation on naturally-parallel multi-file tasks — it previously described only the singular `subagent` and called delegation "sequential", leaving the live model unaware the batch tool existed (#122). Runtime-owned, so both bundled backends inherit it (all-engines rule). Honest caveat recorded in the ledger: the live model delegates when explicitly invited but not yet spontaneously on a purely implicit task.

## [0.33.3] - 2026-06-04

### Added

- docs/live-testing.md §1 marked ✅: outsource write validated live (#121) — 3 consecutive write --apply + 1 write --pr drive, each diff-verified.
- Lock-in tests that the write prompt leads with the task (descriptive commit subject) and asks for lint-clean edits (tests/test_outsource_skill.py).

### Changed

- outsource write prompt (.claude/skills/outsource/prompts/write.md) now leads with $ARGUMENTS so the drive commit subject / PR title describes the change instead of the boilerplate preamble, and adds a lint-clean rule (max line length + one trailing newline) to curb W292/E501 in whole-file rewrites (#121).
- Added docstrings to ToolExecutor.execute, subagents.spawn/batch_spawn, and VllmOpenAIEngine.drive (the real micro-improvements produced by the write validation drives).

## [0.33.2] - 2026-06-04

### Added

- docs/live-testing.md — live-testing ledger tracking end-to-end validation against a real served model (the layer the unit suite cannot reach: tools the model must choose to invoke + config surfaces that must be present to fire), with a per-feature commit+date staleness stamp. Wired to tracking epic #128 and per-item issues #121-#127.

## [0.33.1] - 2026-06-04

### Added

- Test coverage for `doctor --probe` model-availability gaps: the happy-path match (info/passed), an empty/no-id served set (warning naming "(none)"), an unparseable /models body (verdict omitted, reachability still passes), and partial config (probe targets the resolved {base_url}/models, default model still compared).
- CLI-wrapper tests crossing the `cmd_doctor -> diagnose(probe=...)` seam: `doctor --probe` runs the reachability check and a bare `doctor` omits it (opt-in contract).

## [0.33.0] - 2026-06-04

### Added

- colleague learn --json now carries structured work_with (outsource verbs + drive contract) and teach_with_skills (what skills/AGENTS files to author) blocks for collaborating agents

### Changed

- colleague learn reoriented for agents that work WITH colleague: foregrounds outsource explore/review/write/feedback, the drive contract, the ROI loop, and what skills to create; dropped the clone-the-template framing. Root explain entry and CLI description now lead with the swappable coder-agent harness identity to match

### Fixed

- colleague learn now states that the per-model overlay `<model>` token is the *filename-safe* model id (slashes collapse to dashes, e.g. `Qwen/Qwen3-32B` -> `Qwen-Qwen3-32B`), in both the text and `--json` (`teach_with_skills.model_placeholder`) — following the old wording verbatim would have created a literal `.colleague/<org>/<model>/` overlay that never loads (Qodo review)

## [0.32.2] - 2026-06-04

### Added

- pty-driven regression tests that drive the session raw-mode autocomplete loop (`_raw_loop`) end-to-end over an explicit `os.openpty()` pair, using the production slash-command catalog, autofilter, and popup widget — TAB-complete, free-text submit, arrow select, arg-hint trailing space, backspace edit, Ctrl-C/Ctrl-D quit

### Changed

- Removed the now-stale `# pragma: no cover` on `_raw_loop` (it is genuinely covered by the new pty tests) and corrected the comments in `_session_input.py` / `test_session_autocomplete.py` that claimed the raw loop could not be pty-tested under pytest fd capture

## [0.32.1] - 2026-06-04

### Changed

- CI: bump SonarSource/sonarqube-scan-action v6 -> v8.1.0 (node24 runtime, scanner GPG signature verification). Note: the intermittent 403 from binaries.sonarsource.com is a SonarSource CDN flake and is unaffected by the action version; re-run the job if it recurs.

## [0.32.0] - 2026-06-04

### Added

- colleague session: live `/` autocomplete popup on a colour TTY — autofilters slash commands as you type, restores on delete, vanishes on no-match; Tab/Enter completes, arrows select, Esc dismisses. Stdlib raw-mode reader (termios/tty/select) with a plain-input() fallback so piped/--json/--no-tui/Windows/agent paths stay byte-identical. Zero new runtime deps.

### Changed

- Slash commands now come from a single `SlashSpec` catalog that also derives the `/help` text (drift-tested), so help and the popup cannot diverge.

## [0.31.0] - 2026-06-03

### Added

- Escalation (#106): when a drive cannot withstand a request — DriveAborted (timeout/context-overflow/engine error) or step-budget exhaustion — colleague can open ONE tracked agtag continuation issue carrying a 5-section record (continuation / remaining / what's-needed / suggested split / why). Opt-in via COLLEAGUE_ESCALATE (default off), offline/CI-safe, skipped in linked worktrees, approval-gated, idempotent per task_id; best-effort and observe-only (never masks the drive result). docs/features/escalation.md.
- TaskResult.not_finished (#106): explicit flag set from the drive-loop return value — True iff the step budget was exhausted without calling finish (not via DriveAborted) — replacing the unreliable step_count heuristic for not-finished detection.

## [0.30.0] - 2026-06-03

### Added

- NO_RESULT_PRODUCED contract sentinel — a stable, programmatic signal a caller branches on when a drive produced no output (#109)

### Changed

- A no-finish drive surfaces the model's last substantive assistant content (tracked on every turn, including tool-call turns) as result.summary instead of a content-free 'completed in N step(s)'; the 'stopped at the N-step budget' summary string is removed (budget is inferrable from stats.step_count) (#109)

### Fixed

- drive/outsource results no longer read as empty-looking successes when the model does not call finish — the produced content is surfaced in the result, not buried in the artifact JSON (#109)

## [0.29.13] - 2026-06-03

### Added

- Spec + plan: result fidelity — a no-finish drive surfaces the model's last substantive content (and an explicit empty marker when none) instead of a content-free step count (#109)

## [0.29.12] - 2026-06-03

### Added

- Operator-driven audit fan-out recipe (docs/features/audit-fanout.md): split a too-large doc-review into per-surface scoped drives via assign-to-workforce and synthesize one ranked report (#107)

### Changed

- doc-review command template instructs single-surface-only coverage when given a scope argument (names out-of-scope surfaces), making it fan-out-ready (#107)

## [0.29.11] - 2026-06-03

### Added

- Spec + plan: fan out a large read-only audit across scoped drives — operator-driven (assign-to-workforce); in-drive subagents text-aggregation deferred (issue #107)
- Spec + plan: escalate via agtag when a drive cannot withstand a request — runtime-auto finalize hook, opt-in + offline/CI + approval-gated + idempotent, 5-section continuation contract; build gated on #109 (issue #106)

## [0.29.10] - 2026-06-03

### Fixed

- `doc-review` command template now enforces **finish discipline** (mirroring the proven `review.md`/`explore.md` fixes): it explicitly requires calling the `finish` tool with the itemized report and warns that ending without `finish` returns nothing. Found by dogfooding (#104): a full-repo audit read 18 files then ended with a 101-char non-report. Verified: a scoped audit now reaches `finish` with a real itemized findings list. Added a lightweight self-escalation seed — when the audit is too big to finish, report INCOMPLETE with what is covered, what remains, and a suggested split (the prompt-level seed of #106).
- Stale-doc fixes surfaced by that doc-review dogfood (each verified against the code): the `explain` `_SUBAGENT` entry no longer claims subagents are *"sequential only in v0"* / *"synchronous, no thread"* — parallel subagents shipped v0.29.0 (opt-in `COLLEAGUE_SUBAGENT_CONCURRENCY`, `concurrent.futures`, per-child `sub/<id>` worktrees, a merge child); and the README feature table now lists the two existing pages it omitted (`parallel-subagents.md`, `graceful-degradation.md`). (The audit also false-flagged the `MAX_SUBAGENT_*` constants as moved out of `config.py` — they are not; that finding was rejected on verification.)

## [0.29.9] - 2026-06-03

### Fixed

- `colleague tui snapshot` text output now lists **every** file it writes (the quad). It wrote four files — `.taui.json` / `.ansi` / `.events.jsonl` / `.md` — but the text stdout joined only `("taui", "ansi", "events")`, so the `.md` it had just written was invisible on stdout (the `--json` output already listed it). Text and JSON now agree. Found by exercising `tui snapshot`/`diagnose` for issue #99.
- Refreshed stale `tui` help/doc wording that still called the snapshot a *triple*: the `snapshot`/`diagnose` subcommand help, the `--name` help (was "Base name for the three files" → the four files taui/ansi/events/md), the `tui` module docstring, and the overview verb line. The `legacy triple` references in `tui/snapshot.py` / `tui/diagnose.py` are left intact — a pre-`.md` snapshot genuinely is a triple (back-compat).

## [0.29.8] - 2026-06-03

### Fixed

- `resolve_identity` (`colleague/identity.py`) now falls back to the first agent block's `suffix:` in `culture.yaml` when there is no top-level `nick:`. The canonical clone shape nests the nick as `agents:` → `- suffix: <nick>` (exactly what `colleague whoami` reads), but `resolve_identity` only read a top-level `nick:` and so returned `None` for the standard template — silently emptying both the `COLLEAGUE_IDENTITY` injected into every `culture`/`devague` subprocess (the mesh-member identity propagation) and the `feedback record` `by` default (which `--by` help promised resolves to the identity). The two identity paths now agree; found by exercising the `feedback` ROI loop and seeing `by: (unknown)` despite `whoami` reporting `colleague`. (Per PR #100 review: `resolve_identity` now reads `culture.yaml` at most **once** per call — the `nick:` and `suffix:` scans share a single read buffer instead of re-opening the file on the canonical no-`nick:` path.)

## [0.29.7] - 2026-06-03

### Fixed

- `run_command` tool description now states the fact a small model trips on: each call runs in a FRESH shell with cwd already at the repo root, so `cd` and environment changes do NOT persist between calls — use repo-relative paths, never `cd`. This is the systemic root-cause fix for the thrash that made `outsource review` burn its whole step budget on `cd`/`pwd`/`which` churn; correcting it once at the tool level means every verb and every backend inherits it (all-engines rule), not just the one prompt that was patched.
- `outsource explore` prompt (`explore.md`) brought to parity with the hardened `review.md`: a report that never calls `finish` returns NOTHING, so finish early; and don't repeat near-identical searches — once a search points at the relevant file, read it. A live explore had been calling `finish` on step 19/20 after several duplicate `rg` searches, one redundant search away from the same empty-result failure.

## [0.29.6] - 2026-06-03

### Changed

- `whoami` now reports the live *drive identity* — the `drive_engine` a bare drive would pick (`--engine` > `COLLEAGUE_ENGINE` > default `vllm-openai`) and the `drive_model` it would call — alongside the `culture.yaml` mesh backend. The cheapest probe an agent runs before delegating now names the actual delegate instead of an unrelated persona backend (text relabels `backend:` → `mesh backend:` and replaces the meaningless persona `model:` line with `drive engine:`/`drive model:`; JSON keeps the `backend`/`model` keys and adds `drive_engine`/`drive_model`). `drive_model` is `null` for the no-op `mock` engine, which calls no model.
- The first-party `outsource` skill now encodes a **proactive delegate reflex**: its description and a new `SKILL.md` section give a sharp GO/NO-GO rule for reaching out *unprompted* (default the read-only `review`/`explore` verbs — zero side effects), with guardrails (one-glance readiness via the new `whoami` drive identity; output is a second opinion to verify, not authority; close the loop with `feedback`). Side-effecting `write --apply`/`--pr` still requires a user go-ahead. Docs mirrored in `docs/features/outsource.md`. Skill-only change; no runtime code touched.

### Fixed

- Brought every self-describing surface in line with the new `whoami` output: `learn` (command map + JSON summary), `overview`, the top-level `colleague` `explain` catalog entry, and `docs/features/agent-cli.md` no longer claim `whoami` reports only `culture.yaml` identity — they now describe the mesh identity **plus** the live drive engine/model. (No first-party surface contradicts another.)

## [0.29.5] - 2026-06-03

### Added

- docs: converged spec for model-tailored runtime surfaces (the model-profile layer) — a per-model `.colleague/<model>/profile.json` tailoring tool aliases/availability/descriptions, default-limit hints, and a terminal system-prompt overlay, keyed by `sanitize_model(config.model)` and overriding a shipped package default, while keeping the `Task`→`TaskResult` contract, the artifact (canonical tool names), and the all-engines/zero-deps conventions stable (#89).

## [0.29.4] - 2026-06-03

### Changed

- The `run_command` neighbour-clone guard is now token-aware: it `shlex`-splits the command and refuses only a token that resolves to the clone root (`.colleague/neighbours`) or under it, instead of a raw whole-string substring match — so a benign command that merely *mentions* the path inside a quoted string (e.g. `echo "see .colleague/neighbours"`) is no longer a false positive. Unparseable commands (shlex ValueError) fall back to the stricter substring check, so a malformed command never slips through. Still a best-effort policy gate, not a sandbox (bypassable by `sh -c`, pipelines, shell expansion) (#92).

## [0.29.3] - 2026-06-03

### Changed

- Added direct test coverage for the neighbours `_dest_for` path-traversal guard (malicious/typo names: separators, dot/dotdot, absolute, empty) — previously only exercised indirectly (#92).

### Fixed

- `run_command` now maps **any** subprocess failure to a recoverable `ToolError` instead of aborting the whole drive: a hung command (`subprocess.TimeoutExpired`), a launch failure (`OSError`), or any other error (e.g. `ValueError` on an embedded NUL byte in a model-issued command) is fed back to the model as a non-ok step so the drive continues — matching the `_subagent`/`_subagents` catch-all and the culture/devague/hooks subprocess handling (all-engines rule). `KeyboardInterrupt` still propagates. The 300s budget is now the named `_COMMAND_TIMEOUT_SECONDS` constant (#92).

## [0.29.2] - 2026-06-03

### Changed

- README "Subagents" section rewritten to match the shipped v0.29.0 parallel-subagents behavior (COLLEAGUE_SUBAGENT_CONCURRENCY, the subagents batch tool, per-child `sub/<id>` worktrees, the sequential merge-subagent); it had still described v0 as sequential-only (#92).

### Fixed

- outsource skill default model was stale (mmangkad/Qwen3.6-27B-NVFP4) and no longer matched config._DEFAULT_MODEL or the live rig; aligned the skill script, SKILL.md, docs/features/outsource.md, and the skill test to the served sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP so a bare-default `outsource explore` no longer 404s the rig (#92).
- vLLM engine now raises a legible ConnectionError naming the endpoint when the server is unreachable (urllib URLError: connection refused / DNS / server down), instead of letting the loop surface a cryptic bare `URLError: <urlopen error [Errno 111] Connection refused>`; mirrors the graceful URLError handling already in _tokenize_count, with a regression test (#92).

## [0.29.1] - 2026-06-03

### Changed

- Docs/terminology: replaced the car metaphor with standard agent/runtime vocabulary across README, docs/features/*, CLI help text, docstrings, the explain catalog, and CLAUDE.md (engine→backend, driver→adapter, chassis→runtime, wheels→plugins, garage→registry, dashboard→run report, GPS→telemetry, oilcheck→health check, convoy→subagents, gearbox→router/routing policy). New framing: "One runtime, many minds." No CLI verb/flag, module, or test changes; --engine, wheels/doctor/telemetry/drive, colleague.engines, colleague/oilcheck/, and the all-engines rule name are unchanged (#88).

## [0.29.0] - 2026-06-03

### Added

- Parallel subagents: a new `subagents` (plural) loop tool fans out a batch of child drives that run concurrently via a ThreadPoolExecutor confined to `colleague/subagents.py`, each child isolated in its own throwaway git worktree on a `sub/<id>` branch, integrated afterward by a sequential merge-subagent that surfaces (never force-merges or drops) unresolvable conflicts.
- Opt-in concurrency-width knob `COLLEAGUE_SUBAGENT_CONCURRENCY` (on `EngineConfig`, default 1 = byte-identical to the prior sequential path), bounded by `MAX_SUBAGENT_FANOUT=4` (<=3 parallel workers + 1 merge child) and `MAX_SUBAGENT_DEPTH=2`.
- `colleague/worktrees.py`: per-child git worktree + branch lifecycle with idempotent teardown (zero new runtime deps; concurrent.futures and subprocess are stdlib).

### Changed

- Threads (`concurrent.futures`) are sanctioned in exactly one module (`colleague/subagents.py`) via a new thread-confinement check in `tests/test_boundary.py`; forbidden in every other colleague module. `colleague/worktrees.py` is added to the subprocess allow-list.
- The single-child `subagent` tool, the `mock`/`vllm-openai` engines, and the result/artifact shape are unchanged; the new `subagents` tool is wired through both engines (all-engines rule). Documented in CLAUDE.md and a new `docs/features/parallel-subagents.md`.

### Fixed

- Review hardening (PR #90): a CONFLICTED child's `sub/<id>` branch is now RETAINED on teardown (was force-deleted), so its committed work survives for manual integration as the merge child's summary promises. `teardown_all` is scoped to worktrees under `.colleague/worktrees/` and no longer sweeps every `sub/*` branch (could delete unrelated user branches). `worktree_add` no longer writes the shared `.gitignore` (a thread-race that dirtied the working tree during the parallel phase; `/.colleague/*` is already ignored). Nested batches are forbidden in v0: a child drive's `subagent_batch_spawn` is nulled so it can't run a batch against the parent's worktree/depth.

## [0.28.0] - 2026-06-03

### Added

- Configurable per-tool-result output cap: COLLEAGUE_MAX_OUTPUT_CHARS (EngineConfig.max_output_chars, default 100000), raised from the old hardcoded 20000 so a large read_file/run_command result is not truncated inside the bigger context window. Threaded through the loop and forwarded by every engine (all-engines rule).

### Changed

- Context budget default raised 24000 -> 192000 tokens and drive step budget default 25 -> 40, sized for the upgraded 256k (262144-token) vLLM reference rig (model-gear). Override per environment with COLLEAGUE_CONTEXT_BUDGET / COLLEAGUE_MAX_STEPS.

## [0.27.2] - 2026-06-03

### Changed

- session cockpit (ANSI) now fills the terminal width instead of fixed narrow boxes — all panels and frame separators derive from one detected width and align; threaded a width kwarg through render() and every box widget, with a deterministic default (80) for headless/snapshot callers and shutil.get_terminal_size() for the interactive session + live driver
- session prompt is now a clean "colleague ❯" chevron (dropped the meaningless [planning] mode label), with the typing cursor anchored to the prompt via input()

### Fixed

- slash-command output (e.g. /help) no longer mangles mid-word in the conversation panel — the box wraps at the full width instead of 46 chars
- ANSI render no longer overflows the requested width on a narrow terminal (41–71 cols) when both the skills and conversation panels are visible — the side-by-side layout is guarded and falls back to stacking the panels full-width below the column threshold
- box widgets clamp their derived inner widths to a positive minimum, so a pathologically small `width` can no longer raise on a negative field width or spin the wrap loop forever

## [0.27.1] - 2026-06-03

### Fixed

- Stop tracking `.devex/data/pr/events.jsonl` — a per-machine devex PR event log that was committed by mistake. Untracked (kept on disk) and added `/.devex/data/` to `.gitignore` so `devex pr` runs no longer dirty the working tree.

## [0.27.0] - 2026-06-02

### Added

- Deprecated back-compat fallbacks for the rename (read-only): the legacy `.convertible/` config + artifact directories are still read (new writes always target `.colleague/`), `CONVERTIBLE_*` environment variables are honored as a fallback (`COLLEAGUE_*` takes precedence), and `identity_env` emits BOTH `COLLEAGUE_IDENTITY` and `CONVERTIBLE_IDENTITY` so sibling AgentCulture CLIs keep inheriting the identity.

### Changed

- **Renamed the project from `convertible` to `colleague`.** The import package is now `colleague`, the CLI ships as two console scripts (`colleague` and its short alias `clg`), and the PyPI distribution is `colleague` (no longer `convertible-cli`).
- Config directory is now `.colleague/` and the environment variables are `COLLEAGUE_*` (e.g. `COLLEAGUE_ENGINE`, `COLLEAGUE_MODEL`, `COLLEAGUE_OTEL_ENABLED`, `COLLEAGUE_IDENTITY`, `COLLEAGUE_VLLM_E2E`).
- Engine/renderer entry-point groups are now `colleague.engines` / `colleague.renderers`; OpenTelemetry service/tracer/meter names and span/metric names are now `colleague.*`.
- pyproject URLs point at `github.com/agentculture/colleague`; SonarCloud `sonar.sources` is now `colleague` and `sonar.projectKey` is now `agentculture_colleague` (the SonarCloud project must be re-keyed externally to match, or coverage uploads 404).

## [0.26.0] - 2026-06-02

### Added

- doc-test-alignment skill is now implemented (issue #76 C3), replacing the stub check.sh: a portable, stdlib-only verifier with four checks behind `scripts/check.sh [--only readme|claude|skills|tests] [--repo PATH] [--json]` (exit 0 aligned / 1 drift / 2 usage). (c) SKILL.md script-claims-vs-scripts is deterministic and GATES CI; (a) README + (b) CLAUDE.md commands run safe networkless introspection and statically validate networked/drive commands against `convertible --help` (never executing them); (d) test-name-vs-assertion drift is an advisory AST heuristic with inline/file suppression. JSON shape mirrors doctor: {aligned, checks[{id,passed,severity,message,remediation}]}.
- CI now gates on doc-test-alignment check (c) (deterministic) and runs (a)/(b)/(d) as advisory (non-blocking) in the lint job.

### Changed

- docs/skill-sources.md records doc-test-alignment as a first-party implementation diverged from the guildmaster stub (do not re-vendor over it; upstreaming is a follow-up).

## [0.25.0] - 2026-06-02

### Added

- Context-budget graceful degradation in the bounded tool-loop: the running message history is windowed to a configurable token budget (CONVERTIBLE_CONTEXT_BUDGET / EngineConfig.context_budget_tokens, default 24000) before each model turn, and a detected context-overflow error triggers a bounded trim-and-retry before a readable partial result is preserved — a multi-file drive on a small-context model degrades instead of hard-failing (#76 C1).
- Pluggable count_tokens seam (convertible/context.py): the vLLM engine counts tokens exactly via the server /tokenize endpoint, falling back to a zero-dep char heuristic when /tokenize is absent — no third-party tokenizer library, dependencies = [] holds.
- docs/features/graceful-degradation.md documenting the behavior, the /tokenize OpenAI-surface carve-out, and the honest limits.

### Changed

- convertible drive --json now emits the preserved partial TaskResult to stdout on the failure/overflow path (still exiting non-zero, diagnostics on stderr) so a --json consumer gets a parseable result instead of empty stdout (fixes the #76 "convertible produced no result on stdout" symptom).

### Fixed

- A context-window overflow on a small-context model no longer surfaces as an opaque "no result on stdout"; the loop windows + retries, and any unrecoverable drive returns a status=error result with a non-empty step trace.

## [0.24.0] - 2026-06-02

### Added

- Interactive cockpit session (#74 A2): `convertible session` is rebuilt onto the TAUI cockpit. It renders one `CockpitState` (command palette + conversation + popups) through three tiers chosen automatically — the dynamic ANSI cockpit on a colour TTY (redraw-in-place, error popups on failed steps), static **Markdown** menus when piped/captured (`--no-tui` forces it), and `--json` keeping stdout as pure result JSON with the cockpit as stderr chrome.
- Session slash commands (akin to Claude Code / Codex): read-only introspection that folds an existing noun's output into the cockpit (`/help`, `/commands`, `/skills`, `/agents`, `/config`, `/engines`, `/telemetry`, `/feedback`) and live config actions that mutate the session without a restart (`/engine`, `/model`, `/base`, `/pr`). Plain text (number / template name / free-text) still runs a drive.
- A `command_palette` cockpit widget (`convertible/tui/widgets/command_palette.py`) renders a `commands` panel as a numbered menu (ANSI); the Markdown/TAUI views pick it up via generic panel rendering.

### Changed

- `convertible session` non-interactive output is now the full Markdown cockpit (was a terse numbered list); `--json` stdout is unchanged (one `TaskResult` JSON per drive).
- `execute_drive` accepts an optional `progress_sink` so the session injects a sink bound to its own cockpit state (default `None` keeps the `drive` path byte-identical); the live drive frame-writer is factored into a shared `FrameWriter`.

## [0.23.0] - 2026-06-02

### Added

- Live cockpit during a drive (#74 A1): `convertible drive` renders the TAUI cockpit on stderr as it runs — conversation per step and popups on real events (an `error` popup when a tool step fails). Auto-on an interactive TTY; `--tui` / `--no-tui` force it; off a TTY it falls back to the plain `step N:` lines, byte-identical.
- Live `DriveStep` event stream (#74 A3): `drive --tui-events PATH` appends one JSONL event per step as the drive runs (the format `tui replay` / `tui snapshot` consume); a stream written into the driven repo is treated as harness telemetry, never swept into the drive branch.
- `tui replay --trace <id>.trace.jsonl` (#74 A4): fold a finished drive's loop-step trace into the cockpit. Live and replayed steps read identically — one shared converter (`convertible/tui/from_drive.py`) and the same pure reducer.
- NO_COLOR / TTY-aware color gating helpers (`convertible/tui/colors.py`, #74 A5): the live cockpit strips ANSI escapes when `NO_COLOR` is set or the stream is not a terminal.

### Changed

- A failed `DriveStep` now opens an `error` popup in the pure reducer (so it surfaces identically live, in `tui replay`, and in `tui replay --trace`).
- The ANSI conversation widget now renders the reducer-produced `panel.conversation` and accepts a multi-line per-step summary, so a live drive shows its steps.

## [0.22.0] - 2026-06-02

### Added

- outsource explore/review now copy their artifact (plus a last_drive pointer) back to the real repo before the throwaway worktree is removed, so a read-only outsourced drive can be graded with `outsource feedback last` / `convertible feedback record last` (#75 C4).
- Command-template recipes can be committed in-repo: `.convertible/commands/` is no longer gitignored (run artifacts, hooks.json, approvals.json stay local), with a committed `doc-review` example recipe (#75 C5).
- Reverse-coverage test: every registered CLI verb must have an `explain` catalog entry and every action-noun must expose `overview` (#75 D1).

### Changed

- `convertible drive` now returns you to the branch (or detached commit) you started on after it commits — the `convertible/<id>` drive branch keeps the commit, but a drive no longer strands you on it (all commit paths, incl. `--no-pr` and `session`) (#75 C2). Side effect: successive `session` drives now branch independently from your base rather than chaining on the previous drive.

### Fixed

- The read-only outsource artifact-preservation path (#75 C4) now validates the drive `task_id` as a single safe path segment before joining it into a copy destination (mirroring `convertible/feedback.py`), so a malformed/hostile TaskResult can no longer escape `.convertible/`; and it only reports the preserved real-repo path (and writes `last_drive`) when the copy actually succeeds, never claiming an artifact that isn't there.

## [0.21.1] - 2026-06-02

### Added

- docs/features/subagents.md — the missing feature page for the subagent/convoy loop tool; added to the README feature table and the docs/features index.
- README sections for the tui cockpit, the drive-stats/feedback ROI loop, subagents (convoy), and an outsource narrative (all shipped features that the README narrative omitted).

### Changed

- README: corrected the stale Qwen3-32B reference to the current default model sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP; documented doctor --probe (provider_reachable + provider_model_available); added a CHANGELOG pointer and the missing model-selection/tui/stats-and-feedback feature-table rows. Docs-only — no behavior change (#73, umbrella #72).

## [0.21.0] - 2026-06-01

### Added

- `convertible tui render --format ansi|markdown` — a Markdown render of the cockpit, the agent-facing readable third view beside the JSON (TAUI) mirror and the ANSI live screen; `--json` wraps the chosen format (`{"markdown": ...}`).
- `tui snapshot` now writes a quad — a 4th file `<name>.md` (the Markdown render) alongside `<name>.taui.json` / `<name>.ansi` / `<name>.events.jsonl`; legacy triples without a `.md` still read fine.
- `diagnose` now verifies the Markdown frame too — its RENDER faithfulness check runs against the Markdown when present, so `tui diagnose` on a quad proves the JSON mirror and the Markdown agree (zero findings = faithful; a finding = drift). Markdown and JSON are both pure functions of one `CockpitState`, so any disagreement is a render-fidelity bug, never a data divergence.

### Changed

- diagnose success message now reads "the captured views agree" (a snapshot is a quad, no longer a triple).

## [0.20.0] - 2026-06-01

### Added

- `tui` command — an agent-readable terminal UI (issue #69). Every visual frame has a TAUI (Textual Agentic UI) semantic mirror an agent can read, operate by stable dotted-path selector, snapshot, replay deterministically, and diagnose — no OCR or terminal guessing.
- TAUI semantic mirror (`convertible/tui/taui.py`, schema 0.1): the live sibling of the drive artifact, derived via `serialize(state)` from a canonical `CockpitState`; selectors are dotted paths into the tree (no second table to drift).
- Pure Elm-style core: `event -> reduce(state, event) -> State -> serialize()=TAUI + ANSI render`. The reducer is pure (no clock/randomness); animation advances only via injected `tick` events, so replays are byte-identical.
- Snapshot triple (`<name>.taui.json` + `.ansi` + `.events.jsonl`) + deterministic replay; `tui` headless subcommands `render`/`state`/`inspect`/`action`/`replay`/`snapshot`/`test`/`diagnose`/`overview`, all `--json`, plus a guarded `tui live` foreground TTY driver.
- `diagnose`: a pure stdlib cross-mirror differ that classifies 7 bug classes (state/render/layout/focus/input-routing/theme/popup-lifecycle) with no LLM and no network.
- Renderer-is-a-wheel: a hand-rolled stdlib ANSI renderer ships zero-deps as the default; Rich/Textual is an opt-in `[tui]` extra discovered via a new `convertible.renderers` entry-point group.
- JSON scenario runner (`tui test --scenario`) + bundled `boost-popup.scenario.json`; docs at `docs/features/tui.md`.

## [0.19.0] - 2026-06-01

### Added

- doctor --probe provider_model_available check: warns (advisory) when the configured model is not in the provider/v1/models list, naming both the configured id and the served ids with a remediation; omitted when the list cannot be enumerated
- vLLM engine _post_json now folds the HTTP error body into the raised HTTPError, so a wrong-model 404 reads "…model `X` does not exist" instead of a bare "HTTP Error 404: Not Found"

### Changed

- Built-in default model is now sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP (the model the reference rig serves at localhost:8001), so a bare drive reaches a live model instead of a 404; override with CONVERTIBLE_MODEL or --model

## [0.18.0] - 2026-05-31

### Added

- **Drive statistics + feedback loop (the ROI loop)** — calculate the ROI of outsourcing to convertible. Every drive artifact now carries an always-on `stats` block (`TaskResult.stats` / `DriveStats`): request, ISO start + wall-clock duration, model turns, step count, per-tool counts, files changed, exact UTF-8 `bytes_written`, and reasoning-vs-answer char/byte sizes. Populated chassis-side in `convertible/loop.py` so every engine fills it identically (all-engines rule).
- `convertible feedback record|show|overview` — grade a finished drive by `task_id` or `last` with a 1-5 rating + notes, stored as a single record per drive (`<task_id>.feedback.json`) beside the artifact via a stdlib JSON store (`convertible/feedback.py`). A per-repo `last_drive` pointer (written by `execute_drive`) resolves `last`. An ungraded drive reads back as a clean no-op, never an error.
- `outsource feedback <id|last>` skill verb — grade an outsourced drive (with `--rating`) or show its feedback (without), shelling to `convertible feedback`.
- vLLM engine now captures `message.reasoning` (the chain-of-thought, previously discarded) into `ModelResponse`, measured as reasoning chars/bytes in the stats.
- OpenTelemetry parity: two new metrics `convertible.generated.chars` (attr `kind`=reasoning|answer) and `convertible.bytes_written`, a strict no-op when telemetry is off.

### Changed

- Tokens stay verbatim from the model response `usage` (never estimated). Since the served model reports no reasoning-token breakdown, thought-vs-written is measured as chars/bytes, not tokens (no tokenizer, zero deps) — documented honestly.

## [0.17.0] - 2026-05-31

### Changed

- `outsource write` now **previews by default** (#61): without `--apply`/`--pr` it runs the change in a throwaway `git worktree` at HEAD, prints the would-be diff, and discards it — nothing touches your working tree. New `--apply` flag lands the change on a `convertible/<id>` drive branch in place; `--pr` implies `--apply`. The dirty-tree guard now applies only when actually applying.
- The git-repo guard now covers **every** `outsource` verb (previously only the read-only verbs): a non-repo `--repo` fails fast with a clear message instead of an opaque mid-drive error. `git -C`-style targeting is unchanged.

### Fixed

- outsource: `mktemp -d` is given an explicit template (`${TMPDIR:-/tmp}/outsource.XXXXXX`) so the read-only/preview worktree setup is portable on BSD/macOS mktemp (#61).
- outsource: `print_result` routes the result digest to **stderr** on a failed drive (status != ok), keeping stdout clean for scripting; it still exits non-zero (#61).
- outsource: `review` validates that `--base` resolves to a real commit/ref before interpolating it into the LLM review instruction — fails fast on a bogus/unknown ref (#61).
- outsource: `render_prompt` substitutes `$ARGUMENTS`/`$BASE` in a single `re.sub` pass, so a literal `$BASE` inside the user argument survives verbatim instead of being clobbered by a second replace pass (#61).

## [0.16.1] - 2026-05-31

### Added

- `docs/features/model-selection.md`: an operator guide for how convertible
  resolves the engine/model/endpoint (`--engine`/`--model`/`--base-url` → env
  (`CONVERTIBLE_*`, `OPENAI_*`) → defaults), the fact that there is **no model
  config file**, how to point `vllm-openai` at any OpenAI-compatible server, and
  a recipe to keep `CONVERTIBLE_MODEL` auto-synced to a locally-served model
  (generic `/v1/models` lookup, plus model-gear's `model whoami`). Notes that
  subagents inherit the parent model. Linked from `engines.md` and listed in the
  features index (`docs/features/README.md`). Docs only — no behavior change.

## [0.16.0] - 2026-05-30

### Added

- `outsource` skill (first-party, `.claude/skills/outsource/`): hand a scoped repo task to convertible — a *different* engine/model than the calling agent (the value is diversity, not raw power). Three verbs over `convertible drive`: `explore` (read-only investigation → findings), `review` (an independent second opinion on the committed `<base>...HEAD` diff), and `write` (delegate a small implementation). Read-only verbs run in a throwaway `git worktree` at HEAD, so they cannot touch the working tree; `write` refuses a dirty tree unless `--allow-dirty`. Defaults to a local vLLM model (`mmangkad/Qwen3.6-27B-NVFP4`), overridable via flags/env. Advertised in `convertible learn` and `convertible explain outsource`.

## [0.15.0] - 2026-05-30

### Added

- Subagent delegation ("convoy"): mid-drive, an engine can call a `subagent` tool to delegate a scoped sub-task to a nested in-process child drive on an optional different engine and/or model; the child runs the same bounded loop with no git handoff, and its result is folded back into the parent loop and recorded on `TaskResult.sub_results` (omitted when empty). Engine-judged and optional (like the devague tool), NOT an automatic router/gearbox. Sequential-only and bounded (depth 2 / fan-out 4); parallel subagents are a parked follow-up. Chassis-owned (all-engines rule), zero new runtime deps, no daemon/socket/fork.

## [0.14.0] - 2026-05-30

### Added

- Approval gate: operator-declared `.convertible/approvals.json` gates what the harness executes — `run_command` CLIs by program token (allow/deny, shlex) and hook scripts + command templates by checksum. Approval is tamper-protection: `approve` records a file checksum and a later edit voids it (sha256-default, md5 honored). Skills/AGENTS load freely (declarative, never gated). Per-model overlay, strict no-op default, chassis-owned (all-engines rule), stdlib only. Policy gate, not a sandbox.
- `commands approve <name>` / `hooks approve <name>` CLI verbs record a checksum approval; `commands`/`hooks`/`skills list` show approval/accessibility status and `hooks list` shows the run_command policy; `explain approve`.

## [0.13.0] - 2026-05-29

### Added

- `CONVERTIBLE_ENGINE` environment variable for engine selection; the engine now resolves `--engine` > `CONVERTIBLE_ENGINE` > `vllm-openai` and never silently falls back to the no-op `mock` (#53).
- `usage` oilcheck check-group (`usage_effective_engine`): `convertible doctor` now warns (advisory, stays healthy) when a bare drive would pick the no-op `mock` engine.
- `convertible doctor --probe`: opt-in provider-reachability ping (`provider_reachable`), the one check that opens a network connection — invoked outside the no-network registered check-groups.
- `convertible session --pr`: opt back into push + PR per drive.

### Changed

- Default engine for `drive`/`session` is now `vllm-openai` (the real bundled engine) instead of `mock`; `mock` is reachable only via an explicit `--engine mock` / `CONVERTIBLE_ENGINE=mock`.
- `convertible session` commits locally by default and no longer pushes or opens a PR per typed line; use `--pr` to enable handoff (replaces session's `--no-pr`). `drive` is unchanged (PR by default).

### Fixed

- Talking to `convertible session` (or driving a question like `drive "what can you do?"`) no longer opens surprise PRs via the no-op mock engine, and `convertible doctor` no longer reports a misleading clean bill of health while a bare run would silently drive `mock` (#53).

## [0.12.4] - 2026-05-29

### Added

- Per-step progress output during a drive: each loop step emits a concise line to **stderr** (`step N: <tool> <target> [ok|err]`) in all modes, so long drives are observable while stdout stays the single parseable `--json` result (#38). Chassis-owned in the loop and threaded via `EngineConfig.progress`; both engines forward it (all-engines rule).

### Changed

- Refactored `loop.run` to extract the bounded turn loop into `loop._drive_loop`, enabling clean partial-result preservation and bringing `run`'s cognitive complexity back under threshold (SonarCloud S3776).

### Fixed

- A drive that raises mid-loop (e.g. a per-request timeout) now preserves the partial result: the accumulated `steps`, `usage`, and `changed_files` are written to the artifact with `status=error` and the `*.trace.jsonl` is populated, instead of being discarded for an empty `failed_result` (#37). The CLI still exits non-zero and surfaces the error.
- The per-step progress sink is fail-safe: a raising progress callback is suppressed and never aborts the drive (same observability-not-control guarantee as hooks and neighbour clones).
- The engine-failure remediation hint only claims a "partial trace" when one was actually written; the no-partial fallback path (fresh `failed_result`, empty trace) says "a result artifact was still written".

## [0.12.3] - 2026-05-29

### Changed

- Handoff commit subject is now a concise single line (`convertible: <first line of instruction, truncated>`, falling back to the task id); the full instruction is preserved in the commit body, and the PR title uses the short subject (#40).

### Fixed

- Handoff now commits **only the task's own work** (#39): all tracked modifications (so `run_command` edits to tracked files are captured) plus the new untracked files the drive itself produced — never pre-existing operator work-in-progress, prior runs' `.convertible/` artifacts, or other incidental untracked files. The drive snapshots untracked files before running and passes that baseline to the handoff. `changed_files` is derived from the staged set so the artifact agrees with what actually landed.
- Gitignored task output (e.g. a gitignored `site/`) is now surfaced in the handoff note (`N file(s) produced but not committed (gitignored): …`) instead of being silently dropped (#39); the gitignore check uses `check-ignore --stdin` (no argv limit, no leading-dash ambiguity).
- A no-op handoff (nothing of the task's own to commit) no longer strands the operator on a freshly-created task branch — staging happens before `checkout -B`, so operator state is left untouched.

## [0.12.2] - 2026-05-29

### Changed

- Refactored `loop.run`, `session.run_session`, and `commands.load_command` into focused helpers to bring cognitive complexity under the threshold (SonarCloud S3776); behavior-preserving (all 799 tests pass).
- Collapsed `telemetry status` to a single return path (SonarCloud S3516 BLOCKER).

## [0.12.1] - 2026-05-29

### Changed

- SonarCloud: stop excluding `.claude/skills/**` — skill scripts are production code and are now analyzed and gated like the rest of the tree.
- Coverage: emit repo-relative paths in `coverage.xml` (`[tool.coverage.run] relative_files`) so SonarCloud imports coverage instead of reporting none.

### Fixed

- Skill shell scripts: 47 lint findings across agent-config/cicd/communicate/assign-to-workforce/think/spec-to-plan/sonarclaude — use `[[ ]]` tests (S7688), name positional params as locals (S7679), route an error to stderr (S7677).
- Code smells in convertible/: dedupe the `--json` help and `.convertible` literals into constants (S1192), give the no-op telemetry methods docstrings (S1186), merge implicit string concatenations (S5799), rename the `_Span._span` field (S1700), tidy the `$N` placeholder regex (S6353), drop the redundant `JSONDecodeError` except clause (S5713), and fix a malformed `noqa` comment (S7632).
- Tests: stop using publicly-writable `/tmp` paths — switch real artifact writes to the `tmp_path` fixture and string-only paths to a neutral placeholder (S5443).

## [0.12.0] - 2026-05-29

### Added

- Per-model fixes — adapt the harness to a model's known biases. `load_hooks` now resolves a per-model hooks overlay `.convertible/<model>/hooks.json` (model token sanitized via `layers.sanitize_model`) and composes its entries ahead of the base `.convertible/hooks.json` per event, so the loop's first-deny/rewrite-wins gives the per-model fix priority. Exact-path per-model isolation (model X never loads model Y's overlay, no sibling globbing); strict no-op for models without an overlay; the driving model is threaded into the loop's hook load automatically (both engines). `convertible hooks list --model <m>` shows the composed set with per-model entries first, scope-tagged; `explain hooks` documents the overlay + precedence. New feature doc `docs/features/per-model-configuration.md` (the car-metaphor: convertible 'adjusts seat and mirrors' to fit the driving model) with an F9 footer-bias worked example. No new runtime dependency, socket, daemon, or `mcp.json`. Built via /assign-to-workforce — 6 TDD-gated tasks across 3 file-disjoint waves.

## [0.11.3] - 2026-05-29

### Added

- Build plan for per-model fixes (`docs/plans/2026-05-29-convertible-lets-an-operator-configure-per-model-f.md`): 6 TDD-gated tasks across 3 dependency waves covering all 15 spec coverage targets — per-model hooks overlay resolution + composition (`hooks.py`), loop wiring, an isolation test, a zero-deps/no-op guard, a `hooks list --model` CLI surface, and an F9 worked example plus a `per-model-configuration.md` feature doc (the car-metaphor 'adjust seat and mirrors'). Converged via devague /spec-to-plan. Plan only; not yet built.

## [0.11.2] - 2026-05-29

### Added

- Spec: per-model fixes that adapt the harness to a model's known biases (`docs/specs/2026-05-29-convertible-lets-an-operator-configure-per-model-f.md`) — converged via devague `/think`. Proposes a per-model hooks overlay (`.convertible/<model>/hooks.json`) resolved with the same `sanitize_model` + `configdir` machinery as `layers.py` and composed with the base model-blind `.convertible/hooks.json`, with the per-model fix evaluated first (first deny/rewrite wins). Spec only; not yet planned or built.

## [0.11.1] - 2026-05-29

### Added

- Drive-evaluation log under `docs/drive-notes/`: a repeatable, time-series record of convertible self-drive experiments — per-run `stats.json` (timing, iterations, operator nudges, tokens, validation, factual findings), qualitative `notes.md`, preserved `output/` (the built site + render) and raw drive `artifacts/`, a cross-run `index.csv`, a `README.md` defining the schema, and a `repro.sh`. First entry: the 2026-05-29 website-self-build drive.

## [0.11.0] - 2026-05-29

### Changed

- culture loop tool: the inspection-CLI allow-list entry is renamed `agex` -> `devex` (issue #33), matching the cicd skill's standardization on the `devex` name in PR #32 (devex is the same tool as agex, invoked under the `devex` name). The engine-visible `culture` tool schema `enum` is now {agtag, devex}. `agtag` is unaffected. Chassis-owned, so every engine sees the renamed allow-list identically (all-engines rule).

## [0.10.0] - 2026-05-29

### Added

- Destination: an engine can set and converge a devague goal-frame via a curated `devague` loop tool when a task warrants one, drive toward it, and declare the announcement on arrival (the car-metaphor sibling to GPS).
- `devague` loop tool (convertible/devague.py + convertible/tools.py): shells out to the operator-installed devague CLI with cwd + CONVERTIBLE_IDENTITY injected; curated move allow-list (new/capture/interrogate/park/converge/status/show) that structurally excludes the user-only confirm/reject and operator-only export. No runtime dep, no import, no socket, no daemon (the culture-tool pattern; all-engines rule).
- Lightweight arrival declaration: additive optional TaskResult.destination + announcement fields (omitted from the JSON artifact when unset, so a no-destination drive serializes byte-identically); finish gains optional destination/announcement, recorded by the loop.
- Chassis system-prompt guidance (inherited by every engine): setting a destination is optional and engine-judged; convergence is advisory and operator-authoritative; the engine cannot self-confirm.

### Changed

- Boundary guards (tests/test_boundary.py) sanction convertible/devague.py as a subprocess transport with no daemon primitives; the zero-deps guard now imports convertible.devague.
- cicd skill (.claude/skills/cicd): the PR lifecycle now drives `devex pr` instead of `agex pr` (devex is the same tool as agex, invoked under the `devex` name); `workflow.sh open` opens PRs via `devex`, never `gh` directly. Agent env override renamed to `STEWARD_DEVEX_AGENT` (legacy `STEWARD_AGEX_AGENT` still honored).

### Fixed

- The `devague` and `culture` loop tools now map a CLI timeout (`subprocess.TimeoutExpired`) and other launch failures (`OSError`) to a clean tool error instead of letting it escape `ToolExecutor` and crash the drive (Qodo review on #32).

## [0.9.0] - 2026-05-28

### Added

- Mesh-member integration: a convertible drive can run as a named AgentCulture identity (convertible/identity.py — culture.yaml nick / .convertible/identity.json, propagated via CONVERTIBLE_IDENTITY)
- Curated culture loop tool (convertible/culture.py): one identity-injected tool shelling out to allow-listed AgentCulture CLIs (agtag, agex) — the documented re-spec of the closed five-tool surface
- Read-only neighbour clones (convertible/neighbours.py): operator-configured .convertible/neighbours.json allow-list, shallow clone, refresh-on-demand, cloned at drive start and cleaned up at finish (ephemeral, empty by default)
- Per-feature mesh-member doc + feature-index and README updates

### Changed

- Tool-loop surface extended from five to six tools (added culture); loop wires neighbour clone-at-start and cleanup-at-finish into the chassis so every engine inherits it (all-engines rule)
- run_command refuses to execute paths inside the neighbour clone tree (best-effort; clones are inert read-only source)

## [0.8.1] - 2026-05-28

### Added

- docs/features/ — a feature index plus one focused doc per shipped feature (drive/loop, engines, handoff, artifact, command templates, hooks, session, layered config, telemetry, doctor, agent-first CLI), each with source pointers and cross-links

### Changed

- README: documented the doctor/oilcheck check-groups, added a Feature docs index, and filled the What-ships-in-v0 list with the layered-config, GPS/telemetry, and doctor features it was missing

## [0.8.0] - 2026-05-28

### Added

- `convertible/oilcheck/` package — a read-only check-group registry + `diagnose()` aggregator that the `doctor` verb renders (chassis-level, like telemetry).

### Changed

- `doctor` is now a configuration-readiness health check (convertible's "oilcheck"), broadened from agent-identity invariants to a full read-only battery: identity, provider config (with redacted api_key + advisory provider_budget warning), engine wheels (all-engines, asserts bundled mock + vllm-openai), otel readiness, and environment (.convertible/hooks.json/command templates, AGENTS/skills layering, git/gh handoff prereqs, CLI integrity). Emits the rubric-shaped {healthy, checks[]} report; exits 1 on any error-severity check. Diagnose-only (no --fix); zero new runtime deps.

## [0.7.0] - 2026-05-28

### Added

- GPS: opt-in OpenTelemetry traces + metrics for a drive (issue #22). Spans (`convertible.drive` -> `convertible.tool.*` -> `convertible.handoff`) and metrics (steps, tokens, tool latency, tool calls, hook denials, drive duration) emit over OTLP from the loop + the shared drive path, so every engine is instrumented identically (all-engines rule).
- `convertible telemetry status` / `overview` introspection noun, plus an explain catalog entry.
- `TelemetryConfig` resolved from `CONVERTIBLE_OTEL_*` / standard `OTEL_*` env vars (`OTEL_SDK_DISABLED` honored as a kill-switch).
- Optional `[otel]` extra (opentelemetry SDK + OTLP/HTTP exporter); install with `pip install "convertible-cli[otel]"`.

### Changed

- `loop.run()` and `execute_drive` accept/own telemetry, defaulting to a no-op resolved from the environment (mirrors the hooks pattern). Off by default it is a strict no-op: no spans, no SDK import, `TaskResult` unchanged.

## [0.6.0] - 2026-05-28

### Added

- Layered per-model config: AGENTS instructions (`AGENTS.md` -> `AGENTS.convertible.md` -> `AGENTS.convertible.<model>.md` at the repo root, with a `~/.convertible/` fallback) and skills (`.convertible/skills/*.md` -> `.convertible/<model>/skills/*.md`) compose into the engine system prompt via `convertible/layers.py`
- `convertible agents` and `convertible skills` introspection nouns (list + overview, `--json`, `--model`)
- `Engine.system_prompt()` base-class helper injects the layered prompt for every engine (all-engines rule)

### Changed

- Both engines (mock, vllm-openai) now pass a model-specific `system_prompt` to the loop; behavior is byte-identical when no AGENTS/skills files exist

## [0.5.0] - 2026-05-27

### Changed

- Bare `convertible` (no subcommand) now opens the interactive harness (the `session` palette) when run at a terminal — the natural "get in and drive" gesture. Piped, redirected, or otherwise non-interactive, it still prints usage, preserving the discoverable surface for scripts and agents. `-h/--help` is unaffected.
- Reframed `convertible drive` help and `explain` text to lead with the goal/instruction ("drive toward a goal") rather than "run a repo task"; the repo is the target, not the headline. No behavior change.

## [0.4.0] - 2026-05-27

### Added

- Convertible ASCII banner on 'drive' and 'session' start (issue #15): decorative chrome shown only on an interactive TTY and suppressed in --json, so it never pollutes the stdout result stream or agent-parsed stderr.

## [0.3.0] - 2026-05-27

### Added

- Command templates discovered under .convertible/commands/*.md, expanded into a Task via `drive --command <name> [args]` ($ARGUMENTS / $1 substitution).
- Lifecycle hooks (.convertible/hooks.json): operator shell commands fired at task_start/pre_tool/post_tool/finish; a pre_tool hook can allow, deny, or rewrite a tool call (Claude-Code-style stdin-JSON + exit-code/structured-stdout I/O contract).
- Interactive foreground palette: `convertible session` over the shared drive path.
- Agent-first CLI: `convertible commands list/overview` and `convertible hooks list/overview`.
- Result artifact now records every hook firing and the originating command.

### Changed

- Hook lifecycle is wired into the engine-agnostic loop, so it binds every engine (all-engines rule); the chassis is no longer purely one-shot.
- Repo-shipped hooks run by default under the trusted-operator-env model (a per-repo trust gate / opt-out is a documented follow-up, not yet built).

### Fixed

- Hook execution and matching failures (subprocess timeout, launch error, invalid matcher regex) now map to a structured fail-closed decision instead of crashing the drive.
- The originating command is persisted in the result artifact on the failure path and for session-run templates (previously recorded as null).
- `convertible session` routes errors/diagnostics to stderr and honors `--json` (one JSON result per drive on stdout, palette chrome to stderr).
- `hooks list` reads entries via the public `HookConfig.all_entries` accessor (removed an unjustified lint suppression).

## [0.2.2] - 2026-05-27

### Added

- README tip (anecdotal, n=1): qwen3_coder handled tool-argument escaping more reliably than hermes for an NVFP4 Qwen3 checkpoint — a hermes run over-escaped docstring triple-quotes into a SyntaxError. Framed as a single observation, not a benchmark.

## [0.2.1] - 2026-05-27

### Changed

- Generalized the vLLM tool-call-parser docs from hermes-specific to model-appropriate (e.g. hermes or qwen3_coder); the engine is parser-agnostic and only needs OpenAI-format tool calls. Touches vllm_openai docstring, the live-proof test docstring, README, and CLAUDE.md.

## [0.2.0] - 2026-05-27

### Added

- convertible drive: run a repo task through a swappable coder engine (bounded agentic tool-loop: read_file/write_file/list_dir/run_command/finish, repo-confined)
- convertible wheels list: discover engine wheels via the convertible.engines entry-point group
- Shared task contract (Task/TaskResult) with lossless JSON round-trip
- Two bundled engines: deterministic networkless mock, and vllm-openai driving any OpenAI-compatible /v1/chat/completions endpoint with tool calling (stdlib urllib, no SDK)
- Git/PR handoff: branch/commit/push + gh pr create, gated by --no-pr/no-remote for offline/CI
- JSON result artifact + step-trace dashboard under .convertible/
- Opt-in live vLLM end-to-end test (CONVERTIBLE_VLLM_E2E=1)

### Changed

- CLAUDE.md expanded from the /init seed into a full runtime prompt for the harness
- README rewritten to document the engine/driver/chassis/wheels architecture and the v0 boundary

### Fixed

- Loop now serializes outbound tool-call `arguments` as a JSON string (OpenAI wire format), so multi-turn vLLM tool loops aren't rejected by strict servers (Qodo #1)
- `drive` attempts handoff whenever the drive succeeds (not only when `write_file` ran), so edits made via `run_command` are committed/pushed; `changed_files` is backfilled from `git status` (Qodo #2)
- Handoff note no longer claims "local commit only" when the push succeeded but `gh pr create` failed (Qodo #4)
- Reduced the "wheel/garage" pun in the running CLI's user-facing output, keeping external messaging engine-centric (Qodo #3)

## [0.1.2] - 2026-05-27

### Changed

- **Renamed the PyPI distribution from `convertible` to `convertible-cli`** — the
  bare `convertible` name was unavailable/ambiguous on PyPI. Only the published
  distribution name changes; the import package (`convertible/`), the `convertible`
  CLI entry point, and the wheel build target are unchanged. Updated the TestPyPI
  install hint in `.github/workflows/publish.yml` to match.

## [0.1.1] - 2026-05-26

### Changed

- **CI gates on the SonarCloud quality gate**
  ([issue #3](https://github.com/agentculture/convertible/issues/3)) —
  added `sonar.qualitygate.wait=true` to `sonar-project.properties` so a failing
  gate fails the `test` job when `SONAR_TOKEN` is set. Token-less repos and fork
  PRs remain green (the scan step is guarded by `if: env.SONAR_TOKEN != ''`).

## [0.1.0] - 2026-05-26

### Added

- **Onboarded into the AgentCulture mesh** ([issue #1](https://github.com/agentculture/convertible/issues/1)).
- **Agent-first CLI** cited from teken's (`afi-cli`) `python-cli` reference
  (`teken cli cite`) — verbs `whoami`, `learn`, `explain`, `overview`, `doctor`,
  and the `cli` noun group. Runtime is self-contained (`dependencies = []`);
  `teken>=0.8` is a dev dependency only. Passes the seven-bundle agent-first
  rubric (`teken cli doctor . --strict`). `doctor` checks the agent-identity
  invariants (prompt-file-present, backend-consistency, skills-present).
- **Mesh identity**: `culture.yaml` (`suffix: convertible`,
  `backend: claude`) and the matching `CLAUDE.md` prompt file.
- **Canonical guildmaster skill kit** (11 skills) vendored under
  `.claude/skills/` (cite-don't-import): `agent-config`, `assign-to-workforce`,
  `cicd`, `communicate`, `doc-test-alignment`, `pypi-maintainer`, `run-tests`,
  `sonarclaude`, `spec-to-plan`, `think`, `version-bump`. Every `SKILL.md`
  carries `type: command` (load-bearing for the culture/claude backend);
  `cicd` / `communicate` consumer-identifying prose adapted, all script bodies
  verbatim. Provenance in `docs/skill-sources.md`. Three skills (`think`,
  `spec-to-plan`, `assign-to-workforce`) originate in `devague`, re-broadcast
  via guildmaster.
- **Build + deploy baseline**: `pyproject.toml` (hatchling), `tests/` (pytest,
  xdist, coverage), `.github/workflows/{tests,publish}.yml` (CI rubric/lint gate,
  PyPI Trusted Publishing), `.flake8`, `.markdownlint-cli2.yaml`,
  `sonar-project.properties`, and `.claude/skills.local.yaml.example`.

### Changed

### Fixed
