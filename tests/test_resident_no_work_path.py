"""t10 — no-regression: the resident never touches the bounded `colleague work` path.

Covers spec targets c4 (the accurate before-state), h9 (colleague's only
pre-promotion Culture touch is the ephemeral culture tool), c11 (the work-item
path stays bounded/byte-identical) and h3 (the resident is opt-in, never started
by a bare work item). The e2e TaskResult shape is pinned by tests/test_e2e_mock.py;
this module guards the *separation* between the work path and the resident.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import colleague.culture as culture


def test_work_path_does_not_import_resident() -> None:
    """h3/c11: importing the work path never pulls in colleague.resident.

    Run in a FRESH interpreter so the check is deterministic regardless of what
    the test session already imported. The resident (agent-lifecycle + agentirc)
    must load only when the resident actually runs — never on `colleague work`.
    """
    code = (
        "import sys;"
        "import colleague.loop, colleague.engine, colleague.registry;"
        "import colleague.cli;"
        "import colleague.cli._commands.work as w;"
        "import colleague.cli._commands.promote as p;"  # even the verb module stays clean
        "mods=sorted(m for m in sys.modules if m.startswith('colleague.resident'));"
        "assert not mods, ('resident leaked onto work path: %r' % mods);"
        "al=[m for m in sys.modules if m=='agent_lifecycle' or m=='agentirc'];"
        "assert not al, ('culture extra leaked onto work path: %r' % al);"
        "print('clean')"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "clean" in result.stdout


def test_work_cli_source_has_no_resident_reference() -> None:
    """The work CLI module never references the resident package in source."""
    src = Path("colleague/cli/_commands/work.py").read_text(encoding="utf-8")
    assert "resident" not in src


def test_before_state_only_ephemeral_culture_tool() -> None:
    """c4/h9: pre-promotion, colleague's only Culture touch is the curated culture tool.

    The curated tool shells out to exactly agtag/devex inside a bounded work item
    (colleague/culture.py) — ephemeral, no persistent presence. The resident is the
    NEW persistent touch this feature adds, and it lives entirely off the work path.
    """
    assert culture.ALLOWED_CLIS == frozenset({"agtag", "devex"})
    # The before-state claim is the absence of a persistent path on `colleague work`,
    # asserted by test_work_path_does_not_import_resident above.


def test_loop_stays_async_free() -> None:
    """c11: the bounded loop is synchronous — no asyncio on the work path."""
    src = Path("colleague/loop.py").read_text(encoding="utf-8")
    assert "import asyncio" not in src and "from asyncio" not in src
