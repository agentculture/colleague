# Selecting the model & endpoint

> Colleague resolves the engine, model, and endpoint from **flags → env →
> defaults**. There is no model config file — you point colleague with
> `--model` / environment variables, and (optionally) keep it auto-synced to
> whatever your local server is serving.

This page is the operator's companion to [engines.md](engines.md): that doc
covers *what* an engine is; this one covers *how colleague picks the model and
endpoint a `vllm-openai` drive talks to*.

## Resolution precedence

The engine name resolves in `colleague/config.py` (`resolve_engine`):

```text
--engine <name>  >  COLLEAGUE_ENGINE  >  vllm-openai   (never a silent mock)
```

The provider config resolves in `EngineConfig.resolve` (`colleague/config.py`),
each field independently: an explicit flag value wins if given, else the first
**set, non-empty** environment variable, else the default.

| Field | Flag | Environment (checked in order) | Default |
|-------|------|--------------------------------|---------|
| model | `--model` | `COLLEAGUE_MODEL` | `Qwen/Qwen3-32B` |
| base_url | `--base-url` | `COLLEAGUE_BASE_URL`, `OPENAI_BASE_URL` | `http://localhost:8001/v1` |
| api_key | `--api-key` | `COLLEAGUE_API_KEY`, `OPENAI_API_KEY` | `EMPTY` |

Resolution is **literal, not sanitizing** (`_pick`): a flag value is used
verbatim even when empty — `--model ''` resolves to an empty model, it does *not*
fall through — and a whitespace-only environment value is taken as-is (it is not
stripped). Only the **engine name** (`resolve_engine`) treats a blank/whitespace
candidate as absent and strips it. So set the model to a real served name; don't
rely on a blank value falling back to the default.

**There is no persistent model config file.** The repo-level `.colleague/`
directory configures identity, hooks, neighbours, approvals, command templates,
and per-model overlays — but *not* the engine model. Set the model with a flag
or an environment variable.

Confirm what colleague actually resolved (read-only, never drives a task):

```bash
colleague doctor --json     # the provider_config check prints base_url + model
colleague doctor --probe    # adds a live provider_reachable ping to the endpoint
```

## Pointing at an OpenAI-compatible server

The `vllm-openai` engine drives **any** OpenAI-compatible
`/v1/chat/completions` endpoint with tool calling (vLLM, llama.cpp, a proxy) —
retargeting it is a config change, never a code change. The model string
colleague sends **must exactly equal the name the server serves**, or the
server answers with a model-not-found error.

```bash
export COLLEAGUE_BASE_URL=http://localhost:8001/v1
export COLLEAGUE_MODEL='<the exact served model id>'
colleague drive "..." --engine vllm-openai --no-pr
```

## Keeping the model in sync with a locally-served model

When you swap the served checkpoint, a hardcoded `COLLEAGUE_MODEL` goes stale
and the next drive is rejected. Derive the model from the server instead, so
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

A [subagent](drive-and-loop.md) delegated mid-drive inherits the parent's model
by default (`colleague/subagents.py` — the child config is the parent config
with `model=(override or parent.model)`). So a single `COLLEAGUE_MODEL` covers
every nested drive — useful when only one model fits in memory. An explicit
per-subagent `model` is engine-judged and optional; against a single-model
server a stray override simply errors (no second model can load), so the
single-model invariant is fail-closed.

## See also

- [engines.md](engines.md) — the engine/driver/wheel model and the `vllm-openai`
  backend (including the `--tool-call-parser` the *server* needs).
- [doctor.md](doctor.md) — the `provider` check-group reports the resolved
  base_url + model; `--probe` pings the endpoint.
- [per-model-configuration.md](per-model-configuration.md) — per-model hooks
  overlay keyed by the (sanitized) model id.
