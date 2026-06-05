"""``colleague whoami`` — the smallest identity probe.

Two identities, one glance. The *mesh identity* is declared in ``culture.yaml``:
the agent's nick (``suffix``) and the persona backend it runs as in the Culture
mesh. The *drive identity* is what actually executes outsourced repo work — the
engine a bare ``colleague drive`` would pick (``vllm-openai`` by default) and the
model it would call. These are resolved live from the same precedence a real
drive uses (``--engine`` flag > ``COLLEAGUE_ENGINE`` > default; provider config
via ``EngineConfig.resolve``), so the cheapest probe an agent can run before
delegating tells the truth about the delegate instead of reporting an unrelated
persona backend. Read-only; reads ``culture.yaml`` + environment, opens nothing.

When you clone this template, rename the package and update ``culture.yaml`` —
``whoami`` then reflects your new agent's mesh identity with no code change; the
drive identity follows your engine/provider config.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from colleague import __version__
from colleague.cli._output import emit_result
from colleague.config import EngineConfig, resolve_engine

_FALLBACK_NICK = "colleague"


def find_culture_yaml() -> Path | None:
    """Locate this agent's own ``culture.yaml`` by walking up from this module.

    The identity must be the agent's own, not whatever ``culture.yaml`` happens
    to sit in the caller's current working directory. In an editable / source
    install, walking up from ``__file__`` finds the repo root; in a wheel
    install no ``culture.yaml`` ships alongside the package and the caller falls
    back to the literal defaults.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "culture.yaml"
        if candidate.is_file():
            return candidate
    return None


def read_agent_fields() -> dict[str, str]:
    """Return ``suffix``/``backend``/``model`` from the first agent block.

    Parsed without a YAML dependency to keep the runtime deps empty. Reads
    top-level ``key: value`` lines within the first agent entry; anything
    fancier than the documented shape falls back to the defaults below.
    """
    fields = {"nick": _FALLBACK_NICK, "backend": "unknown", "model": "unknown"}
    cfg = find_culture_yaml()
    if cfg is None:
        return fields
    try:
        text = cfg.read_text(encoding="utf-8")
    except OSError:
        return fields
    seen_agent = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("- suffix:", "suffix:")):
            if seen_agent:  # second agent block — stop at the first
                break
            seen_agent = True
            fields["nick"] = _scalar(stripped, "suffix")
        elif seen_agent and stripped.startswith("backend:"):
            fields["backend"] = _scalar(stripped, "backend")
        elif seen_agent and stripped.startswith("model:"):
            fields["model"] = _scalar(stripped, "model")
    return fields


def _scalar(line: str, key: str) -> str:
    """Extract the scalar after ``key:`` from a ``culture.yaml`` line."""
    _, _, value = line.partition(f"{key}:")
    return value.strip().strip("'\"") or "unknown"


def report() -> dict[str, object]:
    fields = read_agent_fields()
    # The drive identity: what a bare ``colleague drive`` would actually run.
    # Resolved exactly as the drive path resolves it (and as ``doctor``'s
    # usage check does) so the probe never disagrees with reality. The mock
    # backend ignores provider config and calls no model, so its drive model
    # is ``None`` rather than the misleading default model id.
    drive_engine = resolve_engine(None)
    drive_model = None if drive_engine == "mock" else EngineConfig.resolve().model
    return {
        "nick": fields["nick"],
        "version": __version__,
        "backend": fields["backend"],
        "model": fields["model"],
        "drive_engine": drive_engine,
        "drive_model": drive_model,
    }


# ``None`` drive_model means the mock backend (which calls no model). Label it
# specifically rather than printing a bare ``None`` or a misleading default model
# id. One literal, one place — ``whoami`` and ``overview`` both render through
# ``format_drive_model`` so the two identity commands can never desync.
MOCK_DRIVE_MODEL_LABEL = "(mock backend — no model)"


def format_drive_model(drive_model: object) -> str:
    """Render a resolved drive model for display, shared by whoami + overview.

    ``is not None`` (not ``or``): only ``None`` means "no model" (the mock
    backend), never a falsy-but-present model string.
    """
    return MOCK_DRIVE_MODEL_LABEL if drive_model is None else str(drive_model)


def cmd_whoami(args: argparse.Namespace) -> None:
    identity = report()
    json_mode = bool(getattr(args, "json", False))
    if json_mode:
        emit_result(identity, json_mode=True)
        return
    drive_model = format_drive_model(identity["drive_model"])
    text = (
        f"nick: {identity['nick']}\n"
        f"version: {identity['version']}\n"
        f"mesh backend: {identity['backend']}\n"
        f"drive engine: {identity['drive_engine']}\n"
        f"drive model: {drive_model}"
    )
    emit_result(text, json_mode=False)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "whoami",
        help="Report nick, version, mesh backend, and the live drive engine + model.",
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=cmd_whoami)
