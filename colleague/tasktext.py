"""Task-text recording (#481): the brief a run actually ran with, verbatim.

``TaskResult.prompt_digest`` proves WHICH prompt arm a run used, but never
recorded the task text itself — so replaying a measurement run meant trusting
whatever the operator remembered typing. This module supplies the two small,
pure pieces the recording needs: the off-knob check and the cap/truncation
helper. Kept separate from :mod:`colleague.contract` /
:mod:`colleague.contract_taskresult_io` (both near their file-length
baseline) so the dataclass field + serialization there stay minimal.

Guards, mirroring the reasoning-sidecar conventions (:mod:`colleague.reasoninglog`):

* **Off-knob** — ``COLLEAGUE_RECORD_TASK_TEXT=0`` disables recording; per
  decision c15 recording is ON by default (only the exact string ``"0"``
  disables it).
* **Cap, never a silent cut** — a brief over :data:`MAX_CHARS` is truncated
  with a literal, discoverable marker appended (mirroring the reasoning
  sidecar's ``{"truncated": true}`` convention, adapted to a plain string
  field): ``"\\n[truncated: original N chars]"``.
"""

from __future__ import annotations

import os
from typing import Any, Mapping, Optional

#: The recording cap: 16 KiB (~16384 chars/bytes, per #481).
MAX_CHARS = 16384

#: The off-knob environment variable: the string ``"0"`` disables task-text
#: recording; anything else (or absence) leaves it enabled (decision c15:
#: recording is ON by default).
ENV_KNOB = "COLLEAGUE_RECORD_TASK_TEXT"


def recording_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    """True unless the off-knob is set to ``"0"``.

    ``env`` defaults to :data:`os.environ`; a mapping is accepted so callers
    (and tests) can pass an explicit environment, mirroring
    :func:`colleague.reasoninglog.enabled`.
    """
    if env is None:
        env = os.environ
    return env.get(ENV_KNOB) != "0"


def prepare_task_text(instruction: str) -> str:
    """Cap ``instruction`` at :data:`MAX_CHARS`, marking truncation explicitly.

    Under the cap, ``instruction`` is returned verbatim. Over the cap, the
    text is cut and a literal trailing marker names the original length —
    discoverable, never a silent cut.
    """
    if len(instruction) <= MAX_CHARS:
        return instruction
    marker = f"\n[truncated: original {len(instruction)} chars]"
    keep = max(MAX_CHARS - len(marker), 0)
    return instruction[:keep] + marker


def apply_continuation_task_text(
    result: Any,
    *,
    continued_from: Optional[str],
    continuation_task_text: Optional[str],
) -> None:
    """Override ``result.task_text`` on a continuation with the propagated
    ORIGINAL brief — never the synthesized seed (c22/h15/h3 of
    ``docs/specs/2026-09-01-small-fixes-then-effort-balance.md``).

    ``work --continue`` (and every leg that reuses it — the session's
    ``/continue``, chain episodes) builds the resumed run's ``Task.instruction``
    from a synthesized seed (preamble + continuation record + original
    request). Left alone, the loop's own task-text stamp
    (:func:`prepare_task_text` over ``task.instruction``) would record that
    SEED as the artifact's ``task_text`` — never the brief a human actually
    wrote. This is the fix: the continuation caller resolves the prior
    artifact's ``task_text`` (:func:`colleague.continuation.prior_task_text`,
    which already carries the ORIGINAL forward even across multiple
    continuations) and this function stamps it over whatever the loop set,
    called at the SAME seam :func:`colleague.contract.TaskResult.continued_from`
    is stamped.

    A no-op when *continued_from* is ``None`` (an ordinary, non-continuation
    run keeps whatever the loop already recorded) or when the off-knob
    (``COLLEAGUE_RECORD_TASK_TEXT=0``) disables recording — the loop's own
    gate already left ``result.task_text`` at ``None`` in that case, and this
    function must not un-do it.

    When it IS a continuation and recording stays enabled, ``result.task_text``
    is set to *continuation_task_text* — the propagated original brief, or
    ``None`` when the prior artifact carried none (an old pre-#481 artifact,
    or one recorded with the knob off): a seed is never a brief, so ``None``
    is the honest value, not a fallback to the seed.
    """
    if continued_from is None:
        return
    if not recording_enabled():
        return
    result.task_text = continuation_task_text
