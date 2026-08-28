"""Armed-facts sentence for the delegation surface (plan t8/t10, spec c30/c31, h19/h20).

When an associate seat is armed (``config.associate`` is not ``None``, the
``scout`` role — :mod:`colleague.associate_seats` — can act as a ``subagent``/
``subagents`` child), the acting model benefits from knowing WHAT that child
seat is, in facts, not instructions: it never tells the model to delegate,
only describes the seat's nature so the model can judge for itself whether a
child is a good fit for a given piece of work. Two pieces:

* :func:`armed_facts` — the ONE sentence itself, built fresh per *config* (no
  digits, no time units, no imperative verbs — decisions c42/c44). Empty
  string when unarmed.
* :func:`apply_armed_facts` — splices that sentence onto the ``subagent``/
  ``subagents`` tool descriptions AND (t10, post-t5 purpose-tools surface)
  the ``web_survey``/``code_survey``/``handover_to_colleague`` purpose-tool
  descriptions. Cortex's curated surface holds the purpose tools and no
  longer holds ``subagent``/``subagents`` (t5); a manual role config (or the
  raw, uncurated schema list) may still hold the latter — either way, only
  names present in the passed-in *schemas* are ever touched. Unarmed (or an
  empty sentence) returns the SAME list object unchanged — byte-identical to
  the pre-t8 schema list (the v1.64.0 fixture), never a copy.
"""

from __future__ import annotations

from typing import Any

__all__ = ["armed_facts", "apply_armed_facts"]

#: Tool names whose description gains the armed-facts sentence: the two raw
#: delegation tools (still offered to a manual role config, or the
#: uncurated full surface) plus the three purpose tools that replaced them on
#: cortex's curated surface (t5/t10).
_DELEGATION_TOOL_NAMES = frozenset(
    {"subagent", "subagents", "web_survey", "code_survey", "handover_to_colleague"}
)


def armed_facts(config: Any) -> str:
    """The armed-facts sentence for *config*, or ``''`` when unarmed.

    Unarmed is ``config.associate is None`` (or *config* itself lacking an
    ``associate`` attribute, the defensive floor). The sentence names the
    ``scout`` seat's nature in observed facts only — a much quicker seat than
    the one acting now, read-only, its reasoning switched off, with its
    findings coming back as the tool result to review before anything is
    done with them — and never instructs the model to use it.
    """
    if getattr(config, "associate", None) is None:
        return ""
    return (
        "A scout child, when used, answers on a seat that runs considerably "
        "quicker than the one acting now, cannot write to the repository, "
        "carries its reasoning switched off, and hands back its findings as "
        "a digest returned as the tool result for review before anything is "
        "done with them."
    )


def apply_armed_facts(schemas: list[dict[str, Any]], config: Any) -> list[dict[str, Any]]:
    """Splice :func:`armed_facts` onto every :data:`_DELEGATION_TOOL_NAMES` entry
    present in *schemas* (``subagent``/``subagents`` and the ``web_survey``/
    ``code_survey``/``handover_to_colleague`` purpose tools — t10).

    Unarmed (or an empty sentence) returns *schemas* itself, unchanged — the
    same list object, so a caller comparing it against the pre-t8 fixture
    sees byte-for-byte identity. Armed, returns a NEW list: every entry whose
    name is not in :data:`_DELEGATION_TOOL_NAMES` is passed through as-is
    (same dict object — nothing about it changes), and each matching entry is
    a shallow-copied dict/``function`` sub-dict with the sentence appended to
    its description. A name in :data:`_DELEGATION_TOOL_NAMES` but absent from
    *schemas* (e.g. ``subagent`` on cortex's post-t5 curated surface) is
    simply never encountered — nothing to splice onto. Nothing else on the
    schema (parameters, name, other tools) is touched.
    """
    sentence = armed_facts(config)
    if not sentence:
        return schemas
    rewritten: list[dict[str, Any]] = []
    for entry in schemas:
        function = entry.get("function") if isinstance(entry, dict) else None
        name = function.get("name") if isinstance(function, dict) else None
        if name not in _DELEGATION_TOOL_NAMES:
            rewritten.append(entry)
            continue
        new_function = dict(function)
        new_function["description"] = function["description"] + " " + sentence
        new_entry = dict(entry)
        new_entry["function"] = new_function
        rewritten.append(new_entry)
    return rewritten
