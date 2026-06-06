# Build Plan — A crashed colleague work no longer wedges your repo: colleague clean reaps stale/corrupt colleague/* branches and orphaned .colleague/ artifacts, the handoff runtime self-cleans after a catchable interruption, and doctor flags a wedged repo and points at the recovery verb

slug: `a-crashed-colleague-work-no-longer-wedges-your-rep` · status: `exported` · from frame: `a-crashed-colleague-work-no-longer-wedges-your-rep`

> A crashed colleague work no longer wedges your repo: colleague clean reaps stale/corrupt colleague/* branches and orphaned .colleague/ artifacts, the handoff runtime self-cleans after a catchable interruption, and doctor flags a wedged repo and points at the recovery verb

## Tasks

### t1 — Add read-only + reaping git helpers to colleague/handoff.py: list_colleague_branches (for-each-ref refs/heads/colleague/ + classify corrupt/merged/old/live via cat-file -e / merge-base / committerdate), empty_loose_objects (pathlib scan of .git/objects/??/* for 0-byte files), reap_colleague_branches (delete via git update-ref -d, guarded to colleague/* only)

- covers: c9, c10, h1, h2, h9
- acceptance:
  - list_colleague_branches enumerates only refs/heads/colleague/ and classifies a fabricated 0-byte-tip ref as 'corrupt'; an unrelated feature/* branch is never returned
  - reap_colleague_branches deletes a corrupt colleague/<id> via git update-ref -d (succeeds on a tip whose object is missing) and refuses any ref not under refs/heads/colleague/
  - empty_loose_objects returns the 0-byte loose object paths under .git/objects and never deletes them
  - tests/test_boundary.py passes unchanged: handoff.py stays in _SUBPROCESS_ALLOWED and no new module imports subprocess

### t2 — Make colleague/handoff.py handoff() crash-resilient: wrap checkout -B -> commit in try/except (HandoffError, KeyboardInterrupt); on a catchable failure before result.committed, restore the operator ref and reap the orphan colleague/<id> branch, then re-raise; success path byte-identical

- depends on: t1
- covers: c11, h3
- acceptance:
  - a handoff() whose commit raises HandoffError leaves no colleague/<id> branch and returns the operator to original_ref
  - a successful handoff yields a byte-identical HandoffResult vs before the change; tests/test_e2e_mock.py stays green

### t3 — Add reap_artifacts(repo, *, dry_run) to colleague/artifact.py (pure stdlib): remove 0-byte .colleague/*.json and *.trace.jsonl, clear a last_work pointer that resolves to a missing/0-byte artifact, never delete a non-empty (gradable) artifact

- covers: h4
- acceptance:
  - reap_artifacts removes a 0-byte .colleague/<id>.json and clears a last_work that points at it, but leaves a non-empty .colleague/<id>.json untouched
  - dry_run reports the same actions while deleting nothing

### t4 — Add the colleague clean CLI verb: NEW colleague/cli/_commands/clean.py (cmd_clean + register, modeled on doctor.py) calling handoff.reap_colleague_branches + artifact.reap_artifacts + handoff.empty_loose_objects; flags --repo/--dry-run/--merged/--older-than/--json; wire in cli/__init__.py; add _CLEAN entry to explain/catalog.py

- depends on: t1, t3
- covers: c1, c3, c6, c8, h5, h7, h10
- acceptance:
  - one colleague clean --repo <tmp> run reaps the corrupt colleague/<id> ref + 0-byte .colleague/ artifacts and prints a git prune hint when 0-byte loose objects remain; git fetch then succeeds
  - --dry-run reports the same reaping while changing nothing; --json emits a structured report; a non-git --repo raises CliError(EXIT_USER_ERROR=1)
  - clean never deletes a file under .git/objects, never deletes a non-empty .colleague/ artifact, and never touches a branch outside refs/heads/colleague/
  - colleague explain clean resolves and clean.py imports the reap helpers from handoff.py (no subprocess import)

### t5 — Add an advisory doctor stale-ref check: NEW colleague/oilcheck/stale_refs.py checks() importing read-only list_colleague_branches from handoff.py, emitting a warning-severity make_check('colleague_stale_refs', ...) pointing at colleague clean; register in oilcheck/__init__.py CHECK_GROUPS

- depends on: t1
- covers: c1
- acceptance:
  - in a repo with a corrupt colleague/<id> ref, doctor shows colleague_stale_refs failing at warning severity and the report stays healthy
  - a non-git cwd (or a clean repo) is a passing no-op; the check never raises and oilcheck/stale_refs.py imports no subprocess

### t6 — Teach the ask-colleague skill the clean verb and fix the #161 nits: ask-colleague.sh adds a clean verb (run_clean -> colleague clean --repo, passing --dry-run, no description ARG), flips the 8 user-input exit 2->1 (+L457 to match the runtime's EXIT_USER_ERROR) keeping env exit 2, documents the 0/1/2 policy, updates usage; SKILL.md adds a clean row + crashed-run note + consumer gitignore note and softens the explore/review side-effect cells

- covers: c2, c5, h5, h6
- acceptance:
  - ask-colleague clean --repo <tmp> shells out to colleague clean and reaps the same corrupt ref, inheriting the colleague/* scoping guard (an unrelated branch survives)
  - ask-colleague with no verb / unknown verb / missing description / bad --repo all exit 1; missing git/CLI/template still exit 2
  - SKILL.md lists clean, notes a crashed run may leave a colleague/<id> branch reapable with ask-colleague clean + that consumers should gitignore .colleague/, and the explore/review side-effect cells no longer claim unqualified None

### t7 — End-to-end + release: NEW reproduce-and-recover test (fabricate a 0-byte loose object under a colleague/<id> ref, assert git fetch aborts, run colleague clean, assert git fetch succeeds); add the Cleanup/reap bullet to CLAUDE.md; /version-bump minor + CHANGELOG (#162 + #161); run pytest -n auto + black/isort/flake8/bandit/teken

- depends on: t1, t2, t3, t4, t5, t6
- covers: c4, c8, h8
- acceptance:
  - a test fabricates a 0-byte loose object under a colleague/<id> ref, asserts git fetch aborts with the empty-object error, then asserts colleague clean makes git fetch succeed
  - CLAUDE.md documents the clean verb + handoff crash-resilience + doctor stale-ref check; version + CHANGELOG bumped; full pytest -n auto and all lint gates pass
