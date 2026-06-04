"""Deterministic, engine-agnostic halves of the #123 gated-configs validation.

The live-testing ledger §3 has five sub-checks. Three of them (3a run_command,
3c hooks deny/rewrite, 3d per-model hooks overlay) need a real model to *issue*
the gated tool call and are proven against the rig in
``tests/test_vllm_live_gated_configs.py``. The other two fire identically on
*every* backend — a live model adds no signal — so they are proven here, fast and
deterministic, with a scripted ``complete`` (no network):

* **3b — checksum-void.** An approved hook runs and denies; tampering the script
  voids the approval (checksum mismatch) → the hook is *skipped* and the tool is
  no longer blocked. Plus the command-template half: a drifted template is refused
  at expand time.
* **3e — per-model AGENTS/skills.** ``system_prompt_for`` — the exact function the
  engine base class calls (``colleague/engine.py``) — composes an
  ``AGENTS.colleague.<model>.md`` layer and a ``.colleague/<model>/skills/*.md``
  skill into the system prompt, and a *sibling* model sees neither (exact-path
  isolation). colleague records the composed prompt nowhere (not in the artifact
  or trace), so this composition surface is the honest deterministic proof; the
  all-engines parity is locked by ``tests/test_layers_engine_parity.py``.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from colleague.commands import CommandError, expand_command
from colleague.contract import OK, Task
from colleague.layers import resolve_agents, resolve_skills, sanitize_model, system_prompt_for
from colleague.loop import _DEFAULT_SYSTEM, ModelResponse, ToolCall, run
from colleague.policy import file_checksum

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scripted(responses: list[ModelResponse]):
    """A ``complete()`` callable that replays *responses* in order (no network)."""
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        i = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[i]

    return complete


def _make_script(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _write_json(repo: Path, rel: str, payload: dict) -> Path:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


def _write_file_then_finish() -> list[ModelResponse]:
    return [
        ModelResponse(
            tool_calls=[ToolCall("1", "write_file", {"path": "out.txt", "content": "hi"})]
        ),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "done"})]),
    ]


# ---------------------------------------------------------------------------
# 3b — checksum drift voids a hook approval (and a command-template approval)
# ---------------------------------------------------------------------------


def test_3b_checksum_drift_voids_hook_approval(tmp_path: Path) -> None:
    """An approved deny-hook runs and blocks the tool; after the script is edited
    the checksum no longer matches → the hook is *skipped* (approval void) and the
    write goes through. This is the live-config gate firing on presence, proven
    engine-agnostically with a scripted complete."""
    repo = tmp_path
    # A pre_tool hook that DENIES write_file: a non-zero exit is a deny (hooks.py).
    script = _make_script(
        repo / "deny.sh", "#!/bin/sh\necho 'blocked by approved hook' >&2\nexit 1\n"
    )
    _write_json(
        repo,
        ".colleague/hooks.json",
        {"hooks": {"pre_tool": [{"matcher": "write_file", "command": str(script)}]}},
    )
    # Approve the script by its current checksum (repo-relative key).
    _write_json(repo, ".colleague/approvals.json", {"hooks": {"deny.sh": file_checksum(script)}})

    # Run A — approval matches → the hook RUNS and denies the write.
    result_a = run(_scripted(_write_file_then_finish()), Task.new(str(repo), "write"), max_steps=10)
    assert result_a.status == OK
    denied = [f for f in result_a.hook_firings if f.decision == "deny"]
    assert denied, "approved deny-hook should run and deny the tool"
    write_a = next(s for s in result_a.steps if s.tool == "write_file")
    assert write_a.ok is False, "the approved deny-hook should block write_file"
    assert not (repo / "out.txt").exists()

    # Tamper the script — its checksum no longer matches the recorded approval.
    script.write_text("#!/bin/sh\necho tampered >&2\nexit 1\n", encoding="utf-8")

    # Run B — drift voids the approval → the hook is SKIPPED → the write executes.
    result_b = run(_scripted(_write_file_then_finish()), Task.new(str(repo), "write"), max_steps=10)
    assert result_b.status == OK
    skipped = [f for f in result_b.hook_firings if f.decision == "skipped"]
    assert skipped, "checksum drift must void the approval → hook skipped"
    assert "approval void" in skipped[0].reason.lower() or "checksum" in skipped[0].reason.lower()
    write_b = next(s for s in result_b.steps if s.tool == "write_file")
    assert write_b.ok is True, "a skipped pre_tool hook must not block the tool"
    assert (repo / "out.txt").read_text(encoding="utf-8") == "hi"


def test_3b_drifted_command_template_is_refused_at_expand(tmp_path: Path) -> None:
    """A command template whose recorded checksum no longer matches is refused
    before any engine runs (the gate fires at expand time)."""
    repo = tmp_path / "repo"
    cmds = repo / ".colleague" / "commands"
    cmds.mkdir(parents=True)
    template = cmds / "tidy.md"
    template.write_text("Tidy up $1.", encoding="utf-8")
    _write_json(repo, ".colleague/approvals.json", {"commands": {"tidy": file_checksum(template)}})

    # Approved + unchanged → expands fine.
    task = expand_command(repo, "tidy", ["src/"], user_home=tmp_path / "home")
    assert isinstance(task, Task) and "src/" in task.instruction

    # Drift the template — the recorded checksum is now stale.
    template.write_text("Tidy up $1 AND reformat everything.", encoding="utf-8")
    with pytest.raises(CommandError):
        expand_command(repo, "tidy", ["src/"], user_home=tmp_path / "home")


# ---------------------------------------------------------------------------
# 3e — per-model AGENTS/skills compose into the system prompt (engine path)
# ---------------------------------------------------------------------------

_MODEL = "acme/Probe-Model-7B"
_OTHER = "acme/Other-Model-7B"


def _seed_per_model_layers(repo: Path, model: str) -> None:
    safe = sanitize_model(model)
    (repo / f"AGENTS.colleague.{safe}.md").write_text(
        "MODEL_AGENTS_MARKER: per-model guidance for this model only.\n", encoding="utf-8"
    )
    skills_dir = repo / ".colleague" / safe / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "probe.md").write_text("# probe\nProbe skill summary line.\n", encoding="utf-8")


def test_3e_per_model_layers_land_in_system_prompt(tmp_path: Path) -> None:
    """``system_prompt_for`` (the exact engine composition path) folds the per-model
    AGENTS layer + skill catalog into the prompt for that model."""
    repo = tmp_path
    _seed_per_model_layers(repo, _MODEL)

    composed = system_prompt_for(repo, _MODEL, base=_DEFAULT_SYSTEM)
    assert composed is not None
    assert composed.startswith(_DEFAULT_SYSTEM), "base default leads the composed prompt"
    assert "MODEL_AGENTS_MARKER" in composed, "the per-model AGENTS layer must land in the prompt"
    assert "- probe: Probe skill summary line." in composed, "the skill catalog must land too"

    # The layers are structurally resolved with the 'model' scope.
    assert any(layer.scope == "model" for layer in resolve_agents(repo, _MODEL))
    skills = resolve_skills(repo, _MODEL)
    assert "probe" in skills and skills["probe"].scope == "model"


def test_3e_sibling_model_sees_neither_layer(tmp_path: Path) -> None:
    """Exact-path isolation: a different model gets neither the AGENTS marker nor
    the skill — overlays are never globbed across sibling models."""
    repo = tmp_path
    _seed_per_model_layers(repo, _MODEL)

    other = system_prompt_for(repo, _OTHER, base=_DEFAULT_SYSTEM)
    # With no layers of its own, the sibling composes to None (byte-identical to
    # a layer-free run) — and certainly never sees the other model's marker/skill.
    assert other is None or "MODEL_AGENTS_MARKER" not in other
    assert not any(layer.scope == "model" for layer in resolve_agents(repo, _OTHER))
    assert "probe" not in resolve_skills(repo, _OTHER)
