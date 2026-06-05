"""Dev-only tooling for the colleague repo (not shipped in the wheel).

The wheel ships ``packages = ["colleague"]`` only (see ``pyproject.toml``); this
``tools`` package holds maintainer utilities that *import* colleague but are never
part of the distribution.
"""
