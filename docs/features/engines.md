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
