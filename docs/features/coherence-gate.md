# Coherence gate — colleague scores the meaning of what it hands back

The fourth rack gate (#294, colleague#291 S3), sibling to the lint,
test-integrity, and affected-tests gates: after a non-aborted tool loop,
before the git handoff, the runtime scores the work item's changed
documentation artifacts (`*.md`) with the operator-installed `coherence` CLI
(`coherence meaning score <file> --json` — the Meaning Gradient, coherence-cli
0.5.x) and records the result on `TaskResult.coherence_report`
(omit-when-None).

## Semantics

- **Advisory + warn-only, always.** No fix-turn, no threshold, never blocks
  the handoff, never flips a run's status. Measured separations hug the 0.5
  midpoint upstream (no calibrated good/bad line exists), so every result is
  a recorded observation, not a judgment.
- **Default-ON with the standard opt-out** (the #291 operator decision):
  `--no-coherence` flag > `COLLEAGUE_COHERENCE=0` env > `.colleague/config.json`
  `{"coherence": false}` > default-on.
- **Configured-detection (the lint precedent).** Lint fires only when the repo
  configures a linter; the coherence analog is an embedder endpoint colleague
  actually knows about — `COHERENCE_EMBED_URL` in the operator's environment
  or injected from the lobes-resolved `embedder` role
  (`colleague/lobes.py` `embed_env`, S2/#293). Without one, every
  `meaning score --json` call exit-2s with no payload (probed live
  2026-07-06), so an unconfigured machine is a strict no-op — byte-identical
  `TaskResult`, no subprocess.
- **Frame provenance (coherence-cli#10).** The report records the embedding
  frame that produced each score (`embed_url`/`embed_model` — the measurement's
  gauge): a meaning score is a *model-relative, anchor-defined* measurement,
  never universal meaning. Unknown payload keys (e.g. a future native `frame`
  block) pass through verbatim.
- **Pinned consumer seam.** The parse is tested against a payload copied
  verbatim from a live `coherence meaning score --json` run, so the
  coherence-cli#11 domain restructure (which keeps the `meaning` noun stable
  per its own decision) cannot silently break the gate.
- **Degradation (h7 — diagnosable, never silent):** CLI absent → a `skipped`
  report with the install hint; a per-file failure (e.g. exit 2, embedder
  unreachable) → that file records the CLI's structured `error`, other files
  still score; the whole gate is fail-safe-wrapped and can never abort `run()`.

## Where it lives

`colleague/coherence.py` (the runner — a sanctioned subprocess consumer,
allow-list exactly `coherence`) + `colleague/loop.py`
`_maybe_run_coherence_gate` (after the lint gate, so it sees the lint-fixed
changed set). Runtime-owned: fires identically for every backend (all-engines
rule). Diagnostics surface as `coherence:` stderr hints in `colleague work`;
the full report (with provenance) is in the artifact — see `docs/contract.md`
`coherence_report`.

## Honest limits

- Scores flat `.md` text only (coherence's own input model today) — no code,
  transcript, or repo-structure scoring.
- The offline lexical-diagnostics degrade path documented upstream does not
  surface through `--json` (exit 2 emits no stdout payload — probed live);
  the gate records the structured error instead. A diagnostics-only `--json`
  payload on exit 2 would be a natural coherence-cli follow-up.
- No blocking mode until a calibration experiment exists upstream (parked in
  the #291 frame).
