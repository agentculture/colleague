# Backends & plugins

> The backend is the model; the adapter invokes it; plugins are how adapters
> are discovered. Swapping backends is a one-flag change.

The **backend** is the model/coder backend and the **adapter** is the code that
invokes and controls one backend. An adapter is a class implementing the
`Engine` protocol (`colleague/engine.py`) — one abstract method,
`work(task, config) -> TaskResult`. Adapters don't re-implement the loop; they
delegate to `colleague.loop.run` and only supply *how the model is called* (a
`complete` function).

## Plugins: entry-point discovery

A backend becomes available by advertising itself under the
`colleague.engines` **Python entry-point group**. The two bundled backends do
this in this repo's `pyproject.toml`; an out-of-tree plugin does the *identical*
thing in its own metadata, and `colleague backends list` discovers it with no
change to colleague core (`colleague/registry.py` — the registry).

```toml
[project.entry-points."colleague.engines"]
my-engine = "my_package.engine:MyEngine"
```

```bash
colleague backends list          # the registry: backends installed in this env
colleague backends list --json
colleague work "..." --engine my-engine
```

Requesting an unknown backend name raises `UnknownEngine`, listing the available
names.

## The two bundled backends

### `mock` — the reference backend

Deterministic and networkless (`colleague/engines/mock.py`). It runs the exact
same runtime as a real backend — the shared contract and the bounded loop — but
supplies a scripted two-turn `complete` (write a marker file
`colleague-mock.md`, then `finish`) instead of calling a model. That makes it
the **CI workhorse**: it proves the harness end-to-end with no network and no
flakiness, and it is the reference against which a live backend's result *shape*
is compared (the all-engines rule). The e2e shape test
(`tests/test_e2e_mock.py`) is the guard.

### `vllm-openai` — the real backend

Drives any **OpenAI-compatible** `/v1/chat/completions` endpoint with tool
calling (`colleague/engines/vllm_openai.py`). The reference rig is Qwen3-32B
on a vLLM server. It touches *only* the OpenAI surface and uses stdlib `urllib`
rather than any vendor SDK — so retargeting it (vLLM, llama.cpp, an OpenAI
proxy) is a config change, never a code change.

vLLM tool calling needs the server started with `--enable-auto-tool-choice` and
a `--tool-call-parser` matching the model:

```bash
vllm serve Qwen/Qwen3-32B --port 8001 \
  --enable-auto-tool-choice --tool-call-parser hermes
```

The right parser depends on the model **and** the vLLM build: `hermes` works for
many models (including `Qwen/Qwen3-32B`); some Qwen3 builds (e.g. an NVFP4
checkpoint) want `qwen3_coder`. The backend is parser-agnostic — any parser that
makes the server emit OpenAI-format tool calls works. The opt-in live test
proves the path against a real server:

```bash
COLLEAGUE_VLLM_E2E=1 uv run pytest tests/test_vllm_live.py -v
```

#### Headless SSE streaming — default-on ([#393][i393])

[i393]: https://github.com/agentculture/colleague/issues/393

Every completion the adapter sends carries `stream: true` +
`stream_options: {include_usage: true}` and is read as Server-Sent Events.
`COLLEAGUE_STREAM=0` (or `false`/`no`/`off`) opts out and restores the
pre-#393 blocking request byte-identically — neither key on the wire, and
`_stream_or_blocking` is never even entered.

**Why the default flipped.** Streaming used to arm *only* off
`EngineConfig.on_delta` — a **display** seam that only the session/cockpit
sinks set (`cli/_commands/work.py` `_arm_delta_stream`). A headless
`colleague work` never set it, so every turn took the blocking `urlopen`,
whose `read()` returns only once the *whole* completion has been generated.
That quietly turned `COLLEAGUE_TIMEOUT` into a per-turn **generation**
ceiling: observed live in the #387 arms, turns of 300-430s against a 600s
ceiling, with one task killed on its finish turn. Under SSE the socket
timeout applies per read, so it measures **silence between chunks** — a long
generation is legitimate, only a genuine stall fails.

**The mechanism.** `_build_chat_payload` is the single arming decision:
streaming arms when a delta sink is present **or**
`_headless_streaming_enabled()` (default true). It is therefore
*engine-uniform* by construction — the acting cortex/worker seat, deepthink,
senses and an evaluator all build their payload there, via `_make_complete`.
The `on_delta` seam is untouched: an unarmed `on_delta` still means "no
display surface", and a headless streamed turn feeds the module-level
`_noop_delta` instead. The mid-stream → one-blocking-request same-turn
fallback, the keepalive/comment-line tolerance, and the
"a 400/422 naming `stream` degrades to blocking" rule are all unchanged — so
retargeting a server that cannot stream stays a config change, never a code
change.

Pinned by `tests/test_headless_streaming.py` (payload, opt-out vocabulary,
seat uniformity, stall classification, fallback, all-engines shape parity on
the streaming / blocking-fallback / opt-out paths). Suites that script turns
by stubbing the blocking `_post_json` keep running on the default streaming
path through `tests/conftest.py`'s `_sse_bridge_over_blocking_stubs`.

## Writing your own backend plugin

```python
from colleague.engine import Engine
from colleague.loop import run

class MyEngine(Engine):
    name = "my-engine"

    def work(self, task, config):
        return run(
            self._make_complete(config),
            task,
            max_steps=config.max_steps,
            system_prompt=self.system_prompt(task, config),
        )
```

Because the loop owns [hook firing](hooks.md) and [telemetry](telemetry.md), and
the base class injects the [layered system prompt](layered-config.md) via
`self.system_prompt(...)`, a custom backend inherits the full lifecycle layer for
free. Advertise it under the entry-point group and it's discoverable — no change
to colleague core.

## Key files

- `colleague/engine.py` — the `Engine` ABC + the `system_prompt()` base helper.
- `colleague/registry.py` — entry-point discovery (`catalog`, `names`, `load`).
- `colleague/engines/mock.py` — the reference backend.
- `colleague/engines/vllm_openai.py` — the OpenAI-compatible adapter.

## See also

- [model-selection.md](model-selection.md) — how colleague resolves the model
  and endpoint (flags → env → defaults), and keeping it synced to a local server.
- [work-and-loop.md](work-and-loop.md) — the contract + loop adapters delegate to.
- [layered-config.md](layered-config.md) — the per-model system prompt every
  backend inherits.
- [doctor.md](doctor.md) — the `engines` check-group probes all plugins uniformly.
