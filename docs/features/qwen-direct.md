# Qwen-direct: the single-model default (1 instance = 1 model = 1 agent)

**Status:** built on the qwen-direct arc (spec
`docs/specs/2026-08-22-qwen-direct-no-gemma.md`, plan
`docs/plans/2026-08-22-qwen-direct-no-gemma.md`, v1.63). The **fifth recorded
v0 → v1 convention change** (see `CLAUDE.md` § v1 scope): sanctioned increment
(4) *presence-default-everywhere* is superseded — senses is opt-in, not default.

## What shipped

- **Discovery is opt-in (c2/c4, `colleague/config.py`).** `EngineConfig.resolve()`
  no longer fills the senses seat from the lobes gateway's `senses` role, nor
  deepthink from the `muse` role. The opt-in is a declaration: the `lobes`
  sentinel (`COLLEAGUE_SENSES_MODEL=lobes` / `COLLEAGUE_DEEPTHINK_MODEL=lobes`,
  or config.json `senses.model` / `deepthink.model` = `"lobes"`) asks for
  discovery; an explicit model id declares a seat directly. Unarmed, a bare run
  on a lobes-armed rig resolves exactly ONE served model — the `cortex` role —
  and dials nothing else.
- **No front door / no senses loop on the default path (c3).** Every senses
  consumer already guards on `config.senses is None` (scope entries s13/s14 of
  the spec): the presence loop, the front door classifier, senses
  streaming/narration, clarify, the talk lane's senses answer. With the seat
  unresolved they are dormant; the operator speaks with the main agent.
- **Mid-run words park for cortex (c15/c28, `session.py` `_park_talk_for_cortex`).**
  An unarmed session no longer drops a typed/voiced line — it is written
  VERBATIM as flight guidance (the seam `colleague talk` already uses) and
  cortex addresses it at its next tool-call boundary.
- **Visible retirement (c7, `config show` / `lobes show`).** One line per
  advertised-but-not-consumed role: `not consumed (opt-in): senses → <model> —
  COLLEAGUE_SENSES_MODEL=lobes` (+ `--json` `not_consumed`).
- **Served options + per-seat effort are inspectable and switchable
  (c25/c26/c29/c32/c33).** Session `/model` (no arg) lists the gateway's
  `/v1/models` roster + role → model lines and marks the current seat; `/model
  <id>` switches AND re-derives the context budget from the role's advertised
  window (`min(window, current)`); bare CLI `--model` / `--effort` print the
  same list / the per-seat effort table (`colleague/cli/_commands/_listing.py`,
  pure renderers) and exit 0 without running; `/effort` (t4) shows `effort_of`
  per seat and switches a seat for the session only (`effort.apply_operator_effort`).
  **Switching is an explicit operator choice, never a routing policy.**
- **Rollback is one declaration (c30).** `COLLEAGUE_SENSES_MODEL=<served id>`
  (or `=lobes`) on the gateway origin re-arms the whole senses lane exactly as
  before; the same-origin key rule is unchanged.

## Why

Complexity is a problem (doctrine 2026-08-20: solo cortex 100 % vs three-tier
0 % on the same task — failures live in the seams, not the minds) and Qwen3.8 is
fast at the default effort (`docs/evidence/2026-08-22-per-seat-thinking-effort-416-results.md`:
off 24 s / xhigh 88 s / medium 129 s). Every extra seat, proxy hop and loop is a
failure surface with no measured benefit. One model, one agent, one hop by
default; the instance spawns ITSELF as subagents (same model, the existing
`subagents`/roles surface).

## Honest limits

- voice / realtime / `/speak` stay senses consumers and are **dormant** on the
  default path (t7 adds the honest "senses not armed" line); re-plumbing them
  onto cortex is a later arc.
- The senses/presence code is **not deleted** — it moved behind the opt-in
  (park v1 of the spec); deletion is a separate re-spec once the opt-in has sat
  unused.
- `/effort` switches are session-only — nothing is persisted to config.json.
- The "second main agent you can talk to" (turning a senses-like agent back on
  as a peer) is a later opt-in arc (spec c16).
- lobes-cli keeps serving and advertising `senses`/`muse`; this arc is
  consumption-side only (spec c8).

## Provenance

Spec scope entries s1–s26 (live gateway probe, `config.py` l.3420-3441,
`session.py` l.2163, two colleague explores, six challenge lenses); workforce
ledger `docs/evidence/2026-08-22-qwen-direct-no-gemma-workforce-ledger.md`;
live proof row in `docs/live-testing.md` (t10).
