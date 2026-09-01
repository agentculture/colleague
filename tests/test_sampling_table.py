"""Sampling profile table + resolution ladder (#479, plan task t2).

Test-first for :mod:`colleague.sampling`: the FIXED builtin table (the Qwen3.8
card values from issue #479), the model-id match rule (organisation prefix +
quantisation suffix stripped, ids ENUMERATED per row so a 4B cannot inherit the
27B card), and the most-specific-wins resolution ladder over
``model+role+half > model+half > role+half > half``.

The highest-risk failure this file guards is a green suite over an unchanged
greedy payload: every criterion is pinned as an explicit fixture, and the
"no keys at all" cases are asserted as ``None``/empty rather than as "some
profile".
"""

from __future__ import annotations

import ast
import subprocess  # nosec B404 - fresh-interpreter import check, fixed argv
import sys
from pathlib import Path

import pytest

from colleague import sampling
from colleague.sampling import (
    BUILTIN_SAMPLING_ROWS,
    NON_THINKING,
    THINKING,
    SamplingProfile,
    SamplingRow,
    half_for_rung,
    normalize_model_id,
    resolve_sampling,
    sampling_payload,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "colleague" / "sampling.py"

# The LIVE served id and the model-card id — pinned fixtures (criterion 3).
LIVE_SERVED_ID = "unsloth/Qwen3.8-27B-NVFP4"
CARD_ID = "Qwen/Qwen3.8-27B"
UNRELATED_ID = "mistralai/Mistral-Small-3-24B-Instruct"
SMALLER_SIBLING_ID = "Qwen/Qwen3.8-4B"


# --------------------------------------------------------------------------
# Criterion 1 — imports only stdlib plus colleague.effort
# --------------------------------------------------------------------------


def _imported_module_names() -> set[str]:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # a relative import inside the package
                names.add("colleague" + ("." + node.module if node.module else ""))
            elif node.module:
                names.add(node.module)
    return names


def test_module_imports_only_stdlib_plus_effort():
    """Static: no import names anything but stdlib and ``colleague.effort``."""
    names = _imported_module_names()
    colleague_imports = {n for n in names if n == "colleague" or n.startswith("colleague.")}
    assert colleague_imports <= {"colleague.effort"}, colleague_imports
    for banned in ("colleague.config", "colleague.loop"):
        assert banned not in names


def test_fresh_interpreter_import_pulls_no_config_or_loop():
    """Dynamic: importing the module in a fresh interpreter never loads
    ``colleague.config`` or ``colleague.loop`` (a lazy in-function import would
    slip past the AST check, so this is the real gate)."""
    code = (
        "import sys; import colleague.sampling; "
        "print(int('colleague.config' in sys.modules), "
        "int('colleague.loop' in sys.modules))"
    )
    proc = subprocess.run(  # nosec B603 - fixed argv, no shell
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    assert proc.stdout.split() == ["0", "0"], proc.stdout


# --------------------------------------------------------------------------
# Criterion 2 — the builtin Qwen3.8 rows equal the issue #479 card values
# --------------------------------------------------------------------------


def test_builtin_qwen_thinking_row_equals_card():
    """thinking: temp 1.0 / top_p 0.95 / top_k 20 / min_p 0.0 /
    presence 0.0 / repetition 1.0."""
    profile = resolve_sampling(LIVE_SERVED_ID, role="cortex", rung="medium")
    assert profile is not None
    assert profile.temperature == 1.0
    assert profile.top_p == 0.95
    assert profile.top_k == 20
    assert profile.min_p == 0.0
    assert profile.presence_penalty == 0.0
    assert profile.repetition_penalty == 1.0


def test_builtin_qwen_non_thinking_row_equals_card():
    """non-thinking: temp 0.7 / top_p 0.80 / top_k 20 / presence 1.5."""
    profile = resolve_sampling(LIVE_SERVED_ID, role="cortex", rung="off")
    assert profile is not None
    assert profile.temperature == 0.7
    assert profile.top_p == 0.80
    assert profile.top_k == 20
    assert profile.presence_penalty == 1.5


def test_builtin_rows_are_frozen_and_immutable():
    assert isinstance(BUILTIN_SAMPLING_ROWS, tuple)
    row = BUILTIN_SAMPLING_ROWS[0]
    with pytest.raises((AttributeError, TypeError)):
        row.half = "nonsense"
    with pytest.raises((AttributeError, TypeError)):
        row.profile.temperature = 0.0


def test_a_row_can_set_only_some_keys():
    """ "set to the server default" and "not set" must be distinguishable."""
    partial = SamplingProfile(temperature=0.5)
    assert partial.top_p is None
    assert sampling_payload(partial) == {"temperature": 0.5}
    explicit_default = SamplingProfile(repetition_penalty=1.0)
    assert sampling_payload(explicit_default) == {"repetition_penalty": 1.0}
    assert sampling_payload(SamplingProfile()) == {}


def test_sampling_payload_of_the_qwen_thinking_row():
    profile = resolve_sampling(CARD_ID, role="cortex", rung="high")
    assert sampling_payload(profile) == {
        "temperature": 1.0,
        "top_p": 0.95,
        "top_k": 20,
        "min_p": 0.0,
        "presence_penalty": 0.0,
        "repetition_penalty": 1.0,
    }


# --------------------------------------------------------------------------
# Criterion 3 — the match rule
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        (LIVE_SERVED_ID, "qwen3.8-27b"),
        (CARD_ID, "qwen3.8-27b"),
        ("Qwen3.8-27B", "qwen3.8-27b"),
        ("  unsloth/Qwen3.8-27B-NVFP4  ", "qwen3.8-27b"),
        ("unsloth/Qwen3.8-27B-FP8", "qwen3.8-27b"),
        ("Qwen/Qwen3.8-27B-AWQ", "qwen3.8-27b"),
        (SMALLER_SIBLING_ID, "qwen3.8-4b"),
        ("", ""),
    ],
)
def test_normalize_model_id(raw, expected):
    assert normalize_model_id(raw) == expected


def test_live_id_and_card_id_resolve_to_the_same_row():
    live = resolve_sampling(LIVE_SERVED_ID, role="cortex", rung="medium")
    card = resolve_sampling(CARD_ID, role="cortex", rung="medium")
    assert live is not None
    assert live == card


def test_unrelated_model_resolves_to_no_row():
    assert resolve_sampling(UNRELATED_ID, role="cortex", rung="medium") is None
    assert resolve_sampling(UNRELATED_ID, role="cortex", rung="off") is None


def test_smaller_sibling_cannot_inherit_the_27b_card():
    """The 27B row enumerates its ids; a loose prefix would hand Qwen3.8-4B the
    27B card. This is the criterion-3 regression guard."""
    assert resolve_sampling(SMALLER_SIBLING_ID, role="cortex", rung="medium") is None


def test_none_model_resolves_to_no_row():
    assert resolve_sampling(None, role="cortex", rung="medium") is None
    assert resolve_sampling("", role="cortex", rung="medium") is None


# --------------------------------------------------------------------------
# Criterion 4 — the resolution ladder, most-specific-wins
# --------------------------------------------------------------------------

_M = "acme/Test-Model-7B-FP8"
_MN = "test-model-7b"

_P_MODEL_ROLE = SamplingProfile(temperature=0.11)
_P_MODEL = SamplingProfile(temperature=0.22)
_P_ROLE = SamplingProfile(temperature=0.33)
_P_DEFAULT = SamplingProfile(temperature=0.44)

_ROW_MODEL_ROLE = SamplingRow(models=(_MN,), role="cortex", half=THINKING, profile=_P_MODEL_ROLE)
_ROW_MODEL = SamplingRow(models=(_MN,), role=None, half=THINKING, profile=_P_MODEL)
_ROW_ROLE = SamplingRow(models=(), role="cortex", half=THINKING, profile=_P_ROLE)
_ROW_DEFAULT = SamplingRow(models=(), role=None, half=THINKING, profile=_P_DEFAULT)

_ALL_ROWS = (_ROW_DEFAULT, _ROW_ROLE, _ROW_MODEL, _ROW_MODEL_ROLE)


@pytest.mark.parametrize(
    "rows,model,role,expected",
    [
        # All four match: model+role+half is the most specific.
        (_ALL_ROWS, _M, "cortex", _P_MODEL_ROLE),
        # Two rows match, the more specific (model+half) wins.
        ((_ROW_DEFAULT, _ROW_MODEL), _M, "cortex", _P_MODEL),
        ((_ROW_ROLE, _ROW_MODEL), _M, "cortex", _P_MODEL),
        ((_ROW_DEFAULT, _ROW_ROLE), _M, "cortex", _P_ROLE),
        # role+half beats default when the model does not match.
        (_ALL_ROWS, "other/Model-1B", "cortex", _P_ROLE),
        # default is the floor when neither model nor role match.
        (_ALL_ROWS, "other/Model-1B", "senses", _P_DEFAULT),
        # model+half beats role+half when the role does not match.
        (_ALL_ROWS, _M, "senses", _P_MODEL),
        # order in the sequence must not decide the winner.
        (tuple(reversed(_ALL_ROWS)), _M, "cortex", _P_MODEL_ROLE),
    ],
)
def test_ladder_most_specific_wins(rows, model, role, expected):
    assert resolve_sampling(model, role=role, rung="medium", rows=rows) == expected


def test_half_gates_every_rung_of_the_ladder():
    """A THINKING row never answers a non-thinking rung."""
    assert resolve_sampling(_M, role="cortex", rung="off", rows=_ALL_ROWS) is None


def test_later_row_wins_a_tie_at_equal_specificity():
    """Equal specificity: the LAST row wins, so a t3 operator table layered
    after the builtin rows overrides it."""
    builtin = SamplingRow(models=(_MN,), role="cortex", half=THINKING, profile=_P_MODEL)
    operator = SamplingRow(models=(_MN,), role="cortex", half=THINKING, profile=_P_ROLE)
    assert resolve_sampling(_M, role="cortex", rung="low", rows=(builtin, operator)) == _P_ROLE


def test_rows_default_to_the_builtin_table():
    assert resolve_sampling(LIVE_SERVED_ID, role="cortex", rung="low") == resolve_sampling(
        LIVE_SERVED_ID, role="cortex", rung="low", rows=BUILTIN_SAMPLING_ROWS
    )


# --------------------------------------------------------------------------
# Criterion 5 — no keys at all for an unmatched model / None / the sentinel
# --------------------------------------------------------------------------


@pytest.mark.parametrize("rung", ["off", "low", "medium", "high", "xhigh"])
def test_every_ladder_rung_maps_to_a_half(rung):
    assert half_for_rung(rung) == (NON_THINKING if rung == "off" else THINKING)


@pytest.mark.parametrize("rung", [None, "default", "", "  ", "bogus"])
def test_no_half_for_none_sentinel_or_unparseable(rung):
    assert half_for_rung(rung) is None


@pytest.mark.parametrize("rung", [None, "default", "bogus"])
def test_no_sampling_keys_for_none_sentinel_or_unparseable(rung):
    """The kill-switch and an absent rung send NOTHING — not a greedy default,
    not a partial profile."""
    assert resolve_sampling(LIVE_SERVED_ID, role="cortex", rung=rung) is None
    assert sampling_payload(resolve_sampling(LIVE_SERVED_ID, role="cortex", rung=rung)) == {}


def test_no_sampling_keys_for_an_unmatched_model():
    assert sampling_payload(resolve_sampling(UNRELATED_ID, role="cortex", rung="medium")) == {}


def test_sentinel_matches_the_effort_module():
    """The kill-switch sentinel is consumed from :mod:`colleague.effort`, never
    re-spelled here."""
    from colleague import effort

    assert sampling.DEFAULT_SENTINEL == effort.DEFAULT_SENTINEL
    assert half_for_rung(effort.DEFAULT_SENTINEL) is None
    for rung in effort.LADDER:
        assert half_for_rung(rung) is not None


def test_resolution_ignores_an_unparseable_value_rather_than_raising():
    """Tolerant per-value resolution, the associate_config precedent."""
    assert resolve_sampling(object(), role="cortex", rung="medium") is None
    assert resolve_sampling(LIVE_SERVED_ID, role=None, rung="medium") is not None
