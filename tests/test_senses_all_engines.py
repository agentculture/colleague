"""Arc-wide proofs for the cortex/senses arc (cortex/senses arc, task t11).

The cortex/senses split (a wide-window **cortex** model that drives the tool loop
plus a tools-off **senses** front door) is an ADDITIVE, opt-in feature. This file
is the consolidated, tests-only proof of the two invariants that let it ship
without touching any existing consumer:

* **Absent → byte-identical.** With no lobes/senses config anywhere, the mock
  work item's ``TaskResult.to_dict()`` carries NO ``"senses"`` key (omit-when-
  None), ``EngineConfig.resolve().to_dict()`` carries no ``senses``/``lobes``
  key, and a ``colleague session`` with no senses config logs no ``senses:``
  line — the artifact/config/session surfaces are indistinguishable from
  v1.34.0. (Acceptance 1.)
* **Senses-armed → the SAME shape across engines.** A senses-armed mock run
  fills a populated ``TaskResult.senses`` block whose serialized shape is exactly
  ``{"mode", "packet", "records": [{"point", "latency", "tokens", "degraded"}]}``
  — the same shape a live engine would fill, with the mock/degraded call
  recorded honestly (``degraded=True``, ``tokens=None``). The all-engines rule is
  proven directly: ``make_senses_run`` bound to the two REAL registry engines
  (``mock`` and ``vllm-openai``) each degrade to the identical ``SensesRecord``
  ``_key_shape`` (the ``test_e2e_mock.py`` cross-engine pattern). (Acceptance 2.)
* **No new base dep / no socket / no daemon.** ``colleague.lobes`` is
  urllib-only and ``colleague.senses`` is subprocess-free; importing both leaks
  no third-party module. The AUTHORITY for this claim is
  ``tests/test_zero_deps.py`` and ``tests/test_boundary.py`` passing UNMODIFIED;
  this file adds a focused, self-contained mirror. (Acceptance 3.)

These are proofs, not new behavior — every assertion here is over shapes the arc
already produces; ``test_e2e_mock.py`` / ``test_zero_deps.py`` / ``test_boundary.py``
are deliberately NOT modified (proving they pass unmodified IS the point).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from colleague import registry
from colleague.cli._commands import session as session_mod
from colleague.cli._commands.session import SensesSessionOptions, SessionIO, _Session
from colleague.config import EngineConfig, SensesConfig
from colleague.contract import OK, SensesBlock, Task, TaskResult
from colleague.engines import vllm_openai
from colleague.loop import ContextControls, ModelResponse, ToolCall, run
from colleague.senses import MEDIA_BRIDGE_POINT, make_senses_run

# The pinned pre-senses TaskResult.to_dict() key set (copied verbatim from
# test_e2e_mock.py's byte-identical guards). A senses-absent run must serialize
# with EXACTLY these keys — "senses" must never appear.
_PRE_SENSES_TASKRESULT_KEYS = {
    "task_id",
    "status",
    "summary",
    "changed_files",
    "steps",
    "usage",
    "stats",
    "finish_states",
    "artifacts_path",
    "error",
    "branch",
    "pr_url",
    "hook_firings",
    "command",
    "not_finished",
    "stopped_without_finish",
    # prompt_digest (plan task t7): the sha256 of the composed system
    # prompt is UNCONDITIONAL observability — every run that composes a
    # prompt carries it, so a live-testing row can attribute its prose
    # arm. Omitted only when the backend composed no prompt at all.
    "prompt_digest",
    # offered_tools (delegation-follow-ups t2): the rendered tool names, so a
    # surface arm is attributable off the artifact. Omitted when None.
    "offered_tools",
    # effort (effort-v4 t5): the {seat: rung} block — unconditional on a
    # default run since the v4 acting seat always resolves ("low").
    "effort",
    "sampling",  # #479 t9: the resolved sampling profile (row + wire)
}


def _key_shape(value):
    """Recursive key signature, ignoring concrete values — for shape comparison.

    Copied from ``test_e2e_mock.py`` so the cross-engine senses comparison uses
    the SAME structural-identity check the e2e shape guard uses.
    """
    if isinstance(value, dict):
        return {k: _key_shape(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return _key_shape(value[0]) if value else None
    return None


def _png(root: Path, name: str = "shot.png") -> str:
    """Write a minimal PNG file and return its path (mirrors test_loop_senses)."""
    path = root / name
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    return str(path)


def _finish_complete(seen: list):
    """A cortex ``complete`` that records the messages it saw and calls finish."""

    def complete(messages: list[dict]) -> ModelResponse:
        seen.append([dict(m) for m in messages])
        return ModelResponse(tool_calls=[ToolCall("1", "finish", {"summary": "done"})])

    return complete


def _senses_armed_config(*, multimodal: bool = True) -> EngineConfig:
    """A config carrying a senses declaration (the presence signal)."""
    return EngineConfig(
        senses=SensesConfig(
            model="gemma-senses",
            base_url="http://senses",
            api_key="k",
            context_budget=24000,
            multimodal=multimodal,
        )
    )


def _image_parts() -> list[dict]:
    """A minimal OpenAI image content-parts list (mirrors test_loop_senses)."""
    return [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}]


# ===========================================================================
# Acceptance 1 — ABSENT everywhere is byte-identical to v1.34.0
# ===========================================================================


def test_absent_mock_taskresult_omits_senses_key_byte_identical(tmp_path: Path) -> None:
    """A mock work item with NO senses config serializes with NO ``senses`` key.

    Mirrors ``test_e2e_mock.py``'s destination/sub_results/policy byte-identical
    guards: the ``senses`` block is omit-when-None, so an unarmed run's
    ``to_dict()`` key set is EXACTLY the pre-senses key set — the artifact is
    indistinguishable from a pre-feature colleague.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    cfg = EngineConfig.resolve()
    assert cfg.senses is None  # nothing armed the front door

    result = registry.load("mock").work(Task.new(str(repo), "do work"), cfg)

    assert result.status == OK
    assert result.changed_files  # a real, non-empty run
    assert result.senses is None  # the field stayed off …
    serialized = result.to_dict()
    assert "senses" not in serialized  # … and the key is OMITTED, not null
    # Byte-identical guard: the exact key set is the pre-senses key set.
    assert set(serialized.keys()) == _PRE_SENSES_TASKRESULT_KEYS


def test_absent_config_to_dict_has_no_senses_or_lobes_key() -> None:
    """``EngineConfig.resolve().to_dict()`` carries no senses/lobes key unarmed.

    Mirrors ``test_config_senses.py``'s ``test_absent_to_dict_has_no_senses_key``:
    the senses snapshot is present ONLY when configured, and the lobes discovery
    rung writes nothing into the config snapshot. So the resolved-config artifact
    is byte-identical to v1.34.0 when nothing is armed.
    """
    snapshot = EngineConfig.resolve().to_dict()
    assert "senses" not in snapshot
    assert "lobes" not in snapshot


def test_absent_config_resolve_equals_bare_default() -> None:
    """resolve() with nothing configured equals the bare dataclass default.

    The senses field (and everything the arc added to ``EngineConfig``) resolves
    to its default when unarmed, so config resolution changed nothing else
    (dataclass ``__eq__`` over every compare=True field).
    """
    assert EngineConfig.resolve() == EngineConfig()
    assert EngineConfig().senses is None


def test_session_without_senses_config_logs_no_senses_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ``colleague session`` with no senses config never runs intake / logs no
    ``senses:`` line — byte-identical to a pre-feature session.

    Reuses the ``tests/test_session_senses.py`` fake-``work_fn`` harness (a
    scripted ``_Session.run`` over a recording fake). ``run_senses_intake`` is
    monkeypatched to a bomb: with no senses model resolved it must never fire.
    """

    def _boom(*a, **k):
        raise AssertionError("senses intake must not run without a senses model")

    monkeypatch.setattr(session_mod, "run_senses_intake", _boom)

    out, err = _CollectingOut(), _CollectingOut()
    result = TaskResult(task_id="t", status=OK, summary="raw cortex summary")
    plain = EngineConfig.resolve(model="cortex-model")  # NO senses declared
    assert plain.senses is None

    sess = _make_session(tmp_path, result, config=plain, out=out, err=err)
    sess.run(iter(["do the thing"]))

    # No packet was attached (intake never ran) → the artifact stays senses-less …
    assert result.senses is None
    # … and no visible senses: line was ever logged.
    assert "senses:" not in out.text()


# ===========================================================================
# Acceptance 2 — SENSES-ARMED pins the full TaskResult.senses shape (all-engines)
# ===========================================================================


def test_senses_armed_mock_run_pins_full_senses_block_shape(tmp_path: Path) -> None:
    """A senses-armed mock run fills a populated ``TaskResult.senses`` block whose
    serialized shape is exactly ``{mode, packet, records:[{point, latency, tokens,
    degraded}]}`` — the SAME shape a live engine would fill, with the mock call
    recorded as a degraded no-op (``degraded=True``, ``tokens=None``).

    Driven through the real loop (``colleague.loop.run``) with a senses-armed
    ``ContextControls`` (the REAL ``make_senses_run(config, "mock")`` binding) +
    an image attachment, so the media bridge fires, calls the mock-bound senses
    run, and — because ``mock.make_complete`` raises — records the degraded
    ``SensesRecord`` the same way a live engine records a real one.
    """
    config = _senses_armed_config(multimodal=True)
    senses_run = make_senses_run(config, "mock")
    assert senses_run is not None  # armed (config.senses is not None)

    from colleague import media

    attachment = media.validate_attachment(_png(tmp_path))
    task = Task.new(str(tmp_path), "what color is this?", attachments=[attachment])
    controls = ContextControls(senses_run=senses_run, senses_media_bridge=True)

    seen: list = []
    result = run(_finish_complete(seen), task, max_steps=3, context=controls)
    assert result.status == OK

    # The block is populated on the object …
    assert isinstance(result.senses, SensesBlock)
    assert result.senses is not None

    # … and its SERIALIZED shape is pinned exactly.
    block = result.senses.to_dict()
    assert set(block.keys()) == {"mode", "packet", "records"}
    assert block["mode"] == "split"
    assert block["packet"] is None  # no context packet, only the bridge record
    assert isinstance(block["records"], list)
    assert len(block["records"]) == 1

    record = block["records"][0]
    assert set(record.keys()) == {"point", "latency", "tokens", "degraded"}
    assert record["point"] == MEDIA_BRIDGE_POINT
    # The mock degrade is a RECORDED no-op — the same shape a live fill would use.
    assert record["degraded"] is True
    assert record["tokens"] is None
    assert isinstance(record["latency"], float)
    assert record["latency"] >= 0.0

    # The block round-trips through from_dict → to_dict identically (artifact
    # read-back is faithful).
    assert SensesBlock.from_dict(block).to_dict() == block

    # The bridge was PREFERRED and standalone — nothing landed on deepthink.
    assert result.deepthink is None


def test_senses_record_shape_identical_across_mock_and_vllm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All-engines rule: ``make_senses_run`` bound to the two REAL registry
    engines (``mock`` and ``vllm-openai``) degrades to the IDENTICAL
    ``SensesRecord`` shape — the ``test_e2e_mock.py`` ``_key_shape`` cross-engine
    guard, applied to the senses record.

    This is the genuine cross-engine comparison (not merely structural): both
    branches load a real ``Engine`` via ``registry.load`` and drive the real
    ``run_senses_media_bridge``. ``mock`` degrades because its ``make_complete``
    raises; ``vllm-openai`` degrades because its wire is stubbed to fail (no real
    network) — the SAME degraded record shape for both, proving the block a live
    vLLM would fill is shape-identical to the mock reference.
    """
    config = _senses_armed_config(multimodal=True)
    parts = _image_parts()

    # mock: make_complete raises → degrade-never-raise.
    mock_run = make_senses_run(config, "mock")
    assert mock_run is not None
    mock_text, mock_record = mock_run("describe the image", parts)

    # vllm-openai: stub BOTH wire seams so the bridge degrades with zero network:
    # the counter's /tokenize probe returns None (→ char fallback, no network),
    # and the completion POST raises (→ degrade). Neither touches a live server.
    monkeypatch.setattr(vllm_openai, "_tokenize_count", lambda *a, **k: None)

    def _no_server(*a, **k):
        raise ConnectionError("no served endpoint in a unit test")

    monkeypatch.setattr(vllm_openai, "_post_json", _no_server)

    vllm_run = make_senses_run(config, "vllm-openai")
    assert vllm_run is not None
    vllm_text, vllm_record = vllm_run("describe the image", parts)

    # Both degraded to a recorded no-op — never raised, never fabricated content.
    assert mock_text is None
    assert vllm_text is None
    for record in (mock_record, vllm_record):
        assert record.degraded is True
        assert record.tokens is None
        assert record.point == MEDIA_BRIDGE_POINT

    # The SERIALIZED shape is identical across the two real engines (the e2e
    # cross-engine _key_shape guard) — the all-engines invariant for senses.
    assert _key_shape(mock_record.to_dict()) == _key_shape(vllm_record.to_dict())
    # And the shape is exactly the pinned SensesRecord contract.
    assert set(mock_record.to_dict().keys()) == {"point", "latency", "tokens", "degraded"}


def test_make_senses_run_is_none_without_senses_config() -> None:
    """No senses config → ``make_senses_run`` returns ``None`` for BOTH engines,
    so the senses bridge stays dormant identically everywhere (all-engines).
    """
    plain = EngineConfig()
    assert plain.senses is None
    assert make_senses_run(plain, "mock") is None
    assert make_senses_run(plain, "vllm-openai") is None


# ===========================================================================
# Acceptance 3 — no new base dep / no socket / no daemon
# ===========================================================================


def test_importing_lobes_and_senses_leaks_no_third_party() -> None:
    """Importing ``colleague.lobes`` + ``colleague.senses`` introduces no
    third-party top-level module beyond the sanctioned ``agentfront`` base dep.

    A focused mirror of ``tests/test_zero_deps.py``'s ``_third_party_modules_
    introduced`` guard, scoped to the two arc modules. The AUTHORITY for the
    zero-deps posture is ``test_zero_deps.py`` passing unmodified; this is a
    named, self-contained check that the arc's new modules did not slip a dep in.
    """
    before = set(sys.modules.keys())
    import colleague.lobes  # noqa: F401
    import colleague.senses  # noqa: F401

    new_top_level = {name.split(".")[0] for name in (set(sys.modules.keys()) - before) if name}
    leaked = [
        name
        for name in sorted(new_top_level)
        if name not in sys.stdlib_module_names
        and not name.startswith("colleague")
        and not name.startswith("_")
        and name != "agentfront"
        and name not in {"importlib", "pip", "pkg_resources", "site"}
    ]
    assert not leaked, (
        f"colleague.lobes / colleague.senses leaked third-party imports: {leaked}. "
        "Expected only stdlib, colleague, or the sanctioned agentfront base dep."
    )


def test_lobes_is_urllib_only_and_senses_is_subprocess_free() -> None:
    """``colleague/lobes.py`` is urllib-only (no socket/subprocess/thread) and
    ``colleague/senses.py`` is subprocess/socket/thread-free.

    A focused, source-level mirror of ``tests/test_boundary.py`` (the authority):
    ``lobes.py`` must NOT appear in ``_SUBPROCESS_ALLOWED`` (it speaks the gateway
    over stdlib ``urllib``, not a subprocess), and ``senses.py`` is a pure
    invocation layer over the engine's ``make_complete`` seam.
    """
    package_dir = Path(__file__).resolve().parents[1] / "colleague"

    lobes_src = (package_dir / "lobes.py").read_text(encoding="utf-8")
    # It IS a urllib client …
    assert "urllib.request" in lobes_src
    # … and it opens no socket / spawns no subprocess / forks no daemon.
    for forbidden in ("import socket", "import subprocess", "import threading", "import asyncio"):
        assert forbidden not in lobes_src, f"lobes.py must not use {forbidden!r}"

    senses_src = (package_dir / "senses.py").read_text(encoding="utf-8")
    for forbidden in (
        "import socket",
        "import subprocess",
        "import threading",
        "concurrent.futures",
        "import asyncio",
    ):
        assert forbidden not in senses_src, f"senses.py must not use {forbidden!r}"


# ===========================================================================
# Session harness (a minimal, self-contained mirror of tests/test_session_senses.py)
# ===========================================================================


class _CollectingOut:
    """A recording stand-in for the session's ``out``/``err`` sinks."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, *args: object, **kwargs: object) -> None:
        self.lines.append(" ".join(str(a) for a in args))

    def text(self) -> str:
        return "\n".join(self.lines)


def _make_session(
    tmp_path: Path,
    result: TaskResult,
    *,
    config: EngineConfig,
    out: _CollectingOut,
    err: _CollectingOut,
    **over: object,
) -> _Session:
    """Build a ``_Session`` over a recording fake ``work_fn`` (mirrors
    ``tests/test_session_senses.py``'s ``_session`` helper).

    The fake stands in for ``execute_work``: it mirrors the loop's t6 packet
    injection (``result.senses = SensesBlock(mode=split, …)`` when a packet rides
    the task) so a real split run's finalize would fold onto it — but with no
    senses config the session never attaches a packet, so ``result.senses`` stays
    ``None`` (the byte-identical path this file exercises).
    """

    def _fake_work(**kwargs: object):
        task = kwargs.get("task")
        packet = getattr(task, "context_packet", None) if task is not None else None
        if packet is not None and result.senses is None:
            result.senses = SensesBlock(mode="split", packet=packet, records=[])
        return result, Path(str(tmp_path)) / ".colleague" / "art.json"

    senses_options = SensesSessionOptions(
        cortex_only=bool(over.pop("cortex_only", False)),
        debug_senses=bool(over.pop("debug_senses", False)),
    )
    return _Session(
        repo=tmp_path,
        engine_name="mock",
        open_pr=False,
        base="main",
        config=config,
        json_mode=False,
        view="markdown",
        io=SessionIO(out=out, err=err),
        work_fn=_fake_work,
        senses_options=senses_options,
        **over,
    )
