"""End-to-end destination guards + before-state characterization (c4/c8/h1/h4).

This is the cross-cutting integration guard for the "colleague destination"
feature. It proves two honest claims hold together, end to end:

* **Arrival recorded (c8/h1).** A drive can BOTH use the ``devague`` destination
  tool AND declare arrival via ``finish(destination=…, announcement=…)`` without
  breaking termination. We script a fake ``complete`` that first issues a
  ``devague`` move and then a ``finish`` carrying the destination + announcement,
  monkeypatch :func:`colleague.devague.run_devague` to a stub (so NO real
  ``devague`` CLI / subprocess / socket is ever touched), drive the loop, write
  the result via :func:`colleague.artifact.write`, and assert the artifact JSON
  CONTAINS ``destination`` + ``announcement`` and that the drive terminated within
  ``max_steps`` (the fake ``complete`` is bounded so it cannot loop forever).

* **Before-state characterization (c4/h4).** The destination/goal concept is
  purely ADDITIVE and opt-in. The :class:`~colleague.contract.Task` carries NO
  destination/goal/convergence field — the instruction is still just a string —
  and a plain drive (no destination) yields ``TaskResult.destination is None`` and
  an artifact JSON that OMITS both keys. This pins the honest claim that
  colleague had no destination concept before; the feature is default-off.

The fake ``complete`` mirrors the scripted-playback pattern from
``tests/test_destination_loop.py`` (ModelResponse / ToolCall construction).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import colleague.devague as devague_mod
from colleague import artifact
from colleague.contract import OK, Task, TaskResult
from colleague.loop import CompleteFn, ModelResponse, ToolCall, run

# ---------------------------------------------------------------------------
# Helpers — scripted, bounded fake complete() (copied pattern from t4 tests)
# ---------------------------------------------------------------------------


def scripted(responses: list[ModelResponse]) -> CompleteFn:
    """Return a complete() that plays back canned responses in order.

    Bounded: once the script is exhausted it repeats the LAST response. Every
    response in the destination scripts below ends in a ``finish`` call, so the
    loop terminates on the finish turn — it can never run away.
    """
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        i = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[i]

    return complete


def _stub_run_devague(monkeypatch: pytest.MonkeyPatch, calls: list[tuple]) -> None:
    """Replace devague.run_devague with an in-process stub.

    Records each call and returns a canned CLI-shaped string. This guarantees NO
    real ``devague`` binary is launched: no subprocess, no socket, no daemon — the
    e2e is fully hermetic. If the real run_devague were ever called it would shell
    out to an (absent) CLI; the stub structurally prevents that.
    """

    def fake(move, args, *, root):
        calls.append((move, list(args), Path(root)))
        return "exit=0\nstub: devague move ran in-process (no subprocess)"

    monkeypatch.setattr(devague_mod, "run_devague", fake)


# ---------------------------------------------------------------------------
# 1. Arrival recorded e2e (c8/h1) — devague tool + finish-with-destination,
#    written through the real artifact writer, terminates within max_steps.
# ---------------------------------------------------------------------------


def test_destination_drive_records_arrival_in_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A drive that uses the devague tool AND declares arrival lands in the artifact.

    Proves honesty condition h1: using the destination tool and declaring arrival
    do NOT break termination — the loop returns within max_steps, and the artifact
    on disk carries both destination + announcement.
    """
    repo = tmp_path / "repo"
    repo.mkdir()

    devague_calls: list[tuple] = []
    _stub_run_devague(monkeypatch, devague_calls)

    slug = "ship-core-widget"
    announcement = "The core widget has shipped."

    # Turn 1: open a goal-frame via the devague tool. Turn 2: finish, declaring
    # arrival. Two scripted turns, both bounded — the second is a finish.
    responses = [
        ModelResponse(
            tool_calls=[ToolCall("dv-1", "devague", {"move": "new", "args": [slug]})],
            prompt_tokens=3,
            completion_tokens=2,
        ),
        ModelResponse(
            tool_calls=[
                ToolCall(
                    "fin-1",
                    "finish",
                    {
                        "summary": "shipped the widget",
                        "destination": slug,
                        "announcement": announcement,
                    },
                )
            ],
            prompt_tokens=2,
            completion_tokens=1,
        ),
    ]

    max_steps = 5
    task = Task.new(str(repo), "ship the core widget")
    result = run(scripted(responses), task, max_steps=max_steps)

    # --- Termination within budget (h1): the drive RETURNED, did not run away. ---
    assert isinstance(result, TaskResult)
    assert result.status == OK
    # The devague step + the finish step were both recorded; <= max_steps proves
    # it terminated on the finish turn, not at the budget ceiling.
    assert 0 < len(result.steps) <= max_steps
    # The finish step itself is the terminating step (it is the last one taken).
    assert result.steps[-1].tool == "finish"

    # --- The destination tool really ran (in-process stub) — no real CLI/subprocess. ---
    assert devague_calls == [("new", [slug], repo.resolve())]

    # --- Arrival recorded on the result object. ---
    assert result.destination == slug
    assert result.announcement == announcement

    # --- Arrival recorded in the ARTIFACT on disk (the dashboard payload). ---
    out_dir = tmp_path / "artifacts"
    result_path = artifact.write(result, out_dir)
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["destination"] == slug
    assert payload["announcement"] == announcement
    # Round-trips back to an equal result (the contract's JSON invariant).
    assert TaskResult.from_dict(payload).destination == slug
    assert TaskResult.from_dict(payload).announcement == announcement


def test_destination_drive_uses_no_real_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The destination e2e is hermetic: with run_devague stubbed, the real
    subprocess.run inside colleague.devague is never reached.

    We sabotage subprocess.run *inside the devague module* to raise if invoked —
    since the stub replaces run_devague entirely, this must never fire. This is the
    explicit "no real subprocess / no socket / no daemon" assertion.
    """
    repo = tmp_path / "repo"
    repo.mkdir()

    devague_calls: list[tuple] = []
    _stub_run_devague(monkeypatch, devague_calls)

    def _boom(*_args, **_kwargs):  # pragma: no cover - asserts it is NOT called
        raise AssertionError("a real subprocess was launched — the e2e is not hermetic")

    monkeypatch.setattr(devague_mod.subprocess, "run", _boom)

    responses = [
        ModelResponse(tool_calls=[ToolCall("dv-1", "devague", {"move": "status"})]),
        ModelResponse(
            tool_calls=[
                ToolCall(
                    "fin-1",
                    "finish",
                    {"summary": "done", "destination": "d", "announcement": "a"},
                )
            ]
        ),
    ]
    result = run(scripted(responses), Task.new(str(repo), "check then finish"), max_steps=5)

    assert result.status == OK
    assert result.destination == "d"
    # The stub absorbed the call; the real subprocess.run was never reached.
    assert devague_calls == [("status", [], repo.resolve())]


# ---------------------------------------------------------------------------
# 2. Before-state characterization (c4/h4) — the concept is additive, default-off.
# ---------------------------------------------------------------------------


def test_task_has_no_destination_field() -> None:
    """The Task contract has NO destination/convergence/announcement/frame field.

    The devague destination concept stays additive on the *result* side only
    (``TaskResult.destination``/``announcement``) — a ``Task`` still cannot
    carry a devague goal-frame. This pins the honest before-state for the
    devague destination feature specifically.

    NOTE (spec R6 / plan t14 / #259): ``Task`` DID later gain a plain, optional
    ``goal`` field — a one-line pre-execution goal statement, unrelated to the
    devague destination/goal-frame concept this test guards against. That
    change is deliberate and documented (see ``test_contract_goal.py``), so
    ``goal`` is intentionally excluded from the forbidden set below.
    """
    task_fields = set(Task.__dataclass_fields__.keys())
    forbidden = {"destination", "convergence", "announcement", "frame"}
    leaked = task_fields & forbidden
    assert leaked == set(), f"Task gained a goal-ish field: {sorted(leaked)} — must stay additive"

    # The instruction is, and remains, a plain string.
    task = Task.new("/repo", "just an instruction")
    assert isinstance(task.instruction, str)
    # Task.to_dict() likewise carries no destination/convergence/etc. keys.
    serialized = task.to_dict()
    assert not (set(serialized.keys()) & forbidden)


def test_plain_drive_yields_no_destination_and_omits_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plain drive (no destination tool, plain finish) → destination is None and
    the artifact OMITS both keys — the default-off path is byte-identical to before.

    run_devague is stubbed to raise if it is ever touched: a plain drive must not
    invoke the destination tool at all.
    """
    repo = tmp_path / "repo"
    repo.mkdir()

    def _should_not_run(*_args, **_kwargs):  # pragma: no cover - asserts NOT called
        raise AssertionError("run_devague was called on a no-destination drive")

    monkeypatch.setattr(devague_mod, "run_devague", _should_not_run)

    responses = [ModelResponse(tool_calls=[ToolCall("fin", "finish", {"summary": "plain"})])]
    result = run(scripted(responses), Task.new(str(repo), "plain task"), max_steps=5)

    assert result.status == OK
    # Default-off: no destination on the object.
    assert result.destination is None
    assert result.announcement is None

    # The artifact JSON OMITS both keys (not present-as-null) — byte-identical
    # to the pre-feature shape.
    out_dir = tmp_path / "artifacts"
    payload = json.loads(artifact.write(result, out_dir).read_text(encoding="utf-8"))
    assert "destination" not in payload
    assert "announcement" not in payload
