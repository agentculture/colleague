# A named guide/docent role for self-knowledge, if advisory injection proves shallow

## Background

The at-home arc (`docs/features/at-home-on-your-machine.md`, spec
`docs/specs/2026-07-09-colleague-now-feels-at-home-on-your-machine-arm-th.md`,
decision "Cortex self-knowledge mechanism") gave cortex a self-knowledge path
via **advisory injection**: `colleague/selfknowledge.py`'s
`classify_selfknowledge` gates ONE advisory message — a live guide-doc index
(`build_guide_index`) plus a resolved facts block (`build_self_facts`) —
appended before cortex's own turn when a self-knowledge question is detected.
Cortex then answers using its existing `read_file` tool.

That decision deliberately deferred a fuller alternative the spec named
up front: a dedicated **guide/docent role** — a typed subagent role
(`colleague/roles.py`'s existing built-in-role machinery) purpose-built to
answer questions about colleague itself, rather than an advisory message
folded into whatever turn cortex was already running.

## Why this might still be needed

The advisory-injection approach is cheap (no new role, no new tool surface,
reuses `read_file`) but has a real failure mode: cortex may read only the
index *line* and answer from the paths' names rather than actually opening a
listed doc, especially under a tight context budget where opening a large doc
competes with the rest of the turn's budget. If that shows up in practice —
shallow, guessy answers to genuinely deep self-knowledge questions ("how does
the affected-tests gate cap selected files?") — a dedicated role would let a
self-knowledge answer run its own bounded turn with the guide docs as its
whole context, instead of sharing budget with an in-progress unrelated task.

## Proposed scope (if pursued)

- A new built-in role (mirroring `explorer`/`reviewer`) whose curated skill
  subset + system prompt are purpose-built for answering questions about
  colleague's own architecture/gates/capabilities from `docs/features/*` +
  `CLAUDE.md`.
- Triggered the same way as today (`classify_selfknowledge`), but instead of
  injecting an advisory into the current turn, dispatches a scoped subagent
  (`subagent` tool, read-only) running under the new role, and folds its
  answer back — same deterministic, code-locked trigger; no new routing
  policy.
- Stays within the router-exclusion boundary: still no per-input model
  judgment picks the route, still no automatic task-to-model routing, cortex
  remains the only mind that can act on the repo.

## Acceptance signal

Only worth building if a live/dogfood pass shows the current advisory
injection giving genuinely shallow answers to real self-knowledge questions
that a docent role would answer better by reading the same docs in an
isolated, undiluted context.
