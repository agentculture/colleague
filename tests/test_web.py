"""Tests for colleague/web.py — curated webglass CLI shell-out launcher.

Written test-first (TDD): tests define the contract, implementation follows.
"""

from __future__ import annotations

import json
import os
import re
import stat
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import colleague.web_schemas as web_schemas
from colleague.web import (
    _MAX_RAW_CHARS,
    ALLOWED_VERBS,
    FORBIDDEN_TOKENS,
    WebToolError,
    run_web,
)

FIXTURES = Path(__file__).parent / "fixtures" / "webglass"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def repo_root(tmp_path: Path) -> Path:
    """A minimal repo root with an identity.json so identity resolves."""
    identity_dir = tmp_path / ".colleague"
    identity_dir.mkdir()
    (identity_dir / "identity.json").write_text(json.dumps({"as": "test-agent"}), encoding="utf-8")
    return tmp_path


@pytest.fixture()
def fake_proc() -> MagicMock:
    """A fake Popen instance returned by a monkeypatched subprocess.Popen."""
    proc = MagicMock()
    proc.pid = 12345
    proc.returncode = 0
    proc.communicate.return_value = ("ok\n", "")
    return proc


def _write_script(bin_dir: Path, name: str, body: str) -> Path:
    script = bin_dir / name
    script.write_text(body, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


# ---------------------------------------------------------------------------
# AC: ALLOWED_VERBS exact set
# ---------------------------------------------------------------------------


def test_allowed_verbs_exact_set() -> None:
    assert ALLOWED_VERBS == frozenset(
        {"search", "page open", "page read", "page inspect", "page extract", "page links"}
    )


def test_forbidden_tokens_exact_set() -> None:
    assert FORBIDDEN_TOKENS == frozenset({"--session-id", "--page-ref", "--policy-profile"})


# ---------------------------------------------------------------------------
# AC: refused verbs never spawn a child
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("verb", ["action", "session", "page screenshot"])
def test_refused_verb_raises_no_spawn(verb: str, repo_root: Path) -> None:
    with patch("subprocess.Popen") as mock_popen:
        with pytest.raises(WebToolError):
            run_web(verb, [], root=repo_root)
    assert mock_popen.call_count == 0


def test_refused_verb_error_lists_allowed(repo_root: Path) -> None:
    with patch("subprocess.Popen"):
        with pytest.raises(WebToolError) as exc_info:
            run_web("action", [], root=repo_root)
    msg = str(exc_info.value)
    assert "action" in msg
    assert "search" in msg


# ---------------------------------------------------------------------------
# AC: COLLEAGUE_WEB=0 hides the tool — run_web refuses before spawning
# ---------------------------------------------------------------------------


def test_colleague_web_zero_raises_no_spawn(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLLEAGUE_WEB", "0")
    with patch("subprocess.Popen") as mock_popen:
        with pytest.raises(WebToolError, match="COLLEAGUE_WEB=0"):
            run_web("search", ["x"], root=repo_root)
    assert mock_popen.call_count == 0


# ---------------------------------------------------------------------------
# AC: forbidden argv tokens never spawn a child
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("token", sorted(FORBIDDEN_TOKENS))
def test_forbidden_token_raises_no_spawn(token: str, repo_root: Path) -> None:
    with patch("subprocess.Popen") as mock_popen:
        with pytest.raises(WebToolError):
            run_web("page open", ["https://example.com", token, "x"], root=repo_root)
    assert mock_popen.call_count == 0


def test_forbidden_token_in_search_args_raises_no_spawn(repo_root: Path) -> None:
    with patch("subprocess.Popen") as mock_popen:
        with pytest.raises(WebToolError):
            run_web("search", ["--policy-profile", "x"], root=repo_root)
    assert mock_popen.call_count == 0


# ---------------------------------------------------------------------------
# AC: url must match ^https?:// for url-taking verbs, checked before spawn
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "verb", ["page open", "page read", "page inspect", "page extract", "page links"]
)
def test_missing_url_raises_no_spawn(verb: str, repo_root: Path) -> None:
    with patch("subprocess.Popen") as mock_popen:
        with pytest.raises(WebToolError):
            run_web(verb, [], root=repo_root)
    assert mock_popen.call_count == 0


@pytest.mark.parametrize(
    "bad_url", ["ftp://example.com", "example.com", "javascript:alert(1)", "  http://example.com"]
)
def test_bad_url_scheme_raises_no_spawn(bad_url: str, repo_root: Path) -> None:
    with patch("subprocess.Popen") as mock_popen:
        with pytest.raises(WebToolError):
            run_web("page open", [bad_url], root=repo_root)
    assert mock_popen.call_count == 0


def test_valid_https_url_is_accepted(repo_root: Path, fake_proc: MagicMock) -> None:
    with patch("subprocess.Popen", return_value=fake_proc) as mock_popen:
        result = run_web("page open", ["https://example.com"], root=repo_root)
    mock_popen.assert_called_once()
    assert result.startswith("exit=0\n")


def test_valid_http_url_is_accepted(repo_root: Path, fake_proc: MagicMock) -> None:
    with patch("subprocess.Popen", return_value=fake_proc) as mock_popen:
        run_web("page read", ["http://example.com"], root=repo_root)
    mock_popen.assert_called_once()


# ---------------------------------------------------------------------------
# AC: exact argv grammar (verified 2026-08-28 against `webglass <verb> --help`)
# ---------------------------------------------------------------------------


def _argv_for(verb: str, args: list[str], repo_root: Path, fake_proc: MagicMock) -> list[str]:
    with patch("subprocess.Popen", return_value=fake_proc) as mock_popen:
        run_web(verb, args, root=repo_root)
    mock_popen.assert_called_once()
    return list(mock_popen.call_args[0][0])


def test_search_argv_exact_options_first_then_dash_then_query(
    repo_root: Path, fake_proc: MagicMock
) -> None:
    argv = _argv_for("search", ["colleague web scout"], repo_root, fake_proc)
    assert argv == ["webglass", "search", "--json", "--", "colleague web scout"]


def test_search_argv_exact_with_limit(repo_root: Path, fake_proc: MagicMock) -> None:
    argv = _argv_for("search", ["colleague web scout", "--limit", "5"], repo_root, fake_proc)
    assert argv == ["webglass", "search", "--json", "--limit", "5", "--", "colleague web scout"]


def test_page_open_argv_exact_url_as_positional(repo_root: Path, fake_proc: MagicMock) -> None:
    argv = _argv_for("page open", ["https://example.com"], repo_root, fake_proc)
    assert argv == ["webglass", "page", "open", "--json", "https://example.com"]


def test_page_read_argv_exact_url_as_flag(repo_root: Path, fake_proc: MagicMock) -> None:
    argv = _argv_for("page read", ["https://example.com"], repo_root, fake_proc)
    assert argv == ["webglass", "page", "read", "--json", "--url", "https://example.com"]


def test_page_inspect_argv_exact_url_as_flag(repo_root: Path, fake_proc: MagicMock) -> None:
    argv = _argv_for("page inspect", ["https://example.com"], repo_root, fake_proc)
    assert argv == ["webglass", "page", "inspect", "--json", "--url", "https://example.com"]


def test_page_links_argv_exact_url_as_flag(repo_root: Path, fake_proc: MagicMock) -> None:
    argv = _argv_for("page links", ["https://example.com"], repo_root, fake_proc)
    assert argv == ["webglass", "page", "links", "--json", "--url", "https://example.com"]


def test_page_extract_argv_exact_url_as_flag(repo_root: Path, fake_proc: MagicMock) -> None:
    argv = _argv_for("page extract", ["https://example.com"], repo_root, fake_proc)
    assert argv == ["webglass", "page", "extract", "--json", "--url", "https://example.com"]


def test_page_extract_argv_exact_with_query_after_dash(
    repo_root: Path, fake_proc: MagicMock
) -> None:
    argv = _argv_for(
        "page extract", ["https://example.com", "what is the title"], repo_root, fake_proc
    )
    assert argv == [
        "webglass",
        "page",
        "extract",
        "--json",
        "--url",
        "https://example.com",
        "--",
        "what is the title",
    ]


def test_page_extract_argv_url_query_limit_exact(repo_root: Path, fake_proc: MagicMock) -> None:
    """Qodo #7: url + query + limit → the limit pair is adjacent and BEFORE
    "--"; only the free-text query goes after it."""
    argv = _argv_for(
        "page extract",
        ["https://example.com/report", "--limit", "5", "what is the title"],
        repo_root,
        fake_proc,
    )
    assert argv == [
        "webglass",
        "page",
        "extract",
        "--json",
        "--url",
        "https://example.com/report",
        "--limit",
        "5",
        "--",
        "what is the title",
    ]


# ---------------------------------------------------------------------------
# AC: FileNotFoundError / OSError → WebToolError, one-line message
# ---------------------------------------------------------------------------


def test_missing_binary_raises_web_tool_error(repo_root: Path) -> None:
    with patch("subprocess.Popen", side_effect=FileNotFoundError):
        with pytest.raises(WebToolError) as exc_info:
            run_web("search", ["x"], root=repo_root)
    msg = str(exc_info.value)
    assert "\n" not in msg
    assert "webglass" in msg.lower()
    assert "not found" in msg.lower() or "installed" in msg.lower()


def test_os_error_on_launch_raises_web_tool_error(repo_root: Path) -> None:
    with patch("subprocess.Popen", side_effect=OSError("permission denied")):
        with pytest.raises(WebToolError) as exc_info:
            run_web("search", ["x"], root=repo_root)
    msg = str(exc_info.value)
    assert "\n" not in msg


# ---------------------------------------------------------------------------
# AC: output is the FULL body, bounded only by the _MAX_RAW_CHARS safety
# ceiling (Qodo #2 + #5). The old 20,000-char pre-parse truncation is gone —
# the model-facing bound is the executor's own _truncate (max_output_chars),
# applied AFTER the envelope is parsed and rendered.
# ---------------------------------------------------------------------------


def test_output_not_truncated_below_raw_ceiling(repo_root: Path, fake_proc: MagicMock) -> None:
    """A 30,000-char body (well under the 2M ceiling) is returned in full —
    the old 20k pre-parse cut that made large-but-valid JSON unparseable is
    gone."""
    fake_proc.communicate.return_value = ("x" * 30_000, "")
    with patch("subprocess.Popen", return_value=fake_proc):
        result = run_web("search", ["q"], root=repo_root)
    assert result == "exit=0\n" + "x" * 30_000
    assert "truncated" not in result


def test_output_bounded_at_raw_ceiling(repo_root: Path, fake_proc: MagicMock) -> None:
    """A runaway body above _MAX_RAW_CHARS is cut at the safety ceiling."""
    fake_proc.communicate.return_value = ("x" * (_MAX_RAW_CHARS + 1000), "")
    with patch("subprocess.Popen", return_value=fake_proc):
        result = run_web("search", ["q"], root=repo_root)
    assert len(result) < _MAX_RAW_CHARS + 100
    assert "truncated" in result


# ---------------------------------------------------------------------------
# AC: identity + cwd (mirrors devague.py shape)
# ---------------------------------------------------------------------------


def test_cwd_is_resolved_root(repo_root: Path, fake_proc: MagicMock) -> None:
    captured_cwd: list[str] = []

    def fake_popen(argv, *, cwd, stdout, stderr, text, env, start_new_session):
        captured_cwd.append(cwd)
        return fake_proc

    with patch("subprocess.Popen", side_effect=fake_popen):
        run_web("search", ["q"], root=repo_root)
    assert captured_cwd[0] == str(repo_root.resolve())


def test_start_new_session_true(repo_root: Path, fake_proc: MagicMock) -> None:
    captured: dict = {}

    def fake_popen(argv, *, cwd, stdout, stderr, text, env, start_new_session):
        captured["start_new_session"] = start_new_session
        return fake_proc

    with patch("subprocess.Popen", side_effect=fake_popen):
        run_web("search", ["q"], root=repo_root)
    assert captured["start_new_session"] is True


def test_identity_injected_into_env(repo_root: Path, fake_proc: MagicMock) -> None:
    captured_env: dict[str, str] = {}

    def fake_popen(argv, *, cwd, stdout, stderr, text, env, start_new_session):
        captured_env.update(env)
        return fake_proc

    with patch("subprocess.Popen", side_effect=fake_popen):
        run_web("search", ["q"], root=repo_root)
    assert "CONVERTIBLE_IDENTITY" in captured_env


# ---------------------------------------------------------------------------
# AC: no .poll() loop, no socket/threading/asyncio import
# ---------------------------------------------------------------------------


def test_no_forbidden_primitives_in_source() -> None:
    source = Path("colleague/web.py").read_text(encoding="utf-8")
    for forbidden in ("import socket", "import asyncio", "import threading", ".poll("):
        assert forbidden not in source, f"web.py must not use {forbidden!r}"


def test_no_adapted_from_header() -> None:
    source = Path("colleague/web.py").read_text(encoding="utf-8")
    assert "adapted-from" not in source.lower()


# ---------------------------------------------------------------------------
# AC: real subprocess — the whole process group is killed on timeout
# ---------------------------------------------------------------------------


def test_timeout_kills_whole_process_group(tmp_path: Path, repo_root: Path, monkeypatch) -> None:
    """A hung webglass that spawns a sleeping grandchild must have BOTH the
    child and the grandchild reaped when the group is killed on timeout."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pid_file = tmp_path / "grandchild.pid"

    script_body = f"""#!/bin/sh
sleep 60 &
echo $! > "{pid_file}"
sleep 60
"""
    _write_script(bin_dir, "webglass", script_body)

    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")
    monkeypatch.setattr("colleague.web._TIMEOUT_SECONDS", 2)

    with pytest.raises(WebToolError) as exc_info:
        run_web("search", ["q"], root=repo_root)
    assert "timed out" in str(exc_info.value).lower()

    # Give the OS a brief moment to finish reaping the killed grandchild.
    deadline = time.time() + 5
    grandchild_pid = None
    while time.time() < deadline:
        if pid_file.exists():
            content = pid_file.read_text(encoding="utf-8").strip()
            if content:
                grandchild_pid = int(content)
                break
        time.sleep(0.1)

    assert grandchild_pid is not None, "fake webglass never wrote the grandchild pid"

    dead = False
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            os.kill(grandchild_pid, 0)
        except ProcessLookupError:
            dead = True
            break
        except PermissionError:
            # Reparented to a different owner/zombie edge case: treat as gone.
            dead = True
            break
        time.sleep(0.1)

    assert dead, f"grandchild pid {grandchild_pid} is still alive after group kill"


def test_success_with_real_fake_cli(tmp_path: Path, repo_root: Path, monkeypatch) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script_body = """#!/bin/sh
echo "$@"
echo '{"ok": true}'
"""
    _write_script(bin_dir, "webglass", script_body)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")

    result = run_web("page open", ["https://example.com"], root=repo_root)
    assert result.startswith("exit=0\n")
    assert "page open --json https://example.com" in result
    assert '{"ok": true}' in result


# ---------------------------------------------------------------------------
# t5 AC: run-report 'web:' line — synthetic artifact, 2 ok + 1 failed
# ---------------------------------------------------------------------------


def _load_envelope(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _web_step(index: int, url: str, envelope_name: str):
    from colleague.contract import Step

    text = web_schemas.render_result(_load_envelope(envelope_name))
    ok = "lifecycle_state: failed" not in text.split(web_schemas.UNTRUSTED_BEGIN, 1)[0]
    return Step(index=index, tool="web", arguments={"url": url}, result=text, ok=ok)


def test_summary_line_absent_without_web_steps() -> None:
    from colleague.contract import Step

    steps = [Step(index=0, tool="write_file", arguments={}, result="ok")]
    assert web_schemas.summary_line(steps) is None


def test_summary_line_counts_ok_and_failed() -> None:
    steps = [
        _web_step(0, "https://example.com/report", "page_read_ok.json"),
        _web_step(1, "https://example.com/report2", "page_read_ok.json"),
        _web_step(2, "https://example.com/search", "search_backend_unavailable.json"),
    ]
    line = web_schemas.summary_line(steps)
    assert line is not None
    assert line.startswith("web: 3 fetch(es), 1 failed:")
    assert "https://example.com/search" in line
    assert "op-2026-08-28-search-0001" in line
    assert "backend_unavailable" in line
    # ok fetches never appear in the failed-url tail
    assert "https://example.com/report" not in line.split(":", 2)[-1]


def test_summary_line_dedups_repeated_failed_url() -> None:
    steps = [
        _web_step(0, "https://example.com/search", "search_backend_unavailable.json"),
        _web_step(1, "https://example.com/search", "search_backend_unavailable.json"),
    ]
    line = web_schemas.summary_line(steps)
    assert line is not None
    assert line.count("https://example.com/search") == 1


def test_render_gains_web_line_on_synthetic_artifact(tmp_path: Path) -> None:
    """t5 AC: the run report (colleague.cli._commands.work._render) gains one
    'web:' line, present only when a step has tool 'web'."""
    from colleague.cli._commands.work import _render
    from colleague.contract import OK, Step, TaskResult

    web_steps = [
        _web_step(0, "https://example.com/a", "page_read_ok.json"),
        _web_step(1, "https://example.com/b", "page_read_ok.json"),
        _web_step(2, "https://example.com/c", "search_backend_unavailable.json"),
    ]
    result = TaskResult(task_id="t5-report", status=OK, summary="done", steps=web_steps)
    text = _render(result, "mock", tmp_path / "artifact.json")
    web_lines = [line for line in text.splitlines() if line.startswith("web: ")]
    assert len(web_lines) == 1
    assert (
        web_lines[0] == "web: 3 fetch(es), 1 failed: https://example.com/c "
        "(op-2026-08-28-search-0001, backend_unavailable)"
    )

    no_web_result = TaskResult(
        task_id="t5-report-none",
        status=OK,
        summary="done",
        steps=[Step(index=0, tool="read_file", arguments={}, result="ok")],
    )
    no_web_text = _render(no_web_result, "mock", tmp_path / "artifact2.json")
    assert not any(line.startswith("web: ") for line in no_web_text.splitlines())


# ---------------------------------------------------------------------------
# t5 AC: pre_tool hook deny (matcher "web") reaches the model, no child spawned
# ---------------------------------------------------------------------------


def test_pre_tool_hook_deny_web_reaches_model_no_child_spawned(
    tmp_path: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from colleague.contract import Task
    from colleague.loop import ModelResponse, ToolCall, run

    def _fail_if_spawned(*_args, **_kwargs):
        raise AssertionError("webglass child must not be spawned when pre_tool denies")

    monkeypatch.setattr("colleague.web.run_web", _fail_if_spawned)
    monkeypatch.setattr(
        "shutil.which", lambda name: "/usr/bin/webglass" if name == "webglass" else None
    )

    deny_script = _write_script(
        repo_root,
        "deny_web.sh",
        "#!/bin/sh\necho 'web calls are blocked by policy' >&2\nexit 1\n",
    )
    dotdir = repo_root / ".colleague"
    dotdir.mkdir(exist_ok=True)
    (dotdir / "hooks.json").write_text(
        json.dumps({"hooks": {"pre_tool": [{"matcher": "web", "command": f"sh {deny_script}"}]}}),
        encoding="utf-8",
    )

    turns = iter(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall("1", "web", {"verb": "page open", "url": "https://example.com"})
                ],
                prompt_tokens=1,
                completion_tokens=1,
            ),
            ModelResponse(
                tool_calls=[ToolCall("2", "finish", {"summary": "done"})],
                prompt_tokens=1,
                completion_tokens=1,
            ),
        ]
    )

    def complete(_messages: list[dict]) -> ModelResponse:
        return next(turns)

    task = Task(id="t5-web-deny", repo_path=str(repo_root), instruction="try the web tool")
    result = run(complete, task, max_steps=5)

    deny_firings = [f for f in result.hook_firings if f.decision == "deny"]
    assert len(deny_firings) >= 1, f"expected a deny firing; got {result.hook_firings}"
    assert deny_firings[0].event == "pre_tool"
    assert deny_firings[0].tool == "web"
    assert "blocked" in deny_firings[0].reason

    web_step = next(s for s in result.steps if s.tool == "web")
    assert web_step.ok is False
    assert "blocked" in web_step.result, "the deny reason must reach the model as the tool result"


# ---------------------------------------------------------------------------
# t5 AC: no url-allow-list identifier anywhere under colleague/ (source scan)
# ---------------------------------------------------------------------------


def test_no_url_allowlist_identifier_under_colleague() -> None:
    """webglass owns the web policy; colleague must never grow its own."""
    forbidden = re.compile(r"ALLOWED_DOMAINS|allowed_hosts|url_policy")
    hits: list[str] = []
    for path in Path("colleague").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if forbidden.search(text):
            hits.append(str(path))
    assert not hits, f"colleague must not define its own url allow-list: {hits}"
