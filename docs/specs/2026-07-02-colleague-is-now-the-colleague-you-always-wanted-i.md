# Colleague is now the colleague you always wanted: it remembers and learns from every run - eidetic and daria memory inform its context before it starts - it wastes fewer steps across the whole arc from scope through plan, explore, work, review and live-test, and it takes work fully off your hands: run it detached in the background, or let it live in the culture mesh as a resident (via the agent-lifecycle harness seam) that runs its own instances.

> Colleague is now the colleague you always wanted: it remembers and learns from every run - eidetic and daria memory inform its context before it starts - it wastes fewer steps across the whole arc from scope through plan, explore, work, review and live-test, and it takes work fully off your hands: run it detached in the background, or let it live in the culture mesh as a resident (via the agent-lifecycle harness seam) that runs its own instances.

## Audience

- Claude (the orchestrating agent), the operator (Ori), and mesh peers who delegate field-work to colleague and need it to be reliable hands and a diverse second mind

## Before → After

- Before: Every run starts cold: colleague re-derives repo knowledge each time (no recall of prior runs), explore wastes steps and mis-cites line numbers (#240), finish can return a meta-description instead of findings (#231), a malformed finish loses the structured report from the artifact (#248), substantial writes do not land in one drive (#237), concurrent runs trip spurious gate failures (#239), and every run occupies a foreground terminal of the caller
- After: A delegated task starts warm - colleague recalls repo-scoped memory (prior decisions, gotchas, repo map) before working - runs efficiently with fewer wasted steps, records what it learned afterward, and can run fully detached: the caller fires it into the background (or hands it to the resident) and folds results back later via artifact, flight feed, and feedback, never blocking a foreground terminal

## Why it matters

- Delegation ROI compounds: the more colleague can be trusted to run unattended, remember, and self-improve, the more field-work moves off Claude and the operator - a diverse mind that gets cheaper and smarter with every run instead of resetting to zero

## Requirements

- R1 memory-informed runtime: colleague recalls before work (repo-scoped eidetic recall folded into the task context at start) and remembers after (a lesson record per work item: what wasted steps, what worked), via shell-out to the operator-installed eidetic CLI with a curated allow-list - the same pattern as the culture/devague tools; absent eidetic CLI = strict no-op
  - honesty: Absent eidetic CLI = strict no-op (byte-identical artifact); recall injection is token-capped and recorded in the artifact so a misleading memory is diagnosable; colleague writes only to its own scope
- R2 report reliability cluster: a work item's findings always survive to the caller - fix #248 (structured report lost on malformed finish or completion-budget exhaustion), #231 (finish returns the findings themselves, never a meta-description), #240 (explore cites accurate line numbers)
  - honesty: Each of #248/#231/#240 gets a regression test reproducing the observed failure BEFORE the fix; the artifact always carries the report or an honest degradation marker, never silence
- R3 substantial writes land: a too-large write task decomposes (plan-first into subagent waves via the existing auto-split/plan machinery) so ask-colleague write can land substantial implementations instead of stalling in one drive (#237)
  - honesty: Proven on a real substantial task against the live rig (the #237 evidence class), not only unit fixtures; if the served model still cannot land it decomposed, that is recorded as a model limit, not claimed solved
- R4 background one-shot: colleague work --background detaches the run (no foreground terminal), with the existing flight control plane as the pilot interface (status/guide/stop), the artifact + feedback as the result interface, and honest crash-residue cleanup (clean reaps a dead background run)
  - honesty: A killed background run leaves recoverable state (partial artifact + reapable residue via clean) and never wedges the repo; detach is one-shot, no polling daemon
- R5 mesh residency (appserver mode): colleague implements agent-lifecycle's Harness interface and lives in the culture mesh as a resident that accepts work requests over the transport, runs them as background work items (including spawning its own colleague instances, governed by the rig budget), and reports results back - the daemon/supervision belongs to agent-lifecycle, not colleague
  - honesty: Resident path gated behind an opt-in extra; a base install stays daemon-free and byte-identical; supervision failures surface via agent-lifecycle failure(), never silently
- R6 concurrent-run correctness: two colleague processes on one repo never trip spurious pre-handoff gate failures (#239) - gates scope to the run's own worktree/changed-files, composing with the rig-slot budget (#258)
  - honesty: Reproduce #239's spurious failure deterministically first; after the fix, two concurrent runs on one repo pass gates with disjoint changed-files
- R7 live-test the arc now the rig serves tool-calling again: run the pending live proofs (mode profiles test_vllm_live_mode.py, deepthink test_dual_live.py, edit_file row), update the ledger, and make the live check repeatable as a single verb (e.g. colleague livecheck) so live validation stops being a manual procedure
  - honesty: Ledger rows updated with commit+date+evidence per procedure; a proof that fails live is recorded honestly as failed/partial, never retro-fitted

## Honesty conditions

- Each of the three legs (memory, arc efficiency, background/residency) ships as its own verifiable increment; the announcement never claims a leg with no landed evidence
- The delegating caller (Claude via ask-colleague, a mesh peer via the transport) can consume results without reading colleague source - artifact + flight + feedback are the entire interface
- Warm-start is measurable: WorkStats of a memory-warm run vs the same task cold shows the saving; if it does not, the claim is retracted, not massaged
- Each named inefficiency is reproduced or evidenced from a real artifact/issue before it is fixed - no phantom problems
- ROI is computed from the existing stats + feedback loop, never just asserted
- colleague ships no socket/daemon code of its own: resident supervision is imported from agent-lifecycle, background one-shots are detached child processes with file-based control; the boundary test suite extends to pin this
- The warm-vs-cold comparison runs on the live rig with the same task, both artifact ids + WorkStats recorded in the feature doc; the first honest comparison counts - no cherry-picking
- The zero-terminal path is demonstrated live end-to-end (detached start, flight status, completion, feedback grade); the resident round-trip is demonstrated over a real transport once agent-lifecycle ships one - until then the resident row is recorded PENDING, never claimed

## Success signals

- A memory-warm work item demonstrably saves steps/tokens vs the same task cold (measured via the always-on WorkStats), and a lesson recorded by one run is recalled by a later run
- A background work item completes with zero foreground terminal: fired detached, piloted via flight, graded via feedback afterward; the resident accepts a work request over the mesh and returns the result

## Scope / boundaries

- Not a multi-model router, not a sandbox, not a colleague-invented daemon: the resident leg builds on agent-lifecycle's Harness seam (colleague is a named proving harness) + the existing promote path, background one-shots reuse the existing flight control plane; memory lives in eidetic's store (colleague invents no store of its own); daria integration is observational (colleague feeds/reads awareness, daria is not in the work loop)

## Non-goals

- No automatic task-to-model routing policy, no N-model generalization beyond the landed deepthink increment, no execution sandbox, no MCP client - the existing out-of-scope lines all hold except the two this spec deliberately re-specs: background execution and mesh residency

## Assumptions

- daria (data-refinery) integration stays observational in this increment: colleague's artifacts/lessons become material daria can observe and investigate; daria does not enter the work loop - deeper coupling is a follow-up once the eidetic leg proves out

## Decisions

- The no-daemon convention is deliberately re-specced (the third recorded convention change, after the agentfront base dep and the LLM self-summary): background/resident operation is IN scope, with the honest split that process supervision + transport belong to agent-lifecycle/culture and colleague contributes the Harness implementation and detached one-shots
- Resident trust model (resolves v4): any channel member can ASK the resident for work, but only the operator has authority - authoritative decisions and confirmations are operator-only; the agent can always refuse a request beyond the limits of its logic, and in case of doubt it can consult other agents for group intelligence before acting

## Open / follow-up

- Deeper daria coupling (colleague consulting daria's investigations mid-run) - follow-up once the eidetic leg proves out
