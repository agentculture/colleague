"""Bundled engine wheels.

Each engine is a class implementing :class:`convertible.engine.Engine`, advertised
through the ``convertible.engines`` entry-point group in ``pyproject.toml`` and
discovered at runtime by :mod:`convertible.registry`. Out-of-tree wheels register
the same way.
"""
