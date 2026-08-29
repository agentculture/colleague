"""The prose lever's three instruments: the P0/P1/P2 writer overlays (plan t12).

``docs/plans/2026-08-29-purpose-tools-get-chosen.md`` task t12 (covers c37,
h26, c52, h39, c39, h28).

The arc's *prose lever* asks one question: does the way the delegation helper
is FRAMED change how often the acting seat delegates? The three overlays are
the manipulated variable and nothing else:

* **P0** (control) — the shipped descriptive sentence, verbatim from
  :func:`colleague.delegation_text.armed_facts`, and no instruction at all;
* **P1** — that SAME sentence (weaker-helper framing kept, verbatim) plus an
  instruction to hand surveying/searching work to a scout child;
* **P2** — capability-EQUAL framing (peer seat, same model family, an
  independent pass) plus the SAME instruction, byte-for-byte.

So ``diff P1 P2`` is exactly one paragraph — the capability framing. Anything
else in that diff would be a confound and would invalidate the arm.

**Why the basename is ``writer.md``.** :func:`colleague.roles.load_role`
resolves an operator overlay at exactly two paths — the per-model overlay
``.colleague/<model>/agents/<name>.md`` and the base file
``.colleague/agents/<name>.md`` — and since plan t5 the depth-0 acting seat of
a BARE run resolves to the role name ``writer``
(:func:`colleague.actingsurface.acting_role_name` →
:func:`colleague.actingsurface.substitute_bare_role`). ``writer.md`` is
therefore the ONE basename that reaches a default run's composed prompt. The
three files are staged in sibling directories under
``docs/live-testing/overlays/`` — NOT under ``.colleague/agents/`` — so their
presence in this repo cannot change a default run here (pinned below); the arm
harness copies the chosen one to ``<arm repo>/.colleague/agents/writer.md``.

**Honest note, recorded rather than hidden.** An overlay REPLACES the built-in
writer ``prompt_fragment`` (``load_role``: the file prompt wins). All three
arms lose that fragment identically, so it is a constant across the arms, not
a between-arm confound — but a P-arm prompt is not the default prompt plus
prose, and no row may claim it is.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from colleague.config import EngineConfig
from colleague.contract import Task
from colleague.delegation_text import armed_facts
from colleague.effort import ROLE_TABLE
from colleague.engines.mock import MockEngine
from colleague.roles import BUILTIN_ROLES, _split_effort_frontmatter, load_role

REPO_ROOT = Path(__file__).resolve().parent.parent
OVERLAY_DIR = REPO_ROOT / "docs" / "live-testing" / "overlays"
ARMS = ("P0", "P1", "P2")

_MODEL = "Qwen/Qwen3-32B"

#: Vocabulary that frames the scout as LESSER. P2's whole point is to carry
#: none of it (spec c52/h39).
_WEAKER_HELPER_WORDS = (
    "quicker",
    "cannot write",
    "switched off",
    "weaker",
    "lesser",
    "smaller",
)


def _overlay_path(arm: str) -> Path:
    return OVERLAY_DIR / arm / "writer.md"


def _split(arm: str) -> "tuple[str | None, str]":
    return _split_effort_frontmatter(_overlay_path(arm).read_text(encoding="utf-8"))


def _paragraphs(arm: str) -> "list[str]":
    _, body = _split(arm)
    return [p.strip() for p in body.strip().split("\n\n") if p.strip()]


def _shipped_sentence() -> str:
    """The shipped sentence, read from its SOURCE, never a copy in this file."""
    return armed_facts(SimpleNamespace(associate="lobes"))


# ---------------------------------------------------------------------------
# (a) all three parse, carrying the SAME effort rung
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("arm", ARMS)
def test_overlay_exists_and_parses(arm: str) -> None:
    path = _overlay_path(arm)
    assert path.is_file(), f"missing overlay: {path}"
    effort, body = _split(arm)
    assert effort is not None, "overlay must lead with an 'effort: <rung>' line"
    assert body.strip(), "overlay body must not be empty"


def test_all_three_overlays_pin_the_same_effort_rung() -> None:
    rungs = {arm: _split(arm)[0] for arm in ARMS}
    assert len(set(rungs.values())) == 1, f"arms differ in effort rung: {rungs}"


def test_pinned_rung_is_the_acting_seat_default() -> None:
    """The pinned rung is the writer's own table default, so pinning it removes
    the #417/#421 rung confound WITHOUT moving the acting seat off its default.
    """
    assert _split("P0")[0] == ROLE_TABLE["writer"]


@pytest.mark.parametrize("arm", ARMS)
def test_overlay_body_is_short_enough_to_read(arm: str) -> None:
    _, body = _split(arm)
    assert len(body.split()) < 250


# ---------------------------------------------------------------------------
# (b) P0 is the shipped sentence VERBATIM (asserted against the source)
# ---------------------------------------------------------------------------


def test_p0_body_is_the_shipped_sentence_verbatim() -> None:
    _, body = _split("P0")
    assert body.strip() == _shipped_sentence()


def test_p1_keeps_the_shipped_sentence_verbatim() -> None:
    assert _paragraphs("P1")[0] == _shipped_sentence()


def test_p2_does_not_carry_the_weaker_helper_framing() -> None:
    _, body = _split("P2")
    assert _shipped_sentence() not in body
    lowered = body.lower()
    for word in _WEAKER_HELPER_WORDS:
        assert word not in lowered, f"P2 still frames the scout as lesser: {word!r}"


def test_p2_frames_the_scout_as_a_capability_equal_peer() -> None:
    framing = _paragraphs("P2")[0].lower()
    assert "peer seat" in framing
    assert "same model family" in framing
    assert "independent" in framing
    assert "digest" in framing


# ---------------------------------------------------------------------------
# P1 vs P2: the capability framing is the ONLY difference
# ---------------------------------------------------------------------------


def test_p1_and_p2_differ_only_in_the_capability_framing() -> None:
    p1, p2 = _paragraphs("P1"), _paragraphs("P2")
    assert len(p1) == len(p2) == 2
    # Paragraph 0 is the framing — the independent variable.
    assert p1[0] != p2[0]
    # Paragraph 1 is the instruction — byte-identical, or the arm is confounded.
    assert p1[1] == p2[1]


def test_p1_and_p2_carry_the_same_delegation_instruction() -> None:
    instruction = _paragraphs("P1")[1].lower()
    assert "scout child" in instruction
    assert "surveying" in instruction
    assert instruction == _paragraphs("P2")[1].lower()


def test_p1_and_p2_are_of_comparable_length() -> None:
    """Length is a plausible alternative cause of a behaviour difference, so it
    is held near-constant: within 15 % on word count."""
    n1, n2 = (len(_split(arm)[1].split()) for arm in ("P1", "P2"))
    assert abs(n1 - n2) / max(n1, n2) < 0.15


def test_p0_is_the_control_and_carries_no_instruction() -> None:
    assert len(_paragraphs("P0")) == 1


# ---------------------------------------------------------------------------
# (c) with NO overlay present, composition is unchanged
# ---------------------------------------------------------------------------


def _bare_prompt(repo: Path) -> "str | None":
    task = Task(id="t12", instruction="do a thing", repo_path=str(repo))
    return MockEngine().system_prompt(task, EngineConfig(model=_MODEL, role=None))


def test_no_overlay_keeps_the_builtin_writer_fragment(tmp_path: Path) -> None:
    role = load_role("writer", tmp_path, _MODEL)
    assert role is not None
    builtin = BUILTIN_ROLES["writer"]
    assert role.prompt_fragment == builtin.prompt_fragment
    assert role.effort == builtin.effort


def test_staged_overlays_do_not_reach_this_repos_default_run() -> None:
    """The three files live under ``docs/``, not ``.colleague/agents/`` — so a
    bare run AT THIS REPO composes the pre-arc prompt: the built-in writer
    fragment, and not one byte of any overlay."""
    assert not (REPO_ROOT / ".colleague" / "agents" / "writer.md").exists()
    prompt = _bare_prompt(REPO_ROOT)
    assert prompt is not None
    assert BUILTIN_ROLES["writer"].prompt_fragment in prompt
    for arm in ARMS:
        assert _split(arm)[1].strip() not in prompt


def test_no_overlay_prompt_is_identical_before_and_after_staging(tmp_path: Path) -> None:
    """The pre-arc composition, reproduced: a repo with no ``.colleague/agents/``
    at all composes exactly what a repo carrying the staged overlay TREE (but no
    resolving ``writer.md``) composes."""
    staged = tmp_path / "staged"
    for arm in ARMS:
        target = staged / "docs" / "live-testing" / "overlays" / arm
        target.mkdir(parents=True, exist_ok=True)
        (target / "writer.md").write_text(_overlay_path(arm).read_text(encoding="utf-8"))
    bare = tmp_path / "bare"
    bare.mkdir()
    assert _bare_prompt(staged) == _bare_prompt(bare)


@pytest.mark.parametrize("arm", ARMS)
def test_copying_an_overlay_into_place_does_reach_the_prompt(tmp_path: Path, arm: str) -> None:
    """The instrument works: copied to the ONE path ``load_role`` resolves, the
    overlay's body replaces the writer fragment and its rung is carried."""
    agents = tmp_path / ".colleague" / "agents"
    agents.mkdir(parents=True)
    (agents / "writer.md").write_text(_overlay_path(arm).read_text(encoding="utf-8"))
    role = load_role("writer", tmp_path, _MODEL)
    assert role is not None
    effort, body = _split(arm)
    assert role.effort == effort
    assert role.prompt_fragment == body
    prompt = _bare_prompt(tmp_path)
    assert prompt is not None and body.strip() in prompt
