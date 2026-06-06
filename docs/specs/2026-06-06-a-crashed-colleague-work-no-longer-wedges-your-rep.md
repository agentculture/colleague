# A crashed colleague work no longer wedges your repo: colleague clean reaps stale/corrupt colleague/* branches and orphaned .colleague/ artifacts, the handoff runtime self-cleans after a catchable interruption, and doctor flags a wedged repo and points at the recovery verb

> A crashed colleague work no longer wedges your repo: colleague clean reaps stale/corrupt colleague/* branches and orphaned .colleague/ artifacts, the handoff runtime self-cleans after a catchable interruption, and doctor flags a wedged repo and points at the recovery verb

## Audience

- an operator (or an agent via the ask-colleague skill) whose repo was left unable to git fetch by a crashed colleague work run

## Before → After

- Before: a crashed work --apply leaves a dangling colleague/<id> ref pointing at 0-byte loose objects and git fetch aborts; there is no cleanup verb and the skill's EXIT-trap only reaps the current read-only run, never a prior crashed one
- After: a single documented command — colleague clean (or ask-colleague clean) — reaps the corrupt colleague/<id> ref + orphaned .colleague/ artifacts and restores git fetch; the handoff also self-cleans after a catchable interruption

## Why it matters

- colleague owns colleague/<id> branches and .colleague/ artifacts, so the lifecycle of what it writes into a user's repo — including recovery from a crash it triggered — is colleague's to self-heal

## Requirements

- clean enumerates only refs/heads/colleague/ (git for-each-ref) and deletes via git update-ref -d (works on a corrupt tip), classifying tips as corrupt/merged/old/live; corrupt is always reaped, merged/older-than are opt-in flags
  - honesty: a fabricated corrupt colleague/<id> ref (pointing at a 0-byte object) in a temp repo is classified 'corrupt' and reaped by git update-ref -d, after which git fetch succeeds; an unrelated feature/* branch is never enumerated or deleted
- the git-touching reap logic lives in handoff.py (the sanctioned subprocess module reusing _git/_branch_name); the clean CLI verb and the doctor stale-ref check call into it and never import subprocess themselves, keeping tests/test_boundary.py green
  - honesty: tests/test_boundary.py still passes unchanged: no new module appears in _SUBPROCESS_ALLOWED, and clean.py + oilcheck/stale_refs.py import the reap helpers from handoff.py rather than importing subprocess
- handoff() wraps checkout -B -> commit in try/except (HandoffError, KeyboardInterrupt) and, on a catchable failure before the commit lands, restores the operator ref and reaps the orphan colleague/<id> branch, then re-raises; the success path stays byte-identical
  - honesty: a handoff() whose commit raises HandoffError leaves no colleague/<id> branch behind and returns the operator to their original ref; a successful handoff produces a byte-identical HandoffResult to before the change (e2e mock shape test green)

## Honesty conditions

- the recovery is a single documented command: colleague clean (and ask-colleague clean) appears in the CLI help, the explain catalog, and SKILL.md, and reaps a wedged repo in one invocation
- both an operator (colleague clean --repo .) and an agent (ask-colleague clean) reach the same reap path; the skill verb shells out to colleague clean and inherits the colleague/* scoping guard
- after clean, the corrupt colleague/<id> ref is gone, the 0-byte .colleague/ artifacts are removed, and git fetch succeeds; a git prune hint is printed for any leftover 0-byte loose objects
- the failure mode is real and reproducible: a fabricated 0-byte loose object under a colleague/<id> ref makes git fetch abort with 'object file ... is empty', and today no colleague verb reaps it
- clean and the handoff self-clean are scoped strictly to colleague-owned artifacts (colleague/* refs, .colleague/ files) — they never modify or delete anything colleague did not create
- clean never deletes a file under .git/objects and never deletes a non-empty .colleague/ artifact or a branch outside refs/heads/colleague/; a test asserts an unrelated branch and a valid artifact survive a clean run
- reap_artifacts removes a 0-byte .colleague/<id>.json and clears a last_work pointer that resolves to it, but leaves a non-empty .colleague/<id>.json (a gradable record the feedback loop depends on) in place

## Success signals

- after a crash that wedges git fetch, one colleague clean run makes git fetch succeed again; --dry-run reports the same reaping while changing nothing; an unrelated branch and a valid artifact are left untouched

## Scope / boundaries

- conservative with .git/objects: clean deletes the corrupt colleague/* ref + 0-byte .colleague/ artifacts and reports leftover 0-byte loose objects (suggests git prune), but never reaches into .git/objects; never touches a non-colleague/* branch or a non-empty (gradable) artifact

## Non-goals

- not a guarantee against future corruption: a SIGKILL/OOM/power-loss mid-commit can still corrupt objects (git/filesystem durability), and not a daemon/auto-reaper — clean is operator/agent-invoked, no socket, no new runtime dep

## Decisions

- doctor gains an advisory (warning-severity) oilcheck stale-ref group that never flips report health and points at colleague clean; a non-git cwd is a no-op

## Open / follow-up

- whether clean should ever offer an opt-in --prune-objects flag that removes 0-byte loose objects under .git/objects (deferred: conservative v0 only reports + suggests git prune)
- whether handoff should set git core.fsync to harden against object corruption on a hard crash (deferred: git/filesystem durability is out of colleague's hands in v0)
