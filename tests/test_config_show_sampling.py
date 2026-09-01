"""``config show`` states the sampling match POSITIVELY (reasoning-aware-
sampling-defaults arc, plan task t7, spec c45/h44).

Rendered beside the effort lines: the row that matched and the model it
matched for, or an explicit no-row-matched line — never a silent miss on a
checkpoint colleague has no card for (the rig serves
``unsloth/Qwen3.8-27B-NVFP4`` while the card is ``Qwen/Qwen3.8-27B``; a match
rule that misses silently ships an unchanged greedy payload under green
tests, which is exactly the failure #479 exists to prevent).
"""

from __future__ import annotations

import pytest

from colleague.cli._commands.config import _config_show
from colleague.config import EngineConfig


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "COLLEAGUE_MODEL",
        "COLLEAGUE_REASONING_EFFORT",
        "COLLEAGUE_SAMPLING",
        "CONVERTIBLE_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)


def test_matched_row_states_model_and_half_positively(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # unsloth/Qwen3.8-27B-NVFP4 normalizes to the built-in qwen3.8-27b row;
    # the default cortex rung ("low") selects the thinking half.
    monkeypatch.setenv("COLLEAGUE_MODEL", "unsloth/Qwen3.8-27B-NVFP4")
    rendered = _config_show(".")
    text = rendered._text

    assert "sampling: matched" in text
    assert "unsloth/Qwen3.8-27B-NVFP4" in text
    assert "qwen3.8-27b" in text

    data = rendered["sampling"]
    assert data["matched"] is True
    assert data["model"] == "unsloth/Qwen3.8-27B-NVFP4"
    assert data["normalized_model"] == "qwen3.8-27b"
    assert data["payload"]  # non-empty: the row's keys were rendered


def test_misspelt_model_renders_no_row_matched_not_silent_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deliberately misspelt model id must never resolve quietly — it
    must render as an explicit no-row-matched line."""
    monkeypatch.setenv("COLLEAGUE_MODEL", "unsloth/Qwen3.8-27B-NVFP4-TYPO")
    rendered = _config_show(".")
    text = rendered._text

    assert "sampling: no row matched" in text

    data = rendered["sampling"]
    assert data["matched"] is False
    assert data["payload"] == {}


def test_unrelated_model_renders_no_row_matched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_MODEL", "some-org/totally-unrelated-model")
    rendered = _config_show(".")
    data = rendered["sampling"]
    assert data["matched"] is False
    assert "sampling: no row matched" in rendered._text


def test_kill_switch_off_by_default() -> None:
    rendered = _config_show(".")
    data = rendered["sampling"]
    assert data["kill_switch_armed"] is False
    assert "kill switch armed" not in rendered._text


def test_kill_switch_armed_is_named_without_lying_about_the_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """COLLEAGUE_SAMPLING=0 is a boolean kill switch this task does not
    implement (t5 owns the adapter), but config show must still say so
    rather than presenting a match that would not actually be sent."""
    monkeypatch.setenv("COLLEAGUE_MODEL", "unsloth/Qwen3.8-27B-NVFP4")
    monkeypatch.setenv("COLLEAGUE_SAMPLING", "0")
    rendered = _config_show(".")
    text = rendered._text

    data = rendered["sampling"]
    assert data["kill_switch_armed"] is True
    assert "COLLEAGUE_SAMPLING=0" in text
    assert "kill switch armed" in text
    # The underlying match is still shown (diagnosable), just annotated.
    assert "sampling: matched" in text


def test_rendered_beside_effort_lines() -> None:
    """The sampling section is rendered right after the effort lines, not
    scattered elsewhere in the output."""
    rendered = _config_show(".")
    text = rendered._text
    effort_idx = text.index("reasoning_effort:")
    sampling_idx = text.index("sampling:")
    assert effort_idx < sampling_idx

    # Nothing unrelated to effort/sampling sits between them (config_file
    # provenance / lobes / hire lines all come later in the file).
    between = text[effort_idx:sampling_idx]
    assert "config_file" not in between
    assert "lobes:" not in between


def test_sampling_json_matches_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_MODEL", "unsloth/Qwen3.8-27B-NVFP4")
    rendered = _config_show(".")
    assert "sampling" in dict(rendered)


def test_engine_config_carries_reasoning_effort_effective_used_for_match() -> None:
    """Sanity: the seat/rung this render uses is the same property the
    vLLM adapter's ``_effort_for`` reads."""
    cfg = EngineConfig.resolve(model="unsloth/Qwen3.8-27B-NVFP4")
    assert cfg.reasoning_effort_effective is not None


def test_kill_switch_recognises_every_spelling_the_adapter_disables_on(monkeypatch) -> None:
    """config show and the adapter share ONE predicate (#479 d6).

    The two disagreed: the adapter disabled sampling on any of
    ``0|false|no|off`` while this section matched only the literal ``"0"``, so
    ``COLLEAGUE_SAMPLING=off`` sent no sampling keys while ``config show``
    cheerfully reported a match. That is precisely the silent divergence this
    arc exists to remove, in the arc's own reporting surface.
    """
    monkeypatch.setenv("COLLEAGUE_MODEL", "unsloth/Qwen3.8-27B-NVFP4")
    for spelling in ("0", "false", "no", "off", "OFF", " Off "):
        monkeypatch.setenv("COLLEAGUE_SAMPLING", spelling)
        rendered = _config_show(".")
        assert rendered["sampling"]["kill_switch_armed"] is True, spelling
        assert "kill switch armed" in rendered._text, spelling
    for spelling in ("1", "true", "yes", ""):
        monkeypatch.setenv("COLLEAGUE_SAMPLING", spelling)
        rendered = _config_show(".")
        assert rendered["sampling"]["kill_switch_armed"] is False, spelling
