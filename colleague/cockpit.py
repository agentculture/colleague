"""Shared repo-context cockpit builder.

Lives top-level (not under ``colleague/tui/``) so it may call ``handoff`` /
``identity`` which shell out; imports no ``subprocess`` itself.
"""

from __future__ import annotations

from pathlib import Path


def resolve_repo_context(repo: Path) -> dict:
    """Resolve repo context facts in one guarded pass.

    Returns ``{"ident", "branch", "dirty", "is_git"}``.  Every value degrades
    to a safe default rather than raising.
    """
    try:
        from colleague import handoff, identity

        return {
            "ident": identity.resolve_identity(repo) or repo.name,
            "branch": handoff.current_ref(repo) or "unknown",
            "dirty": handoff.working_tree_dirty(repo),
            "is_git": handoff.is_git_repo(repo),
        }
    except Exception:  # noqa: BLE001
        return {
            "ident": repo.name,
            "branch": "unknown",
            "dirty": False,
            "is_git": False,
        }


def build_repo_context_panel(repo: Path) -> "Panel":
    """Build the Context panel for the cockpit.

    IDs, labels, and emoji match ``session.py`` ``_context_panel`` so TAUI
    selectors are identical across surfaces.
    """
    from colleague.tui.state import Panel, PanelItem

    facts = resolve_repo_context(repo)
    tree_status = "dirty (tracked changes)" if facts["dirty"] else "clean"
    return Panel(
        id="context",
        title="Context",
        visible=True,
        items=[
            PanelItem(id="ctx.repo", label="📁 repo", status=facts["ident"]),
            PanelItem(id="ctx.branch", label="🌿 branch", status=facts["branch"]),
            PanelItem(id="ctx.tree", label="🧭 working tree", status=tree_status),
        ],
    )


def build_cockpit_state(repo: Path) -> "CockpitState":
    """Build a minimal ``CockpitState`` with the repo-context panel."""
    from colleague.tui.state import CockpitState

    return CockpitState(panels=[build_repo_context_panel(repo)])
