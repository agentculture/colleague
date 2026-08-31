"""Gate report dataclasses split out of :mod:`colleague.contract` (task t13,
hard-1000-line-file-limit): :class:`CapacityDecision` (fill-line),
:class:`CoherenceReport` (the coherence pre-finish gate), :class:`LintReport`
(the lint pre-finish gate), and :class:`IncompletionRecord` (#313). Each is a
small, self-contained ``to_dict``/``from_dict`` dataclass with no dependency
on any sibling contract module — pure data, re-exported from
``colleague.contract`` so every existing ``from colleague.contract import
...`` call site resolves unmodified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class CapacityDecision:
    """The one declared fill-line move colleague made for a work item (#156).

    When the running context crosses the fill-line threshold, the runtime asks the
    backend to declare ONE opinionated move and records it here: ``kind`` is one of
    ``"compact"`` (summarize its own working history to itself), ``"split"`` (fan
    out to child instances), or ``"finish-with-handoff"`` (stop with a continuation
    summary); ``reason`` is a short human note (e.g. the capacity numbers that
    tripped the threshold). ``None`` on ``TaskResult.capacity_decision`` means no
    fill-line event occurred — the key is then omitted from the artifact entirely,
    so a work item that never filled its context serializes byte-identically to today.
    """

    kind: str
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "reason": self.reason}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CapacityDecision":
        return cls(kind=str(data["kind"]), reason=str(data.get("reason", "")))


@dataclass
class CoherenceReport:
    """Report from the coherence pre-finish gate (#294, colleague#291 S3).

    ``status`` is ``"scored"`` (the gate ran; per-file records in ``files``)
    or ``"skipped"`` (the coherence CLI is not installed — ``reason`` says so).
    ``embed_url``/``embed_model`` record the measurement's **frame provenance**
    (coherence-cli#10): the embedding endpoint + model the subprocess saw —
    a meaning score is a model-relative, anchor-defined measurement, never
    universal meaning. Each ``files`` record carries ``path`` plus either the
    CLI's payload (``meaning_score``/``subdimensions``/``diagnostics`` and any
    future keys verbatim) or an ``error`` string. Advisory only: nothing here
    ever blocks the handoff or flips a run's status.
    """

    status: str = "scored"
    reason: Optional[str] = None
    embed_url: Optional[str] = None
    embed_model: Optional[str] = None
    files: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"status": self.status}
        if self.reason is not None:
            d["reason"] = self.reason
        if self.embed_url is not None:
            d["embed_url"] = self.embed_url
        if self.embed_model is not None:
            d["embed_model"] = self.embed_model
        if self.files:
            d["files"] = [dict(f) for f in self.files]
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CoherenceReport":
        return cls(
            status=str(data.get("status", "scored")),
            reason=data.get("reason"),
            embed_url=data.get("embed_url"),
            embed_model=data.get("embed_model"),
            files=[dict(f) for f in data.get("files", [])],
        )


@dataclass
class LintReport:
    """Report from the lint pre-finish gate.

    ``fixed`` lists human-readable notes of what was auto-fixed
    (e.g. "black reformatted 2 file(s)").  ``residual`` lists remaining
    violations surfaced after auto-fix (e.g. "flake8 F811 colleague/x.py:10").
    ``skipped`` lists linters configured but skipped because the binary was
    missing (e.g. "ruff: not installed").
    """

    fixed: list[str] = field(default_factory=list)
    residual: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixed": list(self.fixed),
            "residual": list(self.residual),
            "skipped": list(self.skipped),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LintReport":
        return cls(
            fixed=list(data.get("fixed", [])),
            residual=list(data.get("residual", [])),
            skipped=list(data.get("skipped", [])),
        )


@dataclass(frozen=True)
class IncompletionRecord:
    """Record of why a work item was incomplete.

    Fields
    ------
    reason:
        Human-readable explanation of why the work item did not complete.
    evidence:
        Supporting detail (e.g. last tool-call output, error text).
    recommendation:
        Suggested next step for the operator or a follow-up work item.
    """

    reason: str
    evidence: str
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "evidence": self.evidence,
            "recommendation": self.recommendation,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "IncompletionRecord":
        """Best-effort coercion: each field coerced to str, empty string on failure.

        Robust to a malformed payload (a non-dict, or an explicit ``null`` field):
        a non-dict ``data`` yields an all-empty record, and ``data.get(...) or ""``
        turns a ``None`` value into ``""`` rather than the string ``"None"``. Mirrors
        the type-guarded best-effort parsing the other optional structured fields use.
        """
        if not isinstance(data, dict):
            return cls("", "", "")
        return cls(
            reason=str(data.get("reason") or ""),
            evidence=str(data.get("evidence") or ""),
            recommendation=str(data.get("recommendation") or ""),
        )
