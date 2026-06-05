# colleague CLI/DX — hands-on experience evaluation

A live, hands-on evaluation of what colleague *feels like* to actually use from
the command line — the agent-facing workflow, not the TUI rendering. It is the
companion to [`tui-experience-evaluation.md`](tui-experience-evaluation.md),
which studied the terminal UI frame-by-frame and explicitly covered
*interaction/affordance*, not the command-line workflow itself. This fills that
gap.

## How this was produced

Unlike the TUI evaluation (deterministic simulation of the render seams), this
one **drove the real CLI against the live reference rig**
(`sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP` at `http://localhost:8001/v1`,
healthy via `colleague doctor --probe`). Every drive ran for real; every claim
below is checked against ground truth, not the drive's own summary (the
agent-first rule: outsourced output is a second opinion to verify, never
authority). All throwaway repos were created under `mktemp` and removed
afterward — this repo stayed clean (preserved artifacts land in gitignored
`.colleague/`).

Reproduce the spine of it:

```bash
WORK=$(mktemp -d); git -C "$WORK" init -q
git -C "$WORK" config user.email a@b.c; git -C "$WORK" config user.name sim
git -C "$WORK" commit -q --allow-empty -m init
colleague drive "Create calc.py with add(a,b) and sub(a,b) and a __main__ \
  block that prints add(2,3) and sub(5,1), then run it with python3." \
  --repo "$WORK" --engine vllm-openai --no-pr
```

## What was exercised (all live, verified)

| Journey | Result |
|---------|--------|
| First contact — `colleague`, `whoami`, `overview`, `learn` | Coherent, discoverable; one inconsistency (see P1) |
| Live drive — write `calc.py` + run it | **~16 s**, correct output (independently ran → `5`/`4`), faithful `stats` |
| ROI loop — `feedback record`/`show`/`list`/`last` | Works; identity-aware; `last` echoes its resolution |
| `outsource explore` — the headline front door | **~2 m**, accurate findings, **no trail-off**, zero side effects |
| Error paths — bad engine / bad repo / missing feedback | Every error → actionable `hint:` + exit 1 |
| Introspection — `explain`, `commands list` | Clear, agent-readable, graceful on bad paths |

## What works well

- **Error ergonomics are best-in-class.** Every failure pairs a precise
  `error:` with an actionable `hint:` and a non-zero exit — e.g.
  `error: unknown engine 'nonexistent'; available: mock, vllm-openai` /
  `hint: list engines with: colleague wheels list`. No traceback ever leaks.
  A missing feedback record is a clean `{"feedback": null}` (exit 0), not an
  error — exactly the documented no-op.
- **Stdout/stderr discipline is real, not just claimed.** The drive **result
  block** (`task:`/`status:`/`summary:`/`artifact:`) goes to **stdout**; the
  **step trace** (`step N: …`) and `handoff:` diagnostics go to **stderr** —
  verified by capturing the two streams separately. This is what makes colleague
  genuinely pipeable and `--json`-able.
- **Drive stats are faithful to ground truth.** For the live `calc.py` drive,
  `bytes_written: 137` matched the committed file byte-for-byte; `tool_counts`
  `{write_file:1, run_command:1, finish:1}` and `step_count: 3` mirrored the live
  trace; `usage` was the verbatim server count (`7131/274/7405`), never
  estimated. This re-confirms the §0 field audit against a fresh drive.
- **`outsource explore` delivers *and* verifies.** Asked how engine resolution
  works, it correctly located `resolve_engine()` at `colleague/config.py:74-97`
  *including the legacy `CONVERTIBLE_ENGINE` fallback and the empty-string
  fall-through* — checked against the source, exactly right. It finished with a
  real finding (the #143 trail-off fix holds — no mid-thought narration), and the
  preserved artifact landed in **gitignored** `.colleague/`, so the "read-only"
  promise is real: `git status` stayed clean throughout.
- **`last` never mis-resolves silently.** Grading `last` prints
  `feedback: 'last' resolved to f6c88a278f43 — "echo hi"` — the #132 safety
  behavior, confirmed working live.
- **Identity-aware grade attribution.** `by` defaults to the *target repo's*
  resolved identity — verified: a repo whose `culture.yaml` declares
  `nick: testbot` records `by: testbot` with no flag.

## Findings (prioritized)

### P1 — `overview` and `whoami` disagree about "model" — FIXED in this change

`whoami --json` carries two model fields: `model` (the *mesh* / culture-agent
model, often `"unknown"` when `culture.yaml` declares none) and `drive_model`
(the live drive model, e.g. `sakamakismile/…`). The text `whoami` is well
designed — it surfaces `mesh backend:` and `drive model:` and deliberately omits
the unhelpful `unknown` one.

But `overview`'s Identity block rendered only `model: {ident['model']}` — the
*mesh* model — so a user running the command meant to snapshot "who is this
agent" saw a bare `model: unknown` while `whoami` reported a real drive model.
The two adjacent identity commands silently disagreed.

**Fix (this change):** `overview`'s Identity block now mirrors `whoami` —
`mesh backend`, `drive engine`, `drive model` (with the mock-backend `None`
case handled identically) — and drops the bare `model:` line. `report()` already
resolves the drive engine/model the same way a real drive does, so this is
wiring, not new resolution. Locked by
`tests/test_cli_introspection.py::test_overview_identity_surfaces_drive_model_consistent_with_whoami`.

### P2 — Bare `colleague drive` doesn't echo the `grade:` hint — FIXED [#144]

CLAUDE.md says "every drive echoes `task:` + a `grade:` hint", but the hint was
emitted only by the `outsource` wrapper (`outsource.sh`), not the runtime drive
command. A live `outsource explore` printed
`grade: outsource feedback ee3850dc7858 --rating <1-5>`; a bare
`colleague drive` printed `task:` but no `grade:` line (stdout or stderr).

**Fix ([#144]):** the drive result block now ends with
`grade: colleague feedback record <task_id> --rating <1-5>` (in `_render`,
`drive.py`), pointing at the native feedback verb — so the bare-CLI path gets the
same ROI-loop nudge, and the CLAUDE.md claim becomes literally true. The `--json`
path bypasses the text renderer, so machine output stays clean.

### P3 — Grading in an identity-less repo attributes to `(unknown)` with no hint — FIXED [#145]

`by` correctly defaults to the target repo's resolved identity, but a repo with
no `culture.yaml` / `.colleague/identity.json` recorded `by: (unknown)` with no
signal that `--by` exists or where identity is resolved from.

**Fix ([#145]):** `feedback record` now emits a stderr advisory
(`feedback: no identity resolved for this repo; … pass --by NAME, or add a
culture.yaml nick / .colleague/identity.json "as"`) when neither an explicit
`--by` nor a repo identity resolves. The record still writes (exit 0) and the
`--json` stdout payload is untouched.

## Bottom line

The CLI experience is **strong and honest**. The error/hint discipline, the
genuine stdout/stderr separation, the faithful always-on stats, and a working,
*verifiable* `outsource explore` are all real strengths — and the recent
trail-off (#143) and `last`-safety (#132) fixes hold up under live use. The only
real wart was the `overview` vs `whoami` model disagreement (P1), fixed here; the
two remaining discoverability nits ([#144] / [#145]) are now fixed too. The
reproduction recipe above regenerates every observation against the live rig.

[#144]: https://github.com/agentculture/colleague/issues/144
[#145]: https://github.com/agentculture/colleague/issues/145
