"""Bundled engine wheels.

Each engine is a class implementing :class:`colleague.engine.Engine`, advertised
through the ``colleague.engines`` entry-point group in ``pyproject.toml`` and
discovered at runtime by :mod:`colleague.registry`. Out-of-tree wheels register
the same way.
"""
