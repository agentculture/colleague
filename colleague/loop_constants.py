"""The loop's constants: exit reasons, retry caps, and the injected prompt text.

Extracted from ``colleague/loop.py`` (plan hard-1000-line-file-limit, t15).
The two tiny text helpers that read the markers defined here travel with them.
A pure move — every string is byte-identical to the pre-split loop.
"""

from __future__ import annotations

import re as _re

from colleague import media

# Bounded reactive degradation: how many times the loop may shrink the budget and
# retry a single ``complete`` call after a *context-overflow* error before giving
# up and re-raising. Bounded AND each retry strictly shrinks the budget, so the
# retry inside one turn always terminates (the outer ``max_steps`` loop is
# unchanged). 0.6 is the shrink factor applied per retry.
_MAX_OVERFLOW_RETRIES = 3
_OVERFLOW_SHRINK_FACTOR = 0.6
# A request timeout (vs an instant context-overflow 400) costs a full
# ``COLLEAGUE_TIMEOUT`` window per attempt, so it gets its own, lower retry cap:
# one shrink-and-retry — where almost all the value is (a bloated context makes
# each completion slow, and one 0.6× shrink already sheds ~40% of the tokens),
# not the overflow cap. A genuinely-unreachable server therefore wastes at most
# this many bounded retries before the partial is preserved (#154).
_MAX_TIMEOUT_RETRIES = 1

# How a work item's turn loop ended (return values of ``_work_loop``). The model may
# end a turn with no tool call instead of calling ``finish`` — usually trailing off
# mid-task — so the loop distinguishes a clean finish from that stop, and from a
# step-budget exhaustion, and ``run`` maps each to the right TaskResult flag.
_EXIT_FINISHED = "finished"  # the finish tool was called -> authoritative result
_EXIT_STOPPED = "stopped"  # ended on a no-tool-call turn without ever finishing
_EXIT_BUDGET = "budget"  # ran out of model turns (max_steps) without finishing
_EXIT_PILOT_STOP = "pilot_stop"  # a pilot wrote a cooperative `stop` to the flight control file
_EXIT_TOOL_PROTOCOL = "tool_protocol"  # consecutive unknown-tool calls -> channel is broken (#321)
_EXIT_STALLED = "stalled"  # no completed step within the step-stall bound (#400)
_EXIT_LOOP_GUARD = "loop_guard"  # an always-on loop guard tripped; pending calls dropped (t16)

# Step-stall watchdog (#400): the operator knob (seconds; 0 or negative disables) and
# the default policy — the bound never drops below the floor and scales to 6x the
# observed mean turn latency once three turns have been measured, so a rig whose
# ordinary turns are long is never cut by a fixed number. A progress bound, not a
# duration one: the clock restarts whenever a step completes.
_STALL_ENV = "COLLEAGUE_MAX_STEP_STALL"
_STALL_FLOOR_SECONDS = 5400.0

# Consecutive UnknownToolError steps tolerated before the loop stops the run as
# ``_EXIT_TOOL_PROTOCOL`` (#321). Three failed self-corrections (each fed back the
# valid-tool list) is decisive evidence the tool-call channel itself is broken —
# e.g. a serving-side --tool-call-parser / template mismatch (#320) — and every
# further turn would burn budget on calls that can never exist. Operators tune the
# cap with ``COLLEAGUE_MAX_UNKNOWN_TOOL`` (int >= 1; a missing or invalid value
# falls back here) — read per-check by ``_unknown_tool_cap``.
_UNKNOWN_TOOL_STREAK_CAP = 3
_FINISH_NUDGE = (
    "You ended your turn without calling the `finish` tool and without requesting "
    "another tool. If your work is complete, call `finish` now with your result as "
    "the summary. Otherwise, continue by calling a tool — do not reply with prose alone."
)
# Forced final synthesis (colleague#191): injected once when the loop exhausts its
# step budget (or stops) after reading context but never answering, to turn a
# wasted full-token run into a usable partial.
_SYNTHESIS_PROMPT = (
    "You are out of steps. Stop using tools and answer the original request NOW, "
    "directly, from what you have already read. Do not request any more tools — write "
    "the most complete, useful answer you can from the context gathered so far."
)
# Empty-finish synthesis (colleague#202): the model called `finish` but gave no
# usable summary — for a read-only verb (review/explore) the summary IS the
# deliverable, so a blank finish is a silent no-op (worse than an error: status
# reads ok). Force ONE no-tools turn to produce the answer from what was read,
# rather than falling back to the last planning line.
_EMPTY_FINISH_PROMPT = (
    "You called `finish` without a summary, but the summary IS your deliverable. "
    "Write your complete result NOW, directly, from what you have already read — for "
    "a review, the concrete findings and verdict you gathered. Do not request any "
    "more tools."
)
# Thin-finish synthesis (#248 mode A): the model *called* finish after a read-heavy,
# zero-write run but its summary is only a headline (the observed 130k-token run
# that returned one sentence — the completion budget went to tool-call args). The
# empty-finish guard (#202) misses it because the summary is non-empty, so the
# forced-synthesis path also fires on a THIN finish, with a prompt that names the
# failure. Thresholds are deliberately conservative: a short summary is legitimate
# for a run that wrote files ("wrote out.txt"), so the trigger requires many steps
# AND zero write/edit calls — the findings-run signature.
_THIN_FINISH_CHARS = 160
_THIN_FINISH_MIN_STEPS = 8
_THIN_FINISH_PROMPT = (
    "Your `finish` summary was only a headline, but for a read-heavy run the summary "
    "IS the deliverable. Write the complete findings NOW from what you actually read — "
    "specific and self-contained (files, behaviors, conclusions). Do not request any "
    "more tools; reply with the findings themselves as plain text."
)
# Meta-description finish (#231): the model *called* finish after a read-heavy,
# zero-write run with a summary that DESCRIBES a report ("Report covers all three
# features with file:line references…") that is nowhere in the return value — the
# observed run d0c20c8c2e54 shape. Too long for the thin guard, so a pattern match
# catches the claim-of-coverage language; the length cap keeps a real (long) report
# that merely *says* "analysis complete" out of reach, and the read-heavy/zero-write
# gate (shared with the thin guard) protects write-run summaries.
_META_FINISH_CHARS = 600
_META_FINISH_RE = _re.compile(
    r"\b(report|analysis|review|summary|findings|writeup|write-up)\b[^.]{0,80}?"
    r"\b(covers|includes|contains|provides|documents)\b"
    r"|\b(reconnaissance|analysis|review|survey|investigation|exploration)\s+complete\b"
    r"|\bsee (the )?(full )?(report|analysis|findings)\b",
    _re.IGNORECASE,
)
_META_FINISH_PROMPT = (
    "Your `finish` summary DESCRIBED a report but did not include it — the summary IS "
    "the deliverable, and a description of findings is not the findings. Write the "
    "report itself NOW from what you actually read: the concrete findings, file "
    "references, and conclusions you promised. Do not request any more tools; reply "
    "with the report as plain text."
)

# Literal finish-markup recovery (#248 mode B): a served model sometimes emits its
# finish as literal tool-call MARKUP inside message content (observed shape below,
# including a mangled ``function=finish>`` missing its ``<``) instead of a structured
# tool call. The report exists — only the transport failed — so the loop re-parses
# that shape and treats it as the finish payload instead of losing it to the
# nudge/stop path. Tolerant by design: optional ``<tool_call>`` wrapper, optional
# ``<`` on the function tag, summary = everything between ``<parameter=summary>``
# and the next ``</parameter>``. Parsed with linear ``str.find`` scans (not a
# regex) so a large adversarial content string cannot trigger super-linear
# backtracking (SonarCloud S8786).
#
#   <tool_call>
#   function=finish>
#   <parameter=summary>
#   ...the full report...
#   </parameter>
#   </function>
#   </tool_call>
_SUMMARY_OPEN = "<parameter=summary>"
_SUMMARY_CLOSE = "</parameter>"


def _parse_literal_finish(content: str) -> str | None:
    """Recover a finish summary from literal tool-call markup in message content.

    Returns the summary text, or ``None`` when the content is ordinary prose (the
    cheap substring guards keep the scan off the hot path). #248 mode B.
    """
    marker = content.find("function=finish")
    if marker == -1:
        return None
    start = content.find(_SUMMARY_OPEN, marker)
    if start == -1:
        return None
    start += len(_SUMMARY_OPEN)
    end = content.find(_SUMMARY_CLOSE, start)
    if end == -1:
        return None
    return content[start:end].strip() or None


# Markup-shaped synthesis guard (#264): the forced-synthesis turn's OWN output can
# itself be literal tool-call markup (the same served-model failure mode #248
# recovers for `finish`) — used verbatim it garbles the terminal summary (live:
# work item 55859cb1d605). The guard detects the markup shape, retries ONCE with
# an explicit plain-prose instruction (the bounded-retry precedent of
# `_final_degraded_attempt`; stays on the MAIN model like every synthesis turn),
# and otherwise salvages the prose prefix before the first marker; when nothing
# substantive survives, the summary is left unset so `_resolve_terminal_summary`
# falls through to its next rung (compaction self-summary → last-substantive).
# Markers are LINE-ANCHORED (a marker mid-sentence is prose *about* markup, not
# markup — this repo's own docs discuss these tokens) and scanned with linear
# `str.find` (no regex — SonarCloud S8786).
_TOOL_MARKUP_MARKERS = (
    "<tool_call",
    "</tool_call>",
    "<parameter=",
    "</parameter>",
    "</function>",
)
_MARKUP_SALVAGE_CHARS = 80
_MARKUP_SYNTHESIS_PROMPT = (
    "Your reply was tool-call markup, but there are no tools on this turn — markup "
    "is ignored. Reply again NOW with the answer itself as plain prose only: no "
    "<tool_call>, no <parameter=...> syntax, just the findings/summary text."
)


def _strip_tool_markup(text: str) -> str:
    """Return *text* truncated at the first line-anchored tool-markup marker.

    Returns the stripped input unchanged when no marker starts a line — the
    cheap substring scans keep this off the hot path (#264).
    """
    cut = len(text)
    for marker in _TOOL_MARKUP_MARKERS:
        start = 0
        while True:
            idx = text.find(marker, start)
            if idx == -1 or idx >= cut:
                break
            if idx == 0 or text[idx - 1] == "\n":
                cut = idx
                break
            start = idx + 1
    return text[:cut].strip()


# Pre-completion phase notices (colleague#206) — fired through the progress sink
# right BEFORE a model completion so a long single turn (above all the final
# no-tools synthesis turn) is visibly "working, not stalled" on a slow backend. A
# single completion emits no per-step progress, so for ~minutes a slow but healthy
# run is indistinguishable from a hang. Each notice is encoded as a progress event
# with an EMPTY tool name — a reserved sentinel, since a real tool always has a
# name — so a sink renders it as a standalone phase line, never a `step N:` line.
# Observability only; runtime-owned, so every backend inherits it (all-engines rule).
_PHASE_THINKING = "thinking… (waiting on the model — this can be slow on a large model)"
_PHASE_SYNTHESIZING = (
    "synthesizing the final answer from what was read — this can take a while on a "
    "slow backend; it is working, not stalled…"
)
_PHASE_COMPACTING = "compacting the conversation to free context — this can take a moment…"


# Sentinel: a media-rejection flatten happened (#c7) — retry immediately, and
# this attempt must NOT count against the reactive retry cap (see
# :func:`_attempt_completion_or_retry_plan`).
_RETRY_IMMEDIATE = object()


# Bounded eidetic-CLI wait for the two in-loop memory calls (t2): a recall/remember
# must never stall the loop the way a full COLLEAGUE_TIMEOUT completion may.
_MEMORY_TIMEOUT = 15.0


#: Per-part token-contribution floor for the delivered/dropped classification
#: (t9): half the measured per-tile estimate — any REAL image contributes at
#: least one full tile (~260 tokens, live probe 2026-07-02), so a genuinely
#: tiny image still clears the floor, while a silent drop contributes ~0.
_MEDIA_DELIVERY_FLOOR = media.IMAGE_TOKEN_ESTIMATE // 2

_MEDIA_DELIVERED = "delivered"
_MEDIA_DROPPED = "dropped"
_MEDIA_UNKNOWN = "unknown"


_POINT_MEDIA_BRIDGE = "media-bridge"

_MEDIA_BRIDGE_QUESTION = (
    "You are the multimodal half of a dual-model rig. The MAIN model "
    "driving this task is text-only and cannot see the attached media. "
    "Describe the attached media precisely and completely as it relates "
    "to the task below, so a text-only model can act on your description "
    "alone.\n\nTask:\n"
)

#: The advisory companion message injected when a task carries a senses
#: ContextPacket (t6). The operator's ORIGINAL text is already the first user
#: message (cortex reads it verbatim); this adds the senses interpretation as ONE
#: advisory turn — never a replacement (the recall-before precedent).
_CONTEXT_PACKET_ADVISORY = (
    "[senses] A senses model read the operator's request and interpreted it as "
    "follows. This is ADVISORY: the operator's original request above is "
    "authoritative and unmodified — defer to it on any disagreement.\n"
)


#: The advisory companion injected before the first cortex turn when the
#: operator's message is a *self-knowledge* question (t9 / #306). Mirrors
#: ``_CONTEXT_PACKET_ADVISORY``: cortex's first user message is ALREADY the
#: operator's verbatim question — this ADDS the live guide index + resolved
#: self-facts as ONE advisory turn so cortex answers about colleague from the
#: repo's OWN docs + runtime state instead of guessing. ADVISORY, never a
#: replacement (the recall-before precedent).
_SELF_KNOWLEDGE_ADVISORY = (
    "[self-knowledge] The operator is asking about colleague itself. Answer from "
    "colleague's OWN live documentation and resolved runtime state below — open a "
    "listed guide with read_file for detail rather than guessing. This is ADVISORY: "
    "the operator's original question above is authoritative.\n"
)

#: Cap on the number of guide-doc paths folded into the self-knowledge advisory
#: (t9). ``build_guide_index`` returns CLAUDE.md (always first) + every
#: ``docs/features/*.md`` — a set that grows unbounded as feature docs accumulate.
#: Capping keeps the ONE advisory a small, fixed fraction of the context budget
#: (each entry is one short repo-relative path line, so N paths ≈ N lines) rather
#: than letting it scale with the doc count; cortex reads any FULL doc on demand
#: via ``read_file``, so the index only needs to name enough entry points (CLAUDE.md
#: is the master index, so it is always kept — it heads the list). Overflow is
#: reported honestly as a "… and N more" line, never silently dropped.
_SELF_KNOWLEDGE_GUIDE_CAP = 40


# Bounded extra model turns granted to ONE lint fix-turn (#200). Small — the fix-turn
# only needs to read/edit a few files and finish; the per-work-item cap is
# ``ctx.lint_fix_retries`` fix-turns, each running up to this many model turns.
_LINT_FIX_STEPS = 6

_LINT_FIX_PROMPT = (
    "The pre-finish lint gate ran the repo's configured linters and auto-fixed what it "
    "could, but these violations remain and the auto-fixers cannot resolve them. Fix "
    "ONLY these, using read_file/edit_file/write_file, then call finish:\n"
)


_ACCEPTANCE_CHECK_PROMPT = (
    "Before this work item closes: for EACH acceptance criterion listed below, state "
    "whether the work you just did meets it. Respond with ONLY a JSON array of "
    'objects, one per criterion IN ORDER, shaped {"criterion": "...", "met": '
    'true|false, "evidence": "one concrete sentence"}. No prose outside the JSON, '
    "no tool calls.\n\nCriteria:\n"
)


# A re-examine turn re-enters the loop for at most this many model turns.
_TESTINTEGRITY_FIX_STEPS = 6

_TESTINTEGRITY_FIX_PROMPT = (
    "The test-integrity gate flagged a possible self-confirming test: you and your "
    "test BOTH introduced the following symbol(s), found NOWHERE ELSE in the repo. "
    "This is the signature of a test that merely mirrors the implementation's own "
    "(possibly wrong) assumption about an external API. For each symbol, verify it "
    "against the REAL API shape (the actual library/SDK attribute name or dict key) "
    "and FIX it in BOTH the implementation and the test if it is wrong, using "
    "read_file/edit_file/write_file; if it is genuinely correct, leave it. Then call "
    "finish:\n"
)


# A failed-affected-tests fix-turn re-enters the loop for at most this many model turns.
_AFFECTEDTESTS_FIX_STEPS = 8

_AFFECTEDTESTS_FIX_PROMPT = (
    "The pre-finish affected-tests gate ran the tests that (transitively) import your "
    "changed module(s) and some FAILED — these tests live in files you did not run, but "
    "your change affects them. Investigate and fix the regression in the IMPLEMENTATION "
    "(do not weaken or delete the tests), using read_file/edit_file/write_file, then "
    "call finish. Failing selection:\n"
)


_TESTINTEGRITY_REVIEWER_PROMPT = (
    "You are a DIFFERENT model reviewing another agent's work for a self-confirming "
    "test. An automated check flagged the following symbol(s) as a mirror signature — "
    "co-introduced in BOTH a test and its module-under-test and found nowhere else, "
    "which can mean the test merely mirrors the implementation's own (possibly wrong) "
    "assumption about an external API. INDEPENDENTLY determine the CORRECT real API "
    "shape for each symbol (the actual library/SDK attribute name or dict key) WITHOUT "
    "trusting the existing code, then report whether the code's usage is CORRECT or "
    "WRONG and, if wrong, what the right symbol is. This is a READ-ONLY review: do not "
    "modify files — read what you need and report your verdict via finish.\n\n"
    "Flagged symbol(s):\n"
)
