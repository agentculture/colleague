"""colleague.resident — the Culture-resident runtime (mesh-member promotion).

This package is the **sanctioned async + networked exception** to colleague's
otherwise synchronous, socket-free runtime. The bounded ``colleague work`` path
stays byte-identical and async-free; the resident is a *separate*,
explicitly-opted-in long-lived process that joins the Culture mesh as a peer
(the born → trained → **resident** graduation, spec
``docs/specs/2026-06-10-colleague-graduates-from-a-born-and-trained-task-r.md``).
The boundary guard (``tests/test_boundary.py``) narrows accordingly: ``asyncio``
is permitted under ``colleague/resident/`` only; ``socket`` stays forbidden
everywhere (agentirc-cli owns the wire); ``subprocess`` is confined to
``colleague/resident/steward.py``.

Dependency boundary. The base colleague install is ``dependencies = []``. The
runtime seam (``agent-lifecycle``) and the IRC wire (``agentirc-cli``) ship only
in the opt-in ``[culture]`` extra. This package's **import-clean core** — this
module and :mod:`colleague.resident.steward` — pulls nothing third-party; only
the async seam adapters (``harness`` / ``transport`` / ``supervisor``) import
``agent_lifecycle`` / ``agentirc``, and only when the resident actually runs.
:func:`require_culture_deps` is the friendly gate: it turns a missing extra into
an actionable message instead of a raw :class:`ImportError`.
"""

from __future__ import annotations

#: The import package name for the ``agentirc-cli`` distribution (the IRC wire).
#: The distribution is ``agentirc-cli`` but it imports as ``agentirc``.
_AGENTIRC_IMPORT = "agentirc"

#: The import package name for the ``agent-lifecycle`` distribution (the seam).
_AGENT_LIFECYCLE_IMPORT = "agent_lifecycle"


class CultureExtraMissing(RuntimeError):
    """The ``[culture]`` optional extra is not installed.

    Raised by :func:`require_culture_deps` so an operator who runs a resident
    command without ``pip install "colleague[culture]"`` gets an actionable
    message rather than a bare :class:`ImportError` traceback.
    """


def require_culture_deps() -> None:
    """Verify the ``[culture]`` extra (agent-lifecycle + agentirc-cli) is importable.

    Imports are performed **here** (lazily), never at module top level, so
    importing :mod:`colleague.resident` stays third-party-clean
    (``tests/test_zero_deps.py``).

    Raises:
        CultureExtraMissing: with an install hint if either package is absent.
    """
    import importlib.util

    missing: list[str] = []
    if importlib.util.find_spec(_AGENT_LIFECYCLE_IMPORT) is None:
        missing.append("agent-lifecycle")
    if importlib.util.find_spec(_AGENTIRC_IMPORT) is None:
        missing.append("agentirc-cli")
    if missing:
        names = ", ".join(missing)
        raise CultureExtraMissing(
            f"the colleague[culture] extra is required to run the resident but is "
            f"missing: {names}. The extra needs Python >=3.12. Install it with: "
            f"uv tool install --python 3.12 'colleague[culture]' "
            f"(pip: pip install 'colleague[culture]'; in this checkout: "
            f"uv sync --extra culture)."
        )


__all__ = ["CultureExtraMissing", "require_culture_deps"]
