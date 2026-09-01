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
from typing import Mapping, Optional

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
