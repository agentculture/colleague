# ask-colleague is now a trustworthy standing pre-PR reflex: review front-loads a filtered diff and fans out parallel reviewers so it finishes fast on a real diff and always returns findings; monitor truly streams a running flight's live feed; write --apply no longer trips on a read-only probe's own .colleague/ artifacts; and the SKILL.md provenance reads honestly in any consumer regardless of how it vendors its other skills.

> ask-colleague is now a trustworthy standing pre-PR reflex: review front-loads a filtered diff and fans out parallel reviewers so it finishes fast on a real diff and always returns findings; monitor truly streams a running flight's live feed; write --apply no longer trips on a read-only probe's own .colleague/ artifacts; and the SKILL.md provenance reads honestly in any consumer regardless of how it vendors its other skills.

## Audience

- Agents (Claude and other minds) that delegate to colleague via the ask-colleague skill before opening a PR, plus the operators who vendor that skill verbatim into sibling repos.

## Before → After

- Before: review is turn-bound — ~8 sequential slow model round-trips just to load context, and a manual kill (no --watch flight) returns nothing; monitor is a one-shot 'flight status' read mislabeled a 'live feed'; write --apply refuses because a prior explore/review left untracked .colleague/ artifacts the coarse porcelain guard counts as dirty; the SKILL.md provenance line asserts the consumer's other skills are vendored from guildmaster, false in non-guildmaster consumers.
- After: ask-colleague review front-loads a filtered diff and fans out parallel read-only reviewers, so a real (multi-file, ~KLOC) diff is reviewed quickly and always yields findings; ask-colleague monitor streams a running flight's live feed; write --apply runs after a read-only probe on a clean tracked tree without --allow-dirty; and the SKILL.md provenance paragraph is accurate in any consumer.

## Why it matters

- The 'run review before every PR' reflex only pays off if it is fast, honest, and side-effect-safe. Today it breaks on first real use — too slow to finish, docs that over-promise, and a guard that blocks the documented probe-then-apply workflow — so the diverse-second-opinion value is lost exactly when it matters.

## Requirements

- #217: narrow the ask-colleague.sh write --apply dirty guard to tracked changes only (git status --porcelain --untracked-files=no), matching the runtime working_tree_dirty (handoff.py), so the skill's own untracked .colleague/ artifacts never block an apply.
  - honesty: Narrowing must NOT reintroduce the #149 hazard: tracked uncommitted edits are still refused without --allow-dirty; runtime working_tree_dirty (tracked-only) stays the authoritative backstop; untracked WIP stays protected by the handoff baseline snapshot.
- #218: soften the SKILL.md provenance paragraph to state only that ask-colleague is first-party from colleague and vendored cite-don't-import, deferring any claim about the consumer's OTHER skills (guildmaster or otherwise) to the consumer's own ledger.
  - honesty: The rewritten paragraph reads accurately in a fresh consumer whose sibling skills are NOT guildmaster-vendored, and points to (not asserts) docs/skill-sources.md as the per-repo ledger.
- #219: add a follow mode to colleague flight — flight status --follow (a stdlib poll loop over the .colleague/flight/<id> feed file) that prints feed records as they are appended and exits on flight-finish/EOF or Ctrl-C — point ask-colleague monitor at it, and update wrapper help + SKILL.md.
  - honesty: Follow mode adds NO runtime dependency, daemon, or socket (stdlib poll only); it streams real appended records (not a re-print of the latest), terminates cleanly on finish/EOF/Ctrl-C, and --json emits JSONL; one-shot flight status (no --follow) stays byte-identical.
- #220a: front-load the review's context — compute git diff --stat (always) plus the git diff body with lockfile/vendored noise excluded and capped to the output budget, seeded into the review so the model gets the whole change in ~1 turn instead of ~8 sequential read turns; the model may still read specific files beyond the cap.
  - honesty: The seeded diff is filtered (uv.lock/package-lock.json/etc. excluded) and capped to COLLEAGUE_MAX_OUTPUT_CHARS so it never blows the context budget; when capped, the diffstat is retained and body truncation is explicit (a visible note), never silent; fires identically for mock and vllm-openai.
- #220b: let review partition a multi-folder diff and fan out concurrent read-only reviewer subagents (one per folder/file-group), each reviewing its slice, then fold the findings — reusing the existing subagents + #188 advisory fan-out + #221 reviewer role + batch_spawn merge, with NO new worktree/merge code.
  - honesty: Parallel review is ADVISORY/backend-judged (the #188 mechanism), never a forced split; omitting it leaves review byte-identical; it fires identically for mock and vllm-openai; reviewer children are read-only and cannot mutate the tree.
  - honesty: On a single serializing GPU (vLLM --max-num-seqs=2, the reference rig) parallel fan-out gives little-to-no wall-clock speedup (bounded by overlapped I/O, not model compute); the real concurrency win needs a concurrent-capable backend. Front-loading the diff (#220a) is the speedup that holds on the reference rig; this limit is documented, not hidden.

## Honesty conditions

- All four fixes ship upstream in colleague and re-vendor unchanged; none adds a runtime dependency, daemon, or socket (the zero-deps / no-daemon conventions hold).
- The fixes are usable by both the delegating agent (ask-colleague verbs) and an operator running colleague directly, and the wrapper changes re-vendor cleanly to sibling repos.
- Each after-state is independently verifiable against the filed acceptance criteria (#220 findings-on-real-diff, #219 streams, #217 apply-after-probe, #218 provenance-accurate).
- Each before-state is reproduced from filed evidence (discord-bot-cli PR #7 for #220; wrapper L96/L713 for #219; L633-634 for #217; SKILL.md L211-213 for #218).
- The success bar is 'findings returned in usable time', not a fixed second-count — a partial/fast review beats the nothing operators get today.
- Deferred items (deadline flag, contention detection) are parked as first-class follow-ups, not silently dropped; the shipped forced-synthesis (#191/#197) behavior is unchanged.
- Every success signal is verifiable without an idle reference GPU — correctness checks run on mock/any backend; the wall-clock claim is honestly bounded by backend concurrency.

## Success signals

- A review of a ~32-file / ~1.3-KLOC diff returns findings in a usable time (vs the #220 baseline of zero findings at step 8 / ~8 min); colleague flight status --follow prints feed records as they are appended and exits cleanly on flight-finish or Ctrl-C; ask-colleague explore && ask-colleague write --apply succeeds on a clean tracked tree without --allow-dirty; the SKILL.md provenance paragraph makes no claim about sibling-skill provenance.

## Scope / boundaries

- Out of scope: a wall-clock --deadline flag, GPU/contention auto-detection or automatic model fallback, a multi-backend router, and any daemon/socket. It does not replace the already-shipped forced-synthesis-on-exhaustion (#191/#197) — it complements it by reducing turns and (for monitor) streaming.

## Non-goals

- Not building a wall-clock --deadline flag or GPU-contention auto-detection/model-fallback in this spec; both are deferred follow-ups, parked as first-class items.

## Assumptions

- All four changes are upstream-in-colleague and re-vendor to consumers: the wrapper (ask-colleague.sh) and SKILL.md are vendored verbatim, so fixes propagate via the rollout-cli re-vendor recipe (rollout-cli#11).

## Decisions

- Front-load (#220a) is wrapper-first: the wrapper computes the filtered diff and inlines it into the review instruction, re-vendoring cleanly with zero runtime change; a runtime context-primer is the fallback only if the wrapper approach proves insufficient.
- Parallel review (#220b) reuses the advisory #188 fan-out, fired EARLY from the front-loaded diffstat (folder count known up front) rather than after reading COLLEAGUE_FANOUT_FILES files, so the partition happens before the sequential reads begin.
