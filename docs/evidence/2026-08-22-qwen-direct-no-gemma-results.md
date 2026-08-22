# qwen-direct live proof — results (2026-08-22, rig: lobes http://localhost:8001, cortex unsloth/Qwen3.8-27B-NVFP4)

Spec `docs/specs/2026-08-22-qwen-direct-no-gemma.md` success signal c24 / honesty h15 / assumption h17. Raw outputs below; nothing edited except truncation of request-payload dumps.

## Check 1 — bare session dials only cortex (c24.1, h1) + the h17 ack-latency measurement

Piped `colleague session --no-tui --engine vllm-openai` in a throwaway repo, `COLLEAGUE_DUMP_REQUEST=1`, `COLLEAGUE_LOBES_URL` armed, input `what model are you running on?` then `/quit`:

```text
default: rc=0 wall=12.451145558s models=      2 "model": "unsloth/Qwen3.8-27B-NVFP4";
senses: rc=0 wall=6.807271282s models=      1 "model": "unsloth/gemma-4-12B-it-qat-w4a16";
```

- default arm: 2 requests, both `unsloth/Qwen3.8-27B-NVFP4` (0 non-cortex); answer: `I'm running on unsloth/Qwen3.8-27B-NVFP4 … as my cortex`; wall 12.45 s (a work item: one tool-loop turn + finish).
- senses-opted-in arm (`COLLEAGUE_SENSES_MODEL=lobes`): 1 request to `unsloth/gemma-4-12B-it-qat-w4a16` (front door answered directly); wall 6.81 s.
- **h17:** cortex-direct is 1.83× the senses ack on this non-repo turn — within the ≤2× bar; the assumption stands as measured (n=1, same minute, same rig).

## Check 2 — full suite (c24.2, h6)

```text
uv run pytest -n auto (HEAD 2ec72ee): 9160 passed, 0 failed, 23 skipped
```

## Check 3 — the #422 trio on a checkout whose .colleague/config.json arms lobes (c24.3)

```text
{
  "lobes": "http://localhost:8001"
}
3 passed in 0.10s
```

## Check 4 — the retirement is visible (c24.4, h7) + bare --model / --effort (c25/c26)

```text
colleague: model pin refresh (resolution) — cortex model 'unsloth/Qwen3.6-27B-NVFP4' (pinned via CONVERTIBLE_MODEL) is no longer served; refreshed to 'unsloth/Qwen3.8-27B-NVFP4' from the lobes gateway's cortex role discovery
model:                  unsloth/Qwen3.8-27B-NVFP4
config_file: .colleague/config.json sets [lobes] (wins: lobes)
config_file: /home/spark/.colleague/config.json sets [lobes] (wins: )
lobes: armed (gateway='http://localhost:8001') — resolved model=unsloth/Qwen3.8-27B-NVFP4
not consumed (opt-in): senses → unsloth/gemma-4-12B-it-qat-w4a16 — COLLEAGUE_SENSES_MODEL=lobes
not consumed (opt-in): muse → nvidia/Gemma-4-31B-IT-NVFP4 — COLLEAGUE_DEEPTHINK_MODEL=lobes
---
lobes: armed at http://localhost:8001 — reachable
  not consumed (opt-in): senses → unsloth/gemma-4-12B-it-qat-w4a16 — COLLEAGUE_SENSES_MODEL=lobes
  not consumed (opt-in): muse → nvidia/Gemma-4-31B-IT-NVFP4 — COLLEAGUE_DEEPTHINK_MODEL=lobes
--- colleague work … --model (no value)
current model: unsloth/Qwen3.8-27B-NVFP4
served: unsloth/Qwen3.8-27B-NVFP4  ◀ current
served: Qwen/Qwen3-Reranker-0.6B
served: Qwen/Qwen3-Embedding-0.6B
served: unsloth/gemma-4-12B-it-qat-w4a16
role cortex → unsloth/Qwen3.8-27B-NVFP4 (consumed)
role senses → unsloth/gemma-4-12B-it-qat-w4a16 (not consumed — opt-in: COLLEAGUE_SENSES_MODEL=lobes)
role muse → nvidia/Gemma-4-31B-IT-NVFP4 (not consumed — opt-in: COLLEAGUE_DEEPTHINK_MODEL=lobes)
role worker → nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4 (not consumed)
role stt → nvidia/parakeet-tdt-0.6b-v2 (not consumed)
role tts → ResembleAI/chatterbox (not consumed)
switch: --model <id> (CLI) or /model <id> (session) — an explicit choice, never automatic
--- colleague work … --effort (no value)
reasoning effort per seat (ladder: off|low|medium|high|xhigh | default = unset):
  cortex     medium  (table)
  worker     medium  (table)
  deepthink  xhigh   (table)
  evaluator  medium  (table)
  senses     off     (table)
  design     xhigh   (table)
switch: --effort <rung> (CLI, acting seat) or /effort <rung> [seat] (session)
```

Note: this shell still exported the stale `CONVERTIBLE_MODEL=unsloth/Qwen3.6-27B-NVFP4` (fixed in ~/.bashrc earlier today, not yet re-sourced); the resolution-time pin refresh corrected it to the served id each time — visible in the dumps, harmless.
