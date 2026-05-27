"""Hook config loader and runner — R2/R3 extensibility layer (t4).

Loads ``.convertible/hooks.json``, matches hook entries to lifecycle events
by tool-name regex, and runs individual hooks honoring the Claude-Code-style
I/O contract (JSON on stdin; exit code + structured stdout → a decision).

Events: ``task_start``, ``pre_tool``, ``post_tool``, ``finish``.
Decisions: ``allow``, ``deny``, ``rewrite``, ``observe``.

Config format (`.convertible/hooks.json`)::

    {
      "hooks": {
        "pre_tool":  [ { "matcher": "run_command", "command": "..." } ],
        "post_tool": [ { "matcher": "write_file",  "command": "..." } ],
        "task_start":[ { "command": "echo start" } ],
        "finish":    [ { "command": "echo done"  } ]
      }
    }

``matcher`` is a regex applied via :func:`re.fullmatch` against the tool name.
An absent or empty matcher matches every tool.  For non-tool events
(``task_start`` / ``finish``) the matcher is ignored — all entries always match.

I/O contract (mirrors Claude Code):

- Hook stdin: the ``payload`` dict serialised as JSON.
- exit != 0  →  ``deny``  (reason = stderr, falling back to stdout).
- exit 0 + non-empty JSON stdout:

  - ``{"decision":"deny", ...}``            → deny (reason from ``"reason"``).
  - ``{"decision":"rewrite","arguments":{}}`` → rewrite, carry new arguments.
  - ``{"decision":"allow", ...}`` or ``{}`` → allow.
  - Any response may include ``"additionalContext"``.

- exit 0 + empty / non-JSON stdout → ``allow`` (observe/no-op).
"""

from __future__ import annotations

import json
import re
import subprocess  # nosec B404 - hook commands run in a trusted operator env (D2)
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from convertible.configdir import resolve_file

# Non-tool events: matcher is irrelevant; every entry fires unconditionally.
_NON_TOOL_EVENTS = frozenset({"task_start", "finish"})

# Valid lifecycle events.
VALID_EVENTS = frozenset({"task_start", "pre_tool", "post_tool", "finish"})


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class HookEntry:
    """One entry from the hooks.json config.

    Fields
    ------
    event:
        The lifecycle event this entry is registered under (e.g. ``"pre_tool"``).
    matcher:
        A regex string tested with :func:`re.fullmatch` against the tool name.
        Empty string (the default) matches every tool.
    command:
        The shell command to run.
    """

    event: str
    matcher: str = ""
    command: str = ""


@dataclass
class HookDecision:
    """The outcome of running a single hook.

    Fields
    ------
    decision:
        One of ``"allow"``, ``"deny"``, ``"rewrite"``, ``"observe"``.
    arguments:
        Replacement tool arguments for a ``"rewrite"`` decision; ``None``
        otherwise.
    reason:
        Human-readable explanation — populated from stderr / ``"reason"``
        on deny.
    additional_context:
        Optional context string from ``"additionalContext"`` in hook stdout.
    exit_code:
        The subprocess exit code (``None`` if no subprocess ran).
    """

    decision: str
    arguments: dict[str, Any] | None = None
    reason: str = ""
    additional_context: str = ""
    exit_code: int | None = None


@dataclass
class HookConfig:
    """Parsed hooks configuration.

    Holds a mapping of event name → list of :class:`HookEntry`.
    """

    _entries: dict[str, list[HookEntry]] = field(default_factory=dict)

    def all_entries(self) -> list[HookEntry]:
        """Return every configured entry across all events, in event/declared order.

        Public accessor for read-only enumeration (e.g. ``convertible hooks
        list``), so callers never reach into the private ``_entries`` mapping.
        Events are visited in :data:`VALID_EVENTS`-stable order.
        """
        out: list[HookEntry] = []
        for event in ("task_start", "pre_tool", "post_tool", "finish"):
            out.extend(self._entries.get(event, []))
        return out

    def hooks_for(self, event: str, tool: str | None = None) -> list[HookEntry]:
        """Return all entries for *event* that match *tool*.

        For non-tool events (``task_start``, ``finish``) every registered entry
        is returned unconditionally — the ``matcher`` field is ignored.

        For tool events (``pre_tool``, ``post_tool``) an entry matches when:

        * its ``matcher`` is absent / empty, **or**
        * ``re.fullmatch(entry.matcher, tool)`` succeeds.

        Entries are returned in declared order.

        Args:
            event: Lifecycle event name.
            tool: Tool name being invoked (required for tool events; ``None``
                  for non-tool events).

        Returns:
            List of matching :class:`HookEntry` objects, possibly empty.
        """
        entries = self._entries.get(event, [])
        if not entries:
            return []

        # Non-tool events — matcher irrelevant.
        if event in _NON_TOOL_EVENTS:
            return list(entries)

        # Tool events — filter by matcher. An invalid matcher regex is an
        # operator-config error, not a crash: treat it as non-matching (skip the
        # entry) so a bad pattern can never abort the drive (reliability).
        result = []
        for entry in entries:
            if not entry.matcher:
                result.append(entry)
            elif tool:
                try:
                    matched = re.fullmatch(entry.matcher, tool)
                except re.error:
                    matched = None
                if matched:
                    result.append(entry)
        return result


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def load_hooks(
    repo_path: str | Path,
    *,
    user_home: str | Path | None = None,
) -> HookConfig:
    """Load ``.convertible/hooks.json`` for *repo_path*.

    Resolves the file using :func:`convertible.configdir.resolve_file` (repo
    over user).  Returns an empty :class:`HookConfig` when the file is absent
    or malformed — never raises.

    Args:
        repo_path: Path to the repo being driven.
        user_home: (test fixture) Override for the user home directory.

    Returns:
        Parsed :class:`HookConfig`.
    """
    cfg = HookConfig()

    hooks_path = resolve_file(repo_path, "hooks.json", user_home=user_home)
    if hooks_path is None:
        return cfg

    try:
        raw = json.loads(hooks_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return cfg

    hooks_section = raw.get("hooks")
    if not isinstance(hooks_section, dict):
        return cfg

    for event, raw_entries in hooks_section.items():
        if not isinstance(raw_entries, list):
            continue
        entries: list[HookEntry] = []
        for raw_entry in raw_entries:
            if not isinstance(raw_entry, dict):
                continue
            entries.append(
                HookEntry(
                    event=event,
                    matcher=str(raw_entry.get("matcher", "")),
                    command=str(raw_entry.get("command", "")),
                )
            )
        cfg._entries[event] = entries  # noqa: SLF001  (private field, same module)

    return cfg


def run_hook(
    entry: HookEntry,
    payload: dict[str, Any],
    *,
    cwd: str | Path,
    timeout: int = 60,
) -> HookDecision:
    """Run a single hook entry and return a :class:`HookDecision`.

    The *payload* dict is serialised to JSON and written to the hook's stdin.

    I/O contract:

    - exit != 0  →  ``deny``  (reason = stderr, fallback to stdout).
    - exit 0 + empty / non-JSON stdout  →  ``allow``.
    - exit 0 + JSON stdout:

      - ``{"decision":"deny", ...}``              → deny.
      - ``{"decision":"rewrite","arguments":{}}`` → rewrite.
      - ``{"decision":"allow", ...}`` or ``{}``   → allow.
      - ``"additionalContext"`` is propagated in any case.

    Args:
        entry: The :class:`HookEntry` to run.
        payload: Dict with keys ``event``, ``tool``, ``arguments``,
                 ``task_id``, ``repo_path``.
        cwd: Working directory for the subprocess.
        timeout: Subprocess timeout in seconds (default 60).

    Returns:
        A :class:`HookDecision`.
    """
    stdin_data = json.dumps(payload, default=str)

    # A hook that times out or cannot be launched is an expected operational
    # failure, not a crash: map it to a fail-closed ``deny`` with the cause as
    # the reason so the drive continues (the model receives the reason).
    try:
        proc = subprocess.run(  # nosec B602 - hook commands run in a trusted operator env (D2)
            entry.command,
            shell=True,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            input=stdin_data,
        )
    except subprocess.TimeoutExpired:
        return HookDecision(
            decision="deny", reason=f"hook timed out after {timeout}s", exit_code=None
        )
    except OSError as exc:
        return HookDecision(decision="deny", reason=f"hook failed to run: {exc}", exit_code=None)

    exit_code = proc.returncode

    # --- Non-zero exit → deny. ---
    if exit_code != 0:
        reason = proc.stderr.strip() or proc.stdout.strip()
        return HookDecision(decision="deny", reason=reason, exit_code=exit_code)

    # --- Exit 0: interpret stdout. ---
    stdout = proc.stdout.strip()

    if not stdout:
        return HookDecision(decision="allow", exit_code=exit_code)

    # Try to parse as JSON.
    try:
        parsed: dict[str, Any] = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        # Non-JSON stdout with exit 0 → allow (observe/no-op).
        return HookDecision(decision="allow", exit_code=exit_code)

    if not isinstance(parsed, dict):
        return HookDecision(decision="allow", exit_code=exit_code)

    additional_context = str(parsed.get("additionalContext", ""))
    hook_decision = str(parsed.get("decision", "allow"))

    if hook_decision == "deny":
        return HookDecision(
            decision="deny",
            reason=str(parsed.get("reason", "")),
            additional_context=additional_context,
            exit_code=exit_code,
        )

    if hook_decision == "rewrite":
        new_arguments = parsed.get("arguments")
        return HookDecision(
            decision="rewrite",
            arguments=new_arguments if isinstance(new_arguments, dict) else None,
            additional_context=additional_context,
            exit_code=exit_code,
        )

    # "allow" (explicit) or empty object → allow.
    return HookDecision(
        decision="allow",
        additional_context=additional_context,
        exit_code=exit_code,
    )
