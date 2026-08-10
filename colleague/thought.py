"""Thought contract: typed, versioned, raw-input-preserving (#397, t8).

Pure stdlib, no I/O, no subprocess, no network — same discipline as
:mod:`colleague.lessons`.

This module defines the FOUNDATION contract for an experimental
thought -> action -> evaluation execution mode (issue #397). It is a
contract-only module: nothing here wires into :mod:`colleague.loop`, builds
the execution mode, or adds arming/config. That is deliberately later work
(tasks t12/t13).

The authority split this contract encodes:

* The **front** seat perceives the operator/environment and commits a typed
  :class:`Thought` — it owns intent, rationale, constraints, success
  conditions, and uncertainty. It cannot call repository tools, and a
  thought must never encode an executable tool call.
* The **worker** seat (t9) translates an accepted thought into a plan and
  actions, each action naming exactly one ``thought_id``.
* The **evaluator** seat (t10) judges whether a proposed action faithfully
  realizes the thought.

"Thought" here means a concise, INSPECTABLE decision artifact — never
hidden chain-of-thought, and it never requires exposing private reasoning
tokens.

Two cadences, one safety-load-bearing distinction (spec claim c36)
--------------------------------------------------------------------

The front runs at two distinct cadences:

1. **Presence mode** — thinking disabled; cheap conversational/environmental
   contact. Represented by :class:`PresenceUtterance`, whose ONLY field is
   free text. It structurally CANNOT carry an intent, constraints, success
   conditions, or any other action-authorizing field — extra keys refuse
   the whole payload (:func:`validate_presence`).
2. **Thought-commitment mode** — bounded thinking; emits a typed
   :class:`Thought` when a decision, replan, or ambiguity requires
   commitment.

The load-bearing rule: the worker must never infer a hidden plan from
presence-mode prose. Only a committed, validated :class:`Thought` grants
action-planning authority — see :func:`grants_action_authority`, which
returns ``True`` for exactly one type in this module and ``False`` for
every other input (including a :class:`PresenceUtterance`, a bare string,
or a malformed/refused thought payload).

Raw-input preservation (spec claim c21 / honesty h14)
------------------------------------------------------

A :class:`Thought` owns intent, not evidence. The operator's verbatim
original text is preserved through the EXISTING
:class:`colleague.contract.ContextPacket` ``.original`` seam (documented
there as sacrosanct, byte-for-byte round-tripping JSON). :class:`Thought`
deliberately carries NO field that copies or restates that raw text — only
:data:`Thought.observation_refs`, a list of opaque reference ids a reader
can resolve back to the actual evidence (packet original, tool results,
prior thoughts). This module does not import :mod:`colleague.contract` (to
stay dependency-free); ``tests/test_thought.py`` proves the seam
compatibility directly: a :class:`colleague.contract.ContextPacket` and a
:class:`Thought` coexist and both round-trip byte-identically without
either one duplicating the other's substance.

Refuse-whole validation (mirrors :mod:`colleague.lattice` / :mod:`colleague.lessons`)
----------------------------------------------------------------------------------------

Unknown/extra keys, wrong-typed fields, and a detected embedded tool call
all refuse the WHOLE thought — never stripping the offending part and
keeping the rest. A refused thought is not a partial or repaired thought;
the caller gets a :class:`ThoughtVerdict` with ``allowed=False`` and a
legible ``reason``, and **never raises**.

Versioning
----------

:data:`THOUGHT_SCHEMA_VERSION` is the current schema version. A raw payload
MAY omit ``version`` (defaults to the current version); if present it MUST
match :data:`THOUGHT_SCHEMA_VERSION` exactly, or the whole thought is
refused — so a future schema change is a deliberate, visible bump, never a
silent drift.

Left for later tasks
---------------------

* ``t9`` — :class:`Thought` is not itself an action; an ``ActionProposal``
  bound to exactly one ``thought_id`` (refusing a superseded id) is t9's
  job. ``thought_id``/``supersedes`` are kept as plain opaque strings here
  precisely so t9's ledger can key off them.
* ``t10`` — the tools-off evaluator and its closed verdict/route vocabulary.
* ``t11`` — the append-only thought/action/evaluation/outcome ledger and any
  ``TaskResult`` surface for it (``colleague/contract.py``).
* ``t12``/``t13`` — arming, config, and loop wiring.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional, Union

#: The current Thought schema version. A visible, deliberate bump point —
#: see the module docstring's "Versioning" section.
THOUGHT_SCHEMA_VERSION = 1

#: The only valid keys on a raw Thought payload. Anything else refuses the
#: WHOLE thought (unknown-key stance, mirroring colleague.lattice).
_ALLOWED_KEYS = frozenset(
    {
        "version",
        "thought_id",
        "supersedes",
        "observation_refs",
        "intent",
        "why",
        "constraints",
        "success_conditions",
        "uncertainties",
    }
)

#: Required, non-empty string keys on a raw Thought payload.
_REQUIRED_STRING_KEYS = frozenset({"thought_id", "intent", "why"})

#: Optional string-or-None keys.
_OPTIONAL_STRING_KEYS = frozenset({"supersedes"})

#: Keys whose value must be a list of non-empty strings (may be omitted,
#: defaulting to an empty list).
_LIST_OF_STRING_KEYS = frozenset(
    {"observation_refs", "constraints", "success_conditions", "uncertainties"}
)

#: The only valid key on a raw PresenceUtterance payload. Deliberately
#: disjoint from every action-authorizing Thought key above — a presence
#: payload can never carry intent/constraints/success_conditions/etc.
_PRESENCE_ALLOWED_KEYS = frozenset({"text"})

#: JSON object keys that mark an embedded, machine-parseable tool/function
#: call — mirrors the "capability/executable" instinct of
#: ``colleague.lattice._FORBIDDEN_KEYS`` but scoped to tool-call shapes.
_TOOL_CALL_MARKER_KEYS = frozenset(
    {
        "tool",
        "tool_name",
        "tool_call",
        "tool_calls",
        "function",
        "function_call",
        "arguments",
        "invoke",
    }
)

#: The harness's canonical tool names (mirrored, not imported, from
#: ``colleague/tools.py``'s ``SCHEMAS``/``FINISH``/``DEEPTHINK`` — this module
#: stays dependency-free on purpose; keep this list in sync by hand if the
#: tool surface changes).
_KNOWN_TOOL_NAMES = frozenset(
    {
        "read_file",
        "view_media",
        "write_file",
        "edit_file",
        "list_dir",
        "run_command",
        "culture",
        "devague",
        "subagent",
        "subagents",
        "check_test_integrity",
        "run_tests",
        "memory",
        "finish",
        "deepthink",
    }
)


# ---------------------------------------------------------------------------
# ThoughtVerdict — structured acceptance / refusal result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ThoughtVerdict:
    """The outcome of validating one raw thought payload.

    Attributes
    ----------
    allowed:
        ``True`` when the payload passes every check.
    reason:
        A human-readable explanation, populated ONLY when ``allowed`` is
        ``False`` (an allowed verdict carries an empty reason).
    """

    allowed: bool
    reason: str = ""


@dataclass(frozen=True)
class PresenceVerdict:
    """The outcome of validating one raw presence-utterance payload.

    Same shape/contract as :class:`ThoughtVerdict`, kept as a distinct type
    so a caller can never pass one verdict where the other is expected.
    """

    allowed: bool
    reason: str = ""


class ThoughtValidationError(Exception):
    """Raised for programmatic misuse of this module's API.

    Validation refusals return a :class:`ThoughtVerdict` /
    :class:`PresenceVerdict` with ``allowed=False``. This exception is
    reserved for internal invariants (e.g. a caller passing a non-dict where
    a dict is required to a coercion helper that cannot degrade safely).
    """


# ---------------------------------------------------------------------------
# Tool-call embedding detection
# ---------------------------------------------------------------------------


def _iter_json_objects(text: str) -> list[dict[str, Any]]:
    """Return every balanced JSON object found embedded in *text*.

    Walks *text* for each ``{`` and attempts ``json.JSONDecoder.raw_decode``
    from there; a successful parse whose result is a ``dict`` is yielded.
    This is a best-effort scan (pure stdlib, no regex) used only to detect
    an operator/model attempting to smuggle a machine-parseable tool-call
    payload inside prose — it never raises on unparsable text.
    """
    if not text:
        return []
    decoder = json.JSONDecoder()
    found: list[dict[str, Any]] = []
    idx = 0
    length = len(text)
    while idx < length:
        brace = text.find("{", idx)
        if brace == -1:
            break
        try:
            obj, end = decoder.raw_decode(text, brace)
        except ValueError:  # JSONDecodeError is a ValueError subclass
            idx = brace + 1
            continue
        if isinstance(obj, dict):
            found.append(obj)
        idx = max(end, brace + 1)
    return found


def _looks_like_tool_call(obj: dict[str, Any]) -> bool:
    """Return ``True`` if *obj* (a parsed JSON object) shapes an executable
    tool/function call: it carries a recognized tool-call marker key, or it
    names one of the harness's known tools under a ``name``/``tool`` key."""
    keys_lower = {str(k).lower() for k in obj}
    if keys_lower & _TOOL_CALL_MARKER_KEYS:
        return True
    for name_key in ("name", "tool"):
        value = obj.get(name_key)
        if isinstance(value, str) and value in _KNOWN_TOOL_NAMES:
            return True
    return False


def _find_embedded_tool_call(strings: list[str]) -> Optional[str]:
    """Scan *strings* for an embedded, machine-parseable tool call.

    Returns a legible reason string on the first hit, or ``None`` when no
    field contains one.
    """
    for text in strings:
        for obj in _iter_json_objects(text):
            if _looks_like_tool_call(obj):
                return (
                    "refused: field content embeds an executable tool call "
                    f"({obj!r}) — a thought must never encode a tool call"
                )
    return None


def _collect_string_content(data: dict[str, Any]) -> list[str]:
    """Collect every string value on a raw thought/presence payload —
    top-level string fields plus items of any list-of-string fields —
    for the tool-call-embedding scan. Non-string leaves are skipped here;
    they are caught by the separate type checks."""
    strings: list[str] = []
    for value in data.values():
        if isinstance(value, str):
            strings.append(value)
        elif isinstance(value, list):
            strings.extend(item for item in value if isinstance(item, str))
    return strings


# ---------------------------------------------------------------------------
# Thought — the committed, action-authorizing decision artifact
# ---------------------------------------------------------------------------


@dataclass
class Thought:
    """A committed, typed decision artifact (front seat, thought-commitment mode).

    Fields
    ------
    thought_id:
        An opaque, caller-assigned identifier for this thought (e.g.
        ``"thought-17"``). Kept as a plain string — not interpreted or
        generated here — so a later ledger (t11) can key off it directly.
    supersedes:
        The ``thought_id`` of the thought this one replaces, or ``None`` for
        a first commitment. Plain opaque string, same reasoning as
        ``thought_id``; tracking WHICH id is currently active/superseded is
        the later ledger's job (t9/t11), not this contract's.
    observation_refs:
        Opaque reference ids (e.g. an operator utterance id, a tool-result
        id) a reader resolves back to actual evidence — deliberately NOT a
        copy of that evidence. The raw operator text itself lives in
        :class:`colleague.contract.ContextPacket.original`, untouched by
        this module (see the module docstring).
    intent:
        What this thought commits to doing.
    why:
        The rationale.
    constraints:
        Things the realized action must NOT violate.
    success_conditions:
        Observable conditions that mean the intent was realized.
    uncertainties:
        Named gaps in what is known — an honest admission, not a hidden
        assumption.
    """

    thought_id: str
    intent: str
    why: str
    supersedes: Optional[str] = None
    observation_refs: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    success_conditions: list[str] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    version: int = THOUGHT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "version": self.version,
            "thought_id": self.thought_id,
            "intent": self.intent,
            "why": self.why,
            "observation_refs": list(self.observation_refs),
            "constraints": list(self.constraints),
            "success_conditions": list(self.success_conditions),
            "uncertainties": list(self.uncertainties),
        }
        # supersedes gets the same omit-when-None treatment as the rest of
        # the contract's optional fields (see ContextPacket.ack): a first
        # commitment (no prior thought) serializes without the key at all.
        if self.supersedes is not None:
            data["supersedes"] = self.supersedes
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Thought":
        """Coerce an already-validated thought-shaped mapping into a
        :class:`Thought`. Callers that read untrusted input should run
        :func:`validate_thought` first — this constructor does not
        re-validate; it is the artifact-readback half of the round-trip."""
        return cls(
            thought_id=str(data.get("thought_id", "")),
            intent=str(data.get("intent", "")),
            why=str(data.get("why", "")),
            supersedes=(str(data["supersedes"]) if data.get("supersedes") is not None else None),
            observation_refs=[str(x) for x in data.get("observation_refs", [])],
            constraints=[str(x) for x in data.get("constraints", [])],
            success_conditions=[str(x) for x in data.get("success_conditions", [])],
            uncertainties=[str(x) for x in data.get("uncertainties", [])],
            version=int(data.get("version", THOUGHT_SCHEMA_VERSION)),
        )


# ---------------------------------------------------------------------------
# PresenceUtterance — presence-mode output; carries NO action authority
# ---------------------------------------------------------------------------


@dataclass
class PresenceUtterance:
    """Cheap, presence-mode conversational/environmental contact output.

    The ONLY field is free text. This type structurally cannot carry an
    intent, constraints, success_conditions, or any other action-authorizing
    field — :func:`validate_presence` refuses whole on any key beyond
    ``text`` (see :data:`_PRESENCE_ALLOWED_KEYS`). See the module docstring's
    "Two cadences" section and :func:`grants_action_authority`.
    """

    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PresenceUtterance":
        return cls(text=str(data.get("text", "")))


#: The front's two possible outputs, one per cadence (see the module
#: docstring's "Two cadences" section). A presence-mode utterance is NEVER
#: a valid input to action planning — see :func:`grants_action_authority`.
FrontOutput = Union[Thought, PresenceUtterance]


def grants_action_authority(obj: object) -> bool:
    """Return ``True`` only for a committed :class:`Thought` instance.

    This is the structural guarantee the module docstring promises: a
    :class:`PresenceUtterance` (or a bare string, dict, or anything else)
    NEVER grants action-planning authority, regardless of its content — the
    worker must not infer a hidden plan from presence-mode prose (spec claim
    c36 / honesty h28). A later task (t13) wires the loop and writes the
    test that a presence utterance produces no ``ActionProposal``; this
    function is the type-level guarantee that test relies on.
    """
    return isinstance(obj, Thought)


# ---------------------------------------------------------------------------
# validate_thought — the public refuse-whole entry point
# ---------------------------------------------------------------------------


def _refuse_not_dict(data: object) -> Optional[ThoughtVerdict]:
    if isinstance(data, dict):
        return None
    return ThoughtVerdict(False, f"refused: input is not a JSON object (got {type(data).__name__})")


def _refuse_unknown_keys(data: dict[str, Any]) -> Optional[ThoughtVerdict]:
    extra = [k for k in data if k not in _ALLOWED_KEYS]
    if not extra:
        return None
    return ThoughtVerdict(
        False,
        f"refused: unknown key(s) {extra!r} on thought payload "
        f"(only {sorted(_ALLOWED_KEYS)!r} are valid)",
    )


def _refuse_missing_required(data: dict[str, Any]) -> Optional[ThoughtVerdict]:
    missing = [k for k in _REQUIRED_STRING_KEYS if k not in data]
    if not missing:
        return None
    return ThoughtVerdict(False, f"refused: missing required key(s) {missing!r}")


def _refuse_bad_string_fields(data: dict[str, Any]) -> Optional[ThoughtVerdict]:
    for key in _REQUIRED_STRING_KEYS:
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            return ThoughtVerdict(
                False,
                f"refused: {key!r} must be a non-empty (non-whitespace) string",
            )
    for key in _OPTIONAL_STRING_KEYS:
        if key in data and data[key] is not None and not isinstance(data[key], str):
            return ThoughtVerdict(False, f"refused: {key!r} must be a string or null")
    return None


def _refuse_bad_list_fields(data: dict[str, Any]) -> Optional[ThoughtVerdict]:
    for key in _LIST_OF_STRING_KEYS:
        if key not in data:
            continue
        value = data[key]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return ThoughtVerdict(False, f"refused: {key!r} must be a list of strings")
    return None


def _refuse_bad_version(data: dict[str, Any]) -> Optional[ThoughtVerdict]:
    if "version" not in data:
        return None
    version = data["version"]
    if version != THOUGHT_SCHEMA_VERSION:
        return ThoughtVerdict(
            False,
            f"refused: unsupported thought schema version {version!r} "
            f"(expected {THOUGHT_SCHEMA_VERSION})",
        )
    return None


def _refuse_embedded_tool_call(data: dict[str, Any]) -> Optional[ThoughtVerdict]:
    reason = _find_embedded_tool_call(_collect_string_content(data))
    if reason is None:
        return None
    return ThoughtVerdict(False, reason)


def validate_thought(thought: object) -> ThoughtVerdict:
    """Validate a raw thought payload against the fixed, versioned schema.

    A valid payload is a ``dict`` carrying ``thought_id``/``intent``/``why``
    (non-empty strings), optionally ``supersedes`` (string or ``None``),
    optionally ``observation_refs``/``constraints``/``success_conditions``/
    ``uncertainties`` (each a list of strings, defaulting to empty), and
    optionally ``version`` (must equal :data:`THOUGHT_SCHEMA_VERSION` if
    present). Unknown keys, missing required keys, wrong-typed fields, an
    unsupported version, or an embedded tool call all refuse the WHOLE
    thought — never stripping the offending part and keeping the rest.

    Returns a :class:`ThoughtVerdict`. **Never raises.**
    """
    for refuse in (
        _refuse_not_dict,
        _refuse_unknown_keys,
        _refuse_missing_required,
        _refuse_bad_string_fields,
        _refuse_bad_list_fields,
        _refuse_bad_version,
        _refuse_embedded_tool_call,
    ):
        verdict = refuse(thought)  # type: ignore[arg-type]
        if verdict is not None:
            return verdict
    return ThoughtVerdict(True)


# ---------------------------------------------------------------------------
# validate_presence — the presence-mode counterpart
# ---------------------------------------------------------------------------


def validate_presence(utterance: object) -> PresenceVerdict:
    """Validate a raw presence-utterance payload.

    A valid payload is a ``dict`` with EXACTLY one optional key, ``text``
    (a string; missing/absent defaults to ``""``). Any other key — in
    particular any Thought key such as ``intent``/``constraints``/
    ``success_conditions`` — refuses the WHOLE payload: presence-mode
    output can never carry an action-authorizing field (spec claim c36).

    Returns a :class:`PresenceVerdict`. **Never raises.**
    """
    if not isinstance(utterance, dict):
        return PresenceVerdict(
            False, f"refused: input is not a JSON object (got {type(utterance).__name__})"
        )
    extra = [k for k in utterance if k not in _PRESENCE_ALLOWED_KEYS]
    if extra:
        return PresenceVerdict(
            False,
            f"refused: presence-mode output carries non-presence key(s) {extra!r} "
            f"(only {sorted(_PRESENCE_ALLOWED_KEYS)!r} are valid — presence-mode "
            f"output can never carry an action-authorizing field)",
        )
    if "text" in utterance and not isinstance(utterance["text"], str):
        return PresenceVerdict(False, "refused: 'text' must be a string")
    return PresenceVerdict(True)
