Cross-repo + mesh communication from colleague: file tracked GitHub issues on sibling repos, fetch issues from sibling repos to inline current state into briefs, and send live messages to Culture mesh channels. Use when the next step lives outside colleague (a brief for a sibling-repo agent, a status ping for a Culture channel, or pulling an issue body + comments into context). Issue posts auto-sign with `- colleague (Claude)`; mesh messages are unsigned (the IRC nick is the speaker). Not for in-colleague issues — use `gh issue create` or the `cicd` skill for those. Renamed from `coordinate` in steward 0.8.0; absorbed `gh-issues` in 0.9.1. Issue I/O is backed by `agtag` (>=0.1) starting in 0.11.0.

<!-- learned-from: claude; source: .claude/skills/communicate/SKILL.md; scripts: .claude/skills/communicate/scripts; adapt: claude->colleague -->

# communicate

# Communicate (Cross-Repo + Mesh)

Steward's job is alignment across the AgentCulture mesh; that surfaces in
four distinct channels:

- **Tracked, async hand-offs** — a gap in another repo (a missing public
  API, a divergent skill, a documentation ask) where an agent on the
  other side needs to act, and the ask should outlive the conversation.
  → `agtag issue post` (via the `culture` tool).
- **Follow-up on a tracked thread** — a status update, an answer to a
  question, or a "this is done" note on an issue that's already open.
  → `agtag issue reply` (via the `culture` tool).
- **Inbound state read** — pulling current issue body + comments from a
  sibling repo so a brief or plan can inline what's there instead of
  saying "see issue #N." → `agtag issue fetch` (via the `culture` tool).
- **Ephemeral coordination** — a status ping, a question, a "PR ready
  for merge" notice on a Culture mesh channel where the audience is
  already listening.
  → `culture channel message` (via the `culture` tool).

All four live under one skill because they share the same audience
(sibling-repo agents) and the same red flag (don't double-post the same
ask across post + mesh — pick one).

## Backed by agtag

The three GitHub verbs (`post`, `reply`, `fetch`) are thin wrappers
around the `agtag` CLI, invoked through colleague's `culture` tool
(`culture cli agtag`). agtag handles auto-signature resolution from the
local `culture.yaml` (falling back to repo basename), JSON output mode,
and a uniform exit-code policy. Read `agtag learn` for the agent-facing
self-teaching prompt and `agtag explain agtag` / `agtag explain issue`
for the surface docs — this skill doc does not re-document agtag's
flags.

Mesh messaging uses `culture channel message` directly; agtag mesh
transport is slated for a future agtag release.

## When to Use

### Issue mode (`agtag issue post`)

- A gap surfaces in **another repo's surface** (missing public API,
  wire-format compat fix, divergent skill, documentation ask).
- You're handing off a self-contained brief to a sibling-repo agent.
- You're asking a question that benefits from a tracked artifact rather
  than ephemeral chat.

### Broadcast mode (manual per-consumer)

- You bumped a skill in `.colleague/skills/<name>/` and the change is
  more than identifier-only or doc-only — downstream consumers will
  benefit from re-vendoring.
- Hand-author the brief (what's stale, cite locations, what's in
  upstream now, recipe, acceptance criteria, references), then post
  via `agtag issue post` per consumer.

### Mesh mode (`culture channel message`)

- You want to ping a Culture channel with a status update ("PR #N ready
  for merge", "starting nightly corpus scan").
- You're asking a question where you expect a fast reply from whoever
  is listening on the channel right now.
- You're announcing a decision that doesn't need a tracked artifact.

### Comment mode (`agtag issue reply`)

- An open issue needs a follow-up — a status update, an answer to a
  maintainer's question, a "this is shipped" note pointing at a PR.
- You're closing the loop on an `agtag issue post` you sent earlier and
  the resolution belongs on the same thread (audit trail beats a
  separate ping).
- Auto-signed by agtag; do not hand-author the trailing nick.

### Fetch mode (`agtag issue fetch`)

- You're about to write a brief and want to inline the current state of
  one or more sibling-repo issues (body + comments) instead of saying
  "see issue #N."
- You're triaging a list of cross-repo issues and want their bodies and
  comments in one shot for context.

## When NOT to Use

- **In-colleague issues** — open them with `gh issue create` directly, or
  work them through the `cicd` skill.
- **PR review comments** — that's the `cicd` skill (which already
  auto-signs replies).
- **Routine commits** — those don't get cross-repo signatures.
- **Long-form asks on the mesh** — anything that needs acceptance
  criteria belongs in an issue, not a channel message.

## Conventions

### 1. Briefs are self-contained

The receiving agent must not need steward-side context to act. Inline
the relevant content; do not say "see steward's plan."

A brief that says "see steward#NN" is a bug. The receiving agent will
look at it, get lost in steward-specific context that's irrelevant to
them, and either ask for clarification (slow round-trip) or guess wrong
(worse). Inline the ask, the rationale, and concrete acceptance
criteria. Quote source-of-truth files (path + line numbers + small
excerpts) when their shape matters to the ask.

### 2. Per-channel signature rules

| Channel | Signature | Why |
|---------|-----------|-----|
| GitHub issues / comments | `- <nick> (Claude)` — agtag resolves `<nick>` from the local `culture.yaml`, falling back to repo basename | Cross-repo audit trail — readers can tell at a glance which sibling and that it came from an AI. |
| Culture mesh | none — unsigned | The IRC nick already identifies the speaker. A trailing `- <nick> (Claude)` would be visual noise that the nick already supplies. |

Vendors do not need to edit a literal — agtag does the resolution.
`--as NICK` overrides if a vendor needs to sign as something other than
its `culture.yaml` suffix. Mesh messages stay unsigned across all
vendors.

### 3. Issue title format

`<verb> <thing> (unblocks <consumer>)` — e.g.,
`Vendor portability-lint into <repo> (unblocks steward 0.7 doctor --apply)`.
The parenthetical tells the receiving repo's maintainers what's waiting
on them. Drop the parenthetical only when the ask isn't blocking
anything.

## How to Invoke

Colleague does not execute shell scripts. Use the `culture` tool to
invoke `agtag` or `culture` subcommands.

### File a new issue

```
culture cli agtag issue post --repo agentculture/<sibling> --title "..." --body-file /tmp/brief.md
```

Or write the brief body to a file first (using `write_file`), then pass
`--body-file`. The command prints the issue URL on success — capture it
for cross-references in your spec / plan / PR description. agtag
appends the signature `- <nick> (Claude)` (resolved from `culture.yaml`).

### Comment on an existing issue

```
culture cli agtag issue reply --repo agentculture/<sibling> --number 42 --body-file /tmp/follow-up.md
```

Auto-signed by agtag from `culture.yaml`; do not hand-author the
trailing nick.

### Send a mesh channel message

```
culture cli culture channel message <target> <text>
```

The command wraps the Culture CLI and forwards exit codes unchanged, so
failures (no Culture server, agent not connected) surface verbatim. No
signature is appended — the IRC nick is the speaker.

### Fetch sibling-repo issues

```
culture cli agtag issue fetch 191 --repo agentculture/culture
culture cli agtag issue fetch 191-197 --repo agentculture/culture
culture cli agtag issue fetch 191 195 197
```

Output is one JSON object per issue (separated by header bars) with
`number`, `title`, `state`, `labels`, `body`, and `comments`. Without
`--repo`, `gh` resolves the repo from the current git remote. Failures
on a single issue print `ERROR: Could not fetch issue #N` and continue
with the next one.

## Red Flags

**Never:**

- Scaffold or write files into the *target* repo when the ask is an issue on
  it. Handing off / onboarding is an **issue, not an edit** — a direct "set
  them up" is still an instruction to file the brief.
- Post a brief that says "see steward's plan" without inlining the
  content. Briefs must be self-contained.
- Skip the issue signature. The script enforces it; do not introduce a
  `--no-signature` flag.
- Sign mesh messages with `- <nick> (Claude)`. The nick already says
  who you are.
- Use this skill for in-colleague issues — use `gh issue create` or the
  `cicd` skill instead.
- Manually type `- <nick> (Claude)` at the end of an issue or comment
  body — agtag appends it. Manual typing creates double-signatures.
- Post the same ask twice across channels (issue + mesh). Pick one.
  Tracked → issue. Ephemeral → mesh.
- Use mesh mode for anything that needs acceptance criteria. If the
  receiving agent has to decide "did I do this right?", you owe them
  an issue.
