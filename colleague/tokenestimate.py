"""Token estimation between exact counts — the run-start ``/tokenize`` probe.

adapted-from: qwen-code packages/core/src/services/tokenEstimation.ts
(``estimatePromptTokens``, ``CHARS_PER_TOKEN``) — re-implemented as stdlib
Python, cite-don't-import (plan adopt-from-qwen-code, task t12).

Before this module the vLLM adapter POSTed the FULL message list to the
server's ``/tokenize`` endpoint before every completion — one blocking
round-trip per turn whose only job was the context-window check, and whose
failure (a 404, a missing key) silently degraded to ``chars/4``. qwen-code
has no token-count API at all: it gates compaction on the last response's
``usage`` plus a conservative character estimate. This module does the same
while keeping ONE exact probe at run start:

* the first count a run asks for is exact — one ``/tokenize`` POST — and
  the reply's ``max_model_len`` feeds :func:`colleague.outputclamp.resolve_window`
  (precedence: lobes-advertised context → ``/tokenize`` ``max_model_len`` →
  ``COLLEAGUE_CONTEXT_BUDGET``), recorded as ``(window, window_source)``;
* every later count is an ESTIMATE anchored on the last reported
  ``usage.prompt_tokens``: a candidate list that still starts with the
  snapshot the usage was reported for costs ``prompt_tokens + chars/4`` of
  whatever was appended since; a trimmed candidate (windowing) is scaled by
  the calibrated tokens-per-char ratio, never below ``chars/4`` — the
  estimate is a conservative LOWER bound on room, so windowing and the
  fill-line may over-trigger but never skip (qwen-code's stated rule);
* ``COLLEAGUE_EXACT_TOKENS=1`` restores the per-turn exact call.

The artifact's token fields never come from here — ``usage`` stays the only
source (CLAUDE.md: tokens are exactly what ``usage`` reports, never estimated).
"""

from __future__ import annotations

import math
import os
from typing import Any, Callable, Optional

from colleague import outputclamp
from colleague.context import _content_chars, count_tokens_chars

#: The exact probe: ``(messages, reply_sink) -> count | None``; the sink is
#: filled with the server's ``max_model_len`` when the reply carries one.
ExactProbe = Callable[[list[dict[str, Any]], dict[str, Any]], Optional[int]]

#: qwen-code's ``CHARS_PER_TOKEN`` floor as tokens-per-char (chars / 4).
FLOOR_TOKENS_PER_CHAR = 0.25

ENV_EXACT_TOKENS = "COLLEAGUE_EXACT_TOKENS"


def exact_every_turn() -> bool:
    """``COLLEAGUE_EXACT_TOKENS`` truthy → count exactly on every turn."""
    return os.environ.get(ENV_EXACT_TOKENS, "").strip().lower() in {"1", "true", "yes", "on"}


def message_chars(messages: list[dict[str, Any]]) -> int:
    """The character mass :func:`count_tokens_chars` divides by four."""
    total = 0
    for m in messages:
        total += _content_chars(m.get("content"))
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            total += len(fn.get("name") or "") + len(fn.get("arguments") or "")
    return total


class TokenEstimator:
    """The counter the loop windows history with: exact once, estimated after.

    Callable as ``counter(messages) -> int`` (the ``count_tokens`` contract).
    :meth:`observe_usage` is fed by the engine after every completion with the
    message list that was sent and the ``prompt_tokens`` the server reported.
    """

    def __init__(
        self,
        exact: ExactProbe,
        *,
        budget: int,
        lobes_context: Optional[int] = None,
    ) -> None:
        self._exact = exact
        self._budget = int(budget)
        self._lobes_context = lobes_context
        self.probed = False
        self.exact_calls = 0
        self.max_model_len: Optional[int] = None
        self.window: Optional[int] = None
        self.window_source: Optional[str] = None
        self._snapshot: list[dict[str, Any]] = []
        self._snapshot_tokens = 0
        self._ratio: Optional[float] = None  # tokens per char, calibrated

    # ── the count_tokens contract ────────────────────────────────────────
    def __call__(self, messages: list[dict[str, Any]]) -> int:
        if not self.probed or exact_every_turn():
            count = self._probe(messages)
            if count is not None:
                return count
        return self.estimate(messages)

    def _probe(self, messages: list[dict[str, Any]]) -> Optional[int]:
        reply: dict[str, Any] = {}
        count = self._exact(messages, reply)
        self.exact_calls += 1
        if not self.probed:
            self.probed = True
            mml = reply.get("max_model_len")
            if isinstance(mml, int) and not isinstance(mml, bool) and mml > 0:
                self.max_model_len = mml
            self.window, self.window_source = outputclamp.resolve_window(
                self._lobes_context, self.max_model_len, self._budget
            )
        if count is not None:
            self._calibrate(messages, count)
        return count

    # ── calibration from real numbers ────────────────────────────────────
    def observe_usage(self, messages: list[dict[str, Any]], prompt_tokens: int) -> None:
        """Anchor the estimate on what the server just charged for *messages*."""
        if prompt_tokens > 0:
            self._calibrate(messages, prompt_tokens)

    def _calibrate(self, messages: list[dict[str, Any]], tokens: int) -> None:
        self._snapshot = list(messages)
        self._snapshot_tokens = int(tokens)
        chars = message_chars(messages)
        if chars > 0:
            self._ratio = tokens / chars

    # ── the estimate ─────────────────────────────────────────────────────
    def estimate(self, messages: list[dict[str, Any]]) -> int:
        """``prompt_tokens + chars/4`` past the snapshot, else ratio-scaled chars."""
        snap = self._snapshot
        if snap and len(messages) >= len(snap):
            if all(messages[i] is snap[i] for i in range(len(snap))):
                appended = messages[len(snap) :]
                return self._snapshot_tokens + count_tokens_chars(appended)
        if self._ratio is None:
            return count_tokens_chars(messages)
        chars = message_chars(messages)
        if chars == 0:
            return 0
        return max(1, math.ceil(chars * max(self._ratio, FLOOR_TOKENS_PER_CHAR)))


def observe(config: Any, messages: list[dict[str, Any]], prompt_tokens: int) -> None:
    """Engine hook: feed the run's estimator (a no-op when none is attached)."""
    est = getattr(config, "token_estimator", None)
    if isinstance(est, TokenEstimator):
        est.observe_usage(messages, prompt_tokens)


def attach(config: Any, exact: ExactProbe) -> TokenEstimator:
    """Build the run's estimator from *config* and attach it as ``token_estimator``.

    ``lobes_context`` is read from the config when a resolution rung stamped
    it (``config.lobes_context``); absent, the ``/tokenize`` ``max_model_len``
    or the context budget decides the window (see :func:`outputclamp.resolve_window`).
    """
    est = TokenEstimator(
        exact,
        budget=int(getattr(config, "context_budget_tokens", 0) or 0),
        lobes_context=getattr(config, "lobes_context", None),
    )
    config.token_estimator = est
    return est
