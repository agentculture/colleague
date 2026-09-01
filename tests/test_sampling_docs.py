"""Doc pins for the per-model sampling feature doc (#479 t11).

Covers spec targets c23, h14, c25, h3, c27, h5, c58, h48.

Modelled on ``tests/test_thinking_effort_docs.py``: the shipped values live in
``colleague/`` and are RENDERED once in ``docs/features/sampling.md``. These
tests fail when a shipped value and its documented value diverge — a doc that
can silently drift from the code is exactly the failure mode this arc exists to
prevent, and #479's own incident (a decoding default nobody chose) is what that
drift costs.

Nothing here talks to a rig: the four live probes are RECORDED evidence, and
this file only pins that they are recorded with their limits, never re-runs
them (probe 2 is precisely why a status code proves nothing).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from colleague import repetitionguard, sampling, samplingwire
from colleague.engines import vllm_payload

REPO_ROOT = Path(__file__).resolve().parents[1]
FEATURE_DOC = REPO_ROOT / "docs" / "features" / "sampling.md"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
THINKING_EFFORT_MD = REPO_ROOT / "docs" / "features" / "thinking-effort.md"
MODEL_SELECTION_MD = REPO_ROOT / "docs" / "features" / "model-selection.md"
CONFIG_RESOLUTION_MD = REPO_ROOT / "docs" / "features" / "config-resolution.md"

#: The rung used whenever a test needs a live (thinking-half) ladder value.
_ARMED_RUNG = "low"
_OFF_RUNG = "off"


def _read(path: Path) -> str:
    assert path.exists(), f"missing doc: {path}"
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# markdown table parsing
# ---------------------------------------------------------------------------


def _tables(text: str) -> list[list[list[str]]]:
    """Every markdown pipe-table in *text* as a list of rows of cells.

    The separator row (``|---|---|``) is dropped; the header row is kept as
    row 0. Cells are stripped of whitespace but NOT of backticks — a doc that
    writes a bare ``1.0`` where the table style is ```.0``` should be
    visible, not silently normalised away.
    """
    tables: list[list[list[str]]] = []
    current: list[list[str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if all(set(c) <= set("-: ") and c for c in cells):
                continue  # separator row
            current.append(cells)
            continue
        if current:
            tables.append(current)
            current = []
    if current:
        tables.append(current)
    return tables


def _table_with_header(text: str, header: tuple[str, ...]) -> list[list[str]]:
    """The one table whose header row equals *header*; fails if absent/ambiguous."""
    matches = [t for t in _tables(text) if tuple(t[0]) == header]
    assert matches, f"no table with header {header} in the feature doc"
    assert len(matches) == 1 or header == (
        "key",
        "thinking",
        "non-thinking",
    ), f"ambiguous: {len(matches)} tables with header {header}"
    return matches[0]


def _halves_table(text: str, index: int) -> dict[str, dict[str, str]]:
    """The *index*-th ``| key | thinking | non-thinking |`` table as key -> half -> cell."""
    matches = [t for t in _tables(text) if tuple(t[0]) == ("key", "thinking", "non-thinking")]
    assert len(matches) >= index + 1, "the feature doc is missing a key/thinking/non-thinking table"
    return {
        row[0].strip("`"): {"thinking": row[1], "non_thinking": row[2]}
        for row in matches[index][1:]
    }


def _cell(value: object) -> str:
    """How a shipped value is rendered in a doc table cell."""
    return f"`{value!r}`"


_UNSET_CELL = "—"


# ---------------------------------------------------------------------------
# c23/h14 — the builtin table renders value-for-value
# ---------------------------------------------------------------------------


def _builtin_payloads() -> dict[str, dict[str, object]]:
    return {
        row.half: sampling.sampling_payload(row.profile) for row in sampling.BUILTIN_SAMPLING_ROWS
    }


def _builtin_wires() -> dict[str, dict[str, object]]:
    return {
        row.half: samplingwire.wire_fragment(row.profile) for row in sampling.BUILTIN_SAMPLING_ROWS
    }


def _row_cases(payloads: dict[str, dict[str, object]]) -> list[tuple[str, str, str]]:
    """(key, half, expected cell) for every recognised key x half."""
    cases: list[tuple[str, str, str]] = []
    for key in samplingwire.SAMPLING_COERCERS:
        for half in (sampling.THINKING, sampling.NON_THINKING):
            values = payloads.get(half, {})
            expected = _cell(values[key]) if key in values else _UNSET_CELL
            cases.append((key, half, expected))
    return cases


@pytest.mark.parametrize("key,half,expected", _row_cases(_builtin_payloads()))
def test_feature_doc_renders_the_builtin_table(key: str, half: str, expected: str) -> None:
    """Table 0 (the card) matches BUILTIN_SAMPLING_ROWS cell for cell."""
    table = _halves_table(_read(FEATURE_DOC), 0)
    assert key in table, f"the builtin table does not document the key {key!r}"
    assert table[key][half] == expected, (
        f"builtin table drift: doc says {key}/{half} = {table[key][half]}, "
        f"the shipped row says {expected}"
    )


@pytest.mark.parametrize("key,half,expected", _row_cases(_builtin_wires()))
def test_feature_doc_renders_the_wire_table(key: str, half: str, expected: str) -> None:
    """Table 1 (the wire) matches samplingwire.wire_fragment cell for cell."""
    table = _halves_table(_read(FEATURE_DOC), 1)
    assert key in table, f"the wire table does not document the key {key!r}"
    assert table[key][half] == expected, (
        f"wire table drift: doc says {key}/{half} = {table[key][half]}, "
        f"the filtered wire says {expected}"
    )


def test_feature_doc_documents_exactly_the_recognised_keys() -> None:
    """The doc's key column is the recognised key set — no more, no fewer."""
    documented = set(_halves_table(_read(FEATURE_DOC), 0))
    assert documented == set(samplingwire.SAMPLING_COERCERS)
    assert documented == {f.name for f in sampling.SamplingProfile.__dataclass_fields__.values()}


def test_feature_doc_renders_the_server_default_table() -> None:
    header = ("key", "value treated as the server default")
    rows = _table_with_header(_read(FEATURE_DOC), header)[1:]
    documented = {row[0].strip("`"): row[1] for row in rows}
    expected = {k: _cell(v) for k, v in samplingwire.SERVER_DEFAULT_SAMPLING.items()}
    assert documented == expected, "the server-default table drifted from SERVER_DEFAULT_SAMPLING"
    # The two deliberate absences are stated, not left to inference.
    text = _read(FEATURE_DOC)
    assert "`temperature` is deliberately **absent**" in text
    assert "`top_k` is absent too" in text


# ---------------------------------------------------------------------------
# c23/h14 — the match rule's worked examples actually normalise as claimed
# ---------------------------------------------------------------------------


def _match_rows() -> list[tuple[str, str, str]]:
    header = ("served id", "normalises to", "matches a builtin row")
    rows = _table_with_header(_read(FEATURE_DOC), header)[1:]
    return [(row[0], row[1], row[2]) for row in rows]


@pytest.mark.parametrize("served,normalised,matches", _match_rows())
def test_match_rule_examples_hold(served: str, normalised: str, matches: str) -> None:
    served_id = served.strip("`")
    assert sampling.normalize_model_id(served_id) == normalised.strip(
        "`"
    ), f"the doc claims {served_id!r} normalises to {normalised}"
    resolved = sampling.resolve_sampling(served_id, role=None, rung=_ARMED_RUNG)
    assert matches == (
        "yes" if resolved is not None else "no"
    ), f"the doc claims {served_id!r} matches={matches}"


def test_live_served_id_still_matches() -> None:
    """A rig rename cannot silently disarm the profile (the doc's own claim)."""
    for rung, half in ((_ARMED_RUNG, sampling.THINKING), (_OFF_RUNG, sampling.NON_THINKING)):
        profile = sampling.resolve_sampling("unsloth/Qwen3.8-27B-NVFP4", role=None, rung=rung)
        assert profile is not None
        assert sampling.half_for_rung(rung) == half


def test_unmatched_model_sends_nothing_and_the_doc_reconciles_the_any_model_row() -> None:
    assert sampling.resolve_sampling("Qwen/Qwen3.8-4B", role=None, rung=_ARMED_RUNG) is None
    # The absence that makes that true.
    assert all(row.models for row in sampling.BUILTIN_SAMPLING_ROWS)
    text = _read(FEATURE_DOC)
    assert "no `models=()` any-model row" in text
    assert "would override that guarantee" in text


# ---------------------------------------------------------------------------
# c23/h14 — models.json: half labels, knobs, guard constants
# ---------------------------------------------------------------------------


def test_feature_doc_renders_every_accepted_half_label() -> None:
    rows = _table_with_header(_read(FEATURE_DOC), ("label", "half"))[1:]
    documented = {row[0].strip("`") for row in rows}
    assert documented == set(
        vllm_payload._HALF_LABELS
    ), "the half-label table drifted from the consumer's _HALF_LABELS"


def test_feature_doc_renders_the_kill_switch_values() -> None:
    rows = _table_with_header(_read(FEATURE_DOC), ("variable", "status", "effect"))[1:]
    by_variable = {row[0].strip("`"): row for row in rows}
    assert vllm_payload._SAMPLING_ENV_KEY in by_variable, "the kill switch's env name drifted"
    effect = by_variable[vllm_payload._SAMPLING_ENV_KEY][2]
    documented = set(re.findall(r"`([^`]+)`", effect.split("—")[0]))
    assert documented == set(
        vllm_payload._SAMPLING_DISABLING_VALUES
    ), "the documented disabling values drifted from _SAMPLING_DISABLING_VALUES"
    # Both deprecated variables are named with their status.
    assert "COLLEAGUE_TEMPERATURE" in by_variable
    assert by_variable["COLLEAGUE_TEMPERATURE"][1].startswith("deprecated")
    assert "CONVERTIBLE_TEMPERATURE" in by_variable
    assert by_variable["CONVERTIBLE_TEMPERATURE"][1] == "removed"


def _guard_constants() -> dict[str, int]:
    return {
        name: value
        for name, value in vars(repetitionguard).items()
        if name.isupper() and isinstance(value, int) and not isinstance(value, bool)
    }


def test_feature_doc_renders_every_guard_constant() -> None:
    rows = _table_with_header(_read(FEATURE_DOC), ("constant", "value"))[1:]
    documented = {row[0].strip("`"): row[1].strip("`") for row in rows}
    expected = {name: str(value) for name, value in _guard_constants().items()}
    assert documented == expected, "the guard-constant table drifted from colleague/repetitionguard"


# ---------------------------------------------------------------------------
# c23/h14 — the documented false positive is REPRODUCED, not asserted
# ---------------------------------------------------------------------------


def test_documented_false_positive_reproduces() -> None:
    """The doc's 84-character-line-x8 false positive is real, and x7 is not."""
    line = "Now let me check the next file to see whether the helper is still referenced there.\n"
    assert len(line) == 84
    text = _read(FEATURE_DOC)
    assert "84-character boilerplate narration line" in text
    assert "8 times back-to-back" in text

    _state, trip = repetitionguard.check(line * 8, repetitionguard.new_state())
    assert trip is not None, "the documented false positive no longer trips"
    _state, seven = repetitionguard.check(line * 7, repetitionguard.new_state())
    assert seven is None, "the doc claims seven repeats do not trip"
    interleaved = "".join(line + f"step {i} done.\n" for i in range(8))
    _state, mixed = repetitionguard.check(interleaved, repetitionguard.new_state())
    assert mixed is None, "the doc claims interleaved varying text does not trip"


def test_feature_doc_records_the_false_negative_and_the_token_state() -> None:
    text = _read(FEATURE_DOC)
    assert "false NEGATIVE" in text
    assert str(repetitionguard.MAX_BUFFER_CHARS) in text
    assert "unrecorded" in text
    assert "not zero" in text.lower()


# ---------------------------------------------------------------------------
# c25/h3, c27/h5 — the incident evidence is recorded, with its numbers
# ---------------------------------------------------------------------------


def test_feature_doc_records_the_incident_evidence() -> None:
    text = _read(FEATURE_DOC)
    for token in (
        "2bd306a6916a",  # the greedy `low` run
        "4b74a1bd5a9b",  # the identical-calls run
        "271,486",  # the single truncated turn
        "651,679",  # the run's total reasoning
        "truncated-turn",
        "identical-calls",
    ):
        assert token in text, f"the incident record is missing {token!r}"
    # The per-turn sidecar profile is what makes "looping, not failing" checkable
    # rather than asserted (h5) — including the turns that contradict the spec's
    # own paraphrase.
    assert "46,998" in text
    assert "99,658" in text
    assert "Correction to the spec's paraphrase" in text


# ---------------------------------------------------------------------------
# c23 acceptance 5 — the four probes are recorded WITH their limits
# ---------------------------------------------------------------------------


def test_feature_doc_records_four_probes_each_with_a_limit() -> None:
    text = _read(FEATURE_DOC)
    section = text.split("### Four live probes")[1]
    assert section.count("*Limit:*") == 4, "each of the four probes carries its own limit"
    for token in (
        "byte-identical",  # probe 1: the determinism discriminator
        "colleague_bogus_key",  # probe 2: a 200 proves nothing
        "154 lines",  # probe 3: bulk code emission
        "95%",  # probe 4: the abort
    ):
        assert token in section, f"the probe record is missing {token!r}"
    assert "not a guarantee for another server" in section
    assert "no test may\n   treat a status code as proof" in section


# ---------------------------------------------------------------------------
# c58/h48 — the four reasons the file is not agents.json
# ---------------------------------------------------------------------------


def test_feature_doc_records_the_four_naming_reasons() -> None:
    text = _read(FEATURE_DOC)
    section = text.split("### Why `models.json` and not `agents.json`")[1].split("## ")[0]
    for numeral in ("1.", "2.", "3.", "4."):
        assert f"\n{numeral} " in section, f"naming reason {numeral} is missing"
    for token in ("#411", "config_seats.py", "default-on", "AgentProfile.resolved_model"):
        assert token in section, f"the naming rationale is missing {token!r}"
    assert "references" in section
    assert "absorbing it" in section


def test_feature_doc_records_the_tracked_at_head_rule_and_merge_granularity() -> None:
    text = _read(FEATURE_DOC)
    assert "!models.json" in text  # the gitignore allow-list entry
    assert "uncommitted edit to\n`models.json` does not reach a dispatched work item" in text
    assert "Merge granularity — per model key" in text
    assert "wholesale" in text  # no deep merge inside a model's halves
    # The two format limits, stated rather than implied.
    assert "No role dimension" in text
    assert "ROW-level, not key-level" in text


def test_feature_doc_records_the_config_show_limits() -> None:
    text = _read(FEATURE_DOC)
    assert "renders the BUILTIN table only" in text
    assert "fires\n  only on the literal `0`" in text


# ---------------------------------------------------------------------------
# c23 acceptance 1 — CLAUDE.md's vLLM bullet names the fourth carve-out
# ---------------------------------------------------------------------------


def _vllm_bullet() -> str:
    text = _read(CLAUDE_MD)
    start = text.index("- **The vLLM adapter only touches the OpenAI surface**")
    return text[start : text.index("\n- **", start + 1)]


def test_claude_md_vllm_bullet_names_the_fourth_carve_out() -> None:
    bullet = _vllm_bullet()
    # The three siblings it sits beside.
    assert "/tokenize" in bullet
    assert "stale-pin" in bullet
    assert "chat_template_kwargs" in bullet
    # The fourth carve-out itself, and the one extension key it puts on the wire.
    assert "fourth carve-out" in bullet
    assert "top_k" in bullet
    assert "#479" in bullet
    # The count moved with it: the per-turn carve-outs are now THREE.
    assert "THREE per-turn carve-outs" in bullet
    assert "TWO per-turn carve-outs" not in bullet


def test_claude_md_has_a_sampling_architecture_bullet() -> None:
    text = _read(CLAUDE_MD)
    assert "sampling.md" in text
    assert "COLLEAGUE_SAMPLING" in text


# ---------------------------------------------------------------------------
# c23 acceptance 3 — the sibling docs carry the new resolution
# ---------------------------------------------------------------------------


def test_thinking_effort_wire_section_no_longer_claims_the_only_body_key() -> None:
    text = _read(THINKING_EFFORT_MD)
    wire = text.split("## The wire")[1].split("## Ladder-400")[0]
    # It must point at the sampling doc rather than implying it is alone.
    assert "sampling.md" in wire
    assert "top_k" in wire
    # The old absolute claim is explicitly retracted rather than merely dropped.
    assert "no longer the only per-seat body key" in wire
    assert not re.search(r"(?<!no longer the )only per-seat body key", text)


def test_model_selection_md_carries_the_sampling_resolution() -> None:
    text = _read(MODEL_SELECTION_MD)
    assert "sampling.md" in text
    assert "models.json" in text


def test_config_resolution_md_carries_the_sampling_resolution() -> None:
    text = _read(CONFIG_RESOLUTION_MD)
    assert "sampling.md" in text
    assert ".colleague/models.json" in text
    assert "COLLEAGUE_SAMPLING" in text
    assert "COLLEAGUE_TEMPERATURE" in text
