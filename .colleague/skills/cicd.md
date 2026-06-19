colleague's CI/CD lane, layered on `devex pr` (the same PR-lifecycle CLI as `agex`, invoked under the `devex` name). Delegates lint / open / read / reply / delta to devex; adds two extensions — `status` (SonarCloud quality gate + hotspots + unresolved-thread tally) and `await` (read --wait + status with non-zero exit on Sonar ERROR or unresolved threads). Use when: creating PRs in colleague, handling review feedback, polling CI status, or the user says "create PR", "review comments", "address feedback", "resolve threads".

<!-- learned-from: claude; source: .claude/skills/cicd/SKILL.md; scripts: .claude/skills/cicd/scripts; adapt: claude->colleague -->

# cicd

# CI/CD — colleague edition

This skill drives **`devex pr`** — the agentculture PR-lifecycle CLI,
invoked under the `devex` name. `devex` is the **same tool as `agex`**
(upstream `agentculture/agex-cli`); colleague standardizes on the
`devex` name and never shells out to `gh` directly to open a PR.

Use the `culture` tool to invoke `devex pr` from within a colleague
work loop, or `run_command` to call it directly. Colleague does not
ship shell wrapper scripts — call `devex pr <verb>` directly.

`devex pr` provides the core PR-lifecycle verbs — `lint`, `open`,
`read`, `reply`, `delta`, and the native `await` combo verb. The
`status` and `await` extensions described below are best-effort
compositions of `devex pr` with `gh` and `curl` for SonarCloud gating;
they are not native to the CLI yet (tracked upstream in
[agex-cli#52](https://github.com/agentculture/agex-cli/issues/52)).

## Prerequisites

Hard requirements: `devex` (the agentculture PR CLI; same tool as
`agex`), `gh` (GitHub CLI — used by the `status` / `reply` gating
helpers, never to open a PR), `jq`, `bash`, `python3` (stdlib only),
`curl` (for SonarCloud queries).

Install devex once:

```bash
uv tool install devex   # or: pip install --user devex
```

Soft requirement: `PyYAML` is needed **only for suffix mode** of the
sibling `agent-config` skill, where it parses Culture's server
manifest. Every `cicd` step works without it; suffix mode prints a
clear install hint when invoked without it.

Per-machine paths (sibling-project layout) live in
`.colleague/skills.local.yaml`; see the committed `.example` for the
schema. `devex pr delta` reads the same file.

## How to run

Call `devex pr <verb>` directly. Colleague has no shell wrapper scripts.

| Command | What it does |
|---------|--------------|
| `devex pr lint --exit-on-violation` | Portability + alignment-trigger check. |
| `devex pr open --delayed-read [flags]` | Creates the PR, then polls 180s for an initial briefing. `--title TITLE` required; body via `--body-file PATH` or stdin. |
| `devex pr read [PR] [--wait N]` | One-shot briefing (CI checks, SonarCloud gate + new issues, all comments, next-step footer). Pass `--wait N` to poll up to N seconds for required reviewers. |
| `devex pr reply <PR>` | Batch JSONL replies (stdin) + thread resolve. devex auto-signs from `culture.yaml`. |
| `devex pr delta` | Sibling alignment dump. |
| `devex pr status <PR>` | **Extension.** Sonar gate, OPEN issues, hotspots, unresolved-thread breakdown, deploy preview URL. Authoritative gate for `await`. |
| `devex pr await <PR>` | **Extension.** `devex pr read --wait` then `status`. Exits non-zero on Sonar ERROR or unresolved threads. Tunables: `COLLEAGUE_PR_AWAIT_WAIT` (default 1800s passed to `--wait`). |
| `devex pr help` | Print the list. |

The `status` and `await` extensions are compositions you drive via
`run_command` or the `culture` tool. When the native CLI gains these
features upstream, the shell compositions retire.

## Long waits (background polling)

`devex pr read --wait N` polls in-session for up to N seconds. Two
ways to drive the wait:

- **Synchronous** — `devex pr await <PR>` after `devex pr open`.
  Fine when readiness is expected within ~5 minutes.
- **Asynchronous** — for longer waits, run `devex pr read --wait NNN`
  inside a background subagent (use the `subagent` tool with a
  read-only role) so the main session stays responsive. The
  subagent's only job is to invoke `devex pr read --wait` and echo
  its headline back. The parent triages with `devex pr await` when
  the notification arrives.

## Conventions

`devex pr` emits a **"Next step:"** footer at the end of every command
that names the right next verb — follow that rather than memorizing an
order.

Branch naming: `fix/<desc>`, `feat/<desc>`, `docs/<desc>`,
`skill/<name>`. PR / comment signature: `- <nick> (Claude)`, where
`<nick>` is resolved by `devex` from the agent's own `culture.yaml`
(first agent's `suffix`), falling back to the git-repo basename. devex
auto-appends the signature on `pr open` and `pr reply` only when the
body isn't already signed.

## Finishing a branch

When implementation on a branch is complete and tests pass, go straight
to `devex pr open` (push the branch + open the PR). Do **not** stop to
present a *merge / PR / keep / discard* menu and wait for a choice — in
AgentCulture the standing default is **always "push and create a Pull
Request."**

## Triage rules

For every comment, decide **FIX** or **PUSHBACK** with reasoning.

Default to **FIX** for: portability complaints (always valid for
colleague — recurring bug class), test or doc requests, style nits
aligned with workspace conventions.

Default to **PUSHBACK** for: architecture opinions that conflict with
workspace `CLAUDE.md` or the all-backends rule; greenfield
false-positives (e.g. "add tests" before there's any source — defer
to a later PR, don't refuse).

### Alignment-delta rule

If the PR touches `CLAUDE.md`, `culture.yaml`, or anything under
`.colleague/skills/`, run `devex pr delta` **before** declaring FIX or
PUSHBACK on each comment. Note any sibling that needs a follow-up PR
and mention it in your reply.

## Greenfield-aware steps

The lint and the workflow are always-on. Stack-specific steps
are conditional and currently no-op (greenfield repo):

```bash
[ -d tests ] && [ -f pyproject.toml ] && uv run pytest tests/ -x -q
[ -f pyproject.toml ] && bump_version_per_project_convention   # see project README
[ -f .markdownlint-cli2.yaml ] && markdownlint-cli2 "$(git diff --name-only --cached '*.md')"
```

Revisit each line as the corresponding stack element actually lands.

## Reply etiquette

Every comment must get a reply — no silent fixes. `devex pr reply`
includes thread-resolve by default. Reference the review-comment IDs
in the fix-up commit message.

The `status` extension queries SonarCloud directly. Both surfaces are
trustworthy — `devex pr read` for display in the briefing, `status` for
the gate.
