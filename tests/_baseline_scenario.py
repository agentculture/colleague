"""Shared scenario builder — recorded from main, replayed against this branch.

Task t22 (spec docs/specs/2026-08-27-adopt-from-qwen-code.md, plan
adopt-from-qwen-code): reversibility pinning needs ONE scenario definition
that produces the SAME shape whether it runs against the pre-arc baseline
(``uv run --project <baseline-checkout> python tests/_baseline_scenario.py
<out-dir>``, used ONCE to record ``tests/fixtures/main_baseline/*.json``) or
against this branch with every adopted knob at its off value
(``tests/test_knobs_byte_identical.py`` imports :func:`capture_mock_scenario`
/ :func:`capture_vllm_scenario` directly).

Two scenarios, matched to the brief's shape:

* :func:`capture_mock_scenario` — the mock engine's default two-turn script
  (write the marker file, then finish) against a fixed repo. Mock is the
  contract reference (h8) and its scripted turns are unaffected by any of the
  eleven knobs, so this scenario mainly pins the tool-schema surface + system
  prompt + step shape.
* :func:`capture_vllm_scenario` — a plain single-call-per-turn 3-turn run
  (``list_dir``, ``read_file``, ``finish``) against a REAL
  ``ThreadingHTTPServer`` socket rig (the idiom in ``tests/test_tokenize_once.py``),
  scripted the way ``tests/_batch_fixture.py`` scripts vllm-openai replies.
  Main has no batch scenario (t17 is this-branch-only), so this stays a
  plain sequential script — every call here is concurrency-safe on its own
  (a single call per turn), so ``COLLEAGUE_TOOL_CONCURRENCY`` never changes
  its shape; that knob is pinned separately by a dedicated multi-call-turn
  probe in ``test_knobs_byte_identical.py``.

Both scenarios capture: the request payload JSON per vllm turn (the fixed
key subset ``PAYLOAD_KEYS``), the offered tool schema names + parameter
keys, the assembled system prompt, the Step sequence (tool, ok), and — for
the vllm scenario — the ``/tokenize`` call count. The repo is a fresh tmp
dir recreated identically on each run; no captured payload interpolates its
absolute path (tools address paths repo-relative on the wire), so the
recorded JSON is stable across machines/runs.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

#: The fixed payload key subset the brief calls out; anything else (an extra
#: per-era key neither side is pinning) is dropped before comparison so this
#: fixture never silently starts asserting on an unrelated field.
PAYLOAD_KEYS = (
    "model",
    "messages",
    "temperature",
    "tools",
    "tool_choice",
    "stream",
    "stream_options",
    "chat_template_kwargs",
    "max_tokens",
)

README_BODY = "# fixture\n\nOne runtime, many minds.\n"
MOCK_INSTRUCTION = "add a short note about the fixture repo"
VLLM_INSTRUCTION = "three turns: list, read, finish"

_ENGINE_CONFIG_KW: "dict[str, Any]" = dict(
    max_steps=6,
    watch=False,
    lint=False,
    affected_tests=False,
    testintegrity=False,
    coherence=False,
    memory=False,
)


def make_repo(root: Path) -> Path:
    """A fixed, deterministic repo: one README the vllm script reads."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text(README_BODY)
    return root


def offered_schema_shape() -> "list[dict[str, Any]]":
    """Name + parameter-property keys for every tool this era offers, unfiltered.

    ``curate_schemas`` predates this arc (typed-subagent-roles, PR #221) — it
    is the SAME call on both eras. ``COLLEAGUE_TOOLS_LEGACY`` (when the
    calling process defines it) decides whether ``grep_search``/``glob`` join
    the surface on THIS branch; main never offers them regardless.
    """
    from colleague.tools import curate_schemas

    schemas = curate_schemas(None)
    out = []
    for schema in schemas:
        fn = schema["function"]
        params = fn.get("parameters", {}).get("properties", {})
        out.append({"name": fn["name"], "params": sorted(params.keys())})
    return sorted(out, key=lambda d: d["name"])


def system_prompt_text() -> str:
    """The loop's default system prompt for a layer-free repo.

    This branch's :mod:`colleague.prompttext` module builds the pre-arc text
    byte-for-byte under ``COLLEAGUE_PROMPT_VARIANT=v1`` (set by the caller
    before invoking either scenario); main has no such module, so its
    ``colleague.loop._DEFAULT_SYSTEM`` is read directly.
    """
    try:
        from colleague.prompttext import default_system

        return default_system()
    except ImportError:
        from colleague.loop import _DEFAULT_SYSTEM

        return _DEFAULT_SYSTEM


def _step_shape(result: Any) -> "list[list[Any]]":
    return [[s.tool, bool(s.ok)] for s in result.steps]


def capture_mock_scenario(repo: Path) -> "dict[str, Any]":
    """Run the mock engine's default script against *repo*; capture its shape."""
    from colleague.config import EngineConfig
    from colleague.contract import Task
    from colleague.registry import load

    config = EngineConfig(**_ENGINE_CONFIG_KW)
    task = Task(id="t22-mock", repo_path=str(repo), instruction=MOCK_INSTRUCTION, engine="mock")
    result = load("mock").work(task, config)
    return {
        "status": result.status,
        "steps": _step_shape(result),
        "schemas": offered_schema_shape(),
        "system_prompt": system_prompt_text(),
    }


def _turn(tool: str, arguments: "dict[str, Any]") -> "dict[str, Any]":
    return {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": f"call-{tool}",
                            "type": "function",
                            "function": {"name": tool, "arguments": json.dumps(arguments)},
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3},
    }


def _finish_turn() -> "dict[str, Any]":
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-finish",
                            "type": "function",
                            "function": {
                                "name": "finish",
                                "arguments": json.dumps({"summary": "three turns, done"}),
                            },
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 6, "completion_tokens": 2},
    }


def three_turn_script() -> "list[Callable[[], dict[str, Any]]]":
    """The plain scripted turns: ``list_dir``, ``read_file``, ``finish`` — one
    tool call per turn (every call here is its own concurrency-safe batch of
    one, so ``COLLEAGUE_TOOL_CONCURRENCY`` never changes this scenario's shape)."""
    return [
        lambda: _turn("list_dir", {"path": "."}),
        lambda: _turn("read_file", {"path": "README.md"}),
        lambda: _finish_turn(),
    ]


class ScriptedVllmRig:
    """A plain, blocking fake vLLM: ``/tokenize`` + scripted chat turns, on a
    REAL socket (the idiom in ``tests/test_tokenize_once.py``'s ``_Rig``).

    Records every ``/v1/chat/completions`` payload verbatim (filtered to
    :data:`PAYLOAD_KEYS`) alongside a count of ``/tokenize`` POSTs.
    """

    def __init__(self, turns: "list[Callable[[], dict[str, Any]]]", *, max_model_len: int = 8192):
        self.tokenize_calls = 0
        self.chat_calls = 0
        self.payloads: "list[dict[str, Any]]" = []
        self.max_model_len = max_model_len
        rig = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_a: object) -> None:  # quiet
                return

            def _reply(self, code: int, body: "dict[str, Any]") -> None:
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self) -> None:
                n = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(n) or b"{}")
                if self.path == "/tokenize":
                    rig.tokenize_calls += 1
                    from colleague.context import count_tokens_chars

                    count = count_tokens_chars(payload.get("messages") or [])
                    self._reply(200, {"count": count, "max_model_len": rig.max_model_len})
                    return
                rig.payloads.append({k: payload[k] for k in PAYLOAD_KEYS if k in payload})
                idx = rig.chat_calls
                rig.chat_calls += 1
                script = turns[min(idx, len(turns) - 1)]
                self._reply(200, script())

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self) -> str:
        self.thread.start()
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}/v1"

    def __exit__(self, *exc: object) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def capture_vllm_scenario(repo: Path) -> "dict[str, Any]":
    """Run the plain 3-turn scripted vllm-openai run against *repo*; capture its shape."""
    from colleague.config import EngineConfig
    from colleague.contract import Task
    from colleague.registry import load

    rig = ScriptedVllmRig(three_turn_script())
    with rig as base_url:
        config = EngineConfig(base_url=base_url, model="fake-served", **_ENGINE_CONFIG_KW)
        task = Task(
            id="t22-vllm", repo_path=str(repo), instruction=VLLM_INSTRUCTION, engine="vllm-openai"
        )
        result = load("vllm-openai").work(task, config)
    return {
        "status": result.status,
        "steps": _step_shape(result),
        "schemas": offered_schema_shape(),
        "system_prompt": system_prompt_text(),
        "tokenize_calls": rig.tokenize_calls,
        "chat_calls": rig.chat_calls,
        "payloads": rig.payloads,
    }


def main(argv: "list[str]") -> int:
    """Record both scenarios' captured shape as JSON under ``argv[1]``."""
    out_dir = Path(argv[1]) if len(argv) > 1 else Path(".")
    out_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("COLLEAGUE_PROMPT_VARIANT", "v1")
    os.environ.setdefault("COLLEAGUE_STREAM", "0")
    os.environ.setdefault("COLLEAGUE_EXACT_TOKENS", "1")

    with tempfile.TemporaryDirectory() as td:
        mock_repo = make_repo(Path(td) / "mock")
        mock_capture = capture_mock_scenario(mock_repo)
    (out_dir / "mock_scenario.json").write_text(json.dumps(mock_capture, indent=2, sort_keys=True))

    with tempfile.TemporaryDirectory() as td:
        vllm_repo = make_repo(Path(td) / "vllm")
        vllm_capture = capture_vllm_scenario(vllm_repo)
    (out_dir / "vllm_scenario.json").write_text(json.dumps(vllm_capture, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
