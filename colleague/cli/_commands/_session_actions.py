"""Session slash-palette config actions (extracted from ``session.py``).

The ``/engine`` ``/model`` ``/mode`` ``/base`` ``/pr`` ``/attach`` ``/voice``
``/speak`` ``/learn-from`` handlers plus the ``_CONFIG_ACTIONS`` verb→handler
map the session's ``_slash`` dispatcher consults. Moved out of
``colleague/cli/_commands/session.py`` under the file-length ratchet
(``tests/test_file_length_ratchet.py``: that module may only shrink or split) —
the qwen-direct arc's ``/model`` listing + ``/effort`` actions land HERE, not in
``session.py``. Every handler keeps the exact ``(s, rest) -> str`` contract:
mutate the live session, return one confirmation line, raise ``ValueError`` for
a usage error (the dispatcher renders it). ``session.py`` re-exports the names
so existing imports (``from ...session import _act_mode``) keep working.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from colleague import registry
from colleague.config import resolve_lobes_gateway_url
from colleague.lobes import fetch_served_model_ids, resolve_roles
from colleague.media import validate_attachment
from colleague.session_modes import next_mode, resolve_mode

if TYPE_CHECKING:  # pragma: no cover - typing only
    from colleague.cli._commands.session import _Session


def _act_engine(s: "_Session", rest: list[str]) -> str:
    if not rest:
        raise ValueError("usage: /engine <name>")
    name = rest[0]
    if name not in registry.names():
        raise ValueError(
            f"unknown engine '{name}'; available: {', '.join(registry.names()) or '(none)'}"
        )
    s.engine_name = name
    return f"engine → {name}"


def _act_model(s: "_Session", rest: list[str]) -> str:
    """``/model`` — the qwen-direct arc's model switch (plan task t3).

    No argument lists the gateway's served model roster (one line per id from
    :func:`lobes.fetch_served_model_ids`, Bearer key attached) plus a
    ``role → model`` line per role from :func:`lobes.resolve_roles`, marking the
    current acting model. A ``None`` roster degrades to ``roster unavailable``
    + the current model; an unarmed lobes rung degrades to ``lobes not armed``
    + the current model. Never raises (the roster/roles calls are degrade-to-
    ``None`` by contract; the gateway resolver is wrapped so even a raising
    resolver folds into the unarmed line).

    ``/model <id>`` sets ``s.config.model`` AND re-derives
    ``s.config.context_budget_tokens`` from the matching role's advertised
    context window when known — ``min(window, current)`` (never grows the budget
    past the current value; an unknown window leaves it untouched).
    """
    if not rest:
        return _model_listing(s)
    model = rest[0]
    s.config.model = model
    window = _role_context_window(s, model)
    if window is not None:
        s.config.context_budget_tokens = max(1, min(window, s.config.context_budget_tokens))
        return f"model → {model} · budget {s.config.context_budget_tokens}"
    return f"model → {model}"


def _model_listing(s: "_Session") -> str:
    """The no-arg ``/model`` roster listing (see :func:`_act_model`)."""
    current = s.config.model
    try:
        gateway = resolve_lobes_gateway_url(s.repo)
    except Exception:  # noqa: BLE001 - a raising resolver folds into unarmed
        gateway = None
    if gateway is None:
        return f"lobes not armed · model → {current}"
    roster = fetch_served_model_ids(gateway, api_key=s.config.api_key)
    if roster is None:
        return f"roster unavailable · model → {current}"
    lines = [f"  {mid}" + (" *" if mid == current else "") for mid in roster]
    roles = resolve_roles(gateway)
    if roles is not None:
        for name, role in _role_pairs(roles):
            if role is not None:
                lines.append(f"  {name} → {role.model}" + (" *" if role.model == current else ""))
    return "served models:\n" + "\n".join(lines)


def _role_pairs(roles) -> list[tuple[str, object]]:
    """Every role on a :class:`lobes.LobesRoles` as ``(name, role)`` pairs, in
    display order (cortex/senses first, then the optional seats)."""
    return [
        ("cortex", roles.cortex),
        ("senses", roles.senses),
        ("stt", roles.stt),
        ("tts", roles.tts),
        ("embedder", roles.embedder),
        ("muse", roles.muse),
        ("worker", roles.worker),
        ("associate", roles.associate),
    ]


def _role_context_window(s: "_Session", model: str) -> int | None:
    """The advertised context window of the role serving *model*, or ``None``.

    Consults the gateway only when armed; a ``None`` roles resolution (or no
    role matching *model*) yields ``None`` — the budget is left untouched.
    Never raises."""
    try:
        gateway = resolve_lobes_gateway_url(s.repo)
    except Exception:  # noqa: BLE001
        gateway = None
    if gateway is None:
        return None
    roles = resolve_roles(gateway)
    if roles is None:
        return None
    for _name, role in _role_pairs(roles):
        if role is not None and role.model == model:
            return role.context
    return None


def _act_mode(s: "_Session", rest: list[str]) -> str:
    """``/mode`` — the keyboard-free shift-tab. No arg cycles to the next mode;
    ``/mode <name>`` sets it explicitly; an unknown name raises ``ValueError``
    (surfaced by the slash dispatcher as an error + the valid-modes hint), leaving
    the mode unchanged (``resolve_mode`` raises before the assignment)."""
    # Single return (resolve_mode still raises before the assignment on a bad
    # name, so the mode is left unchanged): the prior two-branch form returned the
    # syntactically identical f-string from both arms, which Sonar reads as S3516
    # "always returns the same value".
    s.mode = next_mode(s.mode) if not rest else resolve_mode(rest[0])
    return f"mode → {s.mode}"


def _act_base(s: "_Session", rest: list[str]) -> str:
    if not rest:
        raise ValueError("usage: /base <branch>")
    s.base = rest[0]
    return f"base branch → {rest[0]}"


def _act_pr(s: "_Session", rest: list[str]) -> str:
    s.open_pr = not s.open_pr
    return f"push + PR on each work item → {'on' if s.open_pr else 'off'}"


def _act_attach(s: "_Session", rest: list[str]) -> str:
    """``/attach <path>`` validates *path* (:func:`colleague.media.validate_attachment`)
    and stages it for the NEXT work line — repeatable, staged in order, one-shot
    (task t11: the following work item's ``Task.attachments`` clears the staging
    list). ``/attach`` with no argument lists what is currently staged, or reports
    none staged — a read, not a mutation, so it never (re)raises.

    A validation failure (missing file / unknown extension) raises ``ValueError``,
    which the ``_slash`` dispatcher reports via the session's normal error style
    (``_error``) and stages nothing — mirroring every other ``_CONFIG_ACTIONS``
    usage error.
    """
    if not rest:
        if not s._staged_attachments:
            return "no attachments staged"
        listed = ", ".join(a["path"] for a in s._staged_attachments)
        return f"staged attachments ({len(s._staged_attachments)}): {listed}"
    attachment = validate_attachment(rest[0])  # raises ValueError -> caught by _slash
    s._staged_attachments.append(attachment)
    return (
        f"attached: {attachment['path']} ({attachment['media_type']}) "
        "— staged for the next work line"
    )


def _act_voice(s: "_Session", rest: list[str]) -> str:
    """``/voice`` — the c27 opt-in toggle for the realtime voice lane.

    Delegates to :meth:`_Session._toggle_voice`: opt in + start capture, or
    toggle a running lane live⇄muted. Realtime unavailable is one honest line,
    no dial — never raises (so the slash dispatcher renders it as a plain
    confirmation, like every other config action)."""
    return s._toggle_voice()


def _act_speak(s: "_Session", rest: list[str]) -> str:
    """``/speak`` — the speak-only opt-in toggle (task t8): TTS-speaks each
    senses REPLY while the operator only types.

    Delegates to :meth:`_Session._toggle_speak`. Independent of ``/voice`` —
    never arms the mic or stt (c7 stands untouched). No tts resolved is one
    honest line, no dial — never raises."""
    return s._toggle_speak()


def _act_learn_from(s: "_Session", rest: list[str]) -> str:
    """Learn skills from a peer in-session via the real ``learn-from`` verb.

    Always runs the deterministic stage-1 copy (``--copy-only``) so an
    interactive invocation never blocks on a model call; the full LLM adapt pass
    is left to ``colleague learn-from`` / a work item. Source defaults to
    ``claude``; extra tokens (skill names, ``--dry-run``) pass straight through.
    """
    rest = list(rest)
    if not rest or rest[0].startswith("-"):
        rest = ["claude", *rest]
    return s._run_cli("learn-from", *rest, "--repo", str(s.repo), "--copy-only")


# Live config actions: map a verb to a mutating handler returning a confirmation.
_CONFIG_ACTIONS: dict[str, Callable[["_Session", list[str]], str]] = {
    "engine": _act_engine,
    "model": _act_model,
    "mode": _act_mode,
    "base": _act_base,
    "pr": _act_pr,
    "attach": _act_attach,
    "voice": _act_voice,
    "speak": _act_speak,
    "learn-from": _act_learn_from,
}
