# Selecting the model & endpoint

> Convertible resolves the engine, model, and endpoint from **flags → env →
> defaults**. There is no model config file — you point convertible with
> `--model` / environment variables, and (optionally) keep it auto-synced to
> whatever your local server is serving.

This page is the operator's companion to [engines.md](engines.md): that doc
covers *what* an engine is; this one covers *how convertible picks the model and
endpoint a `vllm-openai` drive talks to*.

## Resolution precedence

The engine name resolves in `convertible/config.py` (`resolve_engine`):

```text
--engine <name>  >  CONVERTIBLE_ENGINE  >  vllm-openai   (never a silent mock)
```

The provider config resolves in `EngineConfig.resolve` (`convertible/config.py`),
each field independently, first non-empty wins (empty/whitespace falls through to
the next source):

| Field | Flag | Environment (checked in order) | Default |
|-------|------|--------------------------------|---------|
| model | `--model` | `CONVERTIBLE_MODEL` | `Qwen/Qwen3-32B` |
| base_url | `--base-url` | `CONVERTIBLE_BASE_URL`, `OPENAI_BASE_URL` | `http://localhost:8001/v1` |
| api_key | `--api-key` | `CONVERTIBLE_API_KEY`, `OPENAI_API_KEY` | `EMPTY` |

**There is no persistent model config file.** The repo-level `.convertible/`
directory configures identity, hooks, neighbours, approvals, command templates,
and per-model overlays — but *not* the engine model. Set the model with a flag
or an environment variable.

Confirm what convertible actually resolved (read-only, never drives a task):

```bash
convertible doctor --json     # the provider_config check prints base_url + model
convertible doctor --probe    # adds a live provider_reachable ping to the endpoint
```

## Pointing at an OpenAI-compatible server

The `vllm-openai` engine drives **any** OpenAI-compatible
`/v1/chat/completions` endpoint with tool calling (vLLM, llama.cpp, a proxy) —
retargeting it is a config change, never a code change. The model string
convertible sends **must exactly equal the name the server serves**, or the
server answers with a model-not-found error.

```bash
export CONVERTIBLE_BASE_URL=http://localhost:8001/v1
export CONVERTIBLE_MODEL='<the exact served model id>'
convertible drive "..." --engine vllm-openai --no-pr
```

## Keeping the model in sync with a locally-served model

When you swap the served checkpoint, a hardcoded `CONVERTIBLE_MODEL` goes stale
and the next drive is rejected. Derive the model from the server instead, so
convertible always targets whatever is live. Read the served id straight from the
server's `/v1/models` (a wrapper function in your shell rc — for a **single-model**
server `data[0]` is unambiguous):

```bash
# Always target whatever the local server is serving right now.
convertible() {
  local served
  served=$(curl -s --max-time 5 "${CONVERTIBLE_BASE_URL:-http://localhost:8001/v1}/models" \
           | python3 -c 'import sys,json; print(json.load(sys.stdin)["data"][0]["id"])' 2>/dev/null)
  [ -n "$served" ] && export CONVERTIBLE_MODEL="$served"
  command convertible "$@"
}
```

If you run [model-gear](https://github.com/agentculture) (a local vLLM
manager), its `model whoami` is the authoritative source — it reports the
served model and port and stays coherent across `model switch` and fleet
deployments:

```bash
# convertible always drives whatever model-gear is currently serving.
convertible() {
  local served port
  read -r served port < <(model whoami 2>/dev/null | awk '/served_model:/{print $2, $4}')
  if [ -z "$served" ]; then
    echo "convertible: warning — could not read served model from 'model whoami';" \
         "using the configured default." >&2
    command convertible "$@"; return
  fi
  CONVERTIBLE_MODEL="$served" \
  CONVERTIBLE_BASE_URL="http://localhost:${port:-8001}/v1" \
  command convertible "$@"
}
```

Notes:

- `command convertible` calls the installed binary, so the function does not
  recurse; full-path and script callers are unaffected.
- Injecting the env inline (not `export`) scopes it to the single invocation.
- `uv run convertible` (in-repo dev) bypasses a shell function — prefix the same
  env there, e.g. `CONVERTIBLE_MODEL="$(...)" uv run convertible ...`.

## Subagents inherit the model

A [subagent](drive-and-loop.md) delegated mid-drive inherits the parent's model
by default (`convertible/subagents.py` — the child config is the parent config
with `model=(override or parent.model)`). So a single `CONVERTIBLE_MODEL` covers
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
