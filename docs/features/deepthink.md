# Deepthink — dual-model: a fast main driver + a strong-reasoner escalation

> Spec:
> [`docs/specs/2026-07-01-colleague-drives-with-two-minds-a-fast-wide-window.md`](../specs/2026-07-01-colleague-drives-with-two-minds-a-fast-wide-window.md)
> · plan:
> [`docs/plans/2026-07-01-colleague-drives-with-two-minds-a-fast-wide-window.md`](../plans/2026-07-01-colleague-drives-with-two-minds-a-fast-wide-window.md)

colleague can drive with **two minds**: a fast, wide-window **main model**
drives every turn of the bounded tool loop, and a second, stronger-reasoning
**deepthink model** is escalated to at hard-judgment moments. Or it drives
exactly as before with **one** model — the two configurations are selected
purely by operator config, from one installed colleague:

- **Single-model** (no deepthink config anywhere): byte-identical to
  pre-feature colleague — same tool list, same resolution, same artifact, no
  deepthink key. The e2e shape tests pin this.
- **Dual-model**: the main model does the mechanical driving (reads, edits,
  commands — cheap, fast, big window) and the deepthink model answers the
  judgment calls (verdicts, plans, self-checks). Speed *and* accuracy stop
  being either/or, and the diversity between the two minds is itself a safety
  net — two models miss differently.

The reference rig ("lobes") serves **Qwen3.6-27B** as main driver and
**Gemma-4-31B** on thor (via the gateway muse proxy) as the deepthink reasoner,
both with 256K windows. Nothing hard-codes those names: any pair of
OpenAI-compatible endpoints works, through the same `vllm-openai` adapter —
retargeting is a config change, never a code change.

## Configuration

Presence is keyed **solely** on a resolved deepthink *model*: no model, no
dual-mode — regardless of other keys. Per-key precedence is the standard
chain: `COLLEAGUE_DEEPTHINK_*` env (legacy `CONVERTIBLE_DEEPTHINK_*` honored)
> `.colleague/config.json` `deepthink` section > defaults.

```jsonc
// .colleague/config.json
{
  "base_url": "http://localhost:8002/v1",          // main: e.g. Gemma 4
  "model": "google/gemma-4-27b-it",
  "deepthink": {
    "model": "unsloth/Qwen3.6-27B-NVFP4",
    "base_url": "http://localhost:8001/v1",         // defaults to the MAIN base_url
    "api_key": "…",                                  // defaults to the MAIN api_key
    "context_budget": 48000                          // tokens; default 48000 (64K-sized)
  }
}
```

Env equivalents: `COLLEAGUE_DEEPTHINK_MODEL`, `COLLEAGUE_DEEPTHINK_BASE_URL`,
`COLLEAGUE_DEEPTHINK_API_KEY`, `COLLEAGUE_DEEPTHINK_CONTEXT_BUDGET`. The
resolved block is visible (api_key redacted) via `colleague config show`.

### Discovered from lobes (the muse role)

With a lobes gateway configured and no deepthink declared via env or
`config.json`, `EngineConfig.resolve()` fills the deepthink target from the
gateway's advertised muse role — muse's own endpoint and a `context_budget`
derived from the role's advertised window at the same 48000/65536 ratio the
built-in default encodes. Env and `config.json` always win. No lobes or no
muse role means no deepthink (byte-identical).

**api_key hygiene:** the main `api_key` is inherited only when muse's dial
target shares the main endpoint's origin (the reference rig: everything
proxied at one gateway). A cross-origin muse gets the no-auth default
instead — the main Bearer token is never forwarded to a host a wire payload
advertised. To arm a cross-origin muse, declare the key explicitly
(`COLLEAGUE_DEEPTHINK_API_KEY`, or a `config.json` `deepthink.api_key` —
which works even without a declared model); a wrong or absent key degrades
visibly at the escalation point, never fails the run.

This rung serves the operator running colleague against a multi-machine lobes
rig (spark cortex + thor muse on the reference deployment): one gateway URL
arms cortex, senses, *and* deepthink with zero model ids. The boundary with
lobes-cli is the `/capabilities` contract itself — consuming `muse` required
no gateway change, and the gateway's `loaded`/`feasible` flags are
deliberately not consulted (for proxied roles they describe the gateway host,
not the serving host —
[lobes-cli#146](https://github.com/agentculture/lobes-cli/issues/146)).
Before this rung, `colleague/lobes.py`'s `_RESOLVED_ROLES` was exactly
`("cortex", "senses")` and an advertised muse was read and discarded. Spec:
`docs/specs/2026-07-17-two-machines-two-minds.md`.

## The enumerated escalation surface

Deepthink is reachable from exactly **four** points — enumerated in code,
pinned by a boundary test, and listed here (the drift test compares the two):

| Point | Fires | Recorded as |
|---|---|---|
| **`deepthink` loop tool** | backend-judged: the main model MAY call it mid-work with a question + self-composed digest; the schema is offered only under dual config | `point: "tool"` |
| **Plan-mode proposals** | `colleague plan` drives claim/plan-item proposals against the deepthink model (planning *is* the hard-reasoning moment) | stderr line (no artifact — see limits) |
| **Acceptance self-check** | a clean finish of a task with `acceptance` criteria grades them via deepthink, from a self-contained digest | `point: "acceptance_selfcheck"` |
| **Test-integrity reviewer default** | with dual config and no explicit `COLLEAGUE_TESTINTEGRITY_REVIEWER_MODEL`, the reviewer subagent defaults to the deepthink model (same-endpoint only — see limits) | the reviewer subagent's own record |

**Mechanism.** Every deepthink invocation is ONE bounded, **tools-off**
completion through the public `Engine.make_complete(config, tools=[])` seam —
nothing tool-related goes on the wire, so the call *structurally* cannot call a
tool or `finish` (the acceptance-self-check invariant class). The prompt is
**windowed to the deepthink model's own `context_budget`** before sending
(per-endpoint `/tokenize`-exact counting with the char-heuristic fallback,
one quarter reserved for the completion) — never to the main model's bigger
budget. One binding per work item (`colleague.deepthink.make_deepthink_run`)
is injected into both the tool executor and the runtime escalation points by
every backend identically (the all-engines rule).

**Recording.** Every work-loop escalation lands on **`TaskResult.deepthink`**
— a list of `{point, tokens, duration, degraded}` records, omit-when-None, so
a single-model artifact (or a dual run that never escalated) is byte-identical.

## Degradation ladder (a dual run never fails because of deepthink)

Any failure — dead endpoint, timeout, overflow, unknown engine, a backend with
no live model — degrades, never raises:

- the **tool** returns an honest "deepthink is unavailable (degraded) —
  proceed with your own judgment" notice to the main model;
- the **acceptance self-check** falls back to the existing main-model turn;
- **plan-mode** falls back per-call to the main model with one stderr warning;
- on **`mock`** (no live `make_complete`) an escalation records a degraded
  no-op — the lint fix-turn precedent.

The degraded attempt is still recorded (`degraded: true`) — visible, never
silent.

## What deliberately stays on the main model

Forced synthesis (#191) and fill-line compaction (#156) **never** touch the
deepthink seam, by design (spec c11): their prompt *is* the main model's own
windowed history — up to the wide budget — which structurally cannot fit the
deepthink model's smaller window. Re-windowing to fit would discard half the
context and degrade the result rather than improve it. A test pins that these
paths complete against the main model even under dual config.

## The honest line: this is not a router

The historically out-of-scope **multi-model router / routing policy** is still
out of scope. This feature moves the line exactly this far and no further:

- **ONE** operator-declared second model — or alternatively discovered from the lobes muse role — no N-model generalization; a resolution rung only, the sixth sanctioned increment;
- a **fixed, enumerated** escalation surface (above) — no automatic task→model
  routing policy, no per-task selection heuristics; the only "decision maker"
  is the main model's own backend-judged use of the `deepthink` tool;
- absent config = **byte-identical** single-model colleague.

## Three-tier mode — legacy vs three-tier distinction

In **legacy mode** (no `three_tier` config), the deepthink escalation surface
is unchanged: the main model drives the loop, and the deepthink reasoner is
available at the four enumerated escalation points. The `muse` role discovery
from the lobes gateway works as described above — with lobes armed and no
deepthink declared, the advertised `muse` role fills the deepthink target.

In **three-tier mode** (opt-in via `config.json` `three_tier` or
`COLLEAGUE_THREE_TIER`), deepthink is **absent**. The worker acts, senses
relays, and the cortex (if armed) configures — but there is no dual-model
judgment escalation. Three-tier mode and dual-model mode are distinct
configurations, not layered features. See
[three-tier.md](three-tier.md) for the full feature doc.

## Honest limits

- **The live proof is PENDING.** The reference rig does not yet serve a
  tool-calling-enabled backend (Gemma-as-driver needs
  `--enable-auto-tool-choice` + a tool-call parser), so the env-gated live
  test (`COLLEAGUE_DUAL_E2E=1`, `tests/test_dual_live.py`) and the
  wall-clock/quality benchmark (`scripts/bench_dual.py`, graded via the
  feedback loop) are recorded as PENDING in `docs/live-testing.md` — the
  faster-AND-more-accurate after-state ships as a measured hypothesis, never a
  faked validation. `mock` pins the whole contract meanwhile.
- **Reviewer default is same-endpoint only.** The subagent model switch
  carries only a model name (the child inherits the parent `base_url`), so the
  test-integrity reviewer defaults to the deepthink model only when the two
  endpoints share a `base_url`; cross-endpoint reviewer default is a follow-up.
- **Plan-mode calls are stderr-visible, not artifact-recorded.** `colleague
  plan` runs outside the work loop — there is no `TaskResult` to record onto.
- **Digest composition is v1.** What the main model hands the tool (how much
  context, in what form) will be tuned live on the rig.
- **Parked follow-ups:** the main model's multimodality (image input) is not
  surfaced; mode-level model preference (e.g. review mode driving *with* the
  deepthink model as main) is deliberately not built — deepthink stays an
  escalation action in v1.
