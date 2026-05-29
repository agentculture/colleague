#!/usr/bin/env bash
# Repeat the 2026-05-29 website-self-build drive.
#
# Method: only the engine writes files; this script just guides + runs it.
# Requires a live OpenAI-compatible server with tool calling enabled
# (vLLM: --enable-auto-tool-choice + a model-appropriate --tool-call-parser).
#
# Env overrides (defaults match the 2026-05-29 run):
: "${CONVERTIBLE_BASE_URL:=http://localhost:8001/v1}"
: "${CONVERTIBLE_MODEL:=mmangkad/Qwen3.6-27B-NVFP4}"
: "${CONVERTIBLE_TIMEOUT:=900}"   # per-request HTTP timeout; the 120s default timed out (findings F1)
export CONVERTIBLE_BASE_URL CONVERTIBLE_MODEL CONVERTIBLE_TIMEOUT

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

# Pre-flight: confirm the server emits tool calls (uses its own temp repo).
CONVERTIBLE_VLLM_E2E=1 uv run pytest tests/test_vllm_live.py -v

# Canonical (converged) instruction — the attempt-3 guidance that succeeded.
# Note: site/style.css from a prior step was kept in place; this writes index.html.
uv run convertible drive \
"The file site/style.css already exists in this repo (convertible wrote it). Read site/style.css to learn its CSS classes and variables, and read README.md to learn what convertible is. Do NOT read other docs. Then write a single, concise site/index.html: a self-contained landing page in plain HTML that links ./style.css (no external or CDN dependencies), target about 150 lines, avoid long prose. It is for the convertible project - a swappable coder-agent harness: one harness, many model engines, driving a repo through a bounded tool-loop. Include: a hero with the project name and tagline; the car metaphor as a labeled list (engine = the model backend, driver = the per-engine adapter, chassis = the shared task contract, tool-loop = the bounded agentic loop, wheels = pluggable engines discovered via entry points, dashboard = the JSON result artifact, GPS = opt-in OpenTelemetry); and a short list of key features (swappable engines, git/PR handoff, command templates, lifecycle hooks, layered per-model config, zero runtime dependencies). Then verify by listing site/ and finish with a summary of what you built." \
  --repo . --engine vllm-openai --model "$CONVERTIBLE_MODEL" \
  --max-steps 50 --no-pr --json

echo "Output in site/ (gitignored). Drive artifact in .convertible/<task_id>.json"
