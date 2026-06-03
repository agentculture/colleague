"""Engines check-group — backend-plugin discovery and loadability (all-engines rule).

Probes every backend discovered via the ``colleague.engines`` entry-point group
uniformly. No backend is special-cased; behaviour must be symmetric across all
backends including out-of-tree plugins.

Checks emitted (in order):
1. ``engines_discovered`` (error) — fails if fewer than one engine is registered.
2. ``bundled_engines_present`` (error) — fails if either ``mock`` or
   ``vllm-openai`` is absent from the catalog. Remediation points toward
   ``pyproject.toml``'s ``[project.entry-points."colleague.engines"]`` table.
3. One ``engine_load_<name>`` (error) per discovered engine — fails if
   instantiating the engine raises any exception. The failure message names the
   engine and the error; remediation guides the operator to check the wheel's
   entry-point target.

Read-only: importing an entry-point target executes module-load side effects
(the same import the tool-loop does), which the contract accepts. This group
never drives a task, writes a file, or opens a socket.

Never raises: every per-engine error is caught and turned into a failed check.
"""

from __future__ import annotations

from colleague import registry
from colleague.oilcheck import make_check

#: The two engines that ship with this repo and must always be present.
_BUNDLED_ENGINES = ("mock", "vllm-openai")


def checks() -> list[dict]:
    """Return backend-plugin health checks (see module docstring)."""
    out: list[dict] = []

    # 1. Discover all registered engines.
    try:
        discovered = registry.catalog()
    except Exception as exc:  # noqa: BLE001
        out.append(
            make_check(
                "engines_discovered",
                False,
                "error",
                f"failed to enumerate engines: {exc}",
                remediation=(
                    "check that the package is installed correctly and "
                    "colleague.engines entry points are registered"
                ),
            )
        )
        return out

    engine_names = [w.name for w in discovered]
    n = len(engine_names)

    # Check 1: at least one engine must be present.
    if n < 1:
        out.append(
            make_check(
                "engines_discovered",
                False,
                "error",
                "no engines discovered in the colleague.engines entry-point group",
                remediation=(
                    "ensure colleague is installed (uv sync) so the bundled "
                    "mock and vllm-openai entry points are registered"
                ),
            )
        )
    else:
        out.append(
            make_check(
                "engines_discovered",
                True,
                "error",
                f"{n} engine(s) discovered: {', '.join(sorted(engine_names))}",
            )
        )

    # Check 2: both bundled engines must be present.
    missing_bundled = [name for name in _BUNDLED_ENGINES if name not in engine_names]
    if missing_bundled:
        out.append(
            make_check(
                "bundled_engines_present",
                False,
                "error",
                f"bundled engine(s) missing from catalog: {', '.join(missing_bundled)}",
                remediation=(
                    "ensure the missing engines are declared in "
                    'pyproject.toml under [project.entry-points."colleague.engines"] '
                    "and the package is reinstalled (uv sync)"
                ),
            )
        )
    else:
        out.append(
            make_check(
                "bundled_engines_present",
                True,
                "error",
                f"bundled engines present: {', '.join(_BUNDLED_ENGINES)}",
            )
        )

    # Check 3: attempt to load (instantiate) every discovered engine uniformly.
    for wheel in discovered:
        name = wheel.name
        check_id = f"engine_load_{name.replace('-', '_')}"
        try:
            registry.load(name)
            out.append(
                make_check(
                    check_id,
                    True,
                    "error",
                    f"engine '{name}' loaded and instantiated successfully",
                )
            )
        except Exception as exc:  # noqa: BLE001
            out.append(
                make_check(
                    check_id,
                    False,
                    "error",
                    f"engine '{name}' failed to load: {exc}",
                    remediation=(
                        f"check the entry-point target for '{name}' in pyproject.toml "
                        "or the wheel's metadata; ensure the engine class can be "
                        "imported and instantiated without arguments"
                    ),
                )
            )

    return out
