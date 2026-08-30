"""Prompt/surface unification: ONE role resolution feeds BOTH halves (plan t5).

``docs/plans/2026-08-29-purpose-tools-get-chosen.md`` task t5 (covers c50, h37,
c38, h27).

**The defect this pins the fix for.** ``Engine.system_prompt`` used to read
``config.role`` BY NAME and compose a role fragment only when that name was
set, while ``colleague.actingsurface.curate_for_depth`` had ALREADY (deviation
d14) substituted ``BUILTIN_ROLES['writer']`` for a bare ``None`` role at depth
0 — but only for the TOOL SURFACE. So a default run was OFFERED the writer's
carved-out surface while being TOLD nothing about being a writer, and an
operator overlay at ``.colleague/agents/writer.md`` never reached it. Measured
before the fix, on a repo carrying that overlay::

    role=None     -> overlay_reached=False, len=0
    role='writer' -> overlay_reached=True,  len=4059+overlay

Both halves now read ``actingsurface.acting_role_name`` →
``loop.resolve_role`` → ``curate_for_depth``: one resolution, one
substitution site (``actingsurface.substitute_bare_role``).

**Seats that deliberately carry no role fragment** keep composing exactly as
before, and each is pinned below with the REASON it is untouched:

* the **agents-mode (#411) lobes seats** — ``loop.resolve_role`` narrows them
  to a synthetic ``narrowed``/tools-off purpose role BEFORE the bare-run
  substitution can see them, and ``roles.load_role`` refuses those names;
* the **tools-off evaluator seat** — ``colleague.tae_loop`` composes its own
  prompt (``_complete_once("", prompt)``) and never reaches
  ``Engine.system_prompt`` at all.

The **three-tier worker seat** is the honest exception, pinned explicitly by
``test_three_tier_worker_seat_gains_the_acting_seat_fragment``: it IS the
depth-0 acting seat with no ``config.role``, so its curated tool surface has
been the writer's since d14 — leaving its prompt roleless would preserve for
that one seat the exact prompt/surface disagreement this task removes. No
existing test pinned that seat's composed prompt; none was relaxed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from colleague.config import EngineConfig
from colleague.contract import Task
from colleague.engines.mock import MockEngine
from colleague.engines.vllm_openai import VllmOpenAIEngine
from colleague.loop import resolve_role
from colleague.roles import BUILTIN_ROLES
from colleague.tools import curate_schemas

_MODEL = "Qwen/Qwen3-32B"
_OVERLAY_MARKER = "OPERATOR-WRITER-OVERLAY-MARKER"


def _task(repo: Path) -> Task:
    return Task(id="t5", instruction="do a thing", repo_path=str(repo))


def _prompt(repo: Path, role: "str | None") -> "str | None":
    return MockEngine().system_prompt(_task(repo), EngineConfig(model=_MODEL, role=role))


def _surface(repo: Path, role: "str | None") -> "list[str]":
    config = EngineConfig(model=_MODEL, role=role)
    resolved = resolve_role(config, str(repo))
    return [s["function"]["name"] for s in curate_schemas(resolved)]


def _write_writer_overlay(repo: Path, body: str) -> None:
    agents = repo / ".colleague" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    (agents / "writer.md").write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# Acceptance 1 — a bare run and --role writer compose an IDENTICAL prompt AND
#                an identical tool surface
# ---------------------------------------------------------------------------


def test_bare_run_and_explicit_writer_compose_identical_prompt(tmp_path: Path) -> None:
    bare, explicit = _prompt(tmp_path, None), _prompt(tmp_path, "writer")
    assert bare is not None
    assert bare == explicit


def test_bare_run_and_explicit_writer_offer_identical_surface(tmp_path: Path) -> None:
    assert _surface(tmp_path, None) == _surface(tmp_path, "writer")


def test_bare_run_prompt_carries_the_writer_fragment(tmp_path: Path) -> None:
    """The composed prompt is not merely non-empty — it ends with the writer
    role's own fragment, which is what the offered surface belongs to."""
    bare = _prompt(tmp_path, None)
    assert bare is not None
    assert bare.endswith(BUILTIN_ROLES["writer"].prompt_fragment)


def test_both_engines_compose_the_same_bare_prompt(tmp_path: Path) -> None:
    """All-engines rule: the base-class resolution is inherited identically."""
    task, config = _task(tmp_path), EngineConfig(model=_MODEL)
    assert MockEngine().system_prompt(task, config) == VllmOpenAIEngine().system_prompt(
        task, config
    )


# ---------------------------------------------------------------------------
# Acceptance 2 — an operator overlay reaches a bare run
# ---------------------------------------------------------------------------


def test_operator_writer_overlay_reaches_a_bare_run(tmp_path: Path) -> None:
    """The probe that returned ``overlay_reached=False`` before t5."""
    _write_writer_overlay(tmp_path, f"{_OVERLAY_MARKER}\nYou are the operator's writer.")

    bare = _prompt(tmp_path, None)
    assert bare is not None
    assert _OVERLAY_MARKER in bare
    assert _OVERLAY_MARKER in (_prompt(tmp_path, "writer") or "")
    assert bare == _prompt(tmp_path, "writer")


def test_operator_writer_overlay_replaces_the_builtin_fragment_on_a_bare_run(
    tmp_path: Path,
) -> None:
    """The overlay is the fragment, not an addition to it — same as --role."""
    _write_writer_overlay(tmp_path, _OVERLAY_MARKER)

    bare = _prompt(tmp_path, None)
    assert bare is not None
    assert BUILTIN_ROLES["writer"].prompt_fragment not in bare


def test_per_model_writer_overlay_reaches_a_bare_run(tmp_path: Path) -> None:
    """The per-model overlay path (``.colleague/<model>/agents/writer.md``)
    wins for a bare run exactly as it does for an explicit ``--role writer``."""
    from colleague import layers

    per_model = tmp_path / ".colleague" / layers.sanitize_model(_MODEL) / "agents"
    per_model.mkdir(parents=True)
    (per_model / "writer.md").write_text("PER-MODEL-WRITER", encoding="utf-8")
    _write_writer_overlay(tmp_path, "BASE-WRITER")

    bare = _prompt(tmp_path, None)
    assert bare is not None
    assert "PER-MODEL-WRITER" in bare
    assert "BASE-WRITER" not in bare


def test_effort_frontmatter_never_leaks_into_a_bare_run_prompt(tmp_path: Path) -> None:
    """``roles._split_effort_frontmatter`` still consumes the leading
    ``effort:`` line on the bare-run path (it is the SAME load_role call)."""
    _write_writer_overlay(tmp_path, f"effort: high\n{_OVERLAY_MARKER}")

    bare = _prompt(tmp_path, None)
    assert bare is not None
    assert _OVERLAY_MARKER in bare
    assert "effort: high" not in bare


# ---------------------------------------------------------------------------
# Acceptance 3 — seats that deliberately carry NO role fragment are unchanged
# ---------------------------------------------------------------------------


def _agents_config(purpose: "str | None") -> EngineConfig:
    from dataclasses import replace as dc_replace

    config = dc_replace(EngineConfig(model=_MODEL), agents=True)
    if purpose is not None:
        setattr(config, "agents_profile", purpose)
    return config


@pytest.mark.parametrize("purpose", ["talker", "worker", "thinker_coder", "associate", None])
def test_agents_mode_lobes_seats_compose_no_role_fragment(tmp_path: Path, purpose) -> None:
    """#411 agents-mode seats: ``resolve_role`` narrows them to a synthetic
    purpose role whose name is not a built-in, so ``load_role`` refuses it and
    the composition falls through to the role-less prompt — exactly as before
    t5. (``None`` exercises ``DEFAULT_ACTING_PURPOSE``.)"""
    from colleague.layers import system_prompt_for
    from colleague.prompttext import default_system

    config = _agents_config(purpose)
    composed = MockEngine().system_prompt(_task(tmp_path), config)
    roleless = system_prompt_for(str(tmp_path), _MODEL, base=default_system(_MODEL))

    assert composed == roleless
    assert composed is None or BUILTIN_ROLES["writer"].prompt_fragment not in composed


def test_agents_mode_seat_is_never_substituted_to_the_writer_role(tmp_path: Path) -> None:
    """The reason the seat above is untouched, pinned at its source: the role
    resolved for an agents-mode seat is not the writer built-in."""
    resolved = resolve_role(_agents_config("thinker_coder"), str(tmp_path))
    assert resolved is not None
    assert resolved.name != "writer"
    assert BUILTIN_ROLES.get(resolved.name) is None


def test_tools_off_evaluator_seat_never_reaches_engine_system_prompt() -> None:
    """The evaluator composes its own prompt in ``tae_loop`` — it does not go
    through ``Engine.system_prompt``, so t5 structurally cannot touch it."""
    import inspect

    from colleague import tae_loop

    source = inspect.getsource(tae_loop)
    assert "system_prompt(task" not in source
    assert 'self._complete_once("", prompt)' in source


def test_three_tier_worker_seat_gains_the_acting_seat_fragment(tmp_path: Path) -> None:
    """The honest exception, recorded rather than hidden.

    The three-tier worker IS the depth-0 acting seat with no ``config.role``,
    so ``curate_for_depth`` has offered it the writer's carved-out surface
    since deviation d14. Its prompt therefore moves WITH its surface: keeping
    it roleless would preserve, for exactly this seat, the disagreement t5
    exists to remove. Nothing here was relaxed — no existing test pinned this
    seat's composed prompt.
    """
    from dataclasses import replace as dc_replace

    from colleague.config import WorkerConfig

    config = dc_replace(
        EngineConfig(model=_MODEL),
        worker=WorkerConfig(
            model="worker/model",
            base_url="http://gateway.example:8001/v1",
            api_key="k",
            context=1000,
        ),
    )
    composed = MockEngine().system_prompt(_task(tmp_path), config)
    assert composed == _prompt(tmp_path, "writer")


# ---------------------------------------------------------------------------
# The single substitution site
# ---------------------------------------------------------------------------


def test_substitution_lives_in_exactly_one_place(tmp_path: Path) -> None:
    """``substitute_bare_role`` is the ONE place ``None`` becomes the writer;
    both halves reach it, and the module names the role exactly once."""
    from colleague import actingsurface

    assert actingsurface.substitute_bare_role(None) is BUILTIN_ROLES["writer"]
    sentinel = BUILTIN_ROLES["explorer"]
    assert actingsurface.substitute_bare_role(sentinel) is sentinel

    # Both halves reach it: the surface via curate_for_depth, the prompt via
    # acting_role_name — and they agree on the name.
    config = EngineConfig(model=_MODEL)
    assert actingsurface.acting_role_name(config, str(tmp_path)) == "writer"
    assert resolve_role(config, str(tmp_path)).name == "writer"


def test_child_seat_prompt_is_the_writer_fragment_too(tmp_path: Path) -> None:
    """A depth >= 1 roleless child was ALREADY substituted to the (bounded)
    writer for its surface; its prompt now agrees. The child's surface stays
    purpose-tool-free (q9) — unification changes the prompt, not the strip."""
    from dataclasses import replace as dc_replace

    from colleague import actingsurface as actingsurface_mod
    from colleague.purpose_schemas import PURPOSE_TOOL_NAMES

    child = dc_replace(EngineConfig(model=_MODEL))
    # The SAME dynamic attribute colleague.subagents stamps on a child config.
    setattr(child, actingsurface_mod.CHILD_DEPTH_ATTR, 1)

    resolved = resolve_role(child, str(tmp_path))
    assert resolved is not None
    assert not (set(resolved.tool_allowlist) & set(PURPOSE_TOOL_NAMES))
    composed = MockEngine().system_prompt(_task(tmp_path), child)
    assert composed is not None
    assert composed.endswith(BUILTIN_ROLES["writer"].prompt_fragment)
