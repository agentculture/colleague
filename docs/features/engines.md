# Engines & wheels

> The engine is the model; the driver is the adapter; wheels are how drivers
> are discovered. Swapping engines is a one-flag change.

In the car metaphor, the **engine** is the model/coder backend and the
**driver** is the adapter that invokes and controls one engine. A driver is a
class implementing the `Engine` protocol (`convertible/engine.py`) — one
abstract method, `drive(task, config) -> TaskResult`. Drivers don't
re-implement the loop; they delegate to `convertible.loop.run` and only supply
*how the model is called* (a `complete` function).

## Wheels: entry-point discovery

An engine becomes available by advertising itself under the
`convertible.engines` **Python entry-point group**. The two bundled engines do
this in this repo's `pyproject.toml`; an out-of-tree wheel does the *identical*
thing in its own metadata, and `convertible wheels list` discovers it with no
change to convertible core (`convertible/registry.py` — the "garage").

```toml
[project.entry-points."convertible.engines"]
my-engine = "my_package.engine:MyEngine"
```

```bash
convertible wheels list          # the garage: engines installed in this env
convertible wheels list --json
convertible drive "..." --engine my-engine
```

Requesting an unknown engine raises `UnknownEngine`, listing the available
names.

## The two bundled engines

### `mock` — the reference engine

Deterministic and networkless (`convertible/engines/mock.py`). It runs the exact
same chassis as a real engine — the shared contract and the bounded loop — but
supplies a scripted two-turn `complete` (write a marker file
`convertible-mock.md`, then `finish`) instead of calling a model. That makes it
the **CI workhorse**: it proves the harness end-to-end with no network and no
flakiness, and it is the reference against which a live engine's result *shape*
is compared (the all-engines rule). The e2e shape test
(`tests/test_e2e_mock.py`) is the guard.

### `vllm-openai` — the real backend

Drives any **OpenAI-compatible** `/v1/chat/completions` endpoint with tool
calling (`convertible/engines/vllm_openai.py`). The reference rig is Qwen3-32B
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
checkpoint) want `qwen3_coder`. The engine is parser-agnostic — any parser that
makes the server emit OpenAI-format tool calls works. The opt-in live test
proves the path against a real server:

```bash
CONVERTIBLE_VLLM_E2E=1 uv run pytest tests/test_vllm_live.py -v
```

## Writing your own engine wheel

```python
from convertible.engine import Engine
from convertible.loop import run

class MyEngine(Engine):
    name = "my-engine"

    def drive(self, task, config):
        return run(
            self._make_complete(config),
            task,
            max_steps=config.max_steps,
            system_prompt=self.system_prompt(task, config),
        )
```

Because the loop owns [hook firing](hooks.md) and [telemetry](telemetry.md), and
the base class injects the [layered system prompt](layered-config.md) via
`self.system_prompt(...)`, a custom engine inherits the full lifecycle layer for
free. Advertise it under the entry-point group and it's discoverable — no change
to convertible core.

## Key files

- `convertible/engine.py` — the `Engine` ABC + the `system_prompt()` base helper.
- `convertible/registry.py` — entry-point discovery (`catalog`, `names`, `load`).
- `convertible/engines/mock.py` — the reference engine.
- `convertible/engines/vllm_openai.py` — the OpenAI-compatible driver.

## See also

- [model-selection.md](model-selection.md) — how convertible resolves the model
  and endpoint (flags → env → defaults), and keeping it synced to a local server.
- [drive-and-loop.md](drive-and-loop.md) — the contract + loop drivers delegate to.
- [layered-config.md](layered-config.md) — the per-model system prompt every
  engine inherits.
- [doctor.md](doctor.md) — the `engines` check-group probes all wheels uniformly.
