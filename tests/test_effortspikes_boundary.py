"""Boundary + drift guard for the effort-spike surface (#484, t5).

Mirrors ``tests/test_deepthink_boundary.py``'s style: ONE module-level
descriptor list drives the assertions, so a future change that quietly adds a
fourth spike point without updating the pinned list here fails immediately.

``colleague/effortspikes.py`` is the ONE seam. It builds only the table, the
opt-in flag, and the artifact record shape — no consumer exists yet (t8/t9
wire the barrier / gate-escalation / fill-line call sites). This file covers:

1. **Pinned surface** -- :data:`colleague.effortspikes.SPIKE_POINTS` and the
   keys of :data:`colleague.effortspikes.SPIKE_TABLE` equal the descriptor
   list below exactly -- a fourth point added to either without updating
   ``_PINNED_SPIKE_POINTS`` fails this test.
2. **Closed rung set** -- every non-delegated :data:`SPIKE_TABLE` value is a
   member of :data:`colleague.effort.LADDER` (the closed ladder
   :func:`colleague.effort.validate_effort` enforces) -- never an arbitrary
   string a caller might have slipped in.
3. **No model-reachable parameter** -- ``resolve_spike`` is the only function
   in the module returning a rung, and its signature takes a single ``point``
   string with no ``effort``/``rung``-shaped keyword; a grep-level sweep over
   ``colleague/tool_schemas.py`` confirms no existing tool schema mentions
   ``spike`` at all yet (so there is no tool-parameter path today), and this
   test itself pins that ``resolve_spike`` validates any resolved value
   through :func:`colleague.effort.validate_effort` -- the closed vocabulary
   -- rather than returning a caller-supplied string verbatim.
4. **Byte-identical unarmed** -- in a clean environment (no
   ``COLLEAGUE_EFFORT_SPIKES``), :func:`colleague.effortspikes.spikes_enabled`
   is ``False`` and :func:`colleague.effortspikes.resolve_spike` returns
   ``None`` for every pinned point, including the delegated fill-line point.

This file deliberately does not test t8/t9's eventual barrier/gate/fillline
consumers -- those land with their own tests when the sibling tasks wire
them.

5. **The amendment itself, pinned.** This surface AMENDS the recorded
   thinking-effort invariant in ``docs/features/thinking-effort.md`` (line
   11) and the CLAUDE.md "v0 -> v1 graduation" convention-change list (change
   (7)): effort is resolved "never per turn FROM CONTENT -- per enumerated
   point from a fixed table" (amended #484), not merely "never per turn" --
   the older wording alone would not have ruled out a table keyed on turn
   CONTENT. ``TestAmendedInvariantWording`` below asserts the module
   docstring names both halves of that phrase, so a future edit that drops
   the "FROM CONTENT" qualifier while leaving the rest of the surface intact
   still fails a test.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from colleague import effort, effortspikes
from colleague.cli._errors import CliError

_REPO_ROOT: Path = Path(__file__).resolve().parents[1]
_TOOL_SCHEMAS_PATH: Path = _REPO_ROOT / "colleague" / "tool_schemas.py"

# ---------------------------------------------------------------------------
# ONE module-level descriptor list of the three pinned spike points. Both the
# surface-membership assertions and the byte-identical-unarmed sweep below
# are driven from this single source, mirroring test_deepthink_boundary.py's
# _ESCALATION_SURFACE convention.
# ---------------------------------------------------------------------------

_PINNED_SPIKE_POINTS: tuple[str, ...] = (
    "barrier.pre_mutation",
    "gate.repeat_failure",
    "fillline.decision",
)


class TestSpikeSurfaceMembership:
    """SPIKE_POINTS / SPIKE_TABLE hold EXACTLY the pinned three points."""

    def test_spike_points_equals_pinned_list(self) -> None:
        assert effortspikes.SPIKE_POINTS == _PINNED_SPIKE_POINTS

    def test_spike_table_keys_equal_pinned_list(self) -> None:
        assert frozenset(effortspikes.SPIKE_TABLE.keys()) == frozenset(_PINNED_SPIKE_POINTS)

    def test_exactly_three_points(self) -> None:
        # Spelled out literally (not just len(_PINNED_SPIKE_POINTS)) so a
        # careless edit to the pinned list alongside the table can't silently
        # keep this test green.
        assert len(effortspikes.SPIKE_POINTS) == 3
        assert len(effortspikes.SPIKE_TABLE) == 3

    def test_a_fourth_point_would_be_caught(self) -> None:
        """Simulates the drift this test exists to catch.

        A hypothetical fourth-point table (module code adding a point
        without updating ``_PINNED_SPIKE_POINTS`` here) must NOT equal the
        pinned surface -- proving the membership assertions above are not
        vacuous.
        """
        drifted = dict(effortspikes.SPIKE_TABLE)
        drifted["forced_synthesis.decision"] = "medium"
        assert frozenset(drifted.keys()) != frozenset(_PINNED_SPIKE_POINTS)


class TestSpikeTableClosedRungSet:
    """Every SPIKE_TABLE rung is either the fillline sentinel or on the ladder."""

    @pytest.mark.parametrize("point", _PINNED_SPIKE_POINTS)
    def test_row_is_ladder_member_or_delegated_sentinel(self, point: str) -> None:
        row = effortspikes.SPIKE_TABLE[point]
        if row == effortspikes.FILLLINE_DELEGATED:
            return
        assert row in effort.LADDER

    def test_fillline_point_is_delegated_not_a_rung(self) -> None:
        assert effortspikes.SPIKE_TABLE["fillline.decision"] == effortspikes.FILLLINE_DELEGATED
        assert effortspikes.FILLLINE_DELEGATED not in effort.LADDER

    def test_fillline_defers_to_design_site_table(self) -> None:
        # The existing, already-wired contract this point defers to
        # (effort.py:105-112) -- t9's job to consume, not this module's.
        assert effort.DESIGN_SITE_TABLE["fillline.split"] == "xhigh"


class TestResolveSpikeNoModelReachableParameter:
    """resolve_spike takes only a point name; every value it can return is
    drawn from the closed ladder via validate_effort -- never a caller- or
    model-supplied string passed through verbatim."""

    def test_resolve_spike_signature_is_point_only(self) -> None:
        sig = inspect.signature(effortspikes.resolve_spike)
        params = list(sig.parameters.values())
        assert [p.name for p in params] == ["point"]
        assert params[0].annotation in (str, "str")

    def test_no_function_accepts_an_effort_or_rung_keyword(self) -> None:
        """Sweep every public function in the module for a parameter name
        that would let a caller (or a future tool schema) hand it an
        arbitrary rung instead of a point name."""
        forbidden = {"effort", "rung", "reasoning_effort"}
        for name, func in inspect.getmembers(effortspikes, inspect.isfunction):
            if name.startswith("_"):
                continue
            sig = inspect.signature(func)
            leaked = forbidden & set(sig.parameters)
            assert not leaked, f"{name} accepts a model-reachable rung param: {leaked}"

    def test_resolve_spike_validates_through_the_closed_ladder(self, monkeypatch) -> None:
        monkeypatch.setenv("COLLEAGUE_EFFORT_SPIKES", "1")
        resolved = effortspikes.resolve_spike("barrier.pre_mutation")
        assert resolved == effort.validate_effort(resolved)
        assert resolved in effort.LADDER

    def test_resolve_spike_rejects_an_out_of_ladder_env_override(self, monkeypatch) -> None:
        monkeypatch.setenv("COLLEAGUE_EFFORT_SPIKES", "1")
        monkeypatch.setenv("COLLEAGUE_EFFORT_SPIKE_BARRIER_PRE_MUTATION", "not-a-rung")
        with pytest.raises(CliError):
            effortspikes.resolve_spike("barrier.pre_mutation")

    def test_no_tool_schema_mentions_spike_today(self) -> None:
        """Grep-level assertion: since no spike-consuming tool exists yet
        (t8/t9 are the wiring tasks), tool_schemas.py names no 'spike'
        surface at all -- so there is no tool-parameter path today by which
        a model could reach a rung."""
        if not _TOOL_SCHEMAS_PATH.exists():
            pytest.skip("colleague/tool_schemas.py not present")
        source = _TOOL_SCHEMAS_PATH.read_text(encoding="utf-8")
        assert "spike" not in source.lower()
        # Parse to be sure the file is at least well-formed while we're at it.
        ast.parse(source, filename=str(_TOOL_SCHEMAS_PATH))


class TestSpikesUnarmedIsByteIdentical:
    """With the opt-in unset in a clean env, the module is fully inert."""

    def test_spikes_enabled_false_by_default(self, monkeypatch) -> None:
        monkeypatch.delenv("COLLEAGUE_EFFORT_SPIKES", raising=False)
        assert effortspikes.spikes_enabled() is False

    def test_spikes_enabled_false_on_non_one_values(self, monkeypatch) -> None:
        for value in ("0", "", "true", "yes", "on"):
            monkeypatch.setenv("COLLEAGUE_EFFORT_SPIKES", value)
            assert effortspikes.spikes_enabled() is False

    @pytest.mark.parametrize("point", _PINNED_SPIKE_POINTS)
    def test_resolve_spike_none_when_unarmed(self, monkeypatch, point: str) -> None:
        monkeypatch.delenv("COLLEAGUE_EFFORT_SPIKES", raising=False)
        assert effortspikes.resolve_spike(point) is None

    def test_resolve_spike_none_for_unknown_point_even_when_armed(self, monkeypatch) -> None:
        monkeypatch.setenv("COLLEAGUE_EFFORT_SPIKES", "1")
        assert effortspikes.resolve_spike("forced_synthesis.decision") is None

    def test_resolve_spike_none_for_delegated_fillline_point_even_when_armed(
        self, monkeypatch
    ) -> None:
        monkeypatch.setenv("COLLEAGUE_EFFORT_SPIKES", "1")
        assert effortspikes.resolve_spike("fillline.decision") is None


class TestSpikeRecordShape:
    """SpikeRecord is the (point, rung, seat) artifact shape t8/t9 emit."""

    def test_spike_record_fields(self) -> None:
        record = effortspikes.SpikeRecord(
            point="barrier.pre_mutation", rung="medium", seat="cortex"
        )
        assert record.point == "barrier.pre_mutation"
        assert record.rung == "medium"
        assert record.seat == "cortex"

    def test_spike_record_to_dict(self) -> None:
        record = effortspikes.SpikeRecord(point="gate.repeat_failure", rung="medium", seat="cortex")
        assert record.to_dict() == {
            "point": "gate.repeat_failure",
            "rung": "medium",
            "seat": "cortex",
        }


class TestAmendedInvariantWording:
    """The spike surface's own module docstring pins the amended wording.

    This is the drift guard for the amendment itself (see the module
    docstring above): a future edit to ``colleague/effortspikes.py`` that
    drops the amendment's language -- leaving only the pre-#484 "never per
    turn" without the "FROM CONTENT" qualifier that actually rules out a
    content-keyed table -- fails this test, independent of
    ``tests/test_thinking_effort_boundary.py``'s own copy of the same phrase.
    """

    def test_module_docstring_names_the_amendment(self) -> None:
        # Normalize whitespace first: the docstring wraps prose across lines,
        # so a phrase spanning a line break (e.g. "never per\nturn FROM
        # CONTENT") must still match a single-spaced needle.
        doc = " ".join((effortspikes.__doc__ or "").split())
        assert "amends the recorded thinking-effort invariant" in doc
        assert "never per turn FROM CONTENT" in doc
        assert "per enumerated point from a fixed table" in doc

    def test_module_docstring_cites_the_doc_pointer(self) -> None:
        doc = effortspikes.__doc__ or ""
        assert "docs/features/thinking-effort.md" in doc
