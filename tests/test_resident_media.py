"""t12 — mesh media references under the c19 trust model.

Covers the SECURITY-SENSITIVE anti-exfiltration rule this task adds:
``colleague.resident.appserver`` now recognises a line-anchored
``attach: <path>`` token in an inbound mesh request's body, but a
NON-operator's candidate path must resolve INSIDE the target repo's working
tree (``colleague.resident.trust.check_attachment_path``) before it is ever
handed to ``colleague.media.validate_attachment`` — the operator identity
(the SAME check :func:`~colleague.resident.trust.classify_request` already
uses) is the only requester who may reference an arbitrary local path.

Two layers are tested separately, mirroring the codebase's existing split
between ``tests/test_resident_trust.py`` (pure, no ``agent_lifecycle``
needed) and ``tests/test_resident_appserver.py`` (needs the ``[resident]``/
``[culture]`` extra, since ``colleague.resident.appserver`` imports
``agent_lifecycle`` unconditionally at module scope):

* :class:`TestCheckAttachmentPath` — the trust-boundary classifier itself,
  pure/synchronous, no extra required.
* Everything below the ``pytest.importorskip`` — the parsing helper
  (``_extract_attach_lines``) and full ``AppserverHarness`` round trips
  through ``agent_lifecycle``'s in-process ``Supervisor`` + reference
  ``InMemoryTransport`` (the same pattern ``test_resident_appserver.py``
  uses).
"""

from __future__ import annotations

import inspect
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from colleague.media import validate_attachment
from colleague.resident.trust import (
    READ_ONLY_ROLE,
    AttachmentDecision,
    check_attachment_path,
    classify_request,
)

# ---------------------------------------------------------------------------
# TestCheckAttachmentPath -- pure trust-boundary classifier, no agent_lifecycle
# import needed (mirrors tests/test_resident_trust.py's no-gate convention).
# ---------------------------------------------------------------------------


class TestCheckAttachmentPath:
    """The anti-exfiltration containment check applied BEFORE
    ``validate_attachment`` ever touches a candidate path's content."""

    def test_operator_any_local_path_is_allowed(self, tmp_path: Path) -> None:
        repo = tmp_path / "r"
        repo.mkdir()
        outside = tmp_path / "outside" / "secret.png"
        outside.parent.mkdir()
        outside.write_bytes(b"\x89PNG")

        decision = check_attachment_path(
            str(outside), repo_path=str(repo), sender="ori", operator_identity="ori"
        )
        assert isinstance(decision, AttachmentDecision)
        assert decision.allowed is True
        assert "ori" in decision.reason

    def test_non_operator_path_outside_repo_is_refused_with_a_recorded_reason(
        self, tmp_path: Path
    ) -> None:
        """The scenario the task names by example: `attach:
        /home/user/.ssh/id_rsa` from a NON-operator must be refused -- the
        reason names both the path and the containment rule."""
        repo = tmp_path / "r"
        repo.mkdir()
        secret = tmp_path / "outside" / "id_rsa"
        secret.parent.mkdir()
        secret.write_text("private key material")

        decision = check_attachment_path(
            str(secret), repo_path=str(repo), sender="random-peer", operator_identity="ori"
        )
        assert decision.allowed is False
        assert "id_rsa" in decision.reason
        assert "repo" in decision.reason.lower()
        assert "random-peer" in decision.reason

    def test_non_operator_path_inside_repo_is_allowed(self, tmp_path: Path) -> None:
        repo = tmp_path / "r"
        repo.mkdir()
        inside = repo / "diagram.png"
        inside.write_bytes(b"\x89PNG")

        decision = check_attachment_path(
            str(inside), repo_path=str(repo), sender="random-peer", operator_identity="ori"
        )
        assert decision.allowed is True

    def test_non_operator_symlink_inside_repo_escaping_outside_is_refused(
        self, tmp_path: Path
    ) -> None:
        """The resolve-then-contain check: a symlink that LIVES inside the
        repo but resolves OUTSIDE it must not be treated as contained."""
        repo = tmp_path / "r"
        repo.mkdir()
        outside_target = tmp_path / "outside" / "id_rsa"
        outside_target.parent.mkdir()
        outside_target.write_text("private key material")

        escape_link = repo / "escape.png"
        escape_link.symlink_to(outside_target)

        decision = check_attachment_path(
            str(escape_link), repo_path=str(repo), sender="random-peer", operator_identity="ori"
        )
        assert decision.allowed is False
        assert "repo" in decision.reason.lower()

    def test_operator_symlink_escaping_repo_is_still_allowed(self, tmp_path: Path) -> None:
        """The operator's unrestricted branch is checked FIRST -- a symlink
        escaping the repo is irrelevant for the operator identity."""
        repo = tmp_path / "r"
        repo.mkdir()
        outside_target = tmp_path / "outside" / "id_rsa"
        outside_target.parent.mkdir()
        outside_target.write_text("private key material")
        escape_link = repo / "escape.png"
        escape_link.symlink_to(outside_target)

        decision = check_attachment_path(
            str(escape_link), repo_path=str(repo), sender="ori", operator_identity="ori"
        )
        assert decision.allowed is True

    def test_unresolved_operator_identity_is_fail_safe_non_operator(self, tmp_path: Path) -> None:
        """With no operator configured, even a sender string that matches
        nothing in particular is treated as non-operator -- no accidental
        grant, mirroring classify_request's fail-safe default."""
        repo = tmp_path / "r"
        repo.mkdir()
        outside = tmp_path / "outside.png"
        outside.write_bytes(b"\x89PNG")

        decision = check_attachment_path(
            str(outside), repo_path=str(repo), sender="ori", operator_identity=None
        )
        assert decision.allowed is False


# ---------------------------------------------------------------------------
# Requirement 4: media presence adds NO new trust decision branch for roles --
# classify_request's own signature/behavior is untouched by this task.
# ---------------------------------------------------------------------------


def test_classify_request_signature_is_unchanged_by_the_media_feature() -> None:
    """classify_request never learns about attachments/media at all -- it
    still takes exactly sender/metadata/operator_identity, so a non-operator's
    role outcome is structurally unaffected by whether the request also
    happened to carry an attach: line."""
    params = set(inspect.signature(classify_request).parameters)
    assert params == {"sender", "metadata", "operator_identity"}


def test_non_operator_role_outcome_is_still_explorer_regardless_of_media() -> None:
    decision = classify_request(sender="random-peer", metadata=None, operator_identity="ori")
    assert decision.role == READ_ONLY_ROLE == "explorer"


# ---------------------------------------------------------------------------
# Everything below needs the [resident]/[culture] extra -- colleague.resident
# .appserver imports agent_lifecycle unconditionally at module scope, exactly
# like tests/test_resident_appserver.py.
# ---------------------------------------------------------------------------

pytest.importorskip(
    "agent_lifecycle", reason="install the [culture]/[resident] extra to test the resident seam"
)

import asyncio  # noqa: E402

from agent_lifecycle.reference import InMemoryTransport  # noqa: E402
from agent_lifecycle.runtime.message import Message  # noqa: E402

from colleague.config import EngineConfig  # noqa: E402
from colleague.resident.appserver import (  # noqa: E402
    _MAX_ATTACHMENTS,
    _extract_attach_lines,
    build_appserver_supervisor,
)

# ---------------------------------------------------------------------------
# _extract_attach_lines -- the parsing/cap layer appserver.py owns.
# ---------------------------------------------------------------------------


class TestExtractAttachLines:
    def test_no_attach_lines_is_byte_identical(self) -> None:
        """Requirement 4 (TDD list): no attach: lines -> the text comes back
        completely unchanged."""
        text = "please investigate the repo\nand summarize findings"
        cleaned, candidates, dropped = _extract_attach_lines(text)
        assert cleaned == text
        assert candidates == []
        assert dropped == 0

    def test_single_attach_line_is_removed_and_captured(self) -> None:
        text = "look at this\nattach: /tmp/x.png\nthanks"
        cleaned, candidates, dropped = _extract_attach_lines(text)
        assert "attach:" not in cleaned
        assert "look at this" in cleaned and "thanks" in cleaned
        assert candidates == ["/tmp/x.png"]
        assert dropped == 0

    def test_caps_at_max_attachments_and_counts_extras(self) -> None:
        lines = [f"attach: /tmp/{i}.png" for i in range(_MAX_ATTACHMENTS + 2)]
        text = "\n".join(["intro", *lines])
        cleaned, candidates, dropped = _extract_attach_lines(text)
        assert len(candidates) == _MAX_ATTACHMENTS
        assert candidates == [f"/tmp/{i}.png" for i in range(_MAX_ATTACHMENTS)]
        assert dropped == 2
        assert cleaned == "intro"


# ---------------------------------------------------------------------------
# Full AppserverHarness round trips through Supervisor + InMemoryTransport.
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("hi\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _supervisor(repo, **harness_kwargs):
    transport = InMemoryTransport(identity="#colleague")
    supervisor = build_appserver_supervisor(
        transport=transport,
        repo_path=str(repo),
        config=EngineConfig(),
        engine_name="mock",
        drain_timeout=5.0,
        **harness_kwargs,
    )
    return transport, supervisor


async def _round_trip(transport, supervisor, message, *, timeout: float = 10.0):
    await supervisor.start()
    try:
        transport.inject(message)
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while not transport.sent:
            if loop.time() > deadline:
                raise AssertionError("no reply arrived within the timeout")
            await asyncio.sleep(0.02)
    finally:
        await supervisor.stop()
    return transport.sent


def _capture_execute_work(monkeypatch: pytest.MonkeyPatch, captured: dict, artifact: Path):
    """Stand in for the real execute_work -- captures the Task it was handed
    and returns a fake-but-shaped-right (TaskResult-like, artifact_path) pair,
    so these tests assert on Task.attachments without needing a live engine
    or a real git handoff (mirrors test_resident_appserver.py's
    test_expected_work_item_failure_... monkeypatch pattern)."""
    import colleague.cli._commands.work as work_mod

    def _fake_execute_work(**kwargs):
        captured["task"] = kwargs["task"]
        result = SimpleNamespace(task_id="tid-fake", status="ok", summary="fake done")
        return result, artifact

    monkeypatch.setattr(work_mod, "execute_work", _fake_execute_work)


class TestNonOperatorArbitraryPathRefusedOperatorAccepted:
    """TDD item 1: a crafted NON-operator request referencing a path outside
    the repo (e.g. `attach: /home/user/.ssh/id_rsa`) is refused with a
    recorded reason; the SAME path from the OPERATOR identity is accepted."""

    def test_non_operator_outside_repo_attachment_is_refused_with_recorded_reason(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _init_repo(tmp_path)
        secret = tmp_path / "outside" / "secret.png"
        secret.parent.mkdir()
        secret.write_bytes(b"\x89PNG")  # valid media extension -- isolates the trust refusal

        captured: dict = {}
        _capture_execute_work(monkeypatch, captured, tmp_path / "artifact.json")

        transport, supervisor = _supervisor(repo, operator_identity="ori")
        inbound = Message(
            sender="random-peer",
            target="#colleague",
            body=f"please look at this\nattach: {secret}\nthanks",
        )
        sent = asyncio.run(_round_trip(transport, supervisor, inbound))
        reply = sent[0]

        # The request itself still ran (never crashed), read-only, minus the
        # refused attachment.
        assert reply.metadata["role"] == "explorer"
        assert reply.metadata["status"] == "ok"
        assert captured["task"].attachments is None
        notes = reply.metadata.get("attachment_notes")
        assert notes, "the refusal must be recorded, not silent"
        assert any(str(secret) in note for note in notes)
        assert any("repo" in note.lower() for note in notes)

    def test_same_path_from_operator_identity_is_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _init_repo(tmp_path)
        secret = tmp_path / "outside" / "secret.png"
        secret.parent.mkdir()
        secret.write_bytes(b"\x89PNG")

        captured: dict = {}
        _capture_execute_work(monkeypatch, captured, tmp_path / "artifact.json")

        transport, supervisor = _supervisor(repo, operator_identity="ori")
        inbound = Message(
            sender="ori",
            target="#colleague",
            body=f"please look at this\nattach: {secret}\nthanks",
        )
        sent = asyncio.run(_round_trip(transport, supervisor, inbound))
        reply = sent[0]

        assert reply.metadata["role"] is None  # operator -> unrestricted, no role cap
        assert "attachment_notes" not in reply.metadata
        assert captured["task"].attachments == [validate_attachment(str(secret))]


class TestAcceptedAttachmentShapesTaskAttachments:
    """TDD item 3: an accepted candidate lands on Task.attachments in the
    exact {"path", "media_type"} shape validate_attachment produces."""

    def test_non_operator_inside_repo_attachment_matches_validate_attachment_shape(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _init_repo(tmp_path)
        picture = repo / "diagram.png"
        picture.write_bytes(b"\x89PNG")

        captured: dict = {}
        _capture_execute_work(monkeypatch, captured, tmp_path / "artifact.json")

        transport, supervisor = _supervisor(repo, operator_identity="ori")
        inbound = Message(
            sender="random-peer",
            target="#colleague",
            body=f"attach: {picture}",
        )
        sent = asyncio.run(_round_trip(transport, supervisor, inbound))
        reply = sent[0]

        assert reply.metadata["role"] == "explorer"
        assert "attachment_notes" not in reply.metadata
        assert captured["task"].attachments == [validate_attachment(str(picture))]

    def test_invalid_extension_inside_repo_is_refused_via_validate_attachment_not_silently(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Item 3's second half: a validate_attachment failure takes the SAME
        refusal-with-reason path as a trust refusal -- never a crash."""
        repo = _init_repo(tmp_path)
        bogus = repo / "notes.txt"
        bogus.write_text("not a media file")

        captured: dict = {}
        _capture_execute_work(monkeypatch, captured, tmp_path / "artifact.json")

        transport, supervisor = _supervisor(repo, operator_identity="ori")
        inbound = Message(sender="ori", target="#colleague", body=f"attach: {bogus}")
        sent = asyncio.run(_round_trip(transport, supervisor, inbound))
        reply = sent[0]

        assert reply.metadata["status"] == "ok"
        assert captured["task"].attachments is None
        notes = reply.metadata.get("attachment_notes")
        assert notes, "a validate_attachment failure must be recorded, not silent"
        assert any("notes.txt" in note for note in notes)


class TestNoAttachLinesIsByteIdenticalToToday:
    """TDD item 4: a request with no attach: lines behaves exactly as before
    this feature existed -- no attachments key, no attachment_notes key."""

    def test_plain_operator_request_carries_no_attachments(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _init_repo(tmp_path)
        captured: dict = {}
        _capture_execute_work(monkeypatch, captured, tmp_path / "artifact.json")

        transport, supervisor = _supervisor(repo, operator_identity="ori")
        inbound = Message(sender="ori", target="#colleague", body="write a mock file")
        sent = asyncio.run(_round_trip(transport, supervisor, inbound))
        reply = sent[0]

        assert captured["task"].attachments is None
        assert captured["task"].instruction == "write a mock file"
        assert "attachment_notes" not in reply.metadata

    def test_plain_non_operator_request_is_unaffected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _init_repo(tmp_path)
        captured: dict = {}
        _capture_execute_work(monkeypatch, captured, tmp_path / "artifact.json")

        transport, supervisor = _supervisor(repo, operator_identity="ori")
        inbound = Message(sender="random-peer", target="#colleague", body="investigate the repo")
        sent = asyncio.run(_round_trip(transport, supervisor, inbound))
        reply = sent[0]

        assert reply.metadata["role"] == "explorer"
        assert captured["task"].attachments is None
        assert "attachment_notes" not in reply.metadata
