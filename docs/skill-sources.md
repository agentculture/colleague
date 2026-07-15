# Skill upstream sources

colleague vendors its `.claude/skills/` from **guildmaster** — the
AgentCulture **skills supplier** after the steward → guildmaster cutover
(guildmaster 0.5.0, 2026-05-24). `steward` retains the **alignment** role
(`steward doctor`, the sibling-pattern baseline); only the skills-supplier role
moved. This file tracks provenance so re-syncs stay deterministic.

Seven skills (`scope`, `think`, `challenge`, `spec-to-plan`,
`assign-to-workforce`, `deviate`, `summarize-delivery` — listed in devague
flow order) originate in
[`agentculture/devague`](https://github.com/agentculture/devague); guildmaster
only **re-broadcasts** them. Cite guildmaster's copy where it has re-broadcast
(currently `think`, `spec-to-plan`, `assign-to-workforce`); track devague as the
true origin. The four not yet re-broadcast — `summarize-delivery`, `scope`,
`challenge`, `deviate` — are cited **directly from devague** and should be
re-pointed at guildmaster's copy once that broadcast lands.

One skill is **first-party**: `ask-colleague` is **authored here** (origin =
colleague), not vendored. It is the inverse of the rest — when it stabilizes,
guildmaster could pull it *from* colleague and re-broadcast it, the same way
`think`/`spec-to-plan` flow *from* devague.

Every vendored `SKILL.md` carries `type: command`. colleague
declares a culture agent (`culture.yaml`, `backend: claude`), and
`core.skill_loader` silently skips any `SKILL.md` lacking `type:` — so the field
is load-bearing, even where guildmaster's upstream copy omits it.

| Skill | Upstream | Origin | Notes | Last synced |
|-------|----------|--------|-------|-------------|
| `cicd` | `../guildmaster/.claude/skills/cicd/` | guildmaster | CI/CD lane layered on `agex pr`: the 5 thin scripts (`workflow.sh`, `pr-status.sh`, `pr-reply.sh`, `_resolve-nick.sh`, `portability-lint.sh`) delegate lint/open/read/reply/delta to `agex` and add the `status` / `await` SonarCloud-gating extensions. Consumer-identifying prose (`guildmaster` → `colleague`) adapted in the description + heading; upstream history (`Renamed from pr-review in steward 0.7.0; rebased on agex in 0.12.0`) and env-var literals (`STEWARD_*`) kept verbatim. The PR signature resolves at runtime from `culture.yaml` via `_resolve-nick.sh` (→ `colleague`). Requires `agex` on PATH. | 2026-05-26 (guildmaster 0.6.0) |
| `communicate` | `../guildmaster/.claude/skills/communicate/` | guildmaster | Cross-repo + mesh communication. Consumer-identifying prose adapted in the description (incl. the `- colleague (Claude)` signature line). **No hard-coded signature literal in the scripts** — `post-issue.sh` is `agtag`-backed and resolves the signing nick from `culture.yaml`; requires `agtag` (>=0.1) on PATH. The supplier `scripts/templates/` (`skill-update-brief.md`, `skill-new-brief.md`) are kept verbatim — inert for a consumer (they cite guildmaster as upstream). Renamed from `coordinate` in steward 0.8.0; absorbed `gh-issues` in 0.9.1. | 2026-05-26 (guildmaster 0.6.0) |
| `version-bump` | `../guildmaster/.claude/skills/version-bump/` | guildmaster | Pure-Python, CWD-aware (`scripts/bump.py`). Verbatim except added `type: command`. | 2026-05-26 (guildmaster 0.6.0) |
| `agent-config` | `../guildmaster/.claude/skills/agent-config/` | guildmaster (origin steward) | Shows a Culture agent's full config; run `scripts/show.sh` directly (no `guild` binary required). `scripts/show.sh` + `data/backend-fingerprints.yaml` verbatim. Verbatim except added `type: command`. | 2026-05-26 (guildmaster 0.6.0) |
| `doc-test-alignment` | (diverged) | **colleague** | **First-party implementation** — four-check spine (readme/claude/skills/tests). Originated in guildmaster as a STUB; colleague now ships a complete implementation with a working CLI. **Do NOT re-vendor from guildmaster** — offer this implementation upstream to guildmaster as a follow-up. | 2026-06-02 (first-party) |
| `pypi-maintainer` | `../guildmaster/.claude/skills/pypi-maintainer/` | guildmaster | Switch a package install between PyPI / TestPyPI / local editable (`scripts/switch-source.sh`). Verbatim except added `type: command`. | 2026-05-26 (guildmaster 0.6.0) |
| `run-tests` | `../guildmaster/.claude/skills/run-tests/` | guildmaster | pytest + xdist + coverage (`scripts/test.sh`). Verbatim except added `type: command`. | 2026-05-26 (guildmaster 0.6.0) |
| `sonarclaude` | `../guildmaster/.claude/skills/sonarclaude/` | guildmaster | SonarCloud API queries (`scripts/sonar.sh`). Verbatim except added `type: command`. | 2026-05-26 (guildmaster 0.6.0) |
| `think` | `../guildmaster/.claude/skills/think/` | **devague** (re-broadcast via guildmaster) | idea→spec leg of the devague workflow chain. Verbatim (already carried `type: command` at guildmaster). Origin/broadcast prose left verbatim. | 2026-05-26 (guildmaster 0.6.0) |
| `spec-to-plan` | `../guildmaster/.claude/skills/spec-to-plan/` | **devague** (re-broadcast via guildmaster) | spec→plan leg of the devague workflow chain. Verbatim (already carried `type: command`). | 2026-05-26 (guildmaster 0.6.0) |
| `assign-to-workforce` | `../guildmaster/.claude/skills/assign-to-workforce/` | **devague** (re-broadcast via guildmaster) | plan→parallel-implementation leg of the devague workflow chain. Verbatim (already carried `type: command`). | 2026-05-26 (guildmaster 0.6.0) |
| `summarize-delivery` | `../devague/.claude/skills/summarize-delivery/` | **devague** (cited direct — not yet re-broadcast) | delivery-side closure leg of the devague workflow chain: turns an `assign-to-workforce` run into a planned-vs-actual accountability artifact under `docs/deliveries/`. Method-only (no script, no CLI verb); uses read-only `devague plan show` / `plan waves` / `scope --list` / `show` / `status`. Verbatim (already carried `type: command`). Re-point at guildmaster once it re-broadcasts. | 2026-07-10 (devague 0.17.0) |
| `scope` | `../devague/.claude/skills/scope/` | **devague** (cited direct — not yet re-broadcast) | idea→scope leg: the optional opening move ahead of `/think` — surveys the surfaces an idea touches (code, docs, skills, CI, siblings) and seeds boundary / non-goal / assumption claims for the coming frame. Method-only (SKILL.md, no script). Verbatim (carries `type: command`). Re-point at guildmaster once it re-broadcasts. | 2026-07-15 (devague 0.19.1) |
| `challenge` | `../devague/.claude/skills/challenge/` | **devague** (cited direct — not yet re-broadcast) | blind-spot discovery pass **between** `/think` and `/spec-to-plan`: pressure-tests the converged, exported frame through structured lenses, routing every finding back through devague's deterministic moves as proposed-only content the human adjudicates. Method-only (SKILL.md, no script). Verbatim (carries `type: command`). Re-point at guildmaster once it re-broadcasts. | 2026-07-15 (devague 0.19.1) |
| `deviate` | `../devague/.claude/skills/deviate/` | **devague** (cited direct — not yet re-broadcast) | mid-run divergence leg: stops an in-flight `assign-to-workforce` run when execution must diverge from the confirmed plan, gets explicit human approval, and records an append-only deviation via `devague deviate` before resuming. Method-only (SKILL.md, no script). Verbatim (carries `type: command`). Re-point at guildmaster once it re-broadcasts. | 2026-07-15 (devague 0.19.1) |
| `ask-colleague` | — (first-party) | **colleague** | Authored here, not vendored: a portable wrapper (`scripts/ask-colleague.sh`) that drives the `colleague` CLI for `explore`/`review`/`write` — hand a scoped task to a different backend/mind. Carries `type: command`. | n/a (origin) |

## Re-sync procedure

```bash
# Diff against upstream before pulling (example: cicd / communicate):
for s in cicd communicate; do
  diff -ru ../guildmaster/.claude/skills/$s .claude/skills/$s
done

# Pull a skill fresh (remove first so dropped scripts don't linger):
rm -rf .claude/skills/<skill>
cp -R ../guildmaster/.claude/skills/<skill> .claude/skills/

# Re-apply the identifier-only adaptations in SKILL.md:
#   - consumer-identifying prose: `guildmaster` → `colleague` (NOT
#     where it cites guildmaster/steward/devague as the upstream/origin).
#   - add `type: command` to the frontmatter if guildmaster's copy omits it
#     (load-bearing for the culture/claude backend's core.skill_loader).
# No script bodies are edited (cite-don't-import). The communicate signature
# resolves from culture.yaml via agtag — no literal to patch.
```

If a re-sync would lose a colleague adaptation, lift the change
upstream into guildmaster first (per guildmaster's `docs/skill-sources.md`) and
re-vendor.

## learn-from-generated skills (the inverse direction)

The table above tracks `.claude/skills/` — the skills colleague *vendors in* for
its own Claude Code harness. `colleague learn-from claude` runs the **opposite
direction**: it reads those `.claude/skills/` and writes **derived** colleague
skills into `.colleague/skills/*.md` (which the runtime folds into every
backend's system prompt). These are NOT hand-vendored: each carries a
`<!-- learned-from: claude; source: …; adapt: … -->` provenance marker, so a
generated skill is always distinguishable from a hand-authored one (and
`learn-from` will not clobber a marker-less hand-authored doc without `--force`).
See [`docs/features/learn-from.md`](features/learn-from.md). The source is a
registry (currently just `claude`); future minds extend it without a re-vendor.

## Tooling prerequisites

- **`agex`** (>=0.21) on PATH — `cicd` delegates the PR lifecycle to `agex pr`.
- **`agtag`** (>=0.1) on PATH — `communicate` issue I/O wraps `agtag issue`.

Both ship on PATH in the standard AgentCulture dev setup (installed per the
agex-cli / agtag READMEs).
