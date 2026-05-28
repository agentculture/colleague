"""Engines check-group — STUB.

Spec for the sibling agent who fills this in. This group verifies the **engine
wheels** discovered via the ``convertible.engines`` entry-point group, honouring
the all-engines rule: every engine is probed **uniformly**, with no special-case
code per engine. It must:

* Enumerate every discovered wheel via :func:`convertible.registry.catalog`
  (and/or ``names()``), and report what was found as an ``info`` check.
* Emit an ``error`` if **fewer than one** engine is registered (a convertible
  install with no engines cannot drive anything).
* Emit an ``error`` if either bundled engine — ``mock`` or ``vllm-openai`` — is
  missing from the catalog, or is present but **unloadable** (its entry point
  fails to import / instantiate). Probe loadability with
  :func:`convertible.registry.load`, catching the failure and turning it into a
  failed ``error`` check naming the engine and the import error.
* Probe out-of-tree engines uniformly too: a third-party wheel that registers
  but fails to load should surface as a failed check, not a crash.

Read-only: importing an entry-point target executes its module-load side
effects, which the contract treats as acceptable (the same import the loop does)
— but this group must not *drive* anything. Catch every per-engine error and
return it as a failed check; never raise.

Until implemented, returns ``[]``.
"""

from __future__ import annotations


def checks() -> list[dict]:
    """STUB — returns no checks yet. See module docstring for the spec."""
    return []
