"""Tests for colleague.repetitionguard (spec c39/h31/h26, plan t4).

Covers the four acceptance criteria verbatim from the confirmed plan:

1. the module imports nothing from the adapter or the loop;
2. state is passed in/returned, never module-scoped — two concurrent
   detectors (one repeating stream, one healthy stream) trip independently;
3. the escalation bound is a named constant, and the trip threshold is a
   verbatim tail repeat of >=48 chars recurring >=8 times, never entropy;
4. ordinary reasoning prose with repeated identifiers / numbered lists never
   trips the detector.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from colleague import repetitionguard as rg

# ---------------------------------------------------------------------------
# Criterion 1: no imports from the adapter or the loop.
# ---------------------------------------------------------------------------


def test_module_imports_nothing_from_loop_or_engines():
    source = Path(inspect.getfile(rg)).read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_prefixes = ("colleague.loop", "colleague.engines")
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(forbidden_prefixes):
                    offenders.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith(forbidden_prefixes) or module in ("loop", "engines"):
                offenders.append(module)
    assert offenders == []


def test_module_exposes_exactly_one_detector_function():
    # The public entry point both call sites use is `check`. There must be
    # no second, competing detector function exported from this module.
    public_callables = [
        name
        for name, obj in vars(rg).items()
        if not name.startswith("_")
        and callable(obj)
        and getattr(obj, "__module__", None) == rg.__name__
    ]
    # `new_state` is a small state-constructor helper, not a second detector.
    detector_like = [n for n in public_callables if n not in ("new_state",)]
    assert detector_like == ["check"]


# ---------------------------------------------------------------------------
# Criterion 2: state passed in and returned, never module-scoped; two
# concurrent detectors don't interfere.
# ---------------------------------------------------------------------------


def test_state_has_no_module_level_mutable_globals():
    # Nothing at module scope should look like accumulating detector state.
    for name, value in vars(rg).items():
        if name.startswith("_") or name.isupper():
            continue
        if isinstance(value, (dict, list, set)):
            raise AssertionError(f"module-scoped mutable state found: {name!r}")


def test_two_concurrent_detectors_trip_only_the_repeating_stream():
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    unit = alphabet[: rg.TAIL_REPEAT_MIN_LENGTH]
    repeating_text = unit * rg.TAIL_REPEAT_MIN_COUNT
    healthy_text = "".join(
        f"Step {i}: inspect the diff, run the tests, and note what changed. " for i in range(1, 30)
    )

    state_a = rg.new_state()
    state_b = rg.new_state()

    state_a, trip_a = rg.check(repeating_text, state_a)
    state_b, trip_b = rg.check(healthy_text, state_b)

    assert trip_a is not None
    assert trip_b is None

    # The two states are genuinely independent objects.
    assert state_a is not state_b
    assert state_a["buffer"] != state_b["buffer"]


def test_streaming_chunks_accumulate_in_the_returned_state_not_a_global():
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    unit = alphabet[: rg.TAIL_REPEAT_MIN_LENGTH]
    state = rg.new_state()
    trip = None
    # Feed the repeating unit one copy at a time, as a streaming caller would.
    for _ in range(rg.TAIL_REPEAT_MIN_COUNT):
        state, trip = rg.check(unit, state)
    assert trip is not None
    # A brand-new state fed nothing should not report any trip.
    fresh_state = rg.new_state()
    assert fresh_state["buffer"] == ""


# ---------------------------------------------------------------------------
# Criterion 3: escalation bound is a named constant; trip threshold is
# exactly a >=48-char verbatim tail repeat recurring >=8 times.
# ---------------------------------------------------------------------------


def test_escalation_bound_is_a_named_module_constant():
    assert hasattr(rg, "ESCALATION_TRIP_LIMIT")
    assert isinstance(rg.ESCALATION_TRIP_LIMIT, int)
    assert rg.ESCALATION_TRIP_LIMIT >= 1


def test_trips_on_exactly_the_threshold_48_chars_times_8():
    # A non-uniform 48-char unit, so its *fundamental* period is genuinely
    # 48 (not some shorter internal repeat inside a degenerate single-char
    # string).
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    unit = alphabet[: rg.TAIL_REPEAT_MIN_LENGTH]
    assert len(unit) == rg.TAIL_REPEAT_MIN_LENGTH
    text = unit * rg.TAIL_REPEAT_MIN_COUNT
    _, trip = rg.check(text, rg.new_state())
    assert trip is not None
    assert trip["kind"] == rg.WARNING_KIND
    assert trip["period"] == rg.TAIL_REPEAT_MIN_LENGTH
    assert trip["repeats"] == rg.TAIL_REPEAT_MIN_COUNT


def test_does_not_trip_below_the_length_threshold():
    # A 47-character unit repeated many times must never trip — the unit is
    # one character short of the minimum. Uses a varying (non-uniform)
    # pattern so no accidental longer period is found either.
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    base = alphabet[: rg.TAIL_REPEAT_MIN_LENGTH - 1]
    assert len(base) == rg.TAIL_REPEAT_MIN_LENGTH - 1
    text = base * (rg.TAIL_REPEAT_MIN_COUNT * 3)
    _, trip = rg.check(text, rg.new_state())
    assert trip is None


def test_does_not_trip_below_the_count_threshold():
    # A qualifying-length, non-uniform unit repeated only 7 times (one
    # short) must not trip.
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    unit = alphabet[: rg.TAIL_REPEAT_MIN_LENGTH]
    text = unit * (rg.TAIL_REPEAT_MIN_COUNT - 1)
    _, trip = rg.check(text, rg.new_state())
    assert trip is None


def test_trips_only_on_verbatim_repeat_never_on_near_miss_entropy_style():
    # Near-identical but non-verbatim repeats (one character differs each
    # time) must never trip — this is a verbatim-only detector, not an
    # entropy/similarity heuristic.
    base = "d" * (rg.TAIL_REPEAT_MIN_LENGTH - 1)
    units = [base + str(i % 10) for i in range(rg.TAIL_REPEAT_MIN_COUNT * 2)]
    text = "".join(units)
    _, trip = rg.check(text, rg.new_state())
    assert trip is None


def test_trip_report_names_the_repeating_unit():
    unit = "REPEATED-INSIGHT-" + ("z" * 40)
    assert len(unit) >= rg.TAIL_REPEAT_MIN_LENGTH
    text = unit * rg.TAIL_REPEAT_MIN_COUNT
    _, trip = rg.check(text, rg.new_state())
    assert trip is not None
    assert "unit_preview" in trip
    assert trip["unit_preview"].startswith("REPEATED-INSIGHT-")


def test_incident_scale_repetition_trips_with_huge_margin():
    # The real incident: 271,486 characters of one insight repeated
    # verbatim. Reproduce the shape (bounded down for test speed) and
    # confirm the detector trips well inside the bounded buffer.
    unit = "This is the one insight, repeated without an answer ever landing. "
    assert len(unit) >= rg.TAIL_REPEAT_MIN_LENGTH
    text = unit * 4000  # ~272,000 characters, matching the incident's order of magnitude
    state = rg.new_state()
    trip = None
    # Feed it in streaming chunks, as the real streaming call site would.
    chunk_size = 500
    for i in range(0, len(text), chunk_size):
        state, trip = rg.check(text[i : i + chunk_size], state)
        if trip is not None:
            break
    assert trip is not None
    # The bounded buffer never grew past its cap, even over a 272k-char run.
    assert len(state["buffer"]) <= rg.MAX_BUFFER_CHARS


# ---------------------------------------------------------------------------
# Criterion 4: ordinary reasoning prose with repeated identifiers and
# numbered lists must never trip the detector.
# ---------------------------------------------------------------------------


def test_repeated_function_identifier_in_prose_does_not_trip():
    prose = " ".join(
        f"Step {i}: call `_resolve_terminal_summary()` again to check the result of "
        f"`_resolve_terminal_summary()` before continuing past `_resolve_terminal_summary()`."
        for i in range(1, 21)
    )
    _, trip = rg.check(prose, rg.new_state())
    assert trip is None


def test_numbered_list_prose_does_not_trip():
    prose = "\n".join(
        f"{i}. Review the changed module and confirm the tests still pass." for i in range(1, 30)
    )
    _, trip = rg.check(prose, rg.new_state())
    assert trip is None


def test_realistic_reasoning_paragraph_does_not_trip():
    prose = (
        "Let's think through colleague/loop.py step by step. First, loop_setup "
        "builds the initial context; loop_setup is called once per run and never "
        "again. Next, loop_turn drives one model turn; loop_turn calls loop_toolexec "
        "for every pending tool call, and loop_toolexec in turn defers to loop_tae "
        "for typed execution. After loop_turn returns, loop_accounting folds the "
        "usage into WorkStats. Finally, loop_outcomes decides whether to continue, "
        "finish, or escalate. Numbered checklist before landing this: "
        "1. confirm loop_setup ran; 2. confirm loop_turn advanced step_count; "
        "3. confirm loop_accounting recorded tokens; 4. confirm loop_outcomes chose "
        "a terminal state; 5. confirm no warnings were dropped silently."
    )
    _, trip = rg.check(prose, rg.new_state())
    assert trip is None


def test_mixed_streaming_prose_with_repeated_identifiers_does_not_trip():
    state = rg.new_state()
    trip = None
    for i in range(1, 15):
        chunk = (
            f"({i}) Re-checking `contract_coerce.coerce_task_result` once more; "
            f"`contract_coerce.coerce_task_result` stays pure and side-effect free. "
        )
        state, trip = rg.check(chunk, state)
    assert trip is None
