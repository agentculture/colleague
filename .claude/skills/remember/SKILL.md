---
name: remember
type: command
description: >
  Ingest records into the shared eidetic memory store so they can be recalled
  later. Drives `eidetic remember`: accepts one record as a JSON object, or a
  batch as NDJSON on stdin for bulk ingest. Upsert is idempotent by id (and
  dedups by content hash) — re-remembering updates in place, never duplicates.
  Stamps a `created` date on every record at ingest time. Accepts `supersedes`
  (id of the record this one replaces, for within-scope shadowing via `sweep`)
  and `links` (list of related-memory ids). The store uses visibility-aware
  routing: PUBLIC records inside a git repo go to <repo-root>/.eidetic/memory
  (committed, team-shared); PRIVATE records, or any record outside a git repo,
  go to $HOME/.eidetic/memory (never committed). An explicit EIDETIC_DATA_DIR
  wins and short-circuits to that single dir. The wrapper defaults records to
  this agent's PERSONAL, PUBLIC scope (`--scope colleague --visibility
  public`, suffix read from culture.yaml) so a plain /remember commits to
  <repo-root>/.eidetic/memory (in-repo, team-shared) — Claude and the colleague
  backend still share them because both resolve the same suffix via this skill.
  Pass `--visibility private` to keep a record in $HOME (uncommitted). Use when the user says
  "remember this", "store this", "save to memory", "index these", "eidetic
  remember", or when something learned this session should outlive it. Pairs with
  the sibling /recall skill.
---

# remember — write to the shared eidetic memory

`remember` drives **`eidetic remember`**, the write half of the memory surface
(the read half is the sibling **/recall** skill). Records you store here are
recallable later by *any* agent on this machine — Claude or the colleague
backend — because the default store is one shared `<repo-root>/.eidetic/memory`
path (committed, team-shared).

## How to run

```bash
# One record (JSON object as the argument):
bash .claude/skills/remember/scripts/remember.sh \
  '{"id":"d1","text":"Orin Nano draws 7-15W","type":"docs","metadata":{"source":"docs","permalink":"https://..."}}' --json

# Batch (NDJSON on stdin, one record per line) — for bulk re-index:
cat records.ndjson | bash .claude/skills/remember/scripts/remember.sh --json

# Record that supersedes an older one (same scope required for sweep to shadow):
bash .claude/skills/remember/scripts/remember.sh \
  '{"id":"r2","text":"Updated Orin Nano draw: 10-20W","type":"note","supersedes":"r1","links":["r3"]}' --json
```

The wrapper resolves the CLI portably (installed `eidetic` on `PATH`, else
`uv run eidetic` from the checkout) and forwards every flag verbatim.

## Record shape

| Field | Required? | Notes |
|-------|-----------|-------|
| `id` | yes | stable identity; the upsert key |
| `text` | yes | the chunk being remembered |
| `type` | yes | e.g. `note`, `docs`, `discord`, a research object type |
| `hash` | optional | content hash for dedup; derived from `text` when omitted |
| `metadata` | recommended | provenance + facets; **round-trips verbatim** on recall |
| `created` | auto-stamped | ISO-8601 UTC date; stamped at ingest if absent; drives freshness signal age-decay |
| `supersedes` | optional | id of an earlier same-scope record this one replaces; `sweep` auto-shadows the target |
| `links` | optional | list of related-memory ids; persisted for future corroboration scoring |

`score` and `signal` are recall-only and are ignored on ingest. **Mind the
scope:** the default personal scope is **public** (`--scope colleague
--visibility public`), so records land in <repo-root>/.eidetic/memory
(committed, team-shared). Only when you deliberately write to a
**private** scope (`--visibility private`) does the record go to $HOME
(uncommitted).

## Idempotency

Re-submitting a record with the same `id` overwrites the previous value; a record
with a matching content `hash` is de-duplicated. So re-running an ingest (e.g. a
periodic re-scan) is safe and will not create duplicates.

## Lifecycle — supersedes and sweep

Setting `supersedes` on a record declares that this record replaces an earlier one
**within the same scope**. The actual lifecycle transition (marking the older record
as `shadowed`) is applied by `eidetic sweep`, not by `remember` itself. Cross-scope
`supersedes` links are recorded but never auto-shadow (preserving the
public/private no-leak invariant).

To apply pending transitions after ingesting superseding records:

```bash
eidetic sweep --dry-run   # preview what would change
eidetic sweep             # apply transitions
```

## Flags (forwarded to `eidetic remember`)

- `--json` — structured result (`{"upserted": N, "ids": [...]}`) to stdout.
- `--scope NAME` / `--visibility public|private` — record scope. **The wrapper
  defaults this to the agent's PERSONAL, PUBLIC scope** — `--scope <suffix>
  --visibility public`, where `<suffix>` is read from the nearest `culture.yaml`
  (here, `colleague`). Public records land in <repo-root>/.eidetic/memory
  (committed, team-shared). Pass `--scope` to steer to a different scope, or
  `--visibility private` to keep a record in $HOME (uncommitted). A wheel
  install with no `culture.yaml` falls back to the CLI default `default`/`public`.
- `--backend files|mongo|neo4j` — default `files` (the visibility-routed store:
  public → `<repo-root>/.eidetic/memory`, private → `$HOME/.eidetic/memory`);
  use `mongo`/`neo4j` (with `EIDETIC_MONGO_URI` / `NEO4J_URI`) for a server store.

## Notes

- The embed endpoint defaults to the local model-gear embed gear
  (`http://localhost:8002/v1`); override with `EIDETIC_EMBED_URL` /
  `EIDETIC_EMBED_MODEL`. Ingest still works offline (embeddings are recomputed at
  recall time).
- **Use the wrapper, not a bare `eidetic`.** The console script may not be on
  `PATH` (in a dev checkout it isn't); the wrapper resolves it (`PATH` first, else
  `uv run eidetic`). For the docs, run `eidetic explain remember` if installed,
  otherwise `uv run --project <eidetic-cli checkout> eidetic explain remember`.

## Provenance

First-party to **eidetic-cli** — eidetic owns its memory surface. Cite, don't
import: downstream repos copy this skill, they don't symlink it. See
[`docs/skill-sources.md`](../../../docs/skill-sources.md).
