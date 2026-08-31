""".colleague/config.json loading, provenance, and the env/value primitives.

Every read of an operator config file lives here: the per-key merge across
configdir roots (:func:`_merged_config_json`), the typed section loaders each
``EngineConfig.resolve`` rung consults, and the small env-pick / coercion
primitives (``_pick``, ``_file_or_default``, ``_try_int`` …) the rest of the
config siblings share. Split out of ``config.py`` (hard 1000-line file limit,
plan ``hard-1000-line-file-limit`` t14) — a pure move, no semantics changed.

One deliberate seam: the loaders below reach the merged JSON through
:func:`_merged_for`, which dispatches via ``colleague.config`` rather than
calling the local function directly. That keeps the long-standing
``monkeypatch.setattr("colleague.config._merged_config_json", …)`` target
EFFECTIVE (tests/test_cli_flags_listing.py, tests/test_cli_not_consumed.py) —
a patch that silently stopped binding would leave those tests green while
testing nothing.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from colleague import configdir
from colleague.config_defaults import (
    _CONFIG_FILENAME,
    _CONFIG_KEYS,
    _DEEPTHINK_CONFIG_KEYS,
    _DISTILLER_CONFIG_KEYS,
    _REALTIME_CONFIG_KEYS,
    _SEAT_CONFIG_KEYS,
    _SENSES_CONFIG_KEYS,
    _VOICE_CONFIG_KEYS,
    _WORKER_CONFIG_KEYS,
    MAX_SUBAGENT_FANOUT,
)


def _merged_for(repo_path: str | Path) -> dict:
    """The merged config.json, dispatched through :mod:`colleague.config`.

    Deliberate indirection, not ceremony: ``colleague.config._merged_config_json``
    is a landed monkeypatch seam (two tests patch it to force an empty
    config.json). Calling the local definition directly would rebind at import
    time and make those patches inert — green, but testing nothing. Going
    through the module attribute keeps them effective.
    """
    from colleague import config as _config

    return _config._merged_config_json(repo_path)


def _pick(explicit: str | None, *env_keys: str, default: str) -> str:
    if explicit is not None:
        return explicit
    for key in env_keys:
        value = os.environ.get(key)
        if value:
            return value
    return default


def _file_or_default(file_value: str | None, default: str) -> str:
    """``file_value if file_value is not None else default`` as a plain helper.

    Several of :meth:`EngineConfig.resolve`'s numeric-knob defaults (the lint /
    test-integrity / affected-tests retry+depth+max-files knobs) share this
    exact "config.json value, else the builtin default" shape. Calling a
    helper instead of inlining the ternary keeps that branching cost off
    ``resolve``'s own cognitive-complexity tally (SonarCloud S3776) — a
    ternary/if-expression contributes to whichever function's body it lives
    in, so extracting it here (mirroring :func:`_resolve_lobes_rung`'s
    extraction for the same reason) is a pure extraction with no behavior
    change.
    """
    return file_value if file_value is not None else default


def _read_json_object(path: Path) -> dict:
    """Read *path* as a JSON object; a missing/malformed/non-dict payload yields ``{}``.

    Never raises — the shared per-file primitive :func:`_merged_config_json`
    uses so that one malformed level (bad JSON, or JSON that isn't an object)
    is skipped for THAT level only, never aborting the merge of the other
    levels.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _merged_config_json(repo_path: str | Path) -> dict:
    """Merge every resolved ``.colleague/config.json`` across configdir roots, PER TOP-LEVEL KEY.

    Root-cause fix for the whole-file shadow bug (task t1): a repo-level
    ``config.json`` that never mentions ``lobes`` (or ``senses``/``voice``/
    ``deepthink``/``base_url``/...) used to make a same-named USER-level
    default disappear entirely, because :func:`colleague.configdir.resolve_file`
    returns only the first existing match. This instead reads EVERY existing
    match (:func:`colleague.configdir.resolve_files`, precedence order
    highest-first: ``repo/.colleague`` > ``repo/.convertible`` >
    ``user/.colleague`` > ``user/.convertible``) and merges them so a
    higher-precedence file's top-level key wins, but a key ABSENT there falls
    through to the next lower-precedence file that does define it.

    Merge granularity is the TOP-LEVEL KEY only — a key's value (e.g. an
    entire nested ``senses``/``deepthink``/``voice`` object) is taken
    wholesale from whichever file supplies that key first; there is no deep
    merge *inside* a section (a repo-level ``senses`` section wholly replaces
    a user-level one, it does not fold field-by-field).

    Malformed JSON, an unreadable file, or a non-dict payload at any single
    level is skipped for THAT level only via :func:`_read_json_object` — it
    never raises and never prevents the other levels from contributing. No
    matching files at all returns ``{}`` (byte-identical to the pre-merge
    "no config file" case).
    """
    paths = configdir.resolve_files(repo_path, _CONFIG_FILENAME)
    merged: dict = {}
    # Fold lowest-precedence first so each higher-precedence file's keys
    # overwrite it afterwards — "repo wins per-key, user fills the gaps".
    for path in reversed(paths):
        merged.update(_read_json_object(path))
    return merged


def load_config_file(repo_path: str | Path) -> dict[str, str]:
    """Load the persistent config, PER-KEY merged across .colleague/config.json roots.

    Uses :func:`_merged_config_json` (in turn built on
    :func:`colleague.configdir.resolve_files`) so a repo-level file that
    doesn't mention ``base_url``/``api_key``/``model`` no longer shadows a
    user-level default for that same key (task t1) — see that function's
    docstring for the exact merge + malformed-input semantics.

    Returns a dict containing only the recognised keys (``base_url``,
    ``api_key``, ``model``). No matching file, malformed JSON at every level,
    or any read error yields an empty dict and never raises.
    """
    data = _merged_for(repo_path)
    return {k: str(v) for k, v in data.items() if k in _CONFIG_KEYS and v is not None}


def config_provenance(repo_path: str | Path) -> list[dict]:
    """Return provenance for every config.json that contributed keys.

    Mirrors :func:`_merged_config_json`'s semantics: calls
    :func:`colleague.configdir.resolve_files` for ``config.json``, reads each
    existing file with :func:`_read_json_object`, and reports per-file
    top-level keys plus the subset that actually *win* the per-key merge
    (no higher-precedence file also sets that key). Files that read as ``{}``
    (malformed, missing, or empty) are skipped — exactly as
    :func:`_merged_config_json` handles them.

    Returns a list of dicts, highest-precedence first, each with::

        {'path': str(path), 'keys': sorted list of top-level keys,
         'winning_keys': sorted list of keys this file wins}

    Empty list when no config files exist.
    """
    paths = configdir.resolve_files(repo_path, _CONFIG_FILENAME)
    # Build per-file data: path -> (keys_set, data_dict)
    file_data: list[tuple[Path, dict]] = []
    for path in paths:
        data = _read_json_object(path)
        if data:
            file_data.append((path, data))

    # Determine winning keys: a key wins for the highest-precedence file
    # that sets it (first in file_data order).
    claimed: dict[str, str] = {}  # key -> path string of the winner
    for path, data in file_data:
        for key in data:
            if key not in claimed:
                claimed[key] = str(path)

    result: list[dict] = []
    for path, data in file_data:
        keys = sorted(data.keys())
        winning_keys = sorted(k for k in keys if claimed[k] == str(path))
        result.append(
            {
                "path": str(path),
                "keys": keys,
                "winning_keys": winning_keys,
            }
        )
    return result


def _load_deepthink_overrides(repo_path: str | Path) -> dict[str, str]:
    """Read the NESTED ``deepthink`` section of .colleague/config.json, per-key merged.

    Mirrors :func:`load_config_file`'s merge (task t1: reads the ``deepthink``
    key from :func:`_merged_config_json` instead of the first-match-only
    file) but reads a *nested* object (``{"deepthink": {...}}``) instead of
    top-level keys — ``load_config_file``'s ``dict[str, str]`` endpoint
    contract (base_url/api_key/model) must not change. Returns a dict of
    stringified values for the recognised keys (``model``, ``base_url``,
    ``api_key``, ``context_budget``). No file defining ``deepthink``, or an
    absent/non-dict ``deepthink`` section wherever it IS defined, yields an
    empty dict and never raises. Merge granularity is the top-level ``deepthink``
    key itself — the section is taken wholesale from whichever config file
    defines it first (highest precedence), never deep-merged field-by-field
    with a lower-precedence file's ``deepthink`` section.
    """
    data = _merged_for(repo_path)
    section = data.get("deepthink")
    if not isinstance(section, dict):
        return {}
    return {
        key: str(value)
        for key, value in section.items()
        if key in _DEEPTHINK_CONFIG_KEYS and value is not None
    }


def _load_senses_overrides(repo_path: str | Path) -> dict[str, str]:
    """Read the NESTED ``senses`` section of .colleague/config.json, per-key merged.

    Mirrors :func:`_load_deepthink_overrides` field-for-field (cortex/senses
    arc, task t3; per-key merge added in task t1) — reads a *nested* object
    (``{"senses": {...}}``) instead of top-level keys, so
    ``load_config_file``'s ``dict[str, str]`` endpoint contract (base_url/
    api_key/model) stays unchanged. Returns a dict of stringified values for
    the recognised keys (``model``, ``base_url``, ``api_key``,
    ``context_budget``, ``multimodal``). No file defining ``senses``, or an
    absent/non-dict ``senses`` section wherever it IS defined, yields an empty
    dict and never raises. Merge granularity is the top-level ``senses`` key
    itself — see :func:`_merged_config_json`.
    """
    data = _merged_for(repo_path)
    section = data.get("senses")
    if not isinstance(section, dict):
        return {}
    return {
        key: str(value)
        for key, value in section.items()
        if key in _SENSES_CONFIG_KEYS and value is not None
    }


def _load_voice_overrides(repo_path: str | Path) -> dict[str, str]:
    """Read the NESTED ``voice`` section of .colleague/config.json, per-key merged.

    Mirrors :func:`_load_senses_overrides` field-for-field (per-key merge
    added in task t1) — reads a *nested* object (``{"voice": {...}}``) for
    the recognised keys (``stt_model``, ``tts_model``, ``base_url``,
    ``api_key``). No file defining ``voice``, or an absent/non-dict ``voice``
    section wherever it IS defined, yields an empty dict and never raises.
    Merge granularity is the top-level ``voice`` key itself — see
    :func:`_merged_config_json`.
    """
    data = _merged_for(repo_path)
    section = data.get("voice")
    if not isinstance(section, dict):
        return {}
    return {
        key: str(value)
        for key, value in section.items()
        if key in _VOICE_CONFIG_KEYS and value is not None
    }


def _load_realtime_overrides(repo_path: str | Path) -> dict[str, str]:
    """Read the NESTED ``realtime`` section of .colleague/config.json, per-key merged.

    Mirrors :func:`_load_voice_overrides` field-for-field (realtime-speech arc,
    plan task t1) — reads a *nested* object (``{"realtime": {...}}``) for the
    recognised keys (``url``, ``api_key``, ``input_device``, ``output_device``
    — the latter two added task t4). No file defining ``realtime``, or an
    absent/non-dict ``realtime`` section wherever it IS defined, yields an
    empty dict and never raises. Merge granularity is the top-level
    ``realtime`` key itself — see :func:`_merged_config_json`.
    """
    data = _merged_for(repo_path)
    section = data.get("realtime")
    if not isinstance(section, dict):
        return {}
    return {
        key: str(value)
        for key, value in section.items()
        if key in _REALTIME_CONFIG_KEYS and value is not None
    }


def _load_three_tier_override(repo_path: str | Path) -> str | None:
    """Read the ``three_tier`` key from .colleague/config.json as a raw string
    (three-tier-execution arc, plan task t3).

    Accepts either a bare boolean (``{"three_tier": true}``) or a nested
    object (``{"three_tier": {"enabled": true}}`` — the object's own
    presence, absent an explicit ``"enabled": false``, is itself treated as
    armed — the same bare-string-or-object tolerance :func:`_load_lobes_override`
    applies to the ``lobes`` key). Returns the stringified boolean value, or
    ``None`` when the key is absent; never raises. Reads via
    :func:`_merged_config_json` (the at-home per-key merge, #339): a
    repo-level file that omits the key falls through to a user-level default.
    """
    data = _merged_for(repo_path)
    section = data.get("three_tier")
    if section is None:
        return None
    if isinstance(section, dict):
        # Preserve the RAW value so _parse_bool downstream handles string
        # booleans — bool("false") is True, which would arm three-tier on an
        # explicit {"enabled": "false"} disable (Qodo #367 review, thread 4).
        return str(section.get("enabled", True))
    return str(section)


def _load_thought_action_evaluation_override(repo_path: str | Path) -> str | None:
    """Read the ``thought_action_evaluation`` key from .colleague/config.json as
    a raw string (post-#387 program, plan task t12; issue #397).

    The exact shape of :func:`_load_three_tier_override` against a DIFFERENT
    key — arming this mode must never arm three-tier, and vice versa. Accepts
    a bare boolean (``{"thought_action_evaluation": true}``) or a nested object
    (``{"thought_action_evaluation": {"enabled": true}}``, whose bare presence
    is itself armed). The RAW value is preserved so ``_parse_bool`` downstream
    handles string booleans (``bool("false")`` is True — the Qodo #367
    regression class). Reads via :func:`_merged_config_json` (the at-home
    per-key merge, #339), so a machine-wide default survives a repo-level
    config.json that omits the key. Never raises.
    """
    data = _merged_for(repo_path)
    section = data.get("thought_action_evaluation")
    if section is None:
        return None
    if isinstance(section, dict):
        return str(section.get("enabled", True))
    return str(section)


def _load_agents_override(repo_path: str | Path) -> str | None:
    """Read the ``agents`` key from .colleague/config.json as a raw string (#411 t7).

    Accepts either a bare boolean (``{"agents": true}``) or a nested object
    (``{"agents": {"enabled": true}}`` — the object's own presence, absent an
    explicit ``"enabled": false``, is itself treated as armed — the
    ``three_tier`` / ``thought_action_evaluation`` tolerance). Returns the
    stringified value, or ``None`` when the key is absent; never raises. Reads
    via :func:`_merged_config_json` (the at-home per-key merge, #339).
    """
    data = _merged_for(repo_path)
    section = data.get("agents")
    if section is None:
        return None
    if isinstance(section, dict):
        return str(section.get("enabled", True))
    return str(section)


def _load_distiller_override(repo_path: str | Path) -> str | None:
    """Read the declared DISTILLER checkpoint id from .colleague/config.json
    (plan task t12; spec c38/h30).

    Accepts a bare string (``{"distiller": "some/model"}``) or a nested object
    (``{"distiller": {"model": "some/model"}}``) — the ``lobes``
    bare-string-or-object tolerance. Returns the raw id, or ``None`` when
    absent/blank. Per-key merged (:func:`_merged_config_json`); never raises.
    """
    data = _merged_for(repo_path)
    section = data.get("distiller")
    if section is None:
        return None
    if isinstance(section, dict):
        recognised = {
            key: value
            for key, value in section.items()
            if key in _DISTILLER_CONFIG_KEYS and value is not None
        }
        value = recognised.get("model")
        return str(value) if value is not None else None
    return str(section)


def _load_seat_overrides(repo_path: str | Path, section_name: str) -> dict[str, str]:
    """Read one NESTED seat section (``front``/``worker``/``evaluator``) of
    .colleague/config.json, per-key merged (plan task t12).

    The generalisation of :func:`_load_worker_overrides` over a seat name: the
    recognised key set is deliberately narrow (:data:`_SEAT_CONFIG_KEYS` —
    ``api_key`` only) because a seat carries NO declared model/base_url; seats
    are resolved ONLY by lobes role-NAME discovery, never model-name parsing.
    A missing/non-dict section yields an empty dict and never raises.
    """
    data = _merged_for(repo_path)
    section = data.get(section_name)
    if not isinstance(section, dict):
        return {}
    return {
        key: str(value)
        for key, value in section.items()
        if key in _SEAT_CONFIG_KEYS and value is not None
    }


def _load_worker_overrides(repo_path: str | Path) -> dict[str, str]:
    """Read the NESTED ``worker`` section of .colleague/config.json, per-key merged
    (three-tier-execution arc, plan task t3).

    Mirrors :func:`_load_senses_overrides`'s extraction shape but the
    recognised key set is deliberately narrow (:data:`_WORKER_CONFIG_KEYS` —
    ``api_key`` only): unlike deepthink/senses/voice, worker carries no
    declared model/base_url — the worker seat is resolved ONLY via lobes
    role-NAME discovery (:func:`_resolve_worker`), never model-name parsing
    (the t3 design boundary). No file defining ``worker``, or an
    absent/non-dict ``worker`` section wherever it IS defined, yields an
    empty dict and never raises. Merge granularity is the top-level
    ``worker`` key itself — see :func:`_merged_config_json`.
    """
    data = _merged_for(repo_path)
    section = data.get("worker")
    if not isinstance(section, dict):
        return {}
    return {
        key: str(value)
        for key, value in section.items()
        if key in _WORKER_CONFIG_KEYS and value is not None
    }


def _load_lobes_override(repo_path: str | Path) -> str | None:
    """Read the lobes gateway URL from the ``lobes`` key of config.json, per-key merged.

    Task t1's motivating fix: a repo-level ``config.json`` that never
    mentions ``lobes`` used to shadow a user-level machine-wide default
    whole-file (:func:`colleague.configdir.resolve_file` returns only the
    first match). This now reads the ``lobes`` key from
    :func:`_merged_config_json`, so a user-level ``lobes`` default survives a
    repo-level ``config.json`` that carries unrelated keys — but a
    repo-level ``lobes`` key, when present, still wins outright (per-key
    merge, not a fallback chain within the value itself).

    Accepts either a bare string (``{"lobes": "http://host:8001"}``) or a nested
    object with a ``url`` key (``{"lobes": {"url": "http://host:8001"}}``). No
    file defining ``lobes``, malformed JSON at every level, a non-dict payload,
    or an absent/blank section yields ``None`` and never raises. NO network —
    this only reads the URL.
    """
    data = _merged_for(repo_path)
    section = data.get("lobes")
    if isinstance(section, str):
        return section.strip() or None
    if isinstance(section, dict):
        url = section.get("url")
        if isinstance(url, str) and url.strip():
            return url.strip()
    return None


def _load_lint_overrides(repo_path: str | Path) -> tuple[str | None, str | None]:
    """Read ``lint`` / ``lint_fix_retries`` from .colleague/config.json as raw strings.

    Kept separate from :func:`load_config_file` (whose ``dict[str, str]`` endpoint
    contract — base_url/api_key/model — must not change): the lint keys carry a
    bool / int, not an endpoint string. Returns ``(lint, lint_fix_retries)`` where
    each is the stringified config value or ``None`` when absent. A missing or
    malformed file yields ``(None, None)`` and never raises. Reads via
    :func:`_merged_config_json` (the at-home per-key merge, #339): a repo-level
    file that omits these keys no longer shadows a user-level default.
    """
    data = _merged_for(repo_path)
    lint = data.get("lint")
    retries = data.get("lint_fix_retries")
    return (
        None if lint is None else str(lint),
        None if retries is None else str(retries),
    )


def _load_testintegrity_overrides(repo_path: str | Path) -> tuple[str | None, str | None]:
    """Read ``testintegrity`` / ``testintegrity_fix_retries`` from config.json as strings.

    Mirrors :func:`_load_lint_overrides` (kept separate from
    :func:`load_config_file`, whose endpoint-string contract must not change): these
    keys carry a bool / int. Returns ``(testintegrity, testintegrity_fix_retries)``,
    each the stringified value or ``None`` when absent. A missing/malformed file
    yields ``(None, None)`` and never raises. Reads via
    :func:`_merged_config_json` (the at-home per-key merge, #339): a repo-level
    file that omits these keys no longer shadows a user-level default.
    """
    data = _merged_for(repo_path)
    enabled = data.get("testintegrity")
    retries = data.get("testintegrity_fix_retries")
    return (
        None if enabled is None else str(enabled),
        None if retries is None else str(retries),
    )


def _load_watch_override(repo_path: str | Path) -> str | None:
    """Read the ``watch`` key from .colleague/config.json as a raw string (#307).

    Mirrors :func:`_load_coherence_override` — kept separate from
    :func:`load_config_file` (which owns only the endpoint keys). Reads via
    :func:`_merged_config_json` (the at-home per-key merge, #339): a repo-level
    file that omits the key no longer shadows a user-level default.
    """
    data = _merged_for(repo_path)
    value = data.get("watch")
    return None if value is None else str(value)


def _load_chain_overrides(repo_path: str | Path) -> tuple[str | None, str | None, str | None]:
    """Read ``until_done`` / ``max_episodes`` / ``compaction_cap`` from
    .colleague/config.json as raw strings.

    Mirrors :func:`_load_lint_overrides` (kept separate from
    :func:`load_config_file`, whose endpoint-string contract must not change):
    these keys carry a bool / int. Returns ``(until_done, max_episodes,
    compaction_cap)``, each the stringified value or ``None`` when absent. A
    missing/malformed file yields ``(None, None, None)`` and never raises.
    ``compaction_cap`` (#334) rides the same top-level-key convention as
    ``max_episodes`` — a sibling config knob, not a chain-driver setting, but
    read here to reuse the one file-parse. Reads via
    :func:`_merged_config_json` (the at-home per-key merge, PR #338 review):
    a repo-level file that omits one of these keys no longer shadows a
    user-level default for it.
    """
    data = _merged_for(repo_path)
    until_done = data.get("until_done")
    max_episodes = data.get("max_episodes")
    compaction_cap = data.get("compaction_cap")
    return (
        None if until_done is None else str(until_done),
        None if max_episodes is None else str(max_episodes),
        None if compaction_cap is None else str(compaction_cap),
    )


def _str_dict(d: object) -> "dict[str, str]":
    """``{k: str(v)...}`` for a ``dict``, else ``{}`` — the override-map shape."""
    return {k: str(v) for k, v in d.items() if v is not None} if isinstance(d, dict) else {}


def _load_reasoning_effort_overrides(
    repo_path: str | Path,
) -> tuple[str | None, dict[str, str], dict[str, str], str | None]:
    """Read ``reasoning_effort``/``_seats``/``_purposes`` (t1)/``too_long_min``
    from .colleague/config.json (#416 t2); ``(None, {}, {}, None)`` absent."""
    data = _merged_for(repo_path)
    global_value = data.get("reasoning_effort")
    too_long_min = data.get("too_long_min")
    return (
        None if global_value is None else str(global_value),
        _str_dict(data.get("reasoning_effort_seats")),
        _str_dict(data.get("reasoning_effort_purposes")),
        None if too_long_min is None else str(too_long_min),
    )


def _load_coherence_override(repo_path: str | Path) -> str | None:
    """Read the ``coherence`` key from .colleague/config.json as a raw string.

    Mirrors :func:`_load_memory_override` (kept separate from
    :func:`load_config_file`, which owns only the endpoint keys). Reads via
    :func:`_merged_config_json` (the at-home per-key merge, #339): a repo-level
    file that omits the key no longer shadows a user-level default.
    """
    data = _merged_for(repo_path)
    value = data.get("coherence")
    return None if value is None else str(value)


def _load_memory_override(repo_path: str | Path) -> str | None:
    """Read the ``memory`` key from .colleague/config.json as a raw string.

    Mirrors :func:`_load_lint_overrides` (kept separate from
    :func:`load_config_file`, whose endpoint-string contract must not change).
    Returns the stringified value or ``None`` when absent; a missing/malformed
    file yields ``None`` and never raises. Reads via
    :func:`_merged_config_json` (the at-home per-key merge, #339): a repo-level
    file that omits the key no longer shadows a user-level default.
    """
    data = _merged_for(repo_path)
    value = data.get("memory")
    return None if value is None else str(value)


def _load_memory_distill_override(repo_path: str | Path) -> str | None:
    """Read the ``memory_distill`` key from .colleague/config.json as a raw string.

    Mirrors :func:`_load_memory_override` (same merged-read, same never-raises
    contract) for the rung-2 distillation kill switch (t9, spec c29/h24).
    """
    data = _merged_for(repo_path)
    value = data.get("memory_distill")
    return None if value is None else str(value)


def _load_hire_override(repo_path: str | Path) -> str | None:
    """Read the ``hire`` key from .colleague/config.json as a raw string
    (delegation-follow-ups plan task t4). Accepts a bare boolean or, like
    ``agents``, a nested object (``{"hire": {"enabled": false}}`` — the
    object's presence, absent an explicit ``"enabled": false``, arms); a
    review found the nested form used to stringify to a dict repr that
    ``_parse_bool`` read as ARMED. ``None`` when absent; never raises. Reads
    via :func:`_merged_config_json`."""
    data = _merged_for(repo_path)
    value = data.get("hire")
    if value is None:
        return None
    if isinstance(value, dict):
        return str(value.get("enabled", True))
    return str(value)


def _load_affected_tests_overrides(
    repo_path: str | Path,
) -> tuple[str | None, str | None, str | None, str | None]:
    """Read affected-tests keys from .colleague/config.json as raw strings.

    Mirrors :func:`_load_lint_overrides` (kept separate from
    :func:`load_config_file`, whose endpoint-string contract must not change):
    these keys carry a bool / int. Returns
    ``(affected_tests, affected_tests_fix_retries, affected_tests_depth,
    affected_tests_max_files)``, each the stringified value or ``None`` when
    absent. A missing/malformed file yields ``(None, None, None, None)`` and
    never raises. Reads via :func:`_merged_config_json` (the at-home per-key
    merge, #339): a repo-level file that omits these keys no longer shadows a
    user-level default.
    """
    data = _merged_for(repo_path)
    enabled = data.get("affected_tests")
    retries = data.get("affected_tests_fix_retries")
    depth = data.get("affected_tests_depth")
    max_files = data.get("affected_tests_max_files")
    return (
        None if enabled is None else str(enabled),
        None if retries is None else str(retries),
        None if depth is None else str(depth),
        None if max_files is None else str(max_files),
    )


def _load_presence_override(repo_path: str | Path) -> str | None:
    """Read the top-level ``presence`` key from .colleague/config.json.

    Mirrors :func:`_load_memory_override` (kept separate from
    :func:`load_config_file`, whose endpoint-string contract must not change):
    a scalar knob, not the nested-section shape ``deepthink``/``senses``/
    ``voice`` use. Returns the stringified value or ``None`` when absent; a
    missing/malformed file yields ``None`` and never raises. Reads via
    :func:`_merged_config_json` (the at-home per-key merge, #339): a repo-level
    file that omits the key no longer shadows a user-level default.
    """
    data = _merged_for(repo_path)
    value = data.get("presence")
    return None if value is None else str(value)


def _str(value: object | None) -> str | None:
    """None-preserving str() so an unset numeric arg falls through to env/default."""
    return None if value is None else str(value)


def _try_int(value: str | None, default: int) -> int:
    """Try to parse an int from a string; return default if None, empty, or non-numeric."""
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _try_int_or_none(value: str | None) -> int | None:
    """Parse an int, or ``None`` when unset/empty/non-numeric.

    For a dormant-by-default knob (e.g. ``review_fanout_folders``) where the
    absence of a value must stay ``None`` (a strict no-op), not coerce to 0.
    """
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _try_float(value: str | None, default: float) -> float:
    """Try to parse a float from a string; return default if None, empty, or non-numeric."""
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def effective_concurrency(requested: int) -> int:
    """Clamp a requested concurrency width to the valid range [1, MAX_SUBAGENT_FANOUT - 1].

    Args:
        requested: The requested concurrency level (may be 0, negative, or > max).

    Returns:
        The clamped concurrency: min(max(1, requested), MAX_SUBAGENT_FANOUT - 1).
    """
    return min(max(1, requested), MAX_SUBAGENT_FANOUT - 1)


def autosplit_children(target_tokens: int, per_child_budget_tokens: int) -> int:
    """Derive the number of child hand-over assignments for a split.

    children = ceil(target_tokens / per_child_budget_tokens), then structurally
    clamped to [1, MAX_SUBAGENT_FANOUT - 1] (the batch reserves one fan-out slot
    for the sequential merge child). Guards a non-positive per-child budget by
    returning the max usable children.

    The ceiling uses INTEGER arithmetic (``-(-a // b)``), not ``math.ceil(a / b)``:
    true division forces a float, and an absurd operator-provided ``target_tokens``
    (beyond float range) would raise ``OverflowError`` before the clamp — integer
    division stays exact for arbitrarily large ints (#151 review).
    """
    if per_child_budget_tokens <= 0:
        return MAX_SUBAGENT_FANOUT - 1
    raw = -(-target_tokens // per_child_budget_tokens)  # integer ceiling division
    return min(max(1, raw), MAX_SUBAGENT_FANOUT - 1)


# ---------------------------------------------------------------------------
# Mode-profile default layer (spec R1 / issue #254, plan t2)
# ---------------------------------------------------------------------------

# The constraint knobs a mode profile may fill, with the env vars whose


@dataclass(frozen=True)
class FileOverrides:
    """Every ``.colleague/config.json`` value one ``EngineConfig.resolve`` reads.

    ``resolve`` used to declare thirty-one ``file_*`` locals and fill them from
    a single ``if repo_path is not None:`` block; this is that block, verbatim,
    behind a name (plan ``hard-1000-line-file-limit`` t14). The all-defaults
    instance is exactly the "no config file" case ``resolve`` produced when
    *repo_path* was ``None`` — byte-identical, no key newly consulted.
    """

    cfg: dict = field(default_factory=dict)
    cfg_base_url: "str | None" = None
    cfg_api_key: "str | None" = None
    cfg_model: "str | None" = None
    lint: "str | None" = None
    watch: "str | None" = None
    coherence: "str | None" = None
    memory: "str | None" = None
    memory_distill: "str | None" = None
    lint_retries: "str | None" = None
    ti: "str | None" = None
    ti_retries: "str | None" = None
    at: "str | None" = None
    at_retries: "str | None" = None
    at_depth: "str | None" = None
    at_max_files: "str | None" = None
    until_done: "str | None" = None
    max_episodes: "str | None" = None
    compaction_cap: "str | None" = None
    deepthink: dict = field(default_factory=dict)
    senses: dict = field(default_factory=dict)
    voice: dict = field(default_factory=dict)
    realtime: dict = field(default_factory=dict)
    three_tier: "str | None" = None
    worker: dict = field(default_factory=dict)
    tae: "str | None" = None
    agents: "str | None" = None
    hire: "str | None" = None
    distiller: "str | None" = None
    seats: dict = field(default_factory=dict)
    reasoning_effort: "str | None" = None
    reasoning_effort_seats: dict = field(default_factory=dict)
    reasoning_effort_purposes: dict = field(default_factory=dict)
    too_long_min: "str | None" = None


def load_file_overrides(repo_path: "str | Path | None") -> FileOverrides:
    """Read every config.json section ``EngineConfig.resolve`` consults, once.

    ``repo_path is None`` returns the all-defaults :class:`FileOverrides` — the
    empty dicts / ``None``\\ s ``resolve``'s own locals used to start at, so the
    no-config-file path is unchanged.
    """
    if repo_path is None:
        return FileOverrides()
    cfg = load_config_file(repo_path)
    file_lint, file_lint_retries = _load_lint_overrides(repo_path)
    file_ti, file_ti_retries = _load_testintegrity_overrides(repo_path)
    file_at, file_at_retries, file_at_depth, file_at_max_files = _load_affected_tests_overrides(
        repo_path
    )
    file_until_done, file_max_episodes, file_compaction_cap = _load_chain_overrides(repo_path)
    file_worker = _load_worker_overrides(repo_path)
    (
        file_reasoning_effort,
        file_reasoning_effort_seats,
        file_reasoning_effort_purposes,
        file_too_long_min,
    ) = _load_reasoning_effort_overrides(repo_path)
    return FileOverrides(
        cfg=cfg,
        cfg_base_url=cfg.get("base_url"),
        cfg_api_key=cfg.get("api_key"),
        cfg_model=cfg.get("model"),
        lint=file_lint,
        lint_retries=file_lint_retries,
        watch=_load_watch_override(repo_path),
        coherence=_load_coherence_override(repo_path),
        memory=_load_memory_override(repo_path),
        memory_distill=_load_memory_distill_override(repo_path),
        ti=file_ti,
        ti_retries=file_ti_retries,
        at=file_at,
        at_retries=file_at_retries,
        at_depth=file_at_depth,
        at_max_files=file_at_max_files,
        until_done=file_until_done,
        max_episodes=file_max_episodes,
        compaction_cap=file_compaction_cap,
        deepthink=_load_deepthink_overrides(repo_path),
        senses=_load_senses_overrides(repo_path),
        voice=_load_voice_overrides(repo_path),
        realtime=_load_realtime_overrides(repo_path),
        three_tier=_load_three_tier_override(repo_path),
        worker=file_worker,
        # Thought→action→evaluation mode (t12): its own arming key, its own
        # per-seat key-hygiene sections, and the declared distiller authority.
        # The ``worker`` section is SHARED with three-tier — same seat name,
        # same key, and the two modes are mutually exclusive, so there is
        # nothing to disambiguate.
        tae=_load_thought_action_evaluation_override(repo_path),
        agents=_load_agents_override(repo_path),
        hire=_load_hire_override(repo_path),
        distiller=_load_distiller_override(repo_path),
        seats={
            "front": _load_seat_overrides(repo_path, "front"),
            "worker": file_worker,
            "evaluator": _load_seat_overrides(repo_path, "evaluator"),
        },
        reasoning_effort=file_reasoning_effort,
        reasoning_effort_seats=file_reasoning_effort_seats,
        reasoning_effort_purposes=file_reasoning_effort_purposes,
        too_long_min=file_too_long_min,
    )
