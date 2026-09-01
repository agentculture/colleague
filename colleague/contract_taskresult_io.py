"""``TaskResult`` serialization split out of :mod:`colleague.contract` (task
t13, hard-1000-line-file-limit): the ``to_dict``/``from_dict`` bodies (plus
the two ``to_dict`` helpers that hold each half's cognitive complexity under
the SonarCloud S3776 ceiling) as free functions, so ``TaskResult`` itself
stays a data-shape declaration and this module carries the (de)serialization
logic that references nearly every sibling record type.

``TaskResult`` (defined in ``colleague.contract``) delegates its
``to_dict``/``from_dict`` methods to :func:`task_result_to_dict` /
:func:`task_result_from_dict` below, passing ``self`` / ``(cls, data)``
respectively — this module never imports ``colleague.contract`` at module
level (only the lazy-getter functions living there are reached via a
function-local import inside :func:`task_result_from_dict`), so there is no
import cycle: ``contract.py`` imports this module once, at the top, after
which every name here is available by the time ``TaskResult``'s methods
actually run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from colleague.contract_coerce import (
    _coerce_acceptance_outcomes,
    _coerce_config_events,
    _coerce_deepthink_calls,
    _copy_agents_block,
    _copy_hire_entry,
)
from colleague.contract_records import (
    ChainView,
    FinishRecord,
    HookFiring,
    Step,
    SubResult,
    Usage,
    WorkStats,
)
from colleague.contract_reports import (
    CapacityDecision,
    CoherenceReport,
    IncompletionRecord,
    LintReport,
)
from colleague.contract_senses import SensesBlock

if TYPE_CHECKING:
    from colleague.contract import TaskResult


def task_result_to_dict(self: "TaskResult") -> dict[str, Any]:
    d: dict[str, Any] = {
        "task_id": self.task_id,
        "status": self.status,
        "summary": self.summary,
        "changed_files": list(self.changed_files),
        "steps": [s.to_dict() for s in self.steps],
        "usage": self.usage.to_dict(),
        "stats": self.stats.to_dict(),
        # ALWAYS serialized, like "stats" above — decision c30 (t1): the one
        # sanctioned unconditional artifact addition, never omit-when-empty.
        "finish_states": [f.to_dict() for f in self.finish_states],
        "artifacts_path": self.artifacts_path,
        "error": self.error,
        "branch": self.branch,
        "pr_url": self.pr_url,
        "hook_firings": [h.to_dict() for h in self.hook_firings],
        "command": self.command,
        "not_finished": self.not_finished,
        "stopped_without_finish": self.stopped_without_finish,
    }
    # destination and announcement are OMITTED (not emitted as null) when
    # None.  This preserves byte-identical output for the no-destination
    # path — a work item without a destination must serialize identically to
    # today (honesty conditions c8/h8).  This intentionally deviates from
    # the convention used by command/pr_url/etc. which always emit their
    # key even as null; only these two new keys get omit-when-None treatment.
    # warnings (t11) likewise omits-when-empty: a run with no stale-pin
    # refresh serializes byte-identical to the pre-feature shape; a run
    # WITH one carries the greppable key (h21).
    if self.warnings:
        d["warnings"] = list(self.warnings)
    if self.destination is not None:
        d["destination"] = self.destination
    if self.announcement is not None:
        d["announcement"] = self.announcement
    # capacity_decision / capacity_warning get the same omit-when-None
    # treatment (#156): a work item that never crossed the fill-line threshold
    # serializes byte-identically to today (no extra keys).
    if self.capacity_decision is not None:
        d["capacity_decision"] = self.capacity_decision.to_dict()
    if self.capacity_warning is not None:
        d["capacity_warning"] = self.capacity_warning
    # gates_deferred gets omit-when-False treatment (#341): only a chain
    # episode that actually deferred its gates carries the key.
    if self.gates_deferred:
        d["gates_deferred"] = True
    if self.lint_report is not None:
        d["lint_report"] = self.lint_report.to_dict()
    if self.coherence_report is not None:
        d["coherence_report"] = self.coherence_report.to_dict()
    if self.test_integrity_report is not None:
        d["test_integrity_report"] = self.test_integrity_report.to_dict()
    # role gets the same omit-when-None treatment (#t4): a role-less work item
    # serializes byte-identically to the pre-role artifact (no extra key).
    if self.role is not None:
        d["role"] = self.role
    d.update(_extra_fields_to_dict(self))
    # sub_results is OMITTED (not emitted as an empty list) when no sub-task
    # was delegated — mirroring the destination/announcement omit-when-None
    # pattern above so a no-subagent drive serializes byte-identically to
    # today's contract.
    if self.sub_results:
        d["sub_results"] = [s.to_dict() for s in self.sub_results]
    # hires sits BESIDE sub_results with the same omit-when-empty treatment
    # (t13, delegation-follow-ups): a hire-less run serializes
    # byte-identically to today. Entries are copied one level deep (the
    # _copy_agents_block stance) so the artifact never aliases the
    # in-memory roster entries or their assignments lists.
    if self.hires:
        d["hires"] = [_copy_hire_entry(entry) for entry in self.hires]
    return d


def _extra_fields_to_dict(self: "TaskResult") -> dict[str, Any]:
    """The omit-when-None extras added after the original destination/lint
    convention — ``mode``, ``affected_tests_report``, ``importcheck_report``,
    ``acceptance_outcomes``, ``deepthink``, ``finish_recovered``, ``memory``,
    ``media``, ``senses``.

    Split out of :func:`task_result_to_dict` purely to hold its cognitive
    complexity under the SonarCloud S3776 ceiling (15) — pure extraction, no
    behavior change; the returned partial dict is merged into
    ``task_result_to_dict``'s result in the SAME key order these were
    previously inserted in.
    """
    extra: dict[str, Any] = {}
    # mode gets the same omit-when-None treatment (spec R3 / plan t7): a
    # mode-less work item serializes byte-identically to the pre-mode artifact
    # (no extra key).
    if self.mode is not None:
        extra["mode"] = self.mode
    if self.affected_tests_report is not None:
        extra["affected_tests_report"] = self.affected_tests_report.to_dict()
    # importcheck_report gets the same omit-when-None treatment (#482/t6): a
    # run where the gate never fired (off-knob, no changed .py, aborted)
    # serializes byte-identically to the pre-t6 artifact (no extra key).
    if self.importcheck_report is not None:
        extra["importcheck_report"] = self.importcheck_report.to_dict()
    # acceptance_outcomes gets the same omit-when-None treatment (spec R6): a
    # work item with no acceptance criteria serializes byte-identically to
    # today's artifact (no extra key).
    if self.acceptance_outcomes is not None:
        extra["acceptance_outcomes"] = [dict(entry) for entry in self.acceptance_outcomes]
    # deepthink gets the same omit-when-None treatment (plan task t3): a
    # single-model work item (or one that never escalated) serializes
    # byte-identically to today's artifact (no extra key).
    if self.deepthink is not None:
        extra["deepthink"] = [c.to_dict() for c in self.deepthink]
    # finish_recovered gets the same omit-when-None treatment (#248): an
    # intact-finish work item serializes byte-identically (no extra key).
    if self.finish_recovered is not None:
        extra["finish_recovered"] = self.finish_recovered
    # memory gets the same omit-when-None treatment (spec R1 / plan t2): a
    # memory-less work item serializes byte-identically (no extra key).
    if self.memory is not None:
        extra["memory"] = dict(self.memory)
    # media gets the same omit-when-None treatment (t9): an attachment-less
    # work item serializes byte-identically (no extra key).
    if self.media is not None:
        extra["media"] = {
            "attachments": [dict(entry) for entry in self.media.get("attachments", [])]
        }
    # evaluation_ledger gets the same omit-when-None treatment (t11): a
    # ledger-less work item serializes byte-identically (no extra key).
    if self.evaluation_ledger is not None:
        extra["evaluation_ledger"] = dict(self.evaluation_ledger)
    return _extra_fields_tail(self, extra)


def _extra_fields_tail(self: "TaskResult", extra: dict[str, Any]) -> dict[str, Any]:
    """The second half of :func:`_extra_fields_to_dict` (same order), split
    purely to hold each half under the SonarCloud S3776 ceiling."""
    # agents gets the same omit-when-None treatment (#411, t13): an unarmed
    # work item serializes byte-identically (no extra key); an armed one
    # carries the versioned block with its lists copied, not aliased.
    if self.agents is not None:
        extra["agents"] = _copy_agents_block(self.agents)
    # senses gets the same omit-when-None treatment as deepthink (cortex/senses,
    # t2): a run with no senses front door serializes byte-identically to
    # today's artifact (no extra key).
    if self.senses is not None:
        extra["senses"] = self.senses.to_dict()
    # effort gets the same omit-when-None treatment (effort-v4 t5): a run
    # that resolved no seat rung serializes byte-identically (no extra key).
    if self.effort is not None:
        extra["effort"] = dict(self.effort)
    if self.sampling:
        extra["sampling"] = [dict(entry) for entry in self.sampling]
    return _extra_fields_run_record(self, extra)


def _extra_fields_run_record(self: "TaskResult", extra: dict[str, Any]) -> dict[str, Any]:
    """The run-record tail of :func:`_extra_fields_to_dict` (same order).

    Split off when the #479 ``sampling`` field pushed
    :func:`_extra_fields_tail` past the SonarCloud S3776 ceiling — the same
    purely-structural reason that split ``_extra_fields_tail`` from
    :func:`_extra_fields_to_dict`. Every field here keeps its
    omit-when-``None``/empty treatment, so the serialized key order and the
    byte-identical guarantees are unchanged.
    """
    # incompletion gets the same omit-when-None treatment: a completed
    # work item serializes byte-identically (no extra key).
    if self.incompletion is not None:
        extra["incompletion"] = self.incompletion.to_dict()
    # continued_from gets the same omit-when-None treatment (#167): a
    # non-continued run serializes byte-identically (no extra key).
    if self.continued_from is not None:
        extra["continued_from"] = self.continued_from
    # chain gets the same omit-when-None treatment (c20): a non-chained
    # run serializes byte-identically (no extra key).
    if self.chain is not None:
        extra["chain"] = self.chain.to_dict()
    # config_events/config_digest get the same omit-when-empty/None
    # treatment as sub_results/continued_from (plan task t7): a run with
    # no recorded config-event activity serializes byte-identically to
    # today's artifact (no extra keys).
    if self.config_events:
        extra["config_events"] = [e.to_dict() for e in self.config_events]
    if self.config_digest is not None:
        extra["config_digest"] = self.config_digest
    # prompt_digest sits BESIDE config_digest with the same omit-when-None
    # treatment (plan task t7): a run whose backend composed no system
    # prompt serializes byte-identically to today's artifact (no extra key).
    if self.prompt_digest is not None:
        extra["prompt_digest"] = self.prompt_digest
    # offered_tools sits BESIDE prompt_digest with the same omit-when-None
    # treatment (t2, delegation-follow-ups): a run that curated no surface
    # serializes byte-identically to the pre-field artifact.
    if self.offered_tools is not None:
        extra["offered_tools"] = list(self.offered_tools)
    # tip_sha gets the same omit-when-None treatment (plan task t5, covers c5):
    # a run whose handoff produced no commit serializes byte-identically to
    # the pre-tip_sha artifact (no extra key).
    if self.tip_sha is not None:
        extra["tip_sha"] = self.tip_sha
    # task_text gets the same omit-when-None treatment as prompt_digest (#481):
    # a disabled or pre-field run serializes byte-identically (no extra key).
    if self.task_text is not None:
        extra["task_text"] = self.task_text
    return extra


def _sampling_from_dict(data: dict[str, Any]) -> "list[dict[str, Any]] | None":
    """Read back the #479 ``sampling`` block, tolerantly.

    A separate function purely to hold :func:`task_result_from_dict` under the
    SonarCloud S3776 ceiling — this field's inline conditional was the branch
    that pushed it from 15 to 16. A missing or non-list value reads back as
    ``None`` (the omit-when-``None`` counterpart), and a non-dict entry inside
    the list is skipped rather than raising.
    """
    raw = data.get("sampling")
    if not isinstance(raw, list):
        return None
    return [dict(entry) for entry in raw if isinstance(entry, dict)]


def task_result_from_dict(cls: type, data: dict[str, Any]) -> "TaskResult":
    # Local import: the two lazy class getters live on colleague.contract
    # itself (they exist specifically to avoid importing colleague.testintegrity
    # / colleague.affectedtests at module load — see that module's docstring
    # for the full rationale). Importing colleague.contract here, inside the
    # function body, keeps this module free of a module-level import of
    # contract.py (which imports THIS module at its own top level), so there
    # is no import cycle.
    from colleague import contract as _contract

    return cls(
        task_id=str(data["task_id"]),
        status=str(data["status"]),
        summary=str(data.get("summary", "")),
        changed_files=list(data.get("changed_files", [])),
        steps=[Step.from_dict(s) for s in data.get("steps", [])],
        usage=Usage.from_dict(data.get("usage", {})),
        stats=WorkStats.from_dict(data.get("stats", {})),
        finish_states=[
            FinishRecord.from_dict(f) for f in data.get("finish_states", []) if isinstance(f, dict)
        ],
        artifacts_path=data.get("artifacts_path"),
        error=data.get("error"),
        branch=data.get("branch"),
        pr_url=data.get("pr_url"),
        hook_firings=[HookFiring.from_dict(h) for h in data.get("hook_firings", [])],
        sub_results=[SubResult.from_dict(s) for s in data.get("sub_results", [])],
        # hires (t13): tolerant of a malformed artifact — non-dict entries
        # are dropped, an absent key is the empty (omitted-when-empty) list.
        hires=[
            _copy_hire_entry(h)
            for h in (data.get("hires") if isinstance(data.get("hires"), list) else [])
            if isinstance(h, dict)
        ],
        command=data.get("command"),
        destination=data.get("destination"),
        announcement=data.get("announcement"),
        capacity_decision=(
            CapacityDecision.from_dict(data["capacity_decision"])
            if data.get("capacity_decision")
            else None
        ),
        capacity_warning=data.get("capacity_warning"),
        # gates_deferred parses strictly (#341): artifacts are external
        # inputs, so only the JSON boolean ``true`` reads True — any other
        # type/value (a "false" string, an int, a dict) degrades to False,
        # never guessed (the ChainView.from_dict degrade-to-empty stance).
        gates_deferred=data.get("gates_deferred") is True,
        lint_report=(
            LintReport.from_dict(data["lint_report"]) if data.get("lint_report") else None
        ),
        coherence_report=(
            CoherenceReport.from_dict(data["coherence_report"])
            if data.get("coherence_report")
            else None
        ),
        test_integrity_report=(
            _contract._get_test_integrity_report_class().from_dict(data["test_integrity_report"])
            if data.get("test_integrity_report")
            else None
        ),
        affected_tests_report=(
            _contract._get_affected_tests_report_class().from_dict(data["affected_tests_report"])
            if data.get("affected_tests_report")
            else None
        ),
        importcheck_report=(
            _contract._get_import_check_report_class().from_dict(data["importcheck_report"])
            if data.get("importcheck_report")
            else None
        ),
        not_finished=bool(data.get("not_finished", False)),
        stopped_without_finish=bool(data.get("stopped_without_finish", False)),
        role=data.get("role"),
        mode=data.get("mode"),
        acceptance_outcomes=_coerce_acceptance_outcomes(data.get("acceptance_outcomes")),
        deepthink=_coerce_deepthink_calls(data.get("deepthink")),
        finish_recovered=data.get("finish_recovered"),
        memory=data.get("memory"),
        media=data.get("media") if isinstance(data.get("media"), dict) else None,
        evaluation_ledger=(
            data.get("evaluation_ledger")
            if isinstance(data.get("evaluation_ledger"), dict)
            else None
        ),
        agents=(
            _copy_agents_block(data["agents"]) if isinstance(data.get("agents"), dict) else None
        ),
        senses=(
            SensesBlock.from_dict(data["senses"]) if isinstance(data.get("senses"), dict) else None
        ),
        # effort (t5): best-effort like memory/evaluation_ledger — a non-dict
        # (or absent) key degrades to None, never raises on an old artifact.
        effort=(dict(data["effort"]) if isinstance(data.get("effort"), dict) else None),
        sampling=_sampling_from_dict(data),
        incompletion=(
            IncompletionRecord.from_dict(data["incompletion"])
            if isinstance(data.get("incompletion"), dict)
            else None
        ),
        continued_from=(
            str(data["continued_from"]) if data.get("continued_from") is not None else None
        ),
        chain=(ChainView.from_dict(data["chain"]) if isinstance(data.get("chain"), dict) else None),
        config_events=_coerce_config_events(data.get("config_events")),
        config_digest=data.get("config_digest"),
        prompt_digest=data.get("prompt_digest"),
        offered_tools=(
            list(data["offered_tools"]) if isinstance(data.get("offered_tools"), list) else None
        ),
        tip_sha=data.get("tip_sha"),
        task_text=data.get("task_text"),
        warnings=list(data.get("warnings", [])),
    )
