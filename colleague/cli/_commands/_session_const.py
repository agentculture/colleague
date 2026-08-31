"""Module-level constants for ``colleague session``.

Split out of ``colleague/cli/_commands/session.py`` (the 1000-line hard limit,
plan ``hard-1000-line-file-limit`` t17). Pure data with zero ``_Session``
coupling: panel/item ids, quit tokens, and the FIXED operator-facing notice
lines. ``session.py`` re-exports every name here, so ``session_mod.
_SPEAK_STATE_LINES`` (and the tests that import these from ``session``) still
resolve; the lane mixins import them from this module directly.
"""

from __future__ import annotations

_QUIT_TOKENS = frozenset({"q", "quit", "exit", "bye"})
_CONVERSATION_PANEL_ID = "panel.conversation"
#: CSI clear-screen + cursor-home, so the dynamic ANSI view redraws in place.
_CLEAR_HOME = "\x1b[H\x1b[2J"
#: Leading-line markers identifying a previously-rendered suggested action, so a
#: refresh replaces it in place rather than stacking duplicates in the Session panel.
_SUGGESTION_PREFIXES = ("Safest next:", "⚠ Safest next:")

#: The FIXED dispatch notice the middle-manager lane speaks when intake carries
#: no usable ack (talking-to-one arc, t6 / h2): it acknowledges receipt and the
#: hand-off to cortex ONLY — never a fabricated understanding of the request.
_ACK_DISPATCH_NOTICE = "taking your request to cortex now."

#: Streaming containment marker (ssv task t5, covers c25/h20): the ONE legible
#: line printed when a senses stream died mid-reply AFTER at least one
#: transient paint — matches the session's existing ``error:`` line style
#: (grep for ``f"error: {exc}"`` elsewhere in this module) so a live-tty
#: operator recognizes it as the same class of notice, not a new vocabulary.
_STREAM_CUT_MARKER = "error: senses stream cut mid-reply — showing partial text"

#: The Session panel's goal item id (spec R3 / plan t9 / #256) — the running
#: work item's instruction, so the operator always sees WHAT is being driven.
_GOAL_ITEM_ID = "session.goal"
#: Goal line truncation — a first-line, at-a-glance hint, not the full instruction.
_GOAL_MAX_CHARS = 80

#: Capacity panel item ids (spec R3 / plan t9 / #256).
_CAPACITY_PANEL_ID = "capacity"
_CAPACITY_BUDGET_ID = "cap.budget"
#: The disambiguated behavior+source fact (#285 t6) — distinct from the
#: execution-profile row below; together with it these replace the old single
#: conflated "mode — steps≤N · timeout…" line.
_CAPACITY_MODE_ID = "cap.mode"
_CAPACITY_PROFILE_ID = "cap.mode_profile"
_CAPACITY_SIGNAL_ID = "cap.signal"

#: The Next panel (#285 t6) — the safest-next-move promoted from a status-text
#: line buried in the Session panel's ``content_summary`` into a first-class
#: panel + item, so every render tier (flat ANSI, Markdown, TAUI mirror) shows
#: it as a distinct fact rather than prose.
_NEXT_PANEL_ID = "next"
_NEXT_ITEM_ID = "next.action"

#: The running-state panels (#285 t7). ``active_run`` replaces the idle Next
#: block while a work item runs (goal · changes-so-far · last action, live from
#: the sink's fold events); ``last_run`` is the post-run mutation ledger
#: reconciled from ``TaskResult.stats`` + handoff, shown on the restored idle
#: layout (cumulative session totals are parked as a follow-up — spec v4).
_ACTIVE_RUN_PANEL_ID = "active_run"
_LAST_RUN_PANEL_ID = "last_run"

#: Voice lane (realtime-speech arc, t5) state-line surface — the cockpit
#: ``label · state · consequence`` honesty grammar (docs/features/cockpit-ux.md).
#: ``muted`` (the operator paused the mic) MUST read differently from
#: ``degraded`` (the realtime lane fell back / a device won't open) — a
#: test-pinned distinction, so a paused mic never looks like a broken one.
_VOICE_STATE_LINES: dict[str, str] = {
    "off": "voice · off · /voice (or --voice) to talk to senses by voice",
    "live": "voice · live · mic hot — a spoken turn relays to cortex",
    "muted": "voice · muted · mic paused by /voice — /voice again resumes it",
    "degraded": "voice · degraded · realtime fell back — the typed lane still works",
}
#: The ONE c27 offer line: realtime availability NEVER starts capture; it only
#: tells the operator how to opt in.
_VOICE_OFFER_LINE = "voice · available · type /voice (or restart with --voice) to talk by voice"
#: The ONE honest notice for ``--voice`` when nothing resolved to dial.
_VOICE_UNAVAILABLE_LINE = (
    "voice · unavailable · no realtime endpoint resolved — staying on the typed lane"
)

#: Speak-only lane (task t8) state lines — the SAME label·state·consequence
#: honesty grammar ``_VOICE_STATE_LINES`` uses. Only two states: speak-only has
#: no mic to mute/degrade, so there is no ``muted``/``degraded`` distinction to
#: draw — just an honest on/off.
_SPEAK_STATE_LINES: dict[str, str] = {
    "off": "speak · off · /speak (or --speak) to hear senses replies spoken aloud",
    "on": "speak · on · senses replies play as audio — mic stays off, no realtime session",
}
#: The ONE honest notice for ``/speak`` when no tts endpoint resolved.
_SPEAK_UNAVAILABLE_LINE = "speak · unavailable · no tts endpoint resolved — staying text-only"
#: qwen-direct (t7): voice/realtime/speak are senses consumers; with no senses
#: seat resolved (the single-model default) they are dormant — ONE honest line,
#: never a dial, never a raise. Opt in with the lobes sentinel or a model id.
_VOICE_SENSES_UNARMED_LINE = (
    "voice · dormant · senses not armed — opt in with COLLEAGUE_SENSES_MODEL=lobes"
)
_SPEAK_SENSES_UNARMED_LINE = (
    "speak · dormant · senses not armed — opt in with COLLEAGUE_SENSES_MODEL=lobes"
)

#: Trailing window of raw cortex-delta text retained for senses narration
#: (ssv t6, spec assumption c24: ~500-1000 chars). The excerpt handed to a
#: boundary beat is bounded HERE at fold time (``fold_delta``'s width) and
#: again loop-side against senses' own context budget (``_window_text`` in
#: ``SensesLoopDriver._build_prompt``) — a long cortex turn never blows
#: senses' context.
_NARRATION_DELTA_CHARS = 800
