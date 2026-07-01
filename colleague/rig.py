"""Rig-level cooperative concurrency budget (plan t13 / spec R5 / issue #258).

One served endpoint is shared by every colleague process on a machine — two
concurrent ``colleague work`` invocations know nothing of each other, so a
single serializing GPU gets double-booked and both runs starve toward the
request timeout (#239's interference class). This module is the coordination
seam: an operator-declared ``.colleague/rig.json`` names the endpoint's
sustainable concurrency, and a **file-based cooperative slot** (atomic
``mkdir`` under ``.colleague/rig-slots/``) is taken for the duration of each
work item's loop.

Honest contract:

- **Cooperative, not admission control** — only colleague processes that ask
  for a slot are governed; a non-colleague client of the same endpoint is not.
- **Strict no-op when unconfigured** — no ``rig.json`` (or a malformed one)
  means no slot files are ever created and acquisition returns instantly.
- **Degrades open, never wedges** — a work item that cannot get a slot within
  ``max_wait`` proceeds WITHOUT one (with an honest warning via ``on_wait``)
  rather than deadlocking the operator's run; the budget is advisory backstop,
  not a gate.
- **Stale slots self-heal** — each slot records its holder's PID; a slot whose
  process is gone is reclaimed (crash recovery, the ``clean``-adjacent
  philosophy).
- **No daemon, no socket, no threads** — stdlib ``os``/``json``/``pathlib``/
  ``time`` only; atomicity comes from ``mkdir`` semantics. ``subprocess`` is
  never touched (the boundary tests' discipline).
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, Optional

from colleague import configdir

#: The operator-declared rig config, resolved via configdir (repo over user).
RIG_FILENAME = "rig.json"
#: Slot directory name under the repo's .colleague/ bookkeeping dir.
_SLOTS_DIRNAME = "rig-slots"
#: How long acquire polls before degrading open (seconds).
_DEFAULT_MAX_WAIT = 300.0
#: Poll interval while waiting for a slot (seconds).
_DEFAULT_POLL = 0.5


def load_rig_concurrency(repo_path: str | Path) -> Optional[int]:
    """The rig's declared sustainable concurrency, or ``None`` when unconfigured.

    Reads ``.colleague/rig.json`` (configdir-resolved: repo over user, legacy
    ``.convertible`` honored) and returns its positive-int ``concurrency`` key.
    Missing file, malformed JSON, or an invalid value is a strict no-op
    (``None``) — never raises.
    """
    path = configdir.resolve_file(repo_path, RIG_FILENAME)
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    concurrency = data.get("concurrency")
    if isinstance(concurrency, bool) or not isinstance(concurrency, int):
        return None
    return concurrency if concurrency > 0 else None


def _slots_dir(repo_path: str | Path) -> Path:
    return Path(repo_path) / configdir.CONFIG_DIR_NAME / _SLOTS_DIRNAME


def _slot_holder_pid(slot: Path) -> Optional[int]:
    """The PID recorded in a slot, or ``None`` when unreadable."""
    try:
        return int((slot / "pid").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    """Best-effort same-host liveness probe (a rig is one host by definition)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        # Exists but not ours (PermissionError) or unprobeable — treat as
        # alive, never steal.
        return True
    return True


def _reap_stale_slot(slot: Path) -> None:
    """Remove a slot whose holder is gone; racing reapers are both safe."""
    try:
        (slot / "pid").unlink(missing_ok=True)
        slot.rmdir()
    except OSError:
        # Another process reaped it first, or the holder is mid-write — leave it.
        pass


def _try_take_slot(slots: Path, width: int) -> Optional[Path]:
    """One non-blocking pass over the slot indices; the taken slot or ``None``.

    ``mkdir`` is the atomic take; a stale slot (dead holder PID) is reaped and
    retried once in the same pass.
    """
    for index in range(width):
        slot = slots / f"slot-{index}"
        for _attempt in (0, 1):  # second attempt only after reaping a stale slot
            try:
                slot.mkdir(parents=True, exist_ok=False)
            except FileExistsError:
                holder = _slot_holder_pid(slot)
                if holder is not None and not _pid_alive(holder):
                    _reap_stale_slot(slot)
                    continue  # retry this index once after the reap
                break  # genuinely held — next index
            except OSError:
                break  # unwritable bookkeeping dir — next index (degrade open)
            try:
                (slot / "pid").write_text(str(os.getpid()), encoding="utf-8")
            except OSError:
                pass  # a pid-less slot still works; it just can't be reaped early
            return slot
    return None


def _release_slot(slot: Path) -> None:
    """Release a held slot; already-gone artifacts are fine (idempotent)."""
    try:
        (slot / "pid").unlink(missing_ok=True)
        slot.rmdir()
    except OSError:
        pass


def _wait_for_slot(
    slots: Path,
    width: int,
    *,
    on_wait: Optional[Callable[[str], None]],
    max_wait: float,
    poll: float,
) -> Optional[Path]:
    """Poll for a slot until *max_wait* elapses; ``None`` = degrade open.

    Extracted from :func:`rig_slot` (SonarCloud S3776). ``on_wait`` fires once
    when waiting starts and once more if the wait degrades open.
    """
    if on_wait is not None:
        on_wait(f"waiting for a rig slot ({width} configured, all busy)")
    deadline = time.monotonic() + max(0.0, max_wait)
    slot: Optional[Path] = None
    while slot is None and time.monotonic() < deadline:
        time.sleep(max(0.05, poll))
        slot = _try_take_slot(slots, width)
    if slot is None and on_wait is not None:
        on_wait(
            "rig slot wait exceeded — proceeding without a slot "
            "(cooperative budget degrades open, never wedges a run)"
        )
    return slot


@contextmanager
def rig_slot(
    repo_path: str | Path,
    *,
    on_wait: Optional[Callable[[str], None]] = None,
    max_wait: float = _DEFAULT_MAX_WAIT,
    poll: float = _DEFAULT_POLL,
) -> Iterator[bool]:
    """Hold one rig slot for the duration of the ``with`` body.

    Yields ``True`` when a slot was held, ``False`` when the rig is
    unconfigured (strict no-op) or the wait degraded open. ``on_wait`` (when
    given) is called with a human-readable line the FIRST time the caller
    starts waiting, and again if it eventually proceeds without a slot — the
    progress-feed visibility hook ("waiting for rig slot"), never a logger.
    """
    width = load_rig_concurrency(repo_path)
    if width is None:
        yield False
        return
    slots = _slots_dir(repo_path)
    slot = _try_take_slot(slots, width)
    if slot is None:
        slot = _wait_for_slot(slots, width, on_wait=on_wait, max_wait=max_wait, poll=poll)
    try:
        yield slot is not None
    finally:
        if slot is not None:
            _release_slot(slot)
