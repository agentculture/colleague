"""Snapshot quad — write and read a TUI frame capture.

A snapshot captures a complete TUI moment as four complementary files:

* ``<name>.taui.json``      — the semantic mirror (agent-readable dict)
* ``<name>.ansi``           — the visual frame (ANSI-coloured string)
* ``<name>.events.jsonl``   — the event trail (JSONL, one event per line)
* ``<name>.md``             — the Markdown render (human- and agent-readable)

Together these four files are *self-sufficient*: a debugger or agent can
reconstruct what the UI looked like, what the model saw, what happened, and
what the UI narrated — without a live process or any additional context.

Legacy support: ``read_snapshot`` gracefully handles snapshots created before the
``.md`` file was added (the original triple). It sets ``Snapshot.markdown = ""``
and does not raise if the ``.md`` file is absent.

Usage::

    from convertible.tui.snapshot import write_snapshot, read_snapshot

    paths = write_snapshot(directory, "bug-x", state, events)
    snap  = read_snapshot(directory, "bug-x")
    # snap.taui     == serialize(state)
    # snap.ansi     == render(state)
    # snap.events   == original event objects
    # snap.markdown == render_markdown(state)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from convertible.tui.events import dumps_events, loads_events
from convertible.tui.render.ansi import render
from convertible.tui.render.markdown import render_markdown
from convertible.tui.taui import serialize

try:
    from convertible.tui.state import CockpitState
except ImportError:  # pragma: no cover — TYPE_CHECKING guard
    CockpitState = Any  # type: ignore[assignment,misc]


def _validate_snapshot_name(name: str) -> str:
    """Return *name* if it is a safe, bare filename; else raise ``ValueError``.

    Guards against directory traversal: the snapshot ``name`` is interpolated
    into file paths, so a value containing path separators or ``..`` segments
    could escape the target directory. Reject anything that is not a plain
    basename.
    """
    if not name or Path(name).name != name or ".." in name:
        raise ValueError(
            f"invalid snapshot name {name!r}: must be a bare filename "
            "with no path separators or '..' segments"
        )
    return name


@dataclass
class Snapshot:
    """The four components of a TUI snapshot quad.

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
    markdown:
        The Markdown render string — the output of
        :func:`~convertible.tui.render.markdown.render_markdown`. Defaults
        to an empty string for backward compatibility with legacy triples.
    """

    taui: dict[str, Any]
    ansi: str
    events: list
    markdown: str = ""


def write_snapshot(
    directory: "str | Path",
    name: str,
    state: "CockpitState",
    events: list,
) -> dict[str, Path]:
    """Write the snapshot quad for *state* and *events* into *directory*.

    Parameters
    ----------
    directory:
        Target directory.  Created (with all parents) if it does not exist.
    name:
        Base name for the four files.  Must be a plain string — no path
        separators.
    state:
        The :class:`~convertible.tui.state.CockpitState` snapshot to capture.
    events:
        The event trail to store.  May be empty.

    Returns
    -------
    dict[str, Path]
        Mapping with keys ``"taui"``, ``"ansi"``, ``"events"``, and
        ``"markdown"`` pointing to the four written :class:`~pathlib.Path`
        objects.
    """
    _validate_snapshot_name(name)
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)

    taui_path = out / f"{name}.taui.json"
    ansi_path = out / f"{name}.ansi"
    events_path = out / f"{name}.events.jsonl"
    markdown_path = out / f"{name}.md"

    # Write semantic mirror — pretty JSON + trailing newline (artifact.py style)
    taui_path.write_text(
        json.dumps(serialize(state), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Write ANSI visual frame
    ansi_path.write_text(render(state), encoding="utf-8")

    # Write event trail as JSONL
    events_path.write_text(dumps_events(events), encoding="utf-8")

    # Write Markdown render
    markdown_path.write_text(render_markdown(state), encoding="utf-8")

    return {
        "taui": taui_path,
        "ansi": ansi_path,
        "events": events_path,
        "markdown": markdown_path,
    }


def read_snapshot(directory: "str | Path", name: str) -> Snapshot:
    """Read the snapshot quad back from *directory*.

    Parameters
    ----------
    directory:
        Directory that contains the snapshot files.
    name:
        Base name used when the snapshot was written.

    Returns
    -------
    Snapshot
        A :class:`Snapshot` dataclass with ``taui``, ``ansi``, ``events``,
        and ``markdown`` fields populated from the stored files. If the
        ``.md`` file does not exist (legacy triple), ``markdown`` defaults
        to an empty string.

    Notes
    -----
    This function supports legacy snapshots created before the markdown file
    was added. The three original files (`.taui.json`, `.ansi`, `.events.jsonl`)
    are required; the `.md` file is optional.
    """
    _validate_snapshot_name(name)
    out = Path(directory)

    taui = json.loads((out / f"{name}.taui.json").read_text(encoding="utf-8"))
    ansi = (out / f"{name}.ansi").read_text(encoding="utf-8")
    events = loads_events((out / f"{name}.events.jsonl").read_text(encoding="utf-8"))

    # Gracefully handle legacy snapshots: if .md doesn't exist, set to empty string
    markdown_path = out / f"{name}.md"
    markdown = markdown_path.read_text(encoding="utf-8") if markdown_path.exists() else ""

    return Snapshot(taui=taui, ansi=ansi, events=events, markdown=markdown)
