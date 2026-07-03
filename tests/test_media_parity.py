"""t15 — cross-surface attachment parity + byte-identical baseline pins.

Two pins over the already-built media-input arc (Task.attachments,
``colleague/media.py``, the CLI ``--attach`` flag, the session ``/attach``
slash, and the resident's ``attach: <path>`` mesh convention):

1. **Cross-surface parity (spec h4/h14).** All three surfaces that build a
   ``Task.attachments`` value from the SAME source file(s) must land the
   IDENTICAL ``[{"path", "media_type"}, ...]`` list — same keys, same
   values, same order. Each leg drives the REAL code path (not a
   reimplementation of it):

   * CLI — :func:`colleague.cli._commands.work._build_task` (mirrors
     ``tests/test_cli_attach.py``'s fixture pattern).
   * session — the real ``/attach`` slash handler (``_Session._slash``,
     which calls :func:`colleague.media.validate_attachment` itself) stages
     the file, then the real one-shot consume seam
     (``_Session._consume_staged_attachments``) moves it onto a fresh
     ``Task`` (mirrors ``tests/test_session_attach.py``).
   * resident — the mesh ``attach: <path>`` parsing/trust helpers in
     ``colleague/resident/appserver.py`` /
     ``colleague/resident/trust.py`` (mirrors ``tests/test_resident_media.py``),
     driven directly rather than through the full async
     ``AppserverHarness``/``Supervisor`` round trip, under an operator
     identity so the trust check is a pure pass-through.

   ``colleague.resident.appserver`` imports ``agent_lifecycle``
   unconditionally at module scope, so importing it requires the
   ``[resident]``/``[culture]`` extra — exactly like
   ``tests/test_resident_media.py``. Empirically, a module-level
   ``pytest.importorskip("agent_lifecycle")`` skips the ENTIRE module (not
   just the tests below it — confirmed by running
   ``tests/test_resident_media.py`` without the extra installed: it
   collects 0 items, not a partial subset), so the resident-vs-CLI parity
   test below gates the import INSIDE the test function instead. That keeps
   the CLI==session parity tests ungated (they need no optional extra) while
   the resident==CLI leg skips cleanly, alone, when the extra is absent.

2. **Byte-identical baseline (spec h3/c3).** A plain, attachment-less work
   item carries NONE of the media-arc keys on either side of the contract —
   ``Task.to_dict()`` omits ``"attachments"``, ``TaskResult.to_dict()`` omits
   ``"media"`` — and the result round-trips through
   ``TaskResult.from_dict(to_dict())`` (and a real JSON text round trip)
   unchanged. Run twice, on two independent fresh repos, using the standard
   ``registry.load("mock").work(...)`` pattern from ``tests/test_e2e_mock.py``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pytest

from colleague import registry
from colleague.cli._commands.session import SessionIO, _Session
from colleague.cli._commands.work import _build_task
from colleague.config import EngineConfig
from colleague.contract import OK, Task, TaskResult
from colleague.media import validate_attachment
from colleague.resident.trust import check_attachment_path

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A git-initialised tmp_path with an initial commit (mirrors
    ``tests/test_cli_attach.py``'s ``git_repo`` fixture exactly)."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    return tmp_path


def _write_png(path: Path) -> None:
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 10)


def _write_jpg(path: Path) -> None:
    path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 10)


def _make_work_ns(repo: Path, attach: list[str]) -> argparse.Namespace:
    """Mirrors ``tests/test_cli_attach.py``'s ``_make_ns`` — every field
    ``cmd_work``/``_build_task`` reads."""
    return argparse.Namespace(
        instruction=["describe these files"],
        repo=str(repo),
        engine="mock",
        no_pr=True,
        watch=False,
        base=None,
        model=None,
        base_url=None,
        api_key=None,
        max_steps=5,
        json=False,
        command_name=None,
        allow_dirty=True,
        tui=None,
        tui_events=None,
        attach=attach,
    )


def _cli_attachments(repo: Path, paths: list[Path]) -> list[dict]:
    """The CLI leg: ``--attach`` -> ``_build_task`` -> ``Task.attachments``."""
    ns = _make_work_ns(repo, attach=[str(p) for p in paths])
    task = _build_task(ns, repo, "mock", None)
    assert task.attachments is not None
    return task.attachments


def _make_session(repo: Path) -> _Session:
    """Mirrors ``tests/test_session_attach.py``'s ``_make_session``."""
    return _Session(
        repo=repo,
        engine_name="mock",
        open_pr=False,
        base="main",
        config=EngineConfig.resolve(model="m"),
        json_mode=False,
        view="markdown",
        io=SessionIO(out=lambda *a, **k: None, err=lambda *a, **k: None),
        work_fn=lambda **k: None,
    )


def _session_attachments(repo: Path, paths: list[Path]) -> list[dict]:
    """The session leg: real ``/attach`` slash staging + the real one-shot
    consume seam — never reimplements ``validate_attachment`` itself."""
    session = _make_session(repo)
    for p in paths:
        still_running = session._slash(f"/attach {p}")
        assert still_running is True
    task = Task.new(str(repo), "describe these files", engine="mock")
    session._consume_staged_attachments(task)
    assert task.attachments is not None
    return task.attachments


def _resident_attachments(
    repo: Path,
    paths: list[Path],
    *,
    sender: str = "ori",
    operator_identity: str = "ori",
) -> list[dict]:
    """The resident leg: the real mesh ``attach:`` parsing + trust-boundary
    helpers appserver.py's ``feed_message`` uses, driven directly (mirrors
    ``tests/test_resident_media.py``'s ``TestExtractAttachLines`` /
    ``TestCheckAttachmentPath`` style — no full ``AppserverHarness``/
    ``Supervisor`` round trip needed to exercise this seam honestly).

    Import stays function-local and gated: importing
    ``colleague.resident.appserver`` requires ``agent_lifecycle`` at module
    scope (the ``[resident]``/``[culture]`` extra), and a module-level
    ``pytest.importorskip`` would skip this entire test FILE (see the module
    docstring), not just this one leg.
    """
    pytest.importorskip(
        "agent_lifecycle",
        reason="install the [culture]/[resident] extra to test the resident media path",
    )
    from colleague.resident.appserver import _extract_attach_lines

    body = "\n".join(f"attach: {p}" for p in paths)
    cleaned, candidates, dropped = _extract_attach_lines(body)
    assert dropped == 0
    assert "attach:" not in cleaned
    assert candidates == [str(p) for p in paths]

    attachments: list[dict] = []
    for candidate in candidates:
        decision = check_attachment_path(
            candidate,
            repo_path=str(repo),
            sender=sender,
            operator_identity=operator_identity,
        )
        assert decision.allowed is True
        attachments.append(validate_attachment(candidate))
    return attachments


# ---------------------------------------------------------------------------
# 1a. CLI == session parity — ungated, no optional extra required.
# ---------------------------------------------------------------------------


class TestCrossSurfaceParityCliSession:
    """The CLI ``--attach`` path and the session ``/attach`` path build the
    IDENTICAL ``Task.attachments`` value from the same source file(s)."""

    def test_single_file_identical_attachments(self, git_repo: Path, tmp_path: Path) -> None:
        img = tmp_path / "photo.png"
        _write_png(img)

        cli_attachments = _cli_attachments(git_repo, [img])
        session_attachments = _session_attachments(git_repo, [img])
        expected = [validate_attachment(str(img))]

        assert cli_attachments == expected
        assert session_attachments == expected
        assert cli_attachments == session_attachments

    def test_multiple_files_identical_keys_values_and_order(
        self, git_repo: Path, tmp_path: Path
    ) -> None:
        img1 = tmp_path / "one.png"
        img2 = tmp_path / "two.jpg"
        _write_png(img1)
        _write_jpg(img2)

        cli_attachments = _cli_attachments(git_repo, [img1, img2])
        session_attachments = _session_attachments(git_repo, [img1, img2])
        expected = [validate_attachment(str(img1)), validate_attachment(str(img2))]

        assert cli_attachments == expected
        assert session_attachments == expected
        assert cli_attachments == session_attachments
        # Order is load-bearing: reversing either surface's list must not
        # still compare equal (guards against an accidental set-like
        # comparison masking an order bug).
        assert cli_attachments != list(reversed(session_attachments))


# ---------------------------------------------------------------------------
# 1b. resident == CLI parity — gated behind the same extra
#     tests/test_resident_media.py gates its AppserverHarness half on.
# ---------------------------------------------------------------------------


class TestCrossSurfaceParityResidentCli:
    """The resident's ``attach: <path>`` mesh convention (under an operator
    identity, which clears the trust boundary unconditionally) builds the
    IDENTICAL ``Task.attachments`` value the CLI leg builds."""

    def test_single_file_identical_attachments(self, git_repo: Path, tmp_path: Path) -> None:
        img = tmp_path / "photo.png"
        _write_png(img)

        cli_attachments = _cli_attachments(git_repo, [img])
        resident_attachments = _resident_attachments(git_repo, [img])

        assert resident_attachments == cli_attachments == [validate_attachment(str(img))]

    def test_multiple_files_identical_keys_values_and_order(
        self, git_repo: Path, tmp_path: Path
    ) -> None:
        img1 = tmp_path / "one.png"
        img2 = tmp_path / "two.jpg"
        _write_png(img1)
        _write_jpg(img2)

        cli_attachments = _cli_attachments(git_repo, [img1, img2])
        resident_attachments = _resident_attachments(git_repo, [img1, img2])
        expected = [validate_attachment(str(img1)), validate_attachment(str(img2))]

        assert cli_attachments == expected
        assert resident_attachments == expected
        assert resident_attachments == cli_attachments


# ---------------------------------------------------------------------------
# 2. Byte-identical baseline: no attachments -> no media-arc keys anywhere.
# ---------------------------------------------------------------------------


class TestByteIdenticalBaselineNoAttachments:
    """spec h3/c3: a plain, attachment-less work item is byte-identical to
    the pre-media-arc contract shape on BOTH sides — the task-side
    ``"attachments"`` key and the result-side ``"media"`` key are absent —
    and the result round-trips through ``to_dict``/``from_dict`` (including a
    real JSON text round trip) unchanged. Run twice, on two independent
    fresh repos, using the standard mock-run pattern from
    ``tests/test_e2e_mock.py``.
    """

    def test_two_independent_mock_runs_omit_media_keys_and_round_trip(self, tmp_path: Path) -> None:
        cfg = EngineConfig.resolve()

        for name in ("first", "second"):
            repo = tmp_path / name
            repo.mkdir()
            task = Task.new(str(repo), "do work", engine="mock")

            # Task side: an attachment-less task never carries the key.
            assert task.attachments is None
            assert "attachments" not in task.to_dict()

            result = registry.load("mock").work(task, cfg)
            assert result.status == OK

            # Result side: an attachment-less run never carries the key.
            assert result.media is None
            result_dict = result.to_dict()
            assert "media" not in result_dict

            # Round-trips exactly: both a direct from_dict(to_dict()) pass and
            # a real JSON text round trip (what artifact.write actually does).
            assert TaskResult.from_dict(result_dict) == result
            reloaded = TaskResult.from_dict(json.loads(json.dumps(result_dict)))
            assert reloaded == result
            assert reloaded.to_dict() == result_dict
