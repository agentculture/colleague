# Selecting the model & endpoint

> Colleague resolves the engine, model, and endpoint from **flags → env →
> config file → defaults**. You can point colleague with `--model` / environment
> variables, or persist the endpoint in `.colleague/config.json`.

This page is the operator's companion to [engines.md](engines.md): that doc
covers *what* an engine is; this one covers *how colleague picks the model and
endpoint a `vllm-openai` work item talks to*.

## Resolution precedence

The engine name resolves in `colleague/config.py` (`resolve_engine`):

```text
--engine <name>  >  COLLEAGUE_ENGINE  >  vllm-openai   (never a silent mock)
```

The provider config resolves in `EngineConfig.resolve` (`colleague/config.py`),
each field independently: an explicit flag value wins if given, else the first
**set, non-empty** environment variable, else the value from
`.colleague/config.json` (when `repo_path` is provided), else the default.

| Field | Flag | Environment (checked in order) | Default |
|-------|------|--------------------------------|---------|
| model | `--model` | `COLLEAGUE_MODEL` | `unsloth/Qwen3.8-27B-NVFP4` |
| base_url | `--base-url` | `COLLEAGUE_BASE_URL`, `OPENAI_BASE_URL` | `http://localhost:8001/v1` |
| api_key | `--api-key` | `COLLEAGUE_API_KEY`, `OPENAI_API_KEY` | `EMPTY` |

Resolution is **literal, not sanitizing** (`_pick`): a flag value is used
verbatim even when empty — `--model ''` resolves to an empty model, it does *not*
fall through — and a whitespace-only environment value is taken as-is (it is not
stripped). Only the **engine name** (`resolve_engine`) treats a blank/whitespace
candidate as absent and strips it. So set the model to a real served name; don't
rely on a blank value falling back to the default.

The reference rig serves the default model (`unsloth/Qwen3.8-27B-NVFP4`) at a
**1,048,576-token (1M) YaRN context** (probed 2026-08-20, issue #404). The
built-in `context_budget_tokens` default is a **moderate raise, not a max-out**
of that window — `_DEFAULT_CONTEXT_BUDGET = 131072` (128K) — with
`_DEFAULT_MAX_OUTPUT_CHARS` rescaled to the same proportion; see
[graceful-degradation.md](graceful-degradation.md) for the full sizing rationale
and the `COLLEAGUE_TIMEOUT` guidance for long-context runs.

## Persistent config file (.colleague/config.json)

The repo-level `.colleague/config.json` provides a durable way to point
colleague at another OpenAI-compatible provider without re-passing flags or env
vars each run. It supports three keys:

- **`base_url`** — the OpenAI-compatible endpoint (e.g. `https://api.openai.com/v1`).
- **`api_key`** — the provider's API key (never printed in any output; redacted
  in `doctor` and `config show`).
- **`model`** — the model id the server serves.

**Precedence:** explicit flag > `COLLEAGUE_*`/`OPENAI_*` env > `.colleague/config.json` > built-in default.

The file is resolved via `colleague/configdir.py` (repo-level `.colleague/`
overrides user-level `~/.colleague/`). A missing or malformed file is a strict
no-op — it never raises.

### Worked examples

**OpenAI:**

```json
{
  "base_url": "https://api.openai.com/v1",
  "model": "gpt-4o"
}
```

**OpenRouter:**

```json
{
  "base_url": "https://openrouter.ai/api/v1",
  "model": "openai/gpt-4o"
}
```

**Generic OpenAI-compatible local server:**

```json
{
  "base_url": "http://localhost:8001/v1",
  "model": "unsloth/Qwen3.8-27B-NVFP4"
}
```

Confirm what colleague actually resolved (read-only, never drives a task):

```bash
colleague doctor --repo .     # the provider_config check prints base_url + model
colleague doctor --repo . --probe    # adds a live provider_reachable ping to the endpoint
colleague config show --repo .       # resolved provider config (api_key redacted)
```

## Pointing at an OpenAI-compatible server

The `vllm-openai` engine works with **any** OpenAI-compatible
`/v1/chat/completions` endpoint with tool calling (vLLM, llama.cpp, a proxy) —
retargeting it is a config change, never a code change. The model string
colleague sends **must exactly equal the name the server serves**, or the
server answers with a model-not-found error.

```bash
export COLLEAGUE_BASE_URL=http://localhost:8001/v1
export COLLEAGUE_MODEL='<the exact served model id>'
colleague work "..." --engine vllm-openai --no-pr
```

## Keeping the model in sync with a locally-served model

When you swap the served checkpoint, a hardcoded `COLLEAGUE_MODEL` goes stale
and the next work item is rejected. Derive the model from the server instead, so
colleague always targets whatever is live. Read the served id straight from the
server's `/v1/models` (a wrapper function in your shell rc — for a **single-model**
server `data[0]` is unambiguous):

```bash
# Always target whatever the local server is serving right now.
colleague() {
  local served t
  for t in curl python3; do
    command -v "$t" >/dev/null 2>&1 || { echo "colleague: missing required tool: $t" >&2; return 127; }
  done
  served=$(curl -s --max-time 5 "${COLLEAGUE_BASE_URL:-http://localhost:8001/v1}/models" \
           | python3 -c 'import sys,json; print(json.load(sys.stdin)["data"][0]["id"])' 2>/dev/null)
  [ -n "$served" ] && export COLLEAGUE_MODEL="$served"
  command colleague "$@"
}
```

If you run [model-gear](https://github.com/agentculture) (a local vLLM
manager), its `model whoami` is the authoritative source — it reports the
served model and port and stays coherent across `model switch` and fleet
deployments:

```bash
# colleague always drives whatever model-gear is currently serving.
colleague() {
  local served port t
  for t in model awk; do
    command -v "$t" >/dev/null 2>&1 || { echo "colleague: missing required tool: $t" >&2; return 127; }
  done
  read -r served port < <(model whoami 2>/dev/null | awk '/served_model:/{print $2, $4}')
  if [ -z "$served" ]; then
    echo "colleague: warning — could not read served model from 'model whoami';" \
         "using the configured default." >&2
    command colleague "$@"; return
  fi
  COLLEAGUE_MODEL="$served" \
  COLLEAGUE_BASE_URL="http://localhost:${port:-8001}/v1" \
  command colleague "$@"
}
```

Notes:

- `command colleague` calls the installed binary, so the function does not
  recurse; full-path and script callers are unaffected.
- Injecting the env inline (not `export`) scopes it to the single invocation.
- `uv run colleague` (in-repo dev) bypasses a shell function — prefix the same
  env there, e.g. `COLLEAGUE_MODEL="$(...)" uv run colleague ...`.

## Subagents inherit the model

A [subagent](work-and-loop.md) delegated mid-work inherits the parent's model
by default (`colleague/subagents.py` — the child config is the parent config
with `model=(override or parent.model)`). So a single `COLLEAGUE_MODEL` covers
every nested work item — useful when only one model fits in memory. An explicit
per-subagent `model` is engine-judged and optional; against a single-model
server a stray override simply errors (no second model can load), so the
single-model invariant is fail-closed.

## See also

- [engines.md](engines.md) — the backend/adapter/plugin model and the `vllm-openai`
  backend (including the `--tool-call-parser` the *server* needs).
- [doctor.md](doctor.md) — the `provider` check-group reports the resolved
  base_url + model; `--probe` pings the endpoint.
- [per-model-configuration.md](per-model-configuration.md) — per-model hooks
  overlay keyed by the (sanitized) model id.
