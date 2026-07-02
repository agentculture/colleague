"""CI gate: colleague's agent-facing surfaces cannot drift apart (#262).

agentfront 0.20.0 ships the public consumer testing harness
(``agentfront.testing``); colleague — the first external consumer of the
import-rendered CLI (#247) and of ``agentfront.taui`` (#249) — adopts the
one-line surface-agreement gate as the external half of agentfront's success
signal (agentfront#49). It checks the doc/tool inventory across CLI, MCP,
HTTP, and TAUI against the registry, and that the HTTP ``/front`` body agrees
with the TAUI markdown tier; on drift it raises naming the drifted surface and
the missing/extra entries. Complements ``tests/test_cross_surface_parity.py``
(colleague's own catalog set-equality pins) with the upstream invariant.
"""

from agentfront.testing import assert_surfaces_agree

from colleague.cli._app import build_app


def test_surfaces_agree() -> None:
    assert_surfaces_agree(build_app())
