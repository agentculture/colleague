"""``colleague/chain.py``'s episode-boundary config window (plan task t6).

TEST-FIRST for :func:`colleague.chain.apply_config_window` — the ONE named
home for "chain.py's between-episode window (plus before episode 1)" the
plan instruction requires. It is a thin, pure delegation onto
:meth:`colleague.configlifecycle.EpisodeConfigLifecycle.apply_window`;
the interesting behavior (queue drain, digest movement, refusal of an
unsanctioned window) is pinned in ``tests/test_configlifecycle.py`` — this
file pins that ``chain.py`` is genuinely the documented call site, re-exports
the same two window constants, and adds no new import surface.

Covers (plan task t6): c8, h8, c26.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from colleague import chain
from colleague.chain import (
    WINDOW_BEFORE_EPISODE_1,
    WINDOW_BETWEEN_EPISODES,
    apply_config_window,
)
from colleague.configlifecycle import WINDOW_BEFORE_EPISODE_1 as CL_WINDOW_BEFORE_EPISODE_1
from colleague.configlifecycle import WINDOW_BETWEEN_EPISODES as CL_WINDOW_BETWEEN_EPISODES
from colleague.configlifecycle import (
    ConfigLifecycleError,
    EpisodeConfigLifecycle,
)
from colleague.lattice import CapabilityCatalog, ChangeUnit, Origin, Target


def test_chain_window_constants_mirror_configlifecycle_exactly() -> None:
    assert WINDOW_BEFORE_EPISODE_1 == CL_WINDOW_BEFORE_EPISODE_1
    assert WINDOW_BETWEEN_EPISODES == CL_WINDOW_BETWEEN_EPISODES


def test_apply_config_window_before_episode_1_applies_the_queue() -> None:
    lifecycle = EpisodeConfigLifecycle(catalog=CapabilityCatalog(tool_ids=("read_file",)))
    lifecycle.propose(
        ChangeUnit(target=Target.WORKER_TOOLS, origin=Origin.CORTEX, tool_ids=["read_file"])
    )
    before = lifecycle.effective_digest()

    application = apply_config_window(lifecycle, WINDOW_BEFORE_EPISODE_1)

    assert application.digest_before == before
    assert application.digest_after != before
    assert lifecycle.pending_count() == 0
    assert lifecycle.snapshot.tool_set == ("read_file",)


def test_apply_config_window_between_episodes_applies_the_queue() -> None:
    lifecycle = EpisodeConfigLifecycle()
    lifecycle.propose(ChangeUnit(target=Target.WORKER_PROMPT_STRATEGIST, origin=Origin.CORTEX))

    application = apply_config_window(lifecycle, WINDOW_BETWEEN_EPISODES)

    assert application.applied_count == 1
    assert lifecycle.snapshot.strategist_sections == ("cortex#1",)


def test_apply_config_window_refuses_a_mid_episode_call() -> None:
    lifecycle = EpisodeConfigLifecycle()
    lifecycle.propose(ChangeUnit(target=Target.WORKER_PROMPT_STRATEGIST, origin=Origin.CORTEX))

    with pytest.raises(ConfigLifecycleError):
        apply_config_window(lifecycle, "mid-episode")

    assert lifecycle.pending_count() == 1


def test_chain_module_imports_no_threading_or_concurrent_futures() -> None:
    """Structural pin mirroring test_boundary.py's rule 6 (unmodified, still
    green): the between-episode window stays synchronous on the calling
    thread — this diff adds no new threading/concurrent.futures IMPORT
    statement (a prose mention, e.g. in a docstring explaining the absence,
    is not a violation — matches test_boundary.py's own import-statement
    regex, not a free-text substring check)."""
    import re

    thread_import_re = re.compile(
        r"^\s*import threading\b"
        r"|^\s*from threading\b"
        r"|^\s*import concurrent\.futures\b"
        r"|^\s*from concurrent\.futures\b"
        r"|^\s*from concurrent import futures\b",
    )
    source_path = Path(chain.__file__)
    violations = [
        line
        for line in source_path.read_text(encoding="utf-8").splitlines()
        if thread_import_re.search(line)
    ]
    assert violations == []
