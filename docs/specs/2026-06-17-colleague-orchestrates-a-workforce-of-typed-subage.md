# Colleague orchestrates a workforce of typed subagents, each a role with its own prompt, curated tools, and skills — nesting agents of agents, with read-only roles that cannot write

> Colleague orchestrates a workforce of typed subagents, each a role with its own prompt, curated tools, and skills — nesting agents of agents, with read-only roles that cannot write

## Audience

- A backend (any engine) orchestrating a multi-step repo task, plus the operator who declares which roles exist and what each role may touch.

## Before → After

- Before: Today every subagent inherits the SAME full ten-tool surface and the SAME system prompt; only engine and model can switch. Depth is capped at 2, nested batches are forbidden, and a read-only explorer can still write_file and run_command.
- After: A parent work item delegates each scoped sub-task to a TYPED subagent (a role): the child gets a role-specific system prompt, a curated subset of the tool surface, and a curated skill subset, and roles nest recursively to a bounded depth.

## Why it matters

- Smaller, role-scoped contexts ship faster and safer: delegating more work in narrower scopes beats one large context, and a reviewer that cannot write cannot accidentally mutate the tree.

## Requirements

- Roles are operator-authored config with a small set of built-in defaults; absent config falls back to built-in defaults, and absent entirely is byte-identical to todays single full-surface role (purely additive).
  - honesty: With no .colleague/agents config present, a work item runs byte-identically to today (one full-surface role) — verified by the e2e mock shape test.
- A role declares a curated tool allow-list; the loop builds the childs offered tool schema from it (a subset of the base and curated tools) and the executor refuses any withheld tool; a read-only role withholds write_file, edit_file, AND the run_command write vector.
  - honesty: A role declared read-only cannot mutate the tree by ANY offered tool: write_file, edit_file, and run_command are all withheld from its schema and refused by the executor if hallucinated — closing the out-of-the-box-writing hole.
- Each role carries a tailored system-prompt fragment and a curated skill subset, composed through the existing layered-config seam (colleague/layers.py) with per-model override and exact-path isolation, reusing the skills/hooks overlay convention.
  - honesty: A role prompt fragment and its curated skills compose deterministically and per-model through the existing layered-config path, adding no second prompt-assembly code path.
- The subagent and subagents tools gain a role parameter; selection is backend-judged and optional, and omitting role is byte-identical to todays full-surface delegation.
  - honesty: Omitting the role parameter is byte-identical to todays delegation; passing a role is the only behavior change and it is the models choice, never automatic routing.
- Recursion goes deeper than today (agents of agents of agents) but stays structurally terminating: a single explicit global cap bounds the TOTAL agents spawned per top-level work item regardless of nesting shape, checked before any child work.
  - honesty: The total number of agents spawned under one top-level work item is provably bounded by an explicit cap for every nesting shape; a refused level does zero work and the recursion always terminates.
- The same role machinery serves every task type (explore, plan, write, review, validate), and the ask-colleague verbs and the colleague plan workforce stage can request a role per child.
  - honesty: One role-curation mechanism is exercised by explore, plan, write, review, and validate flows — not five parallel implementations.
- Roles are runtime-owned and obey the all-engines rule: a role-typed child yields the same TaskResult/SubResult shape on mock and vllm-openai, with zero new runtime deps and no socket or daemon; the e2e, boundary, and zero-deps guards still pass.
  - honesty: A role-typed childs result shape is identical on mock and vllm-openai, and dependencies stay empty (zero-deps guard green).
- A dedicated read-only test-runner loop tool (e.g. run_tests) lets a read-only role such as validator execute the repos tests and report pass/fail WITHOUT run_command or any file-write tool, reusing the affected-tests/pytest machinery and writing nothing.
  - honesty: The validator role can run the test suite and report pass/fail while its offered tool schema contains NO write_file, edit_file, or run_command — test execution is a separate read-only capability, not a write vector.

## Honesty conditions

- The orchestration is real and bounded: a read-only role cannot write by any offered tool, recursion terminates under an explicit global cap, and the whole feature is additive — absent role config means todays behavior, byte-for-byte.
- The feature serves BOTH the orchestrating backend (which picks a role) and the operator (who declares roles): each has a concrete surface — the role parameter vs the .colleague/agents config — neither is an afterthought.
- After shipping, a delegated sub-task given a role demonstrably changes the childs prompt, offered tool schema, and skills — all observable in the run artifact/trace.
- The stated before-state is accurate against current code: subagent/subagents expose only instruction/engine/model, MAX_SUBAGENT_DEPTH is 2, nested batches are nulled, and read-only is unenforced.
- The safety/speed claims are demonstrable not aspirational: a read-only role provably cannot mutate the tree, and a smaller curated surface does not regress the role.
- Everything in scope reuses existing seams (layered config, in-process loop, subagent launcher); nothing in scope needs a new runtime dep, socket, or daemon.
- Each named success signal is mechanically checkable in tests: the read-only schema, the deterministic prompt+skills compose, the global-cap termination bound, and the mock==vllm result shape.
- By default no offered tool can write outside the repo/worktree box; the free-run cross-repo mode is explicitly absent from this spec — there is no code path that enables an out-of-repo write here.

## Success signals

- A read-only role child has provably no write_file/edit_file/run_command in its offered tool schema (visible in the trace/artifact), a role prompt-plus-skills composes deterministically and per-model, recursion is bounded by an explicit global cap, and the same role fires identically on mock and vllm-openai.

## Scope / boundaries

- In scope: typed roles (prompt plus curated tools plus curated skills), read-only enforcement by tool withholding, bounded deeper recursion, and a role parameter on the existing subagent tools. Roles are stdlib config plus the existing in-process loop.
- Writes are confined to the repo and the agents own throwaway worktree (the existing write-isolation plus path confinement); an agent never writes outside its repo box. Writing BEYOND a single repo is a separate gated free-run mode, not part of typed-subagent orchestration.

## Non-goals

- NOT a multi-backend router: role selection is backend-judged or operator-declared, never an automatic task-to-model routing policy.
- NOT an execution sandbox: read-only is enforced structurally by NOT offering write tools, not by OS-level sandboxing; run_command stays bypassable per the existing trusted-operator (D2) model.
- NOT a daemon, socket, or new runtime dependency: roles reuse the layered-config loader and the in-process subagent loop, like commands, hooks, and skills.

## Assumptions

- A curated, smaller per-role tool surface helps rather than hurts the served model (fewer tools means less confusion and lower cost) and is not a capability regression for the role.

## Decisions

- Built-in default roles: explorer (read-only), planner (read-only thinker), reviewer (read-only), validator (read plus test-run, no file write), writer (full surface).
- Recursion bound set to depth 4 and a single global per-top-level cap of 24 total agents; nested batches are allowed but EVERY spawned agent counts against the 24-cap, checked before any child work so termination stays structural.

## Open / follow-up

- An orchestrator meta-role that dynamically composes a chain of differently-typed children (a role that plans roles) — deferred past v1.
- A free-run mode where colleague writes BEYOND a single repo (cross-repo) — a special mode that requires an issue and explicit thinking before any out-of-repo write; deferred, out of scope for typed-subagent orchestration.
