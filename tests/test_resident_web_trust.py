"""t10 — the c43 ``web`` boundary in the mesh resident.

Two rules, both turn-scoped (see :mod:`colleague.resident.webtrust`):

* a turn that did NOT originate from the operator has ``web`` withheld from
  its curated tool surface — expressed through the EXISTING
  ``narrow_role_by_tool_set`` / ``curate_schemas`` path, never a new gate;
* a turn a Culture node marks as relaying the operator's own request counts
  as operator-initiated, but owes ONE explicit confirmation before its first
  web fetch; the next call proceeds once an affirmative arrives.

The pure classifier/gate tests import no ``agent_lifecycle`` (like
``tests/test_resident_trust.py``), so they run without the
``[culture]``/``[resident]`` extra; the appserver-wiring test importorskips it
inside the test body.

``shutil.which`` is monkeypatched in every test that asserts ``web`` IS
offered, so the suite never depends on webglass being installed on PATH.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from colleague import web_schemas
from colleague.resident.webtrust import (
    RELAYED_OPERATOR_METADATA_KEY,
    WebConfirmationGate,
    classify_origin,
    curate_turn_role,
    curate_turn_schemas,
    is_affirmative,
    resolve_web_access,
    turn_lifecycle,
    turn_tool_set,
)
from colleague.roles import Role

WEB = web_schemas.WEB_TOOL_NAME


@pytest.fixture()
def webglass_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``web`` offerable regardless of the machine running the suite."""
    monkeypatch.setattr(web_schemas.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.delenv(web_schemas.WEB_ENV, raising=False)


def _names(schemas) -> set:
    return {s["function"]["name"] for s in schemas}


def _web_role() -> Role:
    """A read-only role that DOES carry ``web`` — so the withholding is provable
    independently of whether the built-in ``explorer`` happens to carry it."""
    return Role(
        name="web-explorer",
        prompt_fragment="",
        tool_allowlist=("read_file", "list_dir", WEB, "finish"),
        skill_subset=None,
        read_only=True,
    )


# ---------------------------------------------------------------------------
# Rule 1 — withholding on a non-operator turn
# ---------------------------------------------------------------------------


def test_peer_turn_curated_schemas_lack_web(webglass_on_path: None) -> None:
    """A peer-originated turn never sees ``web`` — full surface or curated role."""
    assert WEB not in _names(curate_turn_schemas(None, allow_web=False))
    assert WEB not in _names(curate_turn_schemas(_web_role(), allow_web=False))


def test_operator_turn_curated_schemas_include_web(webglass_on_path: None) -> None:
    """An operator-originated turn is offered ``web`` exactly when it is offerable."""
    assert web_schemas.offered(WEB, None)
    assert WEB in _names(curate_turn_schemas(None, allow_web=True))
    assert WEB in _names(curate_turn_schemas(_web_role(), allow_web=True))


def test_operator_turn_is_byte_identical_to_no_narrowing(webglass_on_path: None) -> None:
    """``allow_web`` narrows NOTHING — the operator lane keeps today's surface."""
    from colleague.tools import curate_schemas

    role = _web_role()
    assert turn_tool_set(role, allow_web=True) == ()
    assert curate_turn_role(role, allow_web=True) is role
    assert curate_turn_schemas(role, allow_web=True) == curate_schemas(role)


def test_withholding_only_ever_removes(webglass_on_path: None) -> None:
    """A role WITHOUT ``web`` is unaffected by the narrowing (never widened)."""
    from colleague.tools import curate_schemas

    role = Role("plain", "", ("read_file", "finish"), None, True)
    assert _names(curate_turn_schemas(role, allow_web=False)) == _names(curate_schemas(role))


def test_withheld_role_is_the_value_both_halves_take(webglass_on_path: None) -> None:
    """The narrowed role — one value for ``curate_schemas`` AND the executor
    allow-list — genuinely drops ``web`` from its allow-list, so the executor
    refuses the name even if a model guesses it."""
    narrowed = curate_turn_role(_web_role(), allow_web=False)
    assert WEB not in narrowed.tool_allowlist
    assert "read_file" in narrowed.tool_allowlist


def test_turn_lifecycle_carries_the_narrowing(webglass_on_path: None) -> None:
    """The engines' existing ``config_lifecycle`` snapshot seam carries it."""
    assert turn_lifecycle(_web_role(), allow_web=True) is None
    lifecycle = turn_lifecycle(_web_role(), allow_web=False)
    assert WEB not in lifecycle.snapshot.tool_set
    assert "read_file" in lifecycle.snapshot.tool_set
    # The engines call these unconditionally on any attachment — never raises.
    assert lifecycle.observe_turn()
    assert lifecycle.end_episode() == 0


# ---------------------------------------------------------------------------
# Turn origin
# ---------------------------------------------------------------------------


def test_operator_message_is_operator_initiated_not_relayed() -> None:
    origin = classify_origin(sender="ori", metadata=None, operator_identity="ori")
    assert origin.operator_initiated and not origin.relayed


def test_plain_peer_message_is_not_operator_initiated() -> None:
    origin = classify_origin(sender="peer", metadata={}, operator_identity="ori")
    assert not origin.operator_initiated and not origin.relayed
    assert WEB in origin.reason


def test_relayed_operator_request_is_operator_initiated() -> None:
    """The marker names the operator (or is ``True``) — the node relays, the
    operator authors."""
    for marker in (True, "ori"):
        origin = classify_origin(
            sender="node",
            metadata={RELAYED_OPERATOR_METADATA_KEY: marker},
            operator_identity="ori",
        )
        assert origin.operator_initiated and origin.relayed


def test_relay_marker_for_a_different_identity_is_not_operator_initiated() -> None:
    origin = classify_origin(
        sender="node",
        metadata={RELAYED_OPERATOR_METADATA_KEY: "someone-else"},
        operator_identity="ori",
    )
    assert not origin.operator_initiated


def test_unresolved_operator_identity_never_grants_web() -> None:
    """Fail-safe: with no operator configured, nothing is operator-initiated."""
    for meta in ({}, {RELAYED_OPERATOR_METADATA_KEY: True}):
        origin = classify_origin(sender="ori", metadata=meta, operator_identity=None)
        assert not origin.operator_initiated


# ---------------------------------------------------------------------------
# Rule 2 — the relayed turn's one confirmation
# ---------------------------------------------------------------------------


def test_first_web_call_requests_confirmation_second_proceeds_after_affirmative() -> None:
    """The acceptance flow: call 1 → the prompt (and no fetch); after 'yes',
    call 2 proceeds."""
    gate = WebConfirmationGate("node", operator_identity="ori")

    first = gate.before_web_call()
    assert not first.allowed
    assert first.confirmation_request is not None
    assert WEB in first.confirmation_request and "node" in first.confirmation_request
    assert gate.awaiting()

    assert gate.affirm("yes") is True

    second = gate.before_web_call()
    assert second.allowed
    assert second.confirmation_request is None
    assert not gate.awaiting()


def test_only_one_confirmation_request_per_turn() -> None:
    """A further call while unconfirmed is refused SILENTLY — never a second prompt."""
    gate = WebConfirmationGate("node", operator_identity="ori")
    assert gate.before_web_call().confirmation_request is not None
    again = gate.before_web_call()
    assert not again.allowed and again.confirmation_request is None


def test_non_affirmative_answer_leaves_the_gate_closed() -> None:
    gate = WebConfirmationGate("node", operator_identity="ori")
    gate.before_web_call()
    assert gate.affirm("no, skip the web") is False
    assert not gate.before_web_call().allowed


def test_confirmed_gate_resets_after_one_grant() -> None:
    """The gate is spent by the grant it makes — a second call after ``reset``
    is unconfirmed again, exactly like a fresh gate."""
    gate = WebConfirmationGate("node", operator_identity="ori")
    gate.before_web_call()
    gate.affirm("yes")
    assert gate.confirmed
    gate.reset()
    assert not gate.confirmed and not gate.awaiting()
    again = gate.before_web_call()
    assert not again.allowed and again.confirmation_request is not None


def test_resolve_web_access_scopes_confirmation_to_one_relayed_turn(
    webglass_on_path: None,
) -> None:
    """The c43 acceptance shape at the ``resolve_web_access`` seam: turn 1 asks,
    the affirmative is answered (not dispatched), turn 2 carries ``web``, and
    turn 3 — the relayed turn AFTER the one that spent the grant — asks again."""
    gates: dict = {}
    origin = classify_origin(
        sender="node", metadata={RELAYED_OPERATOR_METADATA_KEY: "ori"}, operator_identity="ori"
    )
    kwargs = dict(gates=gates, sender="node", origin=origin, operator_identity="ori")

    turn1 = resolve_web_access(body="check the docs online", **kwargs)
    assert not turn1.allow_web and turn1.reply is not None and not turn1.handled

    affirm = resolve_web_access(body="yes", **kwargs)
    assert affirm.allow_web and affirm.handled

    turn2 = resolve_web_access(body="check another page", **kwargs)
    assert turn2.allow_web and turn2.reply is None

    turn3 = resolve_web_access(body="check yet another page", **kwargs)
    assert not turn3.allow_web and turn3.reply is not None and not turn3.handled


def test_is_affirmative_matches_whole_answers_only() -> None:
    assert is_affirmative("yes") and is_affirmative(" OK. ") and is_affirmative("go ahead")
    assert not is_affirmative("no") and not is_affirmative("yes if you must fetch nothing else")


# ---------------------------------------------------------------------------
# The resident wiring
# ---------------------------------------------------------------------------


def _harness(tmp_path: Path, **kwargs):
    from colleague.config import EngineConfig
    from colleague.resident.appserver import AppserverHarness

    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    return AppserverHarness(
        str(repo),
        EngineConfig(),
        engine_name="mock",
        operator_identity="ori",
        default_target="#c",
        **kwargs,
    )


def _feed(harness, sender: str, body: str, metadata=None):
    """Feed one message, capturing the dispatched config; return (configs, replies)."""
    import asyncio

    from agent_lifecycle.runtime.message import Message

    from colleague.contract import TaskResult

    configs = []

    def fake_dispatch(task, config, presence_sink=None):
        configs.append(config)
        result = TaskResult(task_id="t", status="ok", summary="done")
        return result, Path("artifact.json")

    harness._dispatch = fake_dispatch
    asyncio.run(
        harness.feed_message(
            Message(sender=sender, target="#c", body=body, kind="message", metadata=metadata or {})
        )
    )
    replies = []
    while not harness._reply_queue.empty():
        replies.append(harness._reply_queue.get_nowait())
    return configs, replies


def _narrowing(config) -> tuple:
    """The dispatched config's ``tool_set`` narrowing — the value both engines
    feed to ``narrow_role_by_tool_set``; ``()`` means nothing was withheld."""
    lifecycle = getattr(config, "config_lifecycle", None)
    return tuple(getattr(getattr(lifecycle, "snapshot", None), "tool_set", ()) or ())


def _offered_names(config, repo_path: str) -> set:
    """The tool names the dispatched *config* would actually offer this turn —
    resolved exactly the way both engines' ``work()`` resolve them."""
    from colleague.loop import resolve_role
    from colleague.tools import curate_schemas, narrow_role_by_tool_set

    role = resolve_role(config, repo_path)
    return _names(curate_schemas(narrow_role_by_tool_set(role, _narrowing(config))))


def test_resident_withholds_web_from_a_peer_turn(tmp_path: Path, webglass_on_path: None) -> None:
    """A peer's request is dispatched with ``web`` off its surface; the
    operator's own request keeps it."""
    pytest.importorskip(
        "agent_lifecycle", reason="install the [culture]/[resident] extra for the resident seam"
    )
    harness = _harness(tmp_path)
    peer_configs, _ = _feed(harness, "peer", "read the readme")
    assert WEB not in _offered_names(peer_configs[0], harness._repo_path)
    # Withheld by an explicit narrowing — not merely by what the c19 read-only
    # role happens to carry today: the tool_set names the rest of the surface.
    peer_tools = _narrowing(peer_configs[0])
    assert peer_tools and WEB not in peer_tools and "read_file" in peer_tools

    operator_configs, _ = _feed(harness, "ori", "read the readme")
    assert WEB in _offered_names(operator_configs[0], harness._repo_path)
    assert _narrowing(operator_configs[0]) == ()  # the operator lane narrows nothing


def test_resident_relayed_turn_confirms_once_then_proceeds(
    tmp_path: Path, webglass_on_path: None
) -> None:
    """A relayed operator request is operator-initiated, but its first turn
    withholds ``web`` and emits exactly ONE confirmation request; after the
    affirmative the surface carries ``web`` and no second prompt is sent."""
    pytest.importorskip(
        "agent_lifecycle", reason="install the [culture]/[resident] extra for the resident seam"
    )
    harness = _harness(tmp_path)
    meta = {RELAYED_OPERATOR_METADATA_KEY: "ori"}

    configs, replies = _feed(harness, "node", "check the docs online", meta)
    first_tools = _narrowing(configs[0])
    assert first_tools and WEB not in first_tools
    assert WEB not in _offered_names(configs[0], harness._repo_path)
    confirmations = [r for r in replies if r.metadata.get("phase") == "web_confirmation"]
    assert len(confirmations) == 1
    assert WEB in confirmations[0].body

    # The operator's affirmative, relayed back through the same node: answered,
    # never dispatched as a work item of its own.
    affirm_configs, affirm_replies = _feed(harness, "node", "yes", meta)
    assert affirm_configs == []
    assert affirm_replies and affirm_replies[0].metadata.get("phase") == "web_confirmation"

    # c43 is scoped to ONE turn: the next relayed turn carries `web` with no
    # second prompt...
    second_configs, second_replies = _feed(harness, "node", "check another page", meta)
    assert WEB in _offered_names(second_configs[0], harness._repo_path)
    assert not [r for r in second_replies if r.metadata.get("phase") == "web_confirmation"]

    # ...and the turn AFTER that one — the grant already spent — asks again
    # (c43, never once-per-sender-forever): exactly one fresh confirmation.
    third_configs, third_replies = _feed(harness, "node", "check yet another page", meta)
    assert WEB not in _offered_names(third_configs[0], harness._repo_path)
    third_confirmations = [
        r for r in third_replies if r.metadata.get("phase") == "web_confirmation"
    ]
    assert len(third_confirmations) == 1
