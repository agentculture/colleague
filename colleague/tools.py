"""The tool surface the agentic loop offers an engine, plus a repo-confined executor.

Ten tools — ``read_file``, ``write_file``, ``edit_file``, ``list_dir``,
``run_command``, ``culture``, ``devague``, ``subagent``, ``subagents``, and
``finish`` — are exposed to the model as OpenAI function/tool schemas
(:data:`colleague.tool_schemas.SCHEMAS`, re-exported here as :data:`SCHEMAS`).
:class:`ToolExecutor` runs a requested call against a fixed repo root.
``edit_file`` (#174) is the partial-edit primitive: an exact-string replace
whose cost scales with the change, not the file size.

Confinement (honesty condition h3): ``read_file`` / ``write_file`` / ``edit_file`` /
``list_dir`` resolve their path against the root and refuse anything that escapes it
(``..`` traversal, absolute paths outside the tree); ``write_file`` and ``edit_file``
additionally refuse writes into the read-only neighbour clone tree. ``run_command``
runs with ``cwd`` pinned to the root — v0 trusts the command itself (D2).

``read_file`` line-grounding (#240): :func:`_number_lines` prefixes every real
line with its true 1-based number (``cat -n`` style) before truncation — read-display
only, never round-tripped into ``edit_file``.

Two curated tools stay OUT of :data:`SCHEMAS`, appended only by
:func:`curate_schemas`: ``deepthink`` (:data:`DEEPTHINK_SCHEMA`, plan t4, opt-in via
``deepthink=True``) and the six purpose tools (:mod:`colleague.purpose_schemas`, plan
t5, spliced onto a concrete role's allow-list — role=``None`` is unaffected).

The pure data/curation half — :data:`SCHEMAS`, :data:`TOOL_NAMES`,
:data:`DEEPTHINK_SCHEMA`, :func:`curate_schemas`, :func:`narrow_role_by_tool_set` —
lives in the sibling :mod:`colleague.tool_schemas` module (plan
`hard-1000-line-file-limit`, task t5) and is re-exported below unchanged, so every
existing ``from colleague.tools import ...`` call site keeps resolving. This module
keeps :class:`ToolExecutor`, the ``subprocess``/``Path``-using half.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess  # nosec B404 - running model-issued commands is the point (trusted, D2)
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from colleague.roles import Role

import colleague.hire_assign as hire_assign
import colleague.purpose_schemas as purpose_schemas
import colleague.search_schemas as search_schemas
import colleague.web_schemas as web_schemas
from colleague import culture, devague, editgate, media, memory, readpage, testintegrity
from colleague.config import _DEFAULT_MAX_OUTPUT_CHARS, MAX_SUBAGENT_FANOUT
from colleague.contract import SubResult
from colleague.tool_schemas import (  # noqa: F401 - re-exported for existing call sites
    DEEPTHINK,
    DEEPTHINK_SCHEMA,
    FINISH,
    SCHEMAS,
    TOOL_NAMES,
    curate_schemas,
    narrow_role_by_tool_set,
)

#: Size cap for ``view_media`` files (task t5). Base64 inflates bytes ~4/3 and
#: the encoded part rides every subsequent windowed prompt, so the cap bounds
#: wire + context cost; a typical screenshot is well under it.
MAX_MEDIA_BYTES = 4 * 1024 * 1024

#: Bound a runaway model-issued command so it cannot stall the loop indefinitely
#: (mirrors culture/devague ``_TIMEOUT_SECONDS`` and neighbours ``_GIT_TIMEOUT_SECONDS``).
_COMMAND_TIMEOUT_SECONDS = 300

#: Timeout for the curated pytest runner (mirrors lint.py's _LINT_TIMEOUT).
_TESTS_TIMEOUT_SECONDS = 300


class ToolError(Exception):
    """A tool call that cannot be honored (bad path, escape attempt, missing file)."""


class UnknownToolError(ToolError):
    """A tool call naming a tool the harness does not have (#321).

    Distinguished from a plain :class:`ToolError` so the loop can tell a broken
    tool-call *protocol* (a name that can never exist — a serving-side parser /
    template mismatch, see #320) from an ordinary bad call to a real tool, and
    stop a run that would otherwise burn its whole step budget on them.
    """


@dataclass
class ToolOutcome:
    """Result of executing one tool call."""

    result: str
    changed_file: str | None = None
    finished: bool = False
    finish_summary: str = ""
    destination: str | None = None
    """The devague goal-frame slug the work item aimed at, or ``None`` when the
    engine did not declare a destination on finish."""
    announcement: str | None = None
    """The announcement text declared on arrival at the destination, or ``None``
    when the engine did not declare one."""
    media_part: dict[str, Any] | None = None
    """An OpenAI content part produced by ``view_media`` (task t5), or ``None``
    for every other tool. The loop folds a non-None part into a follow-up user
    parts message — tool-message content itself stays a plain string (the
    wire-safe convention every OpenAI-compatible server accepts)."""


#: Column width for the ``cat -n`` style line-number prefix (matches GNU
#: ``cat -n``'s default right-justified 6-column number).
_LINE_NUMBER_WIDTH = 6


def _number_lines(text: str) -> str:
    """Ground *text* for citation: prefix every real line with its true line number.

    ``cat -n`` style — ``f"{n:6d}\\t{line}"`` — so a model quoting a result line
    is quoting a copy-derived ``file:line``, never a re-counted one (issue #240:
    a served model citing "line N" from its own windowed/truncated context
    drifted by ~240 lines from the real file). Splits on bare ``"\\n"`` only,
    NOT :meth:`str.splitlines`, which also breaks on ``\\v``/``\\f``/``\\x1c``-``\\x1e``/
    ``\\x85``/``\\u2028``/``\\u2029`` — a wider set that would silently invent phantom
    line boundaries a real ``grep -n``/editor would never count. A trailing
    newline terminates the last line without minting a phantom extra line (the
    same convention as ``cat -n``/``grep -n``); an empty file grounds to an
    empty string (no lines to number).

    Display-only: the numbering is never written to disk and never read back
    by ``edit_file`` — that tool re-reads the file itself and matches
    ``old_string`` against the raw, unnumbered content.
    """
    if text == "":
        return ""
    body = text[:-1] if text.endswith("\n") else text
    lines = body.split("\n")
    return "\n".join(f"{i:{_LINE_NUMBER_WIDTH}d}\t{line}" for i, line in enumerate(lines, start=1))


def _purpose_dispatch(executor: "ToolExecutor") -> dict[str, Callable[[dict[str, Any]], Any]]:
    """Purpose tools' handlers (t5): ``purpose_schemas.dispatch`` once t6 wires it."""
    if hasattr(purpose_schemas, "dispatch"):
        return purpose_schemas.dispatch(executor)
    return {
        n: (lambda _a, _n=n: ToolOutcome(result=f"purpose tool '{_n}' not wired (t6)"))
        for n in purpose_schemas.PURPOSE_TOOL_NAMES
    }


def _hire_dispatch(executor: "ToolExecutor") -> dict[str, Callable[[dict[str, Any]], Any]]:
    """``hire_colleague``'s handler (delegation-follow-ups t12): the bounded
    two-round negotiation in :func:`colleague.hire_dispatch.dispatch` —
    registered exactly like the purpose handlers above; ``assign_to_colleague``
    registers its own line when t13 lands (:mod:`colleague.hire_assign`)."""
    from colleague import hire_dispatch  # local: mirrors purpose_schemas' lazy tools import

    return hire_dispatch.dispatch(executor)


def _require(arguments: dict[str, Any], key: str, tool: str) -> Any:
    """Fetch a required tool argument or raise a self-correcting :class:`ToolError`.

    A served model sometimes emits a tool call with empty/missing arguments
    (live: work item ``4c6a96107269`` died at step 12 when a bare
    ``arguments["path"]`` raised ``KeyError`` and escaped the dispatch, which
    caught only ``ToolError`` — aborting a 12-step run with 4 folded
    sub-results). A missing required argument is a MODEL error, not a harness
    bug: it must cost one non-ok step carrying a message the model can act on,
    never the run.
    """
    if key not in arguments:
        raise ToolError(f"{tool} requires '{key}'")
    return arguments[key]


def _optional_str_field(item: dict, key: str) -> dict[str, Any]:
    """``{key: item[key]}`` when ``item[key]`` is a non-empty string, else ``{}``.

    Extracted from :func:`_parse_batch_items` (SonarCloud S3776) — DRYs the
    three identically-shaped "carry it forward only if it's a real string"
    optional fields (``profile``/``context_mode``/``effort``).
    """
    value = item.get(key)
    return {key: value} if isinstance(value, str) and value else {}


def _normalize_batch_item(i: int, item: Any) -> dict[str, Any]:
    """Validate + normalize ONE ``subagents`` tool instruction item.

    Extracted from :func:`_parse_batch_items` (SonarCloud S3776). *item* must
    be an object carrying a non-empty ``instruction`` string; ``engine``/
    ``model``/``role`` are optional, and ``profile``/``context_mode``/
    ``effort`` are carried forward only when present (see
    :func:`_optional_str_field`).
    """
    if not isinstance(item, dict):
        raise ToolError(f"subagents: item {i} must be an object with 'instruction'")
    instruction = item.get("instruction")
    if not instruction or not isinstance(instruction, str):
        raise ToolError(f"subagents: item {i} is missing a required 'instruction' string")
    return {
        "instruction": instruction,
        "engine": item.get("engine") or None,
        "model": item.get("model") or None,
        "role": item.get("role") or None,
        **_optional_str_field(item, "profile"),
        **_optional_str_field(item, "context_mode"),
        **_optional_str_field(item, "effort"),
    }


def _parse_batch_items(raw_instructions: list) -> list[dict[str, Any]]:
    """Validate + normalize the ``subagents`` tool's instruction items.

    Extracted from :meth:`ToolExecutor._subagents` to keep that method's
    cognitive complexity within budget (SonarCloud S3776); per-item
    validation/normalization now lives in :func:`_normalize_batch_item`.
    """
    return [_normalize_batch_item(i, item) for i, item in enumerate(raw_instructions)]


class ToolExecutor:
    """Executes tool calls against a single repo root, confining file access to it."""

    def __init__(
        self,
        root: str | Path,
        *,
        spawn=None,
        batch_spawn=None,
        deepthink: Callable[..., Any] | None = None,
        max_output_chars: int = _DEFAULT_MAX_OUTPUT_CHARS,
        allowlist: "Role | tuple[str, ...] | None" = None,
        context_note: str | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.changed: set[str] = set()
        self.read_set = editgate.new_read_set()  # prior-read rule (t13): what was SHOWN
        self.context_note = context_note  # t21: continuation id folded into edit refusals
        # Total UTF-8 bytes the model authored into files via write_file/edit_file
        # across the work item — the exact "tokens written" measure (no tokenizer, so
        # bytes not tokens; an edit_file counts only its replacement bytes). The loop
        # snapshots it onto WorkStats, mirroring the changed_files snapshot.
        self.bytes_written: int = 0
        # t9 web-call budget counters (cap logic in colleague/webbudget.py); per
        # executor so every subagent child has its own; web_cap_hit = cap at refusal.
        self.web_calls: int = 0
        self.web_failed: int = 0
        self.web_cap_hit: int | None = None
        self._spawn = spawn
        # Batch spawn callable: ``batch_spawn(items) -> list[SubResult]``.
        # Injected by the loop (t5); None means the subagents tool is unavailable.
        self._batch_spawn = batch_spawn
        # Deepthink escalation callable (t5): the bound ``DeepthinkRun`` seam,
        # ``deepthink(question, context, *, point="tool") -> DeepthinkResult``
        # (:func:`colleague.deepthink.make_deepthink_run`). Injected by the engine
        # only for a dual-model config; a hallucinated call with None is handled
        # defensively (see ``_deepthink_tool``); a plain str-returning callable is
        # still honored (back-compat: answers, records nothing).
        self._deepthink = deepthink
        # Every DeepthinkCall record the tool dispatch accumulated, in firing
        # order. The loop snapshots this onto ``TaskResult.deepthink`` (spec c14)
        # exactly like ``sub_results`` — empty stays empty → omitted artifact key.
        self.deepthink_calls: list[Any] = []
        # Cap on each tool result fed back to the model so a huge file/command
        # can't blow the context window. Resolved from EngineConfig (env
        # COLLEAGUE_MAX_OUTPUT_CHARS); sized for the served model's window.
        self._max_output_chars = max_output_chars
        self.sub_results: list[SubResult] = []
        # Optional role-aware allow-list: when set, only listed tools may be
        # dispatched; everything else raises ToolError.  Accepts a Role object
        # (uses role.tool_allowlist) or a plain tuple of tool-name strings.
        if allowlist is None:
            self._allowlist: set[str] | None = None
        elif hasattr(allowlist, "tool_allowlist"):
            self._allowlist = set(allowlist.tool_allowlist)
        else:
            self._allowlist = set(allowlist)

        # Read-only flag for role-aware tool restrictions (e.g. memory remember)
        self._is_read_only: bool = False
        if hasattr(allowlist, "read_only"):
            self._is_read_only = allowlist.read_only

    def _truncate(self, text: str, tool: str = "") -> str:
        return readpage.bound_output(text, tool, self._max_output_chars, self.root, self)

    def _safe_path(self, rel: str) -> Path:
        """Resolve ``rel`` under the root, refusing any path that escapes it."""
        candidate = (self.root / rel).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ToolError(f"path '{rel}' escapes the repo root")
        return candidate

    def _refuse_clone_write(self, path: Path, rel: str) -> None:
        """Refuse a write into the neighbour clone tree (honesty condition h12).

        Neighbour clones are read-only source: the model may read them but never
        write into them. ``_safe_path`` only confines to the repo root, which
        includes the clone tree — so every write path (write_file, edit_file)
        guards explicitly via this helper.
        """
        clone_root = (self.root / self._CLONE_SUBDIR).resolve()
        if path == clone_root or clone_root in path.parents:
            raise ToolError(
                f"write refused: '{rel}' is inside the neighbour clone directory "
                f"('{self._CLONE_SUBDIR}'), which is read-only source. "
                "Clones are inert — they may be read, never written."
            )

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        """Dispatch a single tool call by name to its handler.

        Returns the matching handler's ToolOutcome.  When an allow-list is active
        (set via ``allowlist`` on construction), tools not in the list raise
        :class:`ToolError` instead of being executed.
        """
        if self._allowlist is not None and name not in self._allowlist:
            raise ToolError(f"tool '{name}' is not allowed for this role")
        # Table-driven dispatch (was a long if-chain; flattened to keep cognitive
        # complexity in budget — S3776). check_test_integrity takes no args.
        dispatch = {
            "read_file": self._read_file,
            "view_media": self._view_media,
            "write_file": self._write_file,
            "edit_file": self._edit_file,
            "list_dir": self._list_dir,
            **search_schemas.dispatch(self),
            **web_schemas.dispatch(self),
            **_purpose_dispatch(self),
            **hire_assign.dispatch(self),
            **_hire_dispatch(self),
            "run_command": self._run_command,
            "culture": self._culture,
            "devague": self._devague,
            "memory": self._memory,
            "subagent": self._subagent,
            "subagents": self._subagents,
            "run_tests": self._run_tests,
            "check_test_integrity": lambda _a: self._check_test_integrity(),
            DEEPTHINK: self._deepthink_tool,
            FINISH: self._finish,
        }
        handler = dispatch.get(name)
        if handler is None:
            raise UnknownToolError(
                f"unknown tool '{name}' — valid tools: {', '.join(sorted(dispatch))}"
            )
        try:
            return handler(arguments)
        except ToolError:
            raise
        except Exception as exc:  # noqa: BLE001 - defense-in-depth (#269)
            # A handler crash on model-supplied input is a MODEL-visible step error,
            # never a run abort: any unguarded KeyError/TypeError must bounce back
            # as a self-correcting observation naming the tool (the live 1.30.0
            # failure aborted a flight with a bare "'path'").
            raise ToolError(
                f"{name} failed: {type(exc).__name__}: {exc} — check the tool's "
                f"argument schema and retry"
            ) from exc

    def _finish(self, arguments: dict[str, Any]) -> ToolOutcome:
        """The ``finish`` tool — record the terminal summary + optional destination."""
        return ToolOutcome(
            result="finished",
            finished=True,
            finish_summary=str(arguments.get("summary", "")),
            destination=arguments.get("destination") or None,
            announcement=arguments.get("announcement") or None,
        )

    def _read_file(self, arguments: dict[str, Any]) -> ToolOutcome:
        path = self._safe_path(str(_require(arguments, "path", "read_file")))
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ToolError(f"no such file: {arguments['path']}") from exc
        except OSError as exc:
            raise ToolError(f"cannot read {arguments['path']}: {exc}") from exc
        offset, limit = arguments.get("offset"), arguments.get("limit")  # paging (t9, #240 kept)
        rendered = readpage.render_read(text, offset, limit, ceiling=self._max_output_chars)
        editgate.record_read(self.read_set, str(path), text, rendered)
        return ToolOutcome(result=rendered)

    def _view_media(self, arguments: dict[str, Any]) -> ToolOutcome:
        """The ``view_media`` tool (t5) — load a repo image as a content part.

        Pure read: same ``_safe_path`` confinement as ``read_file``, a byte cap
        (:data:`MAX_MEDIA_BYTES`) so one call can't flood the wire/context, and
        images only — audio has no mid-work read use while the serving rig
        drops it, and ``validate_attachment`` already rejects non-media.
        """
        rel = str(_require(arguments, "path", "view_media"))
        path = self._safe_path(rel)
        if not path.is_file():
            raise ToolError(f"no such file: {rel}")
        size = path.stat().st_size
        if size > MAX_MEDIA_BYTES:
            raise ToolError(
                f"cannot view {rel}: {size} bytes exceeds the {MAX_MEDIA_BYTES}-byte "
                "media size cap"
            )
        try:
            attachment = media.validate_attachment(str(path))
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        if not attachment["media_type"].startswith("image/"):
            raise ToolError(f"view_media is images only: {rel} is {attachment['media_type']}")
        try:
            part = media.build_part(attachment)
        except OSError as exc:
            raise ToolError(f"cannot read {rel}: {exc}") from exc
        return ToolOutcome(
            result=f"loaded image {rel} ({size} bytes) into the conversation",
            media_part=part,
        )

    def _write_file(self, arguments: dict[str, Any]) -> ToolOutcome:
        rel = str(_require(arguments, "path", "write_file"))
        path = self._safe_path(rel)
        self._refuse_clone_write(path, rel)
        content = str(arguments.get("content", ""))
        path.parent.mkdir(parents=True, exist_ok=True)
        # newline="" disables newline translation so the on-disk bytes equal
        # len(content.encode("utf-8")) on EVERY platform (newline=None would write
        # "\r\n" on Windows, inflating bytes_written) — byte-deterministic writes.
        path.write_text(content, encoding="utf-8", newline="")
        editgate.record_written(self.read_set, str(path), content)  # authored == shown (t13)
        self.changed.add(rel)
        # Accumulate exact UTF-8 bytes written (== the on-disk size, given
        # newline=""), summed across every write_file — snapshotted into WorkStats.
        n_bytes = len(content.encode("utf-8"))
        self.bytes_written += n_bytes
        return ToolOutcome(result=f"wrote {n_bytes} bytes to {rel}", changed_file=rel)

    def _edit_file(self, arguments: dict[str, Any]) -> ToolOutcome:
        """Replace an exact string in an existing file (partial edit, #174).

        Edit cost scales with the change, not the file size — the structural fix
        for full-file ``write_file`` timing out on large existing files. ``old_string``
        must be unique unless ``replace_all`` is set.
        """
        rel = str(_require(arguments, "path", "edit_file"))
        path = self._safe_path(rel)
        self._refuse_clone_write(path, rel)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ToolError(
                f"no such file: {rel} (edit_file only edits existing files; "
                "use write_file to create)"
            ) from exc
        except UnicodeDecodeError as exc:
            raise ToolError(
                f"cannot edit {rel}: not valid UTF-8 text (edit_file works on text files)"
            ) from exc
        except OSError as exc:
            raise ToolError(f"cannot read {rel}: {exc}") from exc
        old = str(_require(arguments, "old_string", "edit_file"))
        new = str(_require(arguments, "new_string", "edit_file"))
        replace_all = bool(arguments.get("replace_all", False))
        if old == "":
            raise ToolError("old_string must be non-empty; use write_file to create a file")
        if old == new:
            raise ToolError("old_string and new_string are identical (no-op edit)")
        old, count = editgate.resolve_old_string(text, old, rel)  # exact, then relaxed (t13)
        editgate.require_prior_read(
            self.read_set, str(path), rel, text, old, context_note=self.context_note
        )
        if count > 1 and not replace_all:
            raise ToolError(
                f"old_string is not unique in {rel} ({count} matches); add surrounding "
                "context to disambiguate, or set replace_all=true"
            )

        replacements = count if replace_all else 1
        # Exactly two cases here: replace_all (any count) or the single unique
        # match (the `1` cap). str.replace is a single left-to-right pass, so a
        # new_string containing old_string is NOT re-scanned (no runaway expansion).
        updated = text.replace(old, new) if replace_all else text.replace(old, new, 1)
        # newline="" keeps on-disk bytes byte-deterministic cross-platform, exactly
        # as _write_file does; a write failure becomes a recoverable ToolError.
        try:
            path.write_text(updated, encoding="utf-8", newline="")
        except OSError as exc:
            raise ToolError(f"cannot write {rel}: {exc}") from exc
        self.changed.add(rel)
        # Account only the bytes this edit authored into the file (replacement text
        # times the occurrences replaced) — the honest cost-of-output signal that
        # makes an edit's ROI visible against a full-file rewrite (#174).
        self.bytes_written += replacements * len(new.encode("utf-8"))
        plural = "occurrence" if replacements == 1 else "occurrences"
        return ToolOutcome(
            result=f"edited {rel}: replaced {replacements} {plural}", changed_file=rel
        )

    def _list_dir(self, arguments: dict[str, Any]) -> ToolOutcome:
        path = self._safe_path(str(arguments.get("path", ".")))
        if not path.is_dir():
            raise ToolError(f"not a directory: {arguments.get('path', '.')}")
        entries = sorted(p.name + ("/" if p.is_dir() else "") for p in path.iterdir())
        return ToolOutcome(result=self._truncate("\n".join(entries)))

    # Relative path prefix used by the never-execute guard below.
    _CLONE_SUBDIR = ".colleague/neighbours"

    def _run_command(self, arguments: dict[str, Any]) -> ToolOutcome:
        """Execute a shell command with cwd pinned to the repo root.

        Never-execute confinement (AC2, best-effort): this guard refuses any
        command string that contains the clone subdirectory path
        (``.colleague/neighbours``), which is the read-only source tree for
        neighbour clones. Clones exist only to be *read*; executing scripts or
        binaries from them is not part of the contract.

        Honest limitation: the guard is a substring check on the raw command
        string. A sufficiently obfuscated command (e.g. variable expansion,
        concatenation, here-docs) could bypass it. It is best-effort — an
        airtight sandbox is out of v0 scope (see CLAUDE.md). The guard covers
        the obvious / accidental case; document rather than overclaim.
        """
        command = str(_require(arguments, "command", "run_command"))

        # Best-effort guard: refuse commands that EXECUTE a path inside the clone
        # dir. Token-aware (shlex) so a benign mention in a quoted string (e.g.
        # echo "see .colleague/neighbours") is no longer a false positive — only a
        # token resolving to the clone root, or under it, is refused; on unbalanced
        # quotes (shlex ValueError) fall back to the stricter substring check.
        clone_rel = self._CLONE_SUBDIR
        # Must NEVER raise (a pathological tree could fail resolve()); fall back
        # to the unresolved substring check rather than escape tool execution.
        try:
            clone_root: Path | None = (self.root / clone_rel).resolve()
        except (OSError, RuntimeError, ValueError):
            clone_root = None

        def _targets_clone(token: str) -> bool:
            try:
                candidate = (self.root / token).resolve()
            except (OSError, RuntimeError, ValueError):
                # Unresolvable token (e.g. an embedded NUL byte) is not a clone-dir
                # target; let it fall through to subprocess.run, whose own error is
                # mapped to a clean ToolError below rather than escaping the guard.
                return False
            return candidate == clone_root or clone_root in candidate.parents

        try:
            tokens: list[str] | None = shlex.split(command)
        except ValueError:
            tokens = None  # unparseable command → conservative substring fallback
        if clone_root is not None and tokens is not None:
            blocked = any(_targets_clone(t) for t in tokens)
        else:
            # Token-aware check unavailable (unresolvable clone root or unparseable
            # command) → conservative substring fallback on the *unresolved* absolute
            # path, which never raises.
            clone_abs = str(self.root / clone_rel)
            blocked = clone_rel in command or clone_abs in command
        if blocked:
            raise ToolError(
                f"run_command refused: commands must not execute paths inside the "
                f"neighbour clone directory ('{clone_rel}'). "
                f"Clone files are read-only source — use read_file to inspect them."
            )

        try:
            proc = subprocess.run(  # nosec B602 - shell by design; trusted operator env (D2)
                command,
                shell=True,
                cwd=str(self.root),
                capture_output=True,
                text=True,
                timeout=_COMMAND_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            # A hung command must surface as a recoverable ToolError, not an
            # uncaught exception that escapes the executor and aborts the whole
            # drive — the loop only catches ToolError around tool execution
            # (see colleague/loop.py), mirroring culture/devague/hooks.
            raise ToolError(
                f"run_command timed out after {_COMMAND_TIMEOUT_SECONDS}s: {command}"
            ) from exc
        except OSError as exc:
            # Launch/IO failure (e.g. too many open files, no shell) → clean error.
            raise ToolError(f"run_command failed to launch: {exc}") from exc
        except Exception as exc:
            # Any other failure from subprocess.run (e.g. ValueError on an embedded
            # NUL byte in a model-issued command) must ALSO be recoverable, not
            # abort the work item — the whole point of run_command error mapping. Mirrors
            # the _subagent/_subagents catch-all in this module. KeyboardInterrupt is
            # a BaseException and still propagates.
            raise ToolError(f"run_command failed: {type(exc).__name__}: {exc}") from exc
        body = (proc.stdout or "") + (proc.stderr or "")
        result = f"exit={proc.returncode}\n{body}"
        return ToolOutcome(result=self._truncate(result, "run_command"))

    def _culture(self, arguments: dict[str, Any]) -> ToolOutcome:
        """Dispatch the shared ``culture`` tool to an allow-listed AgentCulture CLI.

        The subprocess launch, identity injection, and absent-CLI handling live
        in :mod:`colleague.culture`; here we just translate its error type into
        the loop's :class:`ToolError` so a bad CLI name or an uninstalled CLI
        becomes a clean string fed back to the model, never a crash.
        """
        cli = arguments.get("cli")
        if not cli or not isinstance(cli, str):
            raise ToolError("culture tool requires a 'cli' name (agtag or devex)")
        args = culture.normalize_args(arguments.get("args"))
        try:
            output = culture.run_culture(cli, args, root=self.root)
        except culture.CultureToolError as exc:
            raise ToolError(str(exc)) from exc
        return ToolOutcome(result=output)

    def _devague(self, arguments: dict[str, Any]) -> ToolOutcome:
        """Dispatch the shared ``devague`` tool to the operator-installed devague CLI.

        The subprocess launch, identity injection, and allow-list enforcement live
        in :mod:`colleague.devague`; here we translate its error type into the
        loop's :class:`ToolError` so a disallowed move or an uninstalled CLI
        becomes a clean string fed back to the model, never a crash.
        """
        move = str(arguments.get("move", ""))
        args = devague.normalize_args(arguments.get("args"))
        try:
            output = devague.run_devague(move, args, root=self.root)
        except devague.DevagueToolError as exc:
            raise ToolError(str(exc)) from exc
        return ToolOutcome(result=output)

    def _memory(self, arguments: dict[str, Any]) -> ToolOutcome:
        """Dispatch the memory tool to the eidetic CLI via colleague.memory.

        Enforces role-aware verb restrictions: read-only roles may only use
        'recall' (search); 'remember' (store) is refused with a clear error.
        When the eidetic CLI is absent, recall returns an empty JSON array
        and remember returns 'ok' — never crashes.
        """
        verb = str(arguments.get("verb", ""))
        if verb not in ("recall", "remember"):
            raise ToolError("memory tool requires verb 'recall' or 'remember'")

        # Role-aware refusal: read-only roles cannot use 'remember'
        if verb == "remember" and self._is_read_only:
            raise ToolError(
                "memory 'remember' is not allowed for read-only roles; "
                "use 'recall' to search instead"
            )

        if verb == "recall":
            query = str(arguments.get("query", ""))
            if not query:
                raise ToolError("memory 'recall' requires a 'query' string")
            top_k = int(arguments.get("top_k", 5))
            hits = memory.recall(self.root, query, top_k=top_k)
            # Bounded like every other tool result (PR #267 review): a store
            # with huge records must not blow the tool-output budget.
            return ToolOutcome(result=self._truncate(json.dumps(hits)))
        else:
            # verb == "remember"
            record = arguments.get("record")
            if not isinstance(record, dict):
                raise ToolError("memory 'remember' requires a 'record' object")
            ok = memory.remember(self.root, record)
            return ToolOutcome(result="ok" if ok else "failed")

    def _deepthink_tool(self, arguments: dict[str, Any]) -> ToolOutcome:
        """Dispatch the ``deepthink`` tool to the injected one-shot escalation seam.

        The actual completion call (windowing to the deepthink model's own budget,
        the tools-off invariant, degradation) lives in the injected ``deepthink``
        callable (set by the loop only when a dual-model config is present — task
        t5, see :func:`colleague.deepthink.run_deepthink`); here we validate the
        inputs and translate a missing seam into a clean, non-crashing result
        string.

        Defensive floor (never raises for a missing seam): ``curate_schemas``
        only offers :data:`DEEPTHINK_SCHEMA` when a role allows it AND the loop
        opted in, so a live drive should never reach this branch with
        ``self._deepthink is None`` — but a hallucinated call must still degrade
        gracefully rather than crash the drive.
        """
        question = arguments.get("question")
        if not question or not isinstance(question, str):
            raise ToolError("deepthink tool requires a 'question'")
        context = str(arguments.get("context") or "")

        if self._deepthink is None:
            return ToolOutcome(result="deepthink is not configured for this run")

        try:
            answer = self._deepthink(question, context)
        except Exception as exc:  # the injected seam degrades internally; defense-in-depth
            raise ToolError(f"deepthink failed: {exc}") from exc

        # The bound DeepthinkRun seam returns a DeepthinkResult carrying its call
        # record — accumulate it for the loop's TaskResult.deepthink snapshot
        # (spec c14) and translate a degraded escalation into an honest notice
        # (spec c13: the model proceeds on its own judgment, the run never fails).
        call = getattr(answer, "call", None)
        if call is not None:
            self.deepthink_calls.append(call)
            if getattr(call, "degraded", False):
                return ToolOutcome(
                    result="deepthink is unavailable (degraded) — proceed with your own judgment."
                )
            return ToolOutcome(result=self._truncate(str(getattr(answer, "text", ""))))
        # Back-compat: a plain str-returning seam answers but records nothing.
        return ToolOutcome(result=self._truncate(str(answer)))

    def _check_test_integrity(self) -> ToolOutcome:
        """Run the mirror-detection heuristic on the work item's changed files.

        Takes no arguments — it inspects the work item's already-changed files
        (``self.changed``), so the schema declares no parameters.
        """
        report = testintegrity.detect_mirror(str(self.root), sorted(self.changed))
        if not report.findings:
            return ToolOutcome(result="no mirror findings")
        lines = [
            f"  {f.symbol} ({f.kind}) in {f.test_file} + {f.impl_file}" for f in report.findings
        ]
        return ToolOutcome(result="mirror findings:\n" + "\n".join(lines))

    def _run_tests(self, arguments: dict[str, Any]) -> ToolOutcome:
        """Run the repository's test suite via pytest.

        Curated runner: the command is fixed to ``python -m pytest [paths]`` —
        never taken from the model, so a read-only validator role can run tests
        without access to ``run_command``. Mirrors lint.py's ``_run`` pattern
        (curated program set, per-call timeout, graceful degradation).

        Returns a concise pass/fail summary string.  Never writes files.
        """
        raw_paths: list[str] = arguments.get("paths") or []
        # Confine + de-weaponize the model-supplied paths (#t4 Q2): reject option-like
        # args and anything escaping the repo root, then pass them AFTER ``--`` so
        # pytest treats every one as a POSITIONAL test path, never an option — closing
        # the ``--junitxml=…`` / ``-p plugin`` injection that could write a file or
        # load arbitrary code despite the validator role being "read-only".
        safe_paths: list[str] = []
        for p in raw_paths:
            if not isinstance(p, str) or p.startswith("-"):
                return ToolOutcome(result=f"run_tests skipped: invalid test path {p!r}")
            try:
                self._safe_path(p)
            except ToolError:
                return ToolOutcome(result=f"run_tests skipped: path {p!r} escapes the repo root")
            safe_paths.append(p)
        # Keep the validator role's "never writes files" promise literally true
        # (#221 qodo): pytest/python otherwise drop ``.pytest_cache`` and
        # ``__pycache__`` into the tree. ``-p no:cacheprovider`` disables pytest's
        # cache plugin and ``PYTHONDONTWRITEBYTECODE=1`` stops bytecode caches, so a
        # read-only run leaves the tree byte-identical.
        cmd = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "--", *safe_paths]
        # The ``--`` separator de-weaponizes CLI args but NOT the env: pytest honors
        # ``PYTEST_ADDOPTS`` (arbitrary options) and ``PYTEST_PLUGINS`` (arbitrary
        # plugin imports) from the environment regardless. Strip both so an inherited
        # env can't re-open the option/plugin-injection vector behind the validator's
        # back, and disable bytecode caches to keep the tree byte-identical.
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        env.pop("PYTEST_ADDOPTS", None)
        env.pop("PYTEST_PLUGINS", None)

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.root),
                capture_output=True,
                text=True,
                check=False,
                timeout=_TESTS_TIMEOUT_SECONDS,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return ToolOutcome(
                result=f"run_tests skipped: timed out after {_TESTS_TIMEOUT_SECONDS}s"
            )
        except (OSError, ValueError) as exc:
            return ToolOutcome(result=f"run_tests skipped: {exc}")

        body = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode == 0:
            return ToolOutcome(result="tests passed")
        # Non-zero: include last ~20 lines of output for context.
        last_lines = "\n".join(body.splitlines()[-20:])
        return ToolOutcome(result=f"tests FAILED (exit={proc.returncode})\n{last_lines}")

    def _call_spawn(
        self,
        instruction: str,
        engine: str | None,
        model: str | None,
        role: str | None,
        profile: str | None,
        context_mode: str | None,
        effort: str | None = None,
    ) -> "SubResult":
        """Invoke the spawn closure — positional (legacy) or with the #411/#416 keywords."""
        if profile is None and context_mode is None and effort is None:
            return self._spawn(instruction, engine, model, role)  # type: ignore[misc]
        kwargs: dict[str, Any] = {"context_mode": context_mode or "inherit"}
        if profile is not None:
            kwargs["profile"] = profile
        if effort is not None:
            kwargs["effort"] = effort
        return self._spawn(  # type: ignore[misc]
            instruction,
            engine,
            model,
            role,
            **kwargs,
        )

    def _subagent(self, arguments: dict[str, Any]) -> ToolOutcome:
        """Delegate a scoped sub-task to a nested child work item via the injected spawn.

        The actual launching lives in the injected ``spawn`` callable (set by the
        loop in t6); here we only validate inputs, enforce the per-work-item fan-out
        cap, call the spawn, and translate any non-ToolError exception into a clean
        :class:`ToolError` so a launcher/engine error is fed back to the model and
        never crashes the parent drive.

        The child's changed files are merged into ``self.changed`` so they reach
        the single top-level handoff. ``self.sub_results`` accumulates all children
        for the parent ``TaskResult``.
        """
        if self._spawn is None:
            raise ToolError("subagent delegation is not available in this drive")

        instruction = arguments.get("instruction")
        if not instruction or not isinstance(instruction, str):
            raise ToolError("subagent tool requires an 'instruction'")

        engine = arguments.get("engine") or None
        model = arguments.get("model") or None
        role = arguments.get("role") or None
        # Agents mode (#411): the model-facing profile / context_mode ride onto the
        # ChildSpec through the spawn closure's keyword seam; absent = the pre-#411
        # positional call, byte-identical.
        profile = arguments.get("profile") or None
        context_mode = arguments.get("context_mode") or None
        # Per-child thinking-effort override (#416 t5): same keyword seam, absent
        # by default (the child resolves its own rung from the role/seat tables).
        effort = arguments.get("effort") or None

        if len(self.sub_results) >= MAX_SUBAGENT_FANOUT:
            raise ToolError(
                f"subagent fan-out limit ({MAX_SUBAGENT_FANOUT}) reached for this drive"
            )

        try:
            sub = self._call_spawn(instruction, engine, model, role, profile, context_mode, effort)
        except ToolError:
            raise
        except Exception as exc:  # launcher/engine errors -> clean string for the model
            raise ToolError(f"subagent failed: {exc}") from exc

        self.sub_results.append(sub)
        self.changed.update(sub.changed_files)

        result = (
            f"subagent[{sub.engine}/{sub.model}] {sub.status}: {sub.summary}\n"
            f"changed files: " + (", ".join(sub.changed_files) or "(none)")
        )
        return ToolOutcome(result=self._truncate(result))

    def _subagents(self, arguments: dict[str, Any]) -> ToolOutcome:
        """Fan out a batch of sub-tasks to nested child work items via the injected batch spawn.

        The actual launching lives in the injected ``batch_spawn`` callable (set by
        the loop in t5); here we validate inputs, enforce the per-work-item batch
        fan-out cap (MAX_SUBAGENT_FANOUT - 1 = 3 parallel children, reserving one
        slot for the merge child), call the batch spawn, and translate any
        non-ToolError exception into a clean :class:`ToolError`.

        The returned list includes N child ``SubResult`` objects (in input order)
        followed by exactly one merge child — the shape produced by
        :func:`colleague.subagents.make_batch_spawn`. All are appended to
        ``self.sub_results``; the engine cannot exceed the operator's
        COLLEAGUE_SUBAGENT_CONCURRENCY, which governs actual parallelism.
        """
        if self._batch_spawn is None:
            raise ToolError("subagents delegation is not available in this drive")

        raw_instructions = arguments.get("instructions")
        if not raw_instructions or not isinstance(raw_instructions, list):
            raise ToolError("subagents tool requires a non-empty 'instructions' list")

        # Validate + normalize each item (extracted to keep this method's cognitive
        # complexity in budget — S3776).
        items = _parse_batch_items(raw_instructions)

        # Batch-level role (#t4): applies to every child unless an item set its own.
        batch_role = arguments.get("role") or None

        # Fan-out cap: reserve one slot for the merge child — EXCEPT for a batch
        # whose children are ALL read-only roles (t12): they provably cannot
        # write, so the merge child is a structural no-op and the reservation
        # is freed (the full MAX_SUBAGENT_FANOUT is usable).
        from colleague.roles import is_read_only

        all_read_only = bool(items) and all(
            is_read_only(item.get("role") or batch_role) for item in items
        )
        _batch_cap = MAX_SUBAGENT_FANOUT if all_read_only else MAX_SUBAGENT_FANOUT - 1
        if len(items) > _batch_cap:
            reason = (
                "the read-only batch limit"
                if all_read_only
                else "one slot is reserved for the merge child"
            )
            raise ToolError(
                f"subagents fan-out limit ({_batch_cap} parallel children) exceeded; "
                f"got {len(items)} instructions ({reason})"
            )

        try:
            batch_results = self._batch_spawn(items, batch_role)
        except ToolError:
            raise
        except Exception as exc:
            raise ToolError(f"subagents failed: {exc}") from exc

        self.sub_results.extend(batch_results)
        # Merge every child's changed files into the parent tracker (#263) — the
        # single-`subagent` path already does this (see `_subagent`); without it a
        # batch child's edits are invisible to the artifact's `changed_files` AND
        # to every changed-file-scoped pre-handoff gate (lint / test-integrity /
        # affected-tests), silently under-scoping all three.
        for sub in batch_results:
            self.changed.update(sub.changed_files)

        # Build a summary line: report each child's status + the merge outcome.
        lines = []
        for sub in batch_results:
            lines.append(f"  [{sub.engine}/{sub.model}] {sub.status}: {sub.summary}")
        result = f"subagents batch ({len(items)} children):\n" + "\n".join(lines)
        return ToolOutcome(result=self._truncate(result))
