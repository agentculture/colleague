# Pending decisions — delegation-follow-ups-a7-p3-hire

> **Working state — not committed by default.** Open questions / pending decisions for this frame. Apply a decision into the frame with the normal moves (e.g. `devague capture --kind decision "…"` then `devague confirm`), then mark it resolved here with `devague question --resolve <id>`.

## Open

None.

## Resolved

- [x] `q6`: Negotiation bound: 1 candidate round or 2? And is the candidate the same cortex model tools-off, or the base role's seat? — decided: Operator: negotiation is at most 2 candidate rounds (tools-off completion on the cortex model); a third disagreement = 'not hired'.
- [x] `q5`: Does hire_colleague require COLLEAGUE_AGENTS armed (ledger + typed delegate for free, but excluded from the default seat) or live on the default seat with a run-scoped roster on the executor recorded on the artifact, ledgered only when agents is also armed? — decided: Operator: hire_colleague lives on the DEFAULT seat (COLLEAGUE_HIRE=1 opt-in): roster on the executor, hires recorded on TaskResult with the authored prompt's digest; when COLLEAGUE_AGENTS is also armed the hire additionally emits a task-ledger event. Agents mode is never required.
- [x] `q4`: Where does a WINNING P3 trigger sentence promote to — BUILTIN_ROLES['writer'].prompt_fragment (spec q3's wording) or prompttext._PURPOSE_TOOLS where the shipped delegation prose actually lives (snapshot regen under a deviation)? — decided: Operator: a winning trigger promotes into prompttext._PURPOSE_TOOLS (beside the tools it names) — CONDITIONAL on gating that section to the top-level acting seat in the same PR, since today it renders for every seat incl. children that hold no purpose tool (c2/h10); if the gate is not taken, the writer fragment (the overlay-tested location) is the target.
- [x] `q3`: A7 instrument: a COLLEAGUE_ACTING_ADD_TOOLS env knob at the depth-0 seam (recommended — reverts by unset, no residue) or a temporary allow-list edit like arm 4 (needs a revert commit)? — decided: Operator: the A7 instrument is a COLLEAGUE_ACTING_ADD_TOOLS env knob at the depth-0 seam; unset = byte-identical; children stay stripped.
- [x] `q2`: P3 control: P2's first paragraph alone (recommended — the truthful seat description on this rig, and A6 ran P2) or the P0 overlay as #456 wrote? — decided: Operator: the control is P2-0 — P2's first paragraph alone; P3 = P2-0 + the trigger sentence.
- [x] `q1`: Split the frame? A7+P3 are an arms arc (one PR, v1.69.0); hire_colleague is a twelfth increment needing /think + /challenge of its own — keep one frame through /think and split at spec export, or split now? — decided: Operator 2026-08-30: keep ONE frame through /think; split into the arms PR (A7+P3, v1.69.0) and the hire increment spec at export.
