"""_cmd.py — shared engine for the doc-test-alignment command checks (a)/(b).

Both ``readme_commands`` (check "readme") and ``claude_commands`` (check "claude")
parse fenced ``bash`` blocks for ``convertible`` / ``uv run convertible``
invocations and dispatch each one to ONE of three outcomes:

  * SAFE          — networkless, side-effect-free introspection. EXECUTED via
                    subprocess with a hardened env + short timeout; we assert the
                    exit-code CLASS (default 0, or non-zero when an adjacent
                    ``# … exit 1 …`` comment says so).
  * NETWORKED     — anything that needs a server/network or writes files
                    (``--engine vllm-openai``, ``--base-url``, ``doctor --probe``,
                    ``drive``/``session``, ``CONVERTIBLE_VLLM_E2E``, an absolute
                    ``--repo`` path, …). NEVER executed. STATICALLY validated: the
                    verb/subverb + each ``--flag`` must appear in the parsed
                    ``--help`` choice/option set.
  * UNKNOWN       — a ``convertible`` invocation we can't positively classify as
                    safe. Fail-closed → treated as NETWORKED (static-validate).

Design constraints (HARD): stdlib only, NO ``import convertible``. We MAY run the
``convertible`` CLI as a SUBPROCESS (that is not an import), but only the safe
subset above. Pure-ish functions (``classify``, ``iter_convertible_invocations``,
``parse_help_text``) are unit-testable without a live CLI.

"Matches the prose" — honest scope:
  * exit-code class (from an adjacent ``#`` comment hint), and
  * literal-substring presence when the comment/prose carries a quoted literal,
  otherwise we degrade to "well-formed + verb/flags exist, prose-match not
  asserted" (info). Each per-command message states which tier applied. No NL.
"""

from __future__ import annotations

import os
import pathlib
import re
import shlex
import subprocess  # nosec B404 - we run a fixed, hardened introspection subset
import sys
from dataclasses import dataclass, field
from typing import Iterator, List, Optional, Tuple

# Make ``from _report import make_check`` work the same way the spine does:
# the scripts/ dir (parent of checks/) must be on sys.path.
_SCRIPTS_DIR = str(pathlib.Path(__file__).resolve().parents[1])
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from _report import make_check  # type: ignore[import]  # noqa: E402

__all__ = [
    "Invocation",
    "iter_convertible_invocations",
    "classify",
    "run_safe",
    "static_validate",
    "help_choices",
    "parse_help_text",
]

# Short, hard timeout for any executed introspection command.
_EXEC_TIMEOUT_S = 20

# Env prefixes stripped from the hardened child env so an executed command never
# inherits the operator's live provider/telemetry pointing.
_STRIP_PREFIXES = ("CONVERTIBLE_", "OPENAI_", "OTEL_")

# Networked / side-effecting markers — any of these in the command line forces
# NETWORKED classification (static-validate, never execute).
_NETWORK_FLAGS = (
    "--base-url",
    "--probe",
    "--api-key",
)
_NETWORK_TOKENS = (
    "vllm-openai",  # --engine vllm-openai
    "CONVERTIBLE_VLLM_E2E",  # opt-in live e2e env
)
# Verbs that write files / push / open PRs — never executed.
_SIDE_EFFECT_VERBS = frozenset({"drive", "session"})

# The explicit SAFE allow-list: (verb, optional-subverb). ``None`` subverb means
# the bare verb (or verb + any safe sub) is allowed. We also always allow any
# ``--help`` invocation and the top-level ``overview``/``learn``/``whoami``/
# ``explain`` verbs.
_SAFE_VERBS = frozenset(
    {
        "overview",
        "learn",
        "whoami",
        "explain",
        "wheels",
        "doctor",  # but NOT with --probe (handled by _NETWORK_FLAGS)
        "telemetry",  # telemetry status / overview
        "commands",  # list / overview (NOT approve, which writes)
        "hooks",  # list / overview (NOT approve, which writes)
        "agents",  # list
        "skills",  # list
        "feedback",  # overview only (show reads drive STATE — see below)
        "cli",  # cli overview / introspection
    }
)
# Subverbs that must NOT be executed even under a safe verb because they either
# WRITE (``approve``/``record``) or READ MUTABLE DRIVE STATE whose exit code
# depends on the repo (``feedback show last`` exits 1 when no drive exists).
# These are treated as networked → static-validated, never executed.
_WRITE_SUBVERBS = frozenset({"approve", "record", "show"})


# ---------------------------------------------------------------------------
# Invocation extraction
# ---------------------------------------------------------------------------


@dataclass
class Invocation:
    """One ``convertible`` (or ``uv run convertible``) command line from a block.

    ``command`` is the full command text (continuation lines joined, leading
    ``uv run`` preserved so ``run_safe`` runs it exactly as written). ``comment``
    is the trailing ``# …`` text on the (last) line, used for exit-class hints
    and quoted-literal prose matching.
    """

    command: str
    comment: str = ""
    env_assignments: List[str] = field(default_factory=list)


def _is_convertible_command(remainder: str) -> bool:
    """True iff the PROGRAM TOKEN of *remainder* is ``convertible``.

    Strips an optional leading ``uv run`` launcher. The match is the *program*
    token, not ``convertible`` appearing as an argument (e.g.
    ``black --check convertible tests`` is NOT a convertible invocation).
    """
    toks = _tokenize(remainder)
    if len(toks) >= 2 and toks[0] == "uv" and toks[1] == "run":
        toks = toks[2:]
    return bool(toks) and toks[0] == "convertible"


def _split_trailing_comment(line: str) -> Tuple[str, str]:
    """Split a shell line into (code, comment) honoring quotes.

    A ``#`` only starts a comment when it is not inside quotes and is preceded by
    whitespace or start-of-line (so ``http://x#frag`` is not mistaken for one).
    """
    in_single = in_double = False
    for i, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            if i == 0 or line[i - 1].isspace():
                return line[:i].rstrip(), line[i + 1 :].strip()
    return line.rstrip(), ""


def _leading_env_assignments(code: str) -> Tuple[List[str], str]:
    """Peel leading ``NAME=value`` assignments off the front of a command.

    Returns (assignments, remainder). Stops at the first token that is not a
    bare ``NAME=value`` (i.e. the actual program token).
    """
    assignments: List[str] = []
    try:
        tokens = shlex.split(code)
    except ValueError:
        return [], code
    idx = 0
    for tok in tokens:
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tok):
            assignments.append(tok)
            idx += 1
        else:
            break
    remainder = " ".join(shlex.quote(t) for t in tokens[idx:])
    return assignments, remainder


def iter_convertible_invocations(block_text: str) -> Iterator[Invocation]:
    """Yield :class:`Invocation` for each ``convertible`` line in *block_text*.

    Joins ``\\``-continuation lines into a single logical command, ignores any
    line that does not contain a ``convertible`` program token, and captures the
    trailing ``#`` comment for exit-class hints.
    """
    # First, join backslash continuations into logical lines.
    raw_lines = block_text.splitlines()
    logical: List[str] = []
    buf = ""
    for ln in raw_lines:
        if buf:
            buf = buf + " " + ln.strip()
        else:
            buf = ln
        if buf.rstrip().endswith("\\"):
            buf = buf.rstrip()[:-1].rstrip()
            continue
        logical.append(buf)
        buf = ""
    if buf:
        logical.append(buf)

    for logical_line in logical:
        code, comment = _split_trailing_comment(logical_line)
        if not code.strip():
            continue
        # Strip leading env assignments to find the real program token, but keep
        # the assignments (they carry CONVERTIBLE_VLLM_E2E etc. for classify).
        env_assignments, remainder = _leading_env_assignments(code.strip())
        if not _is_convertible_command(remainder):
            continue
        yield Invocation(
            command=remainder.strip(),
            comment=comment,
            env_assignments=env_assignments,
        )


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _tokenize(command: str) -> List[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _verb_and_subverb(tokens: List[str]) -> Tuple[Optional[str], Optional[str]]:
    """Extract (verb, subverb) from a ``[uv run] convertible <verb> [<sub>] …`` line."""
    # Drop a leading ``uv run`` if present.
    toks = list(tokens)
    if len(toks) >= 2 and toks[0] == "uv" and toks[1] == "run":
        toks = toks[2:]
    if not toks or toks[0] != "convertible":
        # Defensive: the regex already confirmed convertible is present.
        if "convertible" in toks:
            toks = toks[toks.index("convertible") :]
        else:
            return None, None
    rest = toks[1:]
    positional = [t for t in rest if not t.startswith("-")]
    verb = positional[0] if positional else None
    subverb = positional[1] if len(positional) > 1 else None
    return verb, subverb


def classify(command: str, env_assignments: Optional[List[str]] = None) -> str:
    """Classify a command line as ``"safe"`` | ``"networked"`` | ``"unknown"``.

    Order of decision (NETWORKED dominates — fail-closed):
      1. Any networked flag/token/side-effecting verb → ``"networked"``.
      2. ``--help`` on any verb → ``"safe"``.
      3. A verb in the SAFE allow-list with NO write subverb → ``"safe"``.
      4. Otherwise a ``convertible`` line we can't vouch for → ``"unknown"``.

    ``classify`` itself never returns ``"unknown"`` to the *caller's dispatcher*
    as "execute" — callers treat unknown exactly like networked (static-validate).
    The distinct value exists so tests can assert the fail-closed boundary.
    """
    full = command
    if env_assignments:
        full = " ".join(env_assignments) + " " + command

    # 1. Networked / side-effecting markers anywhere in the line.
    lowered = full
    for flag in _NETWORK_FLAGS:
        # match as a standalone token (avoid e.g. --base-urls false positives)
        if re.search(rf"(?:^|\s){re.escape(flag)}(?:=|\s|$)", lowered):
            return "networked"
    for token in _NETWORK_TOKENS:
        if token in full:
            return "networked"

    tokens = _tokenize(command)
    verb, subverb = _verb_and_subverb(tokens)

    # 2. --help is always safe (introspection only), even on a side-effect verb
    #    like ``drive`` — ``convertible drive --help`` writes nothing.
    if "--help" in tokens or "-h" in tokens:
        return "safe"

    if verb in _SIDE_EFFECT_VERBS:
        return "networked"

    # An absolute --repo path (a "real" repo, not '.') means a real drive target.
    repo_val = _flag_value(tokens, "--repo")
    if repo_val and repo_val not in (".", "./") and os.path.isabs(repo_val):
        return "networked"

    # 3. Safe allow-list verb with no write subverb.
    if verb in _SAFE_VERBS:
        if subverb in _WRITE_SUBVERBS:
            return "networked"
        return "safe"

    # 4. Fail closed.
    return "unknown"


def _flag_value(tokens: List[str], flag: str) -> Optional[str]:
    """Return the value of ``--flag value`` or ``--flag=value`` if present."""
    for i, tok in enumerate(tokens):
        if tok == flag and i + 1 < len(tokens):
            return tokens[i + 1]
        if tok.startswith(flag + "="):
            return tok.split("=", 1)[1]
    return None


# ---------------------------------------------------------------------------
# Hardened subprocess execution (SAFE commands only)
# ---------------------------------------------------------------------------


def _hardened_env() -> dict:
    """A copy of the environment with CONVERTIBLE_*/OPENAI_*/OTEL_* stripped."""
    env = {k: v for k, v in os.environ.items() if not any(k.startswith(p) for p in _STRIP_PREFIXES)}
    return env


def _argv_for(command: str) -> List[str]:
    """Resolve the argv to run a command AS WRITTEN.

    A ``uv run convertible …`` line runs ``uv run convertible …``; a bare
    ``convertible …`` line runs ``convertible …``.
    """
    return shlex.split(command)


def _expected_nonzero(comment: str) -> bool:
    """Does an adjacent comment declare an UNCONDITIONAL non-zero exit?

    Heuristic: a comment mentioning ``exit <non-zero>`` (e.g. ``exit 1``).
    ``exit 0`` keeps the default (zero) expectation. A CONDITIONAL phrasing
    (``exit 1 if unhealthy``, ``exit 1 when …``, ``exit 1 on …``) does NOT set a
    non-zero expectation — the success path (e.g. a healthy ``doctor``) is the
    one we exercise, so the default zero expectation stands.
    """
    m = re.search(r"\bexit\s+(\d+)", comment)
    if not m:
        return False
    if int(m.group(1)) == 0:
        return False
    # Conditional exit statement — not an unconditional non-zero expectation.
    tail = comment[m.end() :]
    if re.search(r"\b(if|when|on|unless|otherwise)\b", tail, re.IGNORECASE):
        return False
    return True


_QUOTED_LITERAL_RE = re.compile(r"[`\"']([^`\"']{2,})[`\"']")


def _quoted_literal(comment: str) -> Optional[str]:
    """Extract a quoted literal from a comment (for substring prose-matching)."""
    m = _QUOTED_LITERAL_RE.search(comment)
    if not m:
        return None
    literal = m.group(1).strip()
    # Avoid treating flags/paths/the word 'exit N' as a prose literal.
    if literal.startswith("-") or "/" in literal or literal.lower().startswith("exit"):
        return None
    return literal


def run_safe(inv: "Invocation", repo: pathlib.Path) -> dict:
    """EXECUTE a SAFE introspection command and assert its exit-code class.

    Returns a check dict. On a launch failure (CLI not found) DOWNGRADES to an
    ``info`` "CLI not available" check — never crashes, never fails.
    """
    command = inv.command
    cid = "cmd_" + re.sub(r"[^A-Za-z0-9]+", "_", command)[:60].strip("_")
    argv = _argv_for(command)
    if not argv:
        return make_check(cid, True, "info", f"empty command: {command!r}", "")

    expect_nonzero = _expected_nonzero(inv.comment)

    try:
        proc = subprocess.run(  # nosec B603 - fixed introspection subset, hardened env
            argv,
            cwd=str(repo),
            env=_hardened_env(),
            capture_output=True,
            text=True,
            timeout=_EXEC_TIMEOUT_S,
        )
    except FileNotFoundError:
        return make_check(
            cid,
            True,
            "info",
            f"`{command}`: CLI not available in this environment; not executed",
            "",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        # Timeout or other launch trouble: downgrade, never crash/fail the suite.
        return make_check(
            cid,
            True,
            "info",
            f"`{command}`: not executed ({exc.__class__.__name__}); skipped",
            "",
        )

    rc = proc.returncode
    rc_ok = (rc != 0) if expect_nonzero else (rc == 0)
    want = "non-zero" if expect_nonzero else "0"

    if not rc_ok:
        return make_check(
            cid,
            False,
            "warning",
            f"`{command}`: expected exit {want} but got {rc} "
            f"(exit-class tier; prose hint: {inv.comment!r})",
            "Update the README/CLAUDE example or the command's behavior so they agree.",
        )

    # Optional literal substring prose-match tier.
    literal = _quoted_literal(inv.comment)
    if literal:
        combined = (proc.stdout or "") + (proc.stderr or "")
        if literal in combined:
            return make_check(
                cid,
                True,
                "info",
                f"`{command}`: executed (exit {rc}); prose literal "
                f"{literal!r} present in output (literal-substring tier)",
                "",
            )
        return make_check(
            cid,
            False,
            "warning",
            f"`{command}`: executed (exit {rc}) but prose literal "
            f"{literal!r} NOT found in output (literal-substring tier)",
            "Reconcile the surrounding prose with the command's actual output.",
        )

    # Default tier: well-formed + exit-class OK; prose-match not asserted.
    return make_check(
        cid,
        True,
        "info",
        f"`{command}`: executed (exit {rc} matches expected {want}); "
        f"well-formed, prose-match not asserted (exit-class tier)",
        "",
    )


# ---------------------------------------------------------------------------
# Help parsing + caching (static validation)
# ---------------------------------------------------------------------------


def parse_help_text(text: str) -> Tuple[set, set]:
    """Parse an argparse ``--help`` dump into (choices, flags).

    ``choices`` = the verb/subverb names inside the ``{...}`` choice set(s).
    ``flags``   = every ``--flag`` / ``-f`` token appearing in the help (usage
                  line + options section).
    """
    choices: set = set()
    for group in re.findall(r"\{([^{}]*)\}", text):
        for name in group.split(","):
            name = name.strip()
            if name:
                choices.add(name)

    flags: set = set(re.findall(r"(--[A-Za-z0-9][A-Za-z0-9_-]*)", text))
    flags |= set(re.findall(r"(?:^|\s)(-[A-Za-z])(?:\b|,)", text))
    return choices, flags


def _cli_prefix(command: str) -> List[str]:
    """The launcher prefix for help: ['uv','run','convertible'] or ['convertible']."""
    toks = _tokenize(command)
    if len(toks) >= 3 and toks[0] == "uv" and toks[1] == "run" and toks[2] == "convertible":
        return ["uv", "run", "convertible"]
    return ["convertible"]


def help_choices(
    cli_prefix: List[str],
    verb=None,
    help_cache: Optional[dict] = None,
) -> Tuple[set, set]:
    """Run ``<cli> [verb-path…] --help`` ONCE and cache the parsed (choices, flags).

    *verb* may be ``None`` (top-level help), a single verb string, or a sequence
    of verb-path elements (``["feedback", "record"]``) to introspect a subverb's
    own help. Returns ``(set(), set())`` if the CLI can't be launched (caller
    degrades to "could not introspect" rather than crashing).
    """
    if help_cache is None:
        help_cache = {}

    if verb is None:
        verb_path: Tuple[str, ...] = ()
    elif isinstance(verb, str):
        verb_path = (verb,)
    else:
        verb_path = tuple(verb)

    key = (tuple(cli_prefix), verb_path)
    if key in help_cache:
        return help_cache[key]

    argv = list(cli_prefix) + list(verb_path) + ["--help"]
    try:
        proc = subprocess.run(  # nosec B603 - fixed introspection subset, hardened env
            argv,
            env=_hardened_env(),
            capture_output=True,
            text=True,
            timeout=_EXEC_TIMEOUT_S,
        )
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        parsed = parse_help_text(out)
    except (OSError, subprocess.SubprocessError):
        parsed = (set(), set())

    help_cache[key] = parsed
    return parsed


def static_validate(command: str, repo: Optional[pathlib.Path], help_cache: dict) -> dict:
    """STATICALLY validate a NETWORKED/UNKNOWN command without executing it.

    Confirms the verb (and subverb, when present) appears in the top-level (and
    per-verb) ``--help`` choice set, and that each ``--flag`` appears in that
    subcommand's help. Emits:
      * info/passed   — "SKIPPED execution (networked); verb/flags validated"
      * warning/failed — "doc references unknown verb/flag: X"
      * info/passed   — "could not introspect CLI; not validated" when the CLI
                        can't be launched (never a false failure).
    """
    cid = "cmd_" + re.sub(r"[^A-Za-z0-9]+", "_", command)[:60].strip("_")
    cli_prefix = _cli_prefix(command)
    tokens = _tokenize(command)
    verb, subverb = _verb_and_subverb(tokens)

    if not verb:
        return make_check(
            cid,
            True,
            "info",
            f"`{command}`: no verb to validate; SKIPPED execution (networked)",
            "",
        )

    top_choices, _top_flags = help_choices(cli_prefix, None, help_cache)
    if not top_choices:
        # CLI couldn't be introspected — degrade, never false-fail.
        return make_check(
            cid,
            True,
            "info",
            f"`{command}`: SKIPPED execution (networked); CLI not available "
            "to introspect — verb/flags not validated",
            "",
        )

    if verb not in top_choices:
        return make_check(
            cid,
            False,
            "warning",
            f"`{command}`: doc references unknown verb: {verb!r} "
            f"(not in convertible --help choices)",
            "Fix the doc example or restore the verb in the CLI.",
        )

    # Pool of flags valid at the chosen verb path. Top-level flags (--json,
    # --help, --version) are valid everywhere argparse re-declares them.
    known_flags: set = set(_top_flags)
    verb_choices, verb_flags = help_choices(cli_prefix, verb, help_cache)
    known_flags |= verb_flags

    # A positional after the verb is a SUBVERB only when the verb's help
    # advertises a ``{...}`` choice set. Verbs like ``drive`` take a free-form
    # positional (a task instruction / path) — never treat that as a subverb.
    validated_subverb: Optional[str] = None
    if subverb is not None and verb_choices:
        if subverb not in verb_choices:
            return make_check(
                cid,
                False,
                "warning",
                f"`{command}`: doc references unknown subverb: "
                f"{verb!r} {subverb!r} (not in `convertible {verb} --help` choices)",
                "Fix the doc example or restore the subverb in the CLI.",
            )
        validated_subverb = subverb
        # Descend: the subverb's own help carries its specific flags
        # (e.g. ``feedback record --rating``, ``commands approve --algo``).
        _sub_choices, sub_flags = help_choices(cli_prefix, [verb, subverb], help_cache)
        known_flags |= sub_flags

    # Validate each doc --flag against the pooled flag set.
    if known_flags:
        doc_flags = [t for t in tokens if t.startswith("--")]
        path_label = (
            f"convertible {verb} {validated_subverb}"
            if validated_subverb
            else f"convertible {verb}"
        )
        for raw in doc_flags:
            flag = raw.split("=", 1)[0]
            if flag not in known_flags:
                return make_check(
                    cid,
                    False,
                    "warning",
                    f"`{command}`: doc references unknown flag: {flag!r} " f"for `{path_label}`",
                    "Fix the doc example or restore the flag in the CLI.",
                )

    return make_check(
        cid,
        True,
        "info",
        f"`{command}`: SKIPPED execution (networked); verb/flags validated "
        f"(verb {verb!r}"
        + (f", subverb {validated_subverb!r}" if validated_subverb else "")
        + " exist in --help)",
        "",
    )
