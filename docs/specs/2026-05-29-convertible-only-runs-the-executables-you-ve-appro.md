# Convertible only runs the executables you've approved: a declarative policy allow/deny-lists run_command CLIs by name and pins lifecycle hook scripts and command templates to an approved version or checksum, while declarative skills and AGENTS instructions keep loading freely — and with no policy file present, behaviour is byte-identical to today.

> Convertible only runs the executables you've approved: a declarative policy allow/deny-lists run_command CLIs by name and pins lifecycle hook scripts and command templates to an approved version or checksum, while declarative skills and AGENTS instructions keep loading freely — and with no policy file present, behaviour is byte-identical to today.

## Audience

- Operators running convertible against a repo who want to constrain what the harness executes without hand-writing a pre_tool hook; plus every engine, which inherits the gate via the chassis (all-engines rule).

## Before → After

- Before: run_command is ungated by design (D2, trusted-operator) so every command is auto-approved; the only narrowing today is a hand-rolled pre_tool hook script; repo-shipped hooks and command templates run with content nobody pinned (no integrity/drift check); the per-repo hook trust gate is tracked but unbuilt.
- After: An operator drops a declarative policy into .convertible/ that (a) allow/deny-lists run_command program tokens by name and (b) pins each lifecycle hook script and command template to an approved version or content checksum; only approved executables run, unapproved ones are denied + fed back to the model + recorded; declarative skills and AGENTS stay ungated and load freely.

## Why it matters

- Turns 'give convertible a list of what it may run, and refuse what I did not approve' into a two-line config edit with one well-tested implementation, instead of pushing parse/decide logic onto every operator's hand-rolled script; and adds content-integrity (drift detection) for the executables the harness ships with.

## Requirements

- R2 Strict no-op default: absent any policy file in .convertible/, no gating occurs and TaskResult is unchanged (back-compat).
  - honesty: With no .convertible/ policy file, the JSON artifact is byte-identical to a policy-free run and the zero-deps + e2e shape tests pass.
- R3 run_command name gate: program token extracted with shlex; an allow-list denies tokens not listed, a deny-list blocks listed tokens (issue #55).
  - honesty: shlex.split yields the program token; an allow-list denies a token not listed and a deny-list blocks a listed token; documented plainly as bypassable (sh -c, pipes) — a policy gate, not a sandbox.
- R4 Content-integrity gate: each hook script and command template is pinned by an approval entry keyed by version OR checksum; a file whose current version/hash does not match its approval is refused + recorded.
  - honesty: Checksum is computed with hashlib over the file bytes; a changed file fails to match its approval and is denied + recorded; the honest limit is documented — md5 catches accidental drift, adversarial tampering needs a collision-resistant hash.
- R5 Declarative carve-out: skills and AGENTS instructions are never gated; resolve_skills/resolve_agents stay unchanged and still load under an active policy.
  - honesty: A test asserts skills + AGENTS still load and fold into the system prompt while a policy is active; the gate code path is never reached for declarative config.
- R6 Per-model overlay: .convertible/<sanitize_model(model)>/ policy composes ahead of base with exact-path isolation and no sibling globbing, mirroring hooks/AGENTS/skills layering (layers.py).
  - honesty: The overlay path is built by exact construction via sanitize_model; a test proves model X never loads model Y's policy (no glob over sibling .convertible/*/ dirs).
- R8 Deny feedback: a denied executable is fed back to the model as the tool result and recorded in the step trace / result, mirroring the pre_tool deny path; it never crashes the drive.
  - honesty: The deny path mirrors the existing pre_tool deny in loop.py: the reason is fed back as the tool result, recorded as a non-ok Step / firing, and the drive continues to the next turn.
- R9 Zero-deps convention: stdlib only (json, shlex, hashlib, pathlib); no socket, no daemon, hook/CLI code never imported; the zero-deps guard imports the new module and asserts no third-party leak.
  - honesty: The zero-deps guard (tests/test_zero_deps.py) imports the new policy module and asserts no third-party import leaks, even with the [otel] extra installed.
- R10 Enforcement mode: a category (run_command / hooks / commands) is gated only when its section is present in the policy; once present, only approved (hash/version-matching) entries are permitted and unapproved-or-tampered ones are denied + recorded; with no policy file (or no section for a category) that category is a strict no-op (back-compat).
  - honesty: A test proves: with no policy file the artifact is byte-identical (no-op); with a 'hooks' approval section present, an approved hook runs and an unapproved/tampered one is denied + recorded, while run_command stays ungated until its section is added.
- R1 Chassis-owned enforcement at the EXISTING control points: run_command and hook execution are gated in the loop's pre_tool / hook-firing path (loop.py / tools.py / hooks.py); command-template approval is checked at expansion (commands.py, before the drive starts). All are chassis-owned so every engine inherits them identically (all-engines rule); no engine module touches the policy.
  - honesty: One test drives mock and vllm-openai through the same policy and sees identical run_command + hook denials; a separate test shows a drifted command template is refused at expand time, before any engine runs.
- R7 Surface on EXISTING nouns (no new 'approvals' noun): 'commands' and 'hooks' gain an 'approve <name>' write-verb that records a version/checksum approval into the policy file; 'commands' / 'hooks' / 'skills' 'list' shows approval + accessibility status; 'hooks list' also shows the run_command allow/deny policy. Every verb supports --json, failures raise CliError, each noun keeps 'overview', and explain catalog entries are updated for the new verb.
  - honesty: teken cli doctor . --strict stays green: each noun carrying the new 'approve' action-verb still exposes 'overview', every verb supports --json, 'approve' writes the policy file, and an 'explain' catalog entry exists for 'approve'.

## Honesty conditions

- Shipped behaviour matches the announcement: with a policy present an unapproved/tampered run_command CLI or hook is refused and recorded; skills + AGENTS still load; with no policy file nothing changes — each proven by a test.
- The audience is real: an operator can constrain execution with a declarative config edit instead of a hand-rolled pre_tool hook, and every engine inherits the gate because it lives in the chassis (loop/tools/hooks/commands), not in any engine module.
- The gap is real in today's code: run_command is ungated (tools.py, D2), the only narrowing is a hand-written pre_tool hook, and shipped hooks/templates have no content-integrity check — all verifiable in the current tree.
- The after-state is buildable with stdlib only: one JSON policy drives name-gating (shlex) + checksum/version approval (hashlib), denials are recorded, and skills/AGENTS stay ungated — each leg proven by a test.
- The value holds: one well-tested implementation replaces every operator's hand-rolled hook script, and content-drift detection is genuinely new; the README/CLAUDE.md framing matches what ships.
- The non-goals are honest: the bypass vectors (sh -c, pipelines, shell expansion) are documented as such in code+docs, and no daemon/socket/runtime-dep/MCP is added — the zero-deps guard enforces the last part.
- The success signals are observable: a no-policy run is byte-identical (e2e shape test), and an unapproved/drifted-artifact denial is identical across mock + vllm-openai and inspectable via the list verb (--json).

## Success signals

- With no policy file, behaviour is byte-identical to today (e2e shape + zero-deps guards pass). With a policy, an unapproved CLI / drifted hook / drifted command template is denied identically on mock and vllm-openai, recorded in the result, and inspectable via 'convertible <noun> list --json'.

## Scope / boundaries

- Not a sandbox: token/hash matching is bypassable by sh -c, pipelines, and shell expansion; an airtight execution sandbox stays out of v0. No daemon, no socket, no new runtime dep, no MCP client. Declarative config (skills/AGENTS) is never gated by design.

## Decisions

- Ships behind a version bump like every PR (version-check CI blocks merge otherwise); lands via this re-spec + plan committed on the branch, per v0 discipline.
- Hash values are algorithm-prefixed: 'sha256:<hex>' is the documented default; 'md5:<hex>' is honoured when written but documented as accidental-drift detection only, not adversarial integrity. (Resolves the hash-primitive fork.)
- One unified policy surface covers both gates: the run_command name allow/deny-list AND the hook/command content-approvals live together; the run_command name-list is surfaced under the existing 'hooks' noun ('convertible hooks list' shows hook approvals + run_command allow/deny). (Resolves the scope + run_command-location forks.)
- Approval IS tamper-protection, not mere name-listing: 'approve' records the artifact's current version/checksum; if the artifact is later manipulated the approval is automatically void (hash mismatch) and it is no longer trusted. Being loaded/accessible (a skill in the prompt, a discoverable command) never implies approval.
- The CLI surface hangs off the EXISTING nouns, not a new 'approvals' noun: 'convertible commands|hooks approve <name>' records an approval; 'convertible commands|hooks|skills list' shows approval/accessibility status. The 'approve' write-verb is in v0 scope. (Resolves the noun-name + approve-verb forks.)
- Skills + AGENTS are not approval-gated in v0 (declarative; loaded = accessible). A 'skills approve' that tamper-protects skill-doc content is a documented possible follow-up, not v0 scope.
