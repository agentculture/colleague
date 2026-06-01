"""Snapshot triple — write and read a TUI frame capture.

A snapshot captures a complete TUI moment as three complementary files:

* ``<name>.taui.json``      — the semantic mirror (agent-readable dict)
* ``<name>.ansi``           — the visual frame (ANSI-coloured string)
* ``<name>.events.jsonl``   — the event trail (JSONL, one event per line)

Together these three files are *self-sufficient*: a debugger or agent can
reconstruct what the UI looked like, what the model saw, and what happened —
without a live process or any additional context.

Usage::

    from convertible.tui.snapshot import write_snapshot, read_snapshot

    paths = write_snapshot(directory, "bug-x", state, events)
    snap  = read_snapshot(directory, "bug-x")
    # snap.taui   == serialize(state)
    # snap.ansi   == render(state)
    # snap.events == original event objects
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from convertible.tui.events import dumps_events, loads_events
from convertible.tui.render.ansi import render
from convertible.tui.taui import serialize

try:
    from convertible.tui.state import CockpitState
except ImportError:  # pragma: no cover — TYPE_CHECKING guard
    CockpitState = Any  # type: ignore[assignment,misc]


@dataclass
class Snapshot:
    """The three components of a TUI snapshot triple.

    Fields
    ------
    taui:
        The semantic mirror as a plain dict — the output of
        :func:`~convertible.tui.taui.serialize`.
    ansi:
        The rendered ANSI frame string — the output of
        :func:`~convertible.tui.render.ansi.render`.
    events:
        The event trail — a list of reconstructed event objects parsed by
        :func:`~convertible.tui.events.loads_events`.
    """

    taui: dict[str, Any]
    ansi: str
    events: list


def write_snapshot(
    directory: "str | Path",
    name: str,
    state: "CockpitState",
    events: list,
) -> dict[str, Path]:
    """Write the snapshot triple for *state* and *events* into *directory*.

    Parameters
    ----------
    directory:
        Target directory.  Created (with all parents) if it does not exist.
    name:
        Base name for the three files.  Must be a plain string — no path
        separators.
    state:
        The :class:`~convertible.tui.state.CockpitState` snapshot to capture.
    events:
        The event trail to store.  May be empty.

    Returns
    -------
    dict[str, Path]
        Mapping with keys ``"taui"``, ``"ansi"``, ``"events"`` pointing to
        the three written :class:`~pathlib.Path` objects.
    """
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)

    taui_path = out / f"{name}.taui.json"
    ansi_path = out / f"{name}.ansi"
    events_path = out / f"{name}.events.jsonl"

    # Write semantic mirror — pretty JSON + trailing newline (artifact.py style)
    taui_path.write_text(
        json.dumps(serialize(state), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Write ANSI visual frame
    ansi_path.write_text(render(state), encoding="utf-8")

    # Write event trail as JSONL
    events_path.write_text(dumps_events(events), encoding="utf-8")

    return {"taui": taui_path, "ansi": ansi_path, "events": events_path}


def read_snapshot(directory: "str | Path", name: str) -> Snapshot:
    """Read the snapshot triple back from *directory*.

    Parameters
    ----------
    directory:
        Directory that contains the three snapshot files.
    name:
        Base name used when the snapshot was written.

    Returns
    -------
    Snapshot
        A :class:`Snapshot` dataclass with ``taui``, ``ansi``, and ``events``
        fields populated from the stored files.
    """
    out = Path(directory)

    taui = json.loads((out / f"{name}.taui.json").read_text(encoding="utf-8"))
    ansi = (out / f"{name}.ansi").read_text(encoding="utf-8")
    events = loads_events((out / f"{name}.events.jsonl").read_text(encoding="utf-8"))

    return Snapshot(taui=taui, ansi=ansi, events=events)
