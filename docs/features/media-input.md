# Media Input

## Gemma4-as-main: staged, not flipped

The Gemma4 model is **staged** as a potential future main model but is **not
flipped** (not the default). The default main model remains the 27B Qwen model
at the default 48 000 context budget.

### Per-model overlay recipe

To run colleague against the served Gemma4 model with its correct 128K window
budget, create a per-model profiles overlay:

**File path:**
```
.colleague/coolthor-gemma-4-12B-it-NVFP4A16/profiles.json
```

**Contents:**
```json
{
  "default": {
    "context_budget_tokens": 96000
  }
}
```

The directory name `coolthor-gemma-4-12B-it-NVFP4A16` is the output of
`colleague.layers.sanitize_model("coolthor/gemma-4-12B-it-NVFP4A16")` —
slashes become hyphens, the rest is preserved verbatim.

When the resolved model id matches `coolthor/gemma-4-12B-it-NVFP4A16`, the
`apply_mode_profile` layer reads this overlay and sets `context_budget_tokens`
to 96 000 (matching the 128K serving window at ~0.75 fill fraction).

### Default stays at 48 000

The built-in default context budget remains **48 000 tokens** for the 27B main
model (`sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP`). No source code change is
required — the default is a constant in `colleague/config.py` and the per-model
overlay seam is purely data-driven (JSON files in `.colleague/`).

### Flip prerequisite: serving-side Gemma tool parser

Flipping Gemma4 to the default main model requires a **serving-side change**:
the lobes serving rig must grow a Gemma-format tool-call parser. The current
Gemma4 model emits no structured tool calls yet (probed and confirmed). This
is an **external prerequisite** — it is never worked around in colleague code.
Until the serving-side parser lands, Gemma4 remains staged (configurable via
the per-model overlay above) but not the default.