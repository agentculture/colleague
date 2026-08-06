"""Engine configuration: where the model lives and how hard the loop drives it.

Resolution precedence, highest first:

1. an explicit value passed in code / from a CLI flag,
2. a ``COLLEAGUE_*`` environment variable (the legacy ``CONVERTIBLE_*`` name is
   still honored as a deprecated fallback during the rename),
3. an OpenAI-style ``OPENAI_*`` environment variable (so an existing OpenAI
   client setup is reused),
4. a persistent ``.colleague/config.json`` file (repo-level, falling back to
   user-level ``~/.colleague/config.json``) — the ``base_url``/``api_key``/
   ``model`` endpoint keys only, and only when ``resolve`` is given a
   ``repo_path``. This is the durable way to point colleague at another
   OpenAI-compatible provider without re-passing flags or env vars each run,
5. the built-in default.

Defaults point at the vLLM reference rig (decision D3): an OpenAI-compatible
server on ``localhost:8001``. Because the driver only speaks the OpenAI surface,
pointing ``base_url`` elsewhere is a config change, never a code change (h2) —
whether via env var, CLI flag, or ``.colleague/config.json``.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Collection, Mapping, Optional
from urllib.parse import urlsplit, urlunsplit

from colleague import configdir
from colleague.fillline import DEFAULT_COMPACTION_CAP

if TYPE_CHECKING:
    # Annotation-only (three-tier-execution arc, plan task t3): the real
    # import stays LAZY inside :func:`_worker_refusal` (keeps config's
    # module-level import graph unchanged, the ``colleague.lobes`` lazy-import
    # precedent) — this satisfies the forward-reference type checker/linter
    # only, never executed at runtime.
    from colleague.cli._errors import CliError

    # Annotation-only (change-content consumption lane, plan task t3): types
    # ``config_lifecycle`` below. No runtime import — the attachment is read
    # defensively via getattr (colleague/loop.py:2934 already does this
    # forward-compatibly), and any object exposing the same read surface
    # (a frozen child view, a future adapter) is accepted, never just this
    # concrete class.
    from colleague.configlifecycle import EpisodeConfigLifecycle

    # Annotation-only (same-role stale-pin refresh, plan task t9): types
    # ``model_refresh_warnings`` below. No runtime import — the real import
    # stays LAZY inside :func:`_refresh_stale_model_pin` (the same
    # ``colleague.lobes`` lazy-import precedent as every other lobes-fed
    # rung in this module).
    from colleague.lobes import ModelRefreshWarning

# vLLM ignores the key, but the OpenAI wire format wants a non-empty string.
_DEFAULT_API_KEY = "EMPTY"
_DEFAULT_BASE_URL = "http://localhost:8001/v1"
# Built-in fallback model id. Points at the model the reference rig actually
# serves at _DEFAULT_BASE_URL so a bare work item (no COLLEAGUE_MODEL / --model)
# reaches a live model instead of a 404 "model does not exist". Override per
# environment with COLLEAGUE_MODEL or --model.
_DEFAULT_MODEL = "unsloth/Qwen3.6-27B-NVFP4"
_DEFAULT_MAX_STEPS = 40
_DEFAULT_TEMPERATURE = 0.0
_DEFAULT_TIMEOUT = 120.0
# Proactive context budget in tokens. Counted exactly via the served model's
# /tokenize endpoint when reachable; char-based fallback otherwise (best-effort
# exact, char-approximate fallback, never token-exact-guaranteed — no tokenizer
# library is bundled). Sized for the window the reference rig ACTUALLY serves
# the default model at: the lobes rig serves the 27B at 64K (65536 tokens,
# probed live 2026-07-02 — the old 192000 default assumed the retired 256K
# serving and drove every long run into overflow/latency churn), keeping the
# same ~0.73 fill fraction (48000/65536) with headroom for the completion +
# system/tools prompt. Override per environment with COLLEAGUE_CONTEXT_BUDGET
# (e.g. raise it for a wider-window model: the rig's Gemma4-12B serves 128K →
# 96000; a Gemma4 default-model flip is staged on the serving side growing a
# Gemma-format tool-call parser — probed: it emits no structured tool calls yet).
_DEFAULT_CONTEXT_BUDGET = 48000
# Cap on each tool result (read_file / run_command / list_dir / subagent) fed
# back to the model, in characters. Scaled with the context budget (the same
# ~13% of window as the previous 100000-for-192000 sizing) so one large read
# cannot evict half the working history; still above the old hardcoded 20000.
# Tunable per environment with COLLEAGUE_MAX_OUTPUT_CHARS.
_DEFAULT_MAX_OUTPUT_CHARS = 25000

# Opt-in concurrency width for subagent delegation (how many may run in
# parallel). Clamped to [1, MAX_SUBAGENT_FANOUT - 1] by effective_concurrency().
# Tunable per environment with COLLEAGUE_SUBAGENT_CONCURRENCY.
_DEFAULT_SUBAGENT_CONCURRENCY = 1

# Subagent recursion depth cap (agents of agents). Tunable per environment
# with COLLEAGUE_SUBAGENT_DEPTH.
_DEFAULT_SUBAGENT_DEPTH = 4
# Global per-top-level total-agent budget for subagent delegation. Tunable per
# environment with COLLEAGUE_SUBAGENT_TOTAL.
_DEFAULT_SUBAGENT_TOTAL = 24

# Auto-split capacity target in tokens (issue #151). The operator-tunable
# "~1M effective capacity" knob: colleague recommends splitting a too-large
# assignment into children whose count is derived from this target divided by
# the per-child context budget, then structurally clamped to the subagent
# fan-out cap. Override with COLLEAGUE_AUTOSPLIT_TARGET.
_DEFAULT_AUTOSPLIT_TARGET_TOKENS = 1_000_000

# Fill-line decision threshold (issue #156): the fraction of the context budget at
# which the runtime offers the proactive capacity decision (compact | split |
# finish-with-handoff). 0.8 leaves headroom for the decision prompt + the model's
# declaring turn before a hard overflow. Override with COLLEAGUE_FILLLINE_THRESHOLD;
# 0 (or out of (0, 1]) leaves the proactive decision dormant — degradation + the
# reactive auto-split still apply.
_DEFAULT_FILLLINE_THRESHOLD = 0.8

# Mapping fan-out trigger (issue #188): the number of files a read-only mapping run
# may read before the runtime injects ONE advisory recommendation to fan the survey
# out across folders via the ``subagents`` tool (instead of grinding serially through
# the step budget). Override with COLLEAGUE_FANOUT_FILES; 0 (or negative) leaves the
# advisory dormant — a strict no-op. This is the parked-`v1` default knob.
_DEFAULT_FANOUT_FILES = 12

# Instruction-token threshold at/above which a normal work item injects ONE advisory
# recommendation to enter plan mode (the auto-trigger, #t8). Override with
# COLLEAGUE_PLAN_OFFER_TOKENS; 0 (or negative) leaves the advisory DORMANT — a strict
# no-op (opt-in, so existing behavior is byte-identical). Detection lives in
# ``colleague.plan.trigger``.
_DEFAULT_PLAN_OFFER_TOKENS = 0

# Number of times the loop nudges a stalled no-tool-call turn to continue before
# giving up (lifts the previously hardcoded ``_MAX_FINISH_NUDGES = 1``).
# Override with COLLEAGUE_MAX_CONTINUE_NUDGES.
_DEFAULT_MAX_CONTINUE_NUDGES = 2
# Synthesis reserve (#197): steps held back from the reading budget so the
# forced-synthesis verdict turn isn't starved by context-reading on a big-diff
# review. 0 = off (byte-identical: the whole budget is spent reading); the review
# caller raises it.
_DEFAULT_SYNTHESIS_RESERVE = 0

# Episode chaining (indefinite-run, decision c21). ``until_done`` arms the
# chain driver (colleague/chain.py decisions, dispatched by the work path):
# default OFF, so an untouched config keeps today's single-episode behavior
# byte-identical. ``max_episodes`` caps an ARMED chain's episodes: default 5,
# 0 = unlimited. Precedence for both: --until-done / --max-episodes flag
# (applied by the CLI, t5) > COLLEAGUE_UNTIL_DONE / COLLEAGUE_MAX_EPISODES env
# > .colleague/config.json {"until_done": ..., "max_episodes": ...} > default.
_DEFAULT_UNTIL_DONE = False
_DEFAULT_MAX_EPISODES = 5

# Lint pre-finish gate (#200). When enabled (the default — operator intent is
# default-ON with an opt-out), the runtime runs the repo's configured linters on
# the work item's changed files before handoff and auto-fixes what it can. Disable
# per run with the ``--no-lint`` flag, ``COLLEAGUE_LINT=0``, or
# ``.colleague/config.json`` ``{"lint": false}`` (precedence flag > env > config
# > default-on). ``lint_fix_retries`` caps the bounded model fix-turn for residual
# (non-auto-fixable) violations; 0 runs only the deterministic fixers. A repo with
# no linter configured is a strict no-op regardless of this flag.
_DEFAULT_LINT_ENABLED = True
_DEFAULT_LINT_FIX_RETRIES = 1

# Flight plane armed by default (#307): every run (work / drive / session) arms
# the file-based flight-control plane so `colleague talk` / `colleague flight` /
# senses live-presence always have a plane to attach to. Opt out per run with the
# ``--no-watch`` flag, ``COLLEAGUE_WATCH=0``, or ``.colleague/config.json``
# ``{"watch": false}`` (precedence flag > env > config > default-on). The plane is
# an append-only side file with no daemon/socket/thread; a run with no pilot is
# byte-identical on stdout and in the artifact, so default-on is a strict no-op
# for an unattended run.
_DEFAULT_WATCH_ENABLED = True

# Coherence pre-finish gate (#294, colleague#291 S3). Default-ON warn-only
# (operator decision on #291) with the same opt-out shape as lint:
# --no-coherence flag, COLLEAGUE_COHERENCE=0, or config.json
# {"coherence": false}. Advisory only — no fix-turn, never blocks the handoff;
# a run with no changed .md files or no coherence CLI is a strict no-op.
_DEFAULT_COHERENCE_ENABLED = True

# Memory-informed runtime (spec R1 / plan t2). Default-ON with opt-outs
# (COLLEAGUE_MEMORY=0 / config.json {"memory": false} / --no-memory); the loop
# additionally arms only when the repo has a .eidetic/ store and the eidetic
# CLI is installed, so a store-less repo is a strict no-op regardless.
_DEFAULT_MEMORY_ENABLED = True

# Affected-tests gate (#213). Default-ON with an opt-out: after the loop the
# runtime selects and runs only the tests whose import chain reaches the changed
# files (bounded-depth transitive reverse-import selection). Disable with
# ``COLLEAGUE_AFFECTED_TESTS=0`` or ``.colleague/config.json``
# ``{"affected_tests": false}``. ``affected_tests_fix_retries`` caps the bounded
# model fix-turn for failing tests; 0 is run-and-record only.
# ``affected_tests_depth`` controls the transitive reverse-import walk depth.
# ``affected_tests_max_files`` caps the number of selected test files (honest cap:
# reports total and whether the cap was hit). ``affected_tests_override`` is set
# later from a CLI flag (no env var); default None.
_DEFAULT_AFFECTED_TESTS_ENABLED = True
_DEFAULT_AFFECTED_TESTS_FIX_RETRIES = 1
_DEFAULT_AFFECTED_TESTS_DEPTH = 3
_DEFAULT_AFFECTED_TESTS_MAX_FILES = 20

# Test-integrity gate (#203). Default-ON like lint (an opt-out, not opt-in): after
# the loop the runtime flags the *mirror signature* on the work item's changed files
# (a novel identifier co-introduced in both a changed test and the module under test,
# found nowhere else). Disable with ``COLLEAGUE_TESTINTEGRITY=0`` or
# ``.colleague/config.json`` ``{"testintegrity": false}``. ``testintegrity_fix_retries``
# caps the bounded model re-examine turn for a flagged symbol; 0 (the conservative
# default) is detect-and-record only.
_DEFAULT_TESTINTEGRITY_ENABLED = True
_DEFAULT_TESTINTEGRITY_FIX_RETRIES = 0
# The diverse-model reviewer (the robust guard — a same-model re-examine turn can
# re-confirm its own mirror). When a DIFFERENT model id is configured here
# (``COLLEAGUE_TESTINTEGRITY_REVIEWER_MODEL`` / config.json), a flagged finding
# auto-spawns a reviewer subagent on that model to independently re-derive the real
# API shape. Empty (the default) degrades to record-only — no reviewer is spawned.
_DEFAULT_TESTINTEGRITY_REVIEWER_MODEL = ""

# Dual-model deepthink escalation target (spec
# docs/specs/2026-07-01-colleague-drives-with-two-minds-a-fast-wide-window.md,
# claims c8/h1/c2/h11). Optional: a second OpenAI-compatible endpoint the
# runtime MAY escalate hard-reasoning turns to at a fixed, enumerated set of
# points (the deepthink loop tool, the acceptance self-check, plan-mode
# proposals, and the test-integrity reviewer default) — never an automatic
# router. Present iff the resolved model is a non-empty, non-whitespace
# string; ``base_url``/``api_key`` then default to the MAIN resolved
# endpoint's own values (so declaring dual-model needs only a model id unless
# deepthink truly lives elsewhere). ``context_budget`` defaults to a
# 64K-window-sized share (48000/65536 ≈ 0.73) — since the rig now serves the
# default main model at 64K too, this equals the main default's fill fraction
# by construction. Override per
# environment with COLLEAGUE_DEEPTHINK_MODEL / _BASE_URL / _API_KEY /
# _CONTEXT_BUDGET, or a ``deepthink`` section in .colleague/config.json.
_DEFAULT_DEEPTHINK_CONTEXT_BUDGET = 48000
# The deepthink model window the 48000 default was sized for (the original
# reference reasoner's 64K window). A lobes-discovered muse role (the
# two-machines-two-minds arc, t5) reports its OWN window; it is scaled by the
# same headroom ratio (48000/65536 ≈ 0.73) so a 64K role reproduces the
# hand-tuned default and any other window scales proportionally — never the
# raw window (which leaves no completion headroom). Mirrors
# _SENSES_DEFAULT_WINDOW below, field-for-field.
_DEEPTHINK_DEFAULT_WINDOW = 65536

# Senses config (cortex/senses arc, spec
# docs/specs/2026-07-03-colleague-drives-with-a-cortex-and-senses-it-resol.md,
# claims c7/h2, plan task t3). Optional: a second OpenAI-compatible endpoint
# declared as the multimodal front door (intake / speak-back on the
# operator-facing surfaces) — mirrors DeepthinkConfig field-for-field.
# Present iff the resolved model is a non-empty, non-whitespace string;
# ``base_url``/``api_key`` then default to the MAIN resolved endpoint's own
# values, exactly like deepthink. ``context_budget`` defaults to a
# 32K-window-sized share (24000/32768 ≈ 0.73) — the same ~75% headroom ratio
# deepthink uses for its own window. Override per environment with
# COLLEAGUE_SENSES_MODEL / _BASE_URL / _API_KEY / _CONTEXT_BUDGET /
# _MULTIMODAL, or a ``senses`` section in .colleague/config.json. This task
# (t3) resolves env > config.json > absent; the lobes discovery rung (t4, below)
# additionally feeds a SensesConfig from the gateway's senses role.
_DEFAULT_SENSES_CONTEXT_BUDGET = 24000
# The senses model window the 24000 default was sized for (the live senses
# role's 32K window). A lobes-discovered senses role reports its OWN window; it
# is scaled by the same headroom ratio (24000/32768 ≈ 0.73) so the live 32K role
# reproduces the hand-tuned 24000 default and any other window scales
# proportionally — never the raw window (which leaves no completion headroom).
_SENSES_DEFAULT_WINDOW = 32768

# Three-tier execution arming (three-tier-execution arc, plan task t3).
# EXPLICIT config block: ``COLLEAGUE_THREE_TIER`` env > a ``three_tier`` key
# in .colleague/config.json (bool, or an object whose presence — absent an
# explicit ``{"enabled": false}`` — itself means armed, the ``lobes``
# bare-string-or-object precedent) > default-OFF. Default OFF (never
# ambient) is the SAME opt-in stance ``until_done`` takes (decision c21): an
# execution-mode change needs explicit operator intent, never an accident of
# an armed lobes gateway alone. When armed, resolution REQUIRES a ready
# ``worker`` role from lobes — see :func:`_resolve_worker` — and refuses
# loudly rather than ever falling back to cortex silently acting as the
# worker (c25/h21).
_DEFAULT_THREE_TIER_ENABLED = False

# Engine SELECTION default (distinct from the provider config below — mock
# ignores provider config entirely). The default is the real bundled engine,
# never the no-op ``mock`` contract reference: a bare ``drive``/``session`` must
# not silently fake work (issue #53, "Mock shouldn't be default"). ``mock`` is
# reachable only by an explicit ``--engine mock`` / ``COLLEAGUE_ENGINE=mock``.
_DEFAULT_ENGINE = "vllm-openai"

# Subagent delegation bounds.
MAX_SUBAGENT_DEPTH = 4
MAX_SUBAGENT_FANOUT = 4
MAX_SUBAGENT_TOTAL = 24

# The persistent per-repo config file, resolved under .colleague/ (configdir).
_CONFIG_FILENAME = "config.json"
# Recognised keys in .colleague/config.json.
_CONFIG_KEYS = frozenset({"base_url", "api_key", "model"})
# Recognised keys inside the NESTED "deepthink" section of .colleague/config.json.
_DEEPTHINK_CONFIG_KEYS = frozenset({"model", "base_url", "api_key", "context_budget", "multimodal"})
# Recognised keys inside the NESTED "senses" section of .colleague/config.json.
_SENSES_CONFIG_KEYS = frozenset({"model", "base_url", "api_key", "context_budget", "multimodal"})
# Recognised key inside the NESTED "worker" section of .colleague/config.json
# (three-tier-execution arc, plan task t3). Unlike deepthink/senses/voice,
# worker carries NO declared model/base_url — the worker seat is resolved
# ONLY via lobes role-NAME discovery (never model-name parsing, the t3
# design boundary); the only recognised key is the key-hygiene override.
_WORKER_CONFIG_KEYS = frozenset({"api_key"})

_VOICE_CONFIG_KEYS = frozenset({"stt_model", "tts_model", "base_url", "api_key"})
# Recognised keys inside the NESTED "realtime" section of .colleague/config.json
# (realtime-speech arc, plan task t1; ``input_device``/``output_device`` added
# task t4). ``url`` is the presence signal (the "model IS presence" rule every
# sibling rung takes, adapted: realtime has no model of its own — see
# :func:`_resolve_realtime`). ``input_device``/``output_device`` are PURE LOCAL
# knobs (a PortAudio device id or name substring on THIS machine) — see
# :func:`_resolve_realtime_devices`.
_REALTIME_CONFIG_KEYS = frozenset({"url", "api_key", "input_device", "output_device"})
# Recognised key inside the NESTED "lobes" section of .colleague/config.json
# (the lobes discovery rung, task t4). A bare string is also accepted as the
# gateway URL directly (``{"lobes": "http://..."}``).
_LOBES_CONFIG_KEYS = frozenset({"url"})


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
    data = _merged_config_json(repo_path)
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
    data = _merged_config_json(repo_path)
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
    data = _merged_config_json(repo_path)
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
    data = _merged_config_json(repo_path)
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
    data = _merged_config_json(repo_path)
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
    data = _merged_config_json(repo_path)
    section = data.get("three_tier")
    if section is None:
        return None
    if isinstance(section, dict):
        # Preserve the RAW value so _parse_bool downstream handles string
        # booleans — bool("false") is True, which would arm three-tier on an
        # explicit {"enabled": "false"} disable (Qodo #367 review, thread 4).
        return str(section.get("enabled", True))
    return str(section)


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
    data = _merged_config_json(repo_path)
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
    data = _merged_config_json(repo_path)
    section = data.get("lobes")
    if isinstance(section, str):
        return section.strip() or None
    if isinstance(section, dict):
        url = section.get("url")
        if isinstance(url, str) and url.strip():
            return url.strip()
    return None


def resolve_lobes_gateway_url(repo_path: str | Path | None = None) -> str | None:
    """The armed lobes gateway URL, or ``None`` when the rung is unarmed. NO network.

    Precedence: ``COLLEAGUE_LOBES_URL`` env (``CONVERTIBLE_LOBES_URL`` honored as
    a deprecated fallback) > a ``lobes`` section in .colleague/config.json (only
    when *repo_path* is given) > ``None``. Public so the doctor / ``config show``
    surfaces can report the ARMED state without consulting the gateway.

    ``None`` means the lobes discovery rung is not armed — resolution stays
    byte-identical to a pre-feature run (no ``resolve_roles`` call, no notice).
    """
    for key in ("COLLEAGUE_LOBES_URL", "CONVERTIBLE_LOBES_URL"):
        value = os.environ.get(key)
        if value and value.strip():
            return value.strip()
    if repo_path is not None:
        return _load_lobes_override(repo_path)
    return None


def _lobes_base_url(origin_url: str) -> str:
    """Append the builtin default's OpenAI path suffix (``/v1``) to *origin_url*.

    A pure shape helper: match whatever :data:`_DEFAULT_BASE_URL` carries as a
    path suffix so every lobes-derived base_url (gateway origin OR a per-role
    dial target — see :func:`_role_dial_base_url`) has the same shape as the
    builtin default. Historically this was applied to the gateway origin ONLY
    (LOBES_LIVE_FINDINGS decision 2, pre-0.38: every role's own ``endpoint``
    reported an internal, non-client-reachable host, e.g. ``http://localhost:8000``,
    so both cortex and senses were forced to dial the gateway origin instead).
    Since lobes-cli 0.38.0 closed lobes-cli#87, a role's own ``endpoint`` is
    genuinely client-reachable, so :func:`_role_dial_base_url` now feeds this
    helper the role's OWN resolved origin — the gateway origin is only the
    documented fallback (see ``colleague/lobes.py``'s ``resolve_role_base_url``).
    """
    suffix = urlsplit(_DEFAULT_BASE_URL).path.rstrip("/")
    return origin_url.rstrip("/") + suffix


#: Scheme swap applied by :func:`_realtime_ws_url` — any scheme not in this
#: map (e.g. an operator who already supplied ``ws://``/``wss://``) passes
#: through unchanged.
_WS_SCHEME_MAP = {"http": "ws", "https": "wss"}


def _realtime_ws_url(origin: str) -> str:
    """Derive the ws(s) ``/v1/realtime`` dial target from an http(s) *origin*
    (realtime-speech arc, plan task t1).

    The one shape rule: scheme swaps http->ws / https->wss via
    :data:`_WS_SCHEME_MAP` (any other scheme passes through unchanged, so an
    operator who already declares a ``ws://``/``wss://`` knob is idempotent),
    the netloc (host[:port]) is preserved exactly, and the path is ALWAYS the
    literal ``/v1/realtime`` — the OpenAI-compatible realtime session path the
    lobes gateway tunnels (probed live 2026-07-22, docs/specs/2026-07-22-
    realtime-speech.md decision c23: ``/v1/realtime`` answers 401 bare and
    101-upgrades with a Bearer key). Any query/fragment on *origin* is
    dropped — this derives a DIAL TARGET, not a general URL rewrite. Never
    raises; a malformed *origin* degrades to whatever :func:`urlsplit`
    tolerates, matching this module's degrade-never-raise stance elsewhere.
    """
    parts = urlsplit(origin)
    scheme = _WS_SCHEME_MAP.get(parts.scheme.lower(), parts.scheme.lower())
    return urlunsplit((scheme, parts.netloc, "/v1/realtime", "", ""))


def _role_dial_base_url(role: object, gateway_url: str) -> str:
    """Resolve *role*'s own dial target and apply the ``/v1``-shape suffix (lobes-cli#87).

    Delegates to :func:`colleague.lobes.resolve_role_base_url` for the
    SSRF-guarded per-role origin — the role's own ``endpoint`` when it is a
    non-empty, allowed-scheme URL, else *gateway_url* itself (an unwired role
    or a disallowed scheme) — then applies :func:`_lobes_base_url`'s suffix so
    every lobes-derived base_url shares one shape. This is the consumer switch
    (colleague#292, S1's follow-on) closing lobes-cli#87 end-to-end: cortex,
    senses, and voice (stt/tts) each dial THEIR OWN advertised endpoint instead
    of the pre-0.38 gateway-origin-for-all workaround.
    """
    # Lazy import mirrors _resolve_lobes_rung's own lazy `colleague.lobes` import
    # (keeps config's module import graph unchanged; lets tests monkeypatch it).
    from colleague import lobes as _lobes

    origin = _lobes.resolve_role_base_url(role, gateway_url)
    return _lobes_base_url(origin)


def _senses_budget_from_window(window: int) -> int:
    """A senses context_budget derived from a role's reported window.

    Applies the same headroom ratio the built-in default encodes
    (:data:`_DEFAULT_SENSES_CONTEXT_BUDGET` / :data:`_SENSES_DEFAULT_WINDOW`), so
    the live 32K senses role reproduces the hand-tuned 24000 default and any
    other window scales proportionally. Floored at 1; a non-positive window
    falls back to the default (never zero — that would disable the budget path).
    """
    if window <= 0:
        return _DEFAULT_SENSES_CONTEXT_BUDGET
    ratio = _DEFAULT_SENSES_CONTEXT_BUDGET / _SENSES_DEFAULT_WINDOW
    return max(1, int(window * ratio))


def _senses_from_lobes_role(role: object, base_url: str, api_key: str) -> "SensesConfig | None":
    """Build a :class:`SensesConfig` from the gateway's senses role (t4).

    Used only when senses is NOT otherwise declared (env/config.json win).
    *base_url* is the senses role's OWN resolved dial target (colleague#292,
    S1's follow-on: :func:`_role_dial_base_url` closes lobes-cli#87 — the
    role's own ``endpoint`` when reachable, the gateway origin only as the
    documented fallback; NOT a blanket gateway-origin-for-all as before);
    api_key inherits the resolved MAIN endpoint's value. ``multimodal`` stays
    ``False`` — the t1 :class:`~colleague.lobes.RoleInfo` carries no ``mtp``
    field, so an operator arms the media bridge by declaring senses explicitly
    (env/config, which take precedence). Returns ``None`` on a blank model.
    """
    model = str(getattr(role, "model", "") or "").strip()
    if not model:
        return None
    return SensesConfig(
        model=model,
        base_url=base_url,
        api_key=api_key,
        context_budget=_senses_budget_from_window(int(getattr(role, "context", 0) or 0)),
        multimodal=False,
    )


def _deepthink_budget_from_window(window: int) -> int:
    """A deepthink context_budget derived from a role's reported window.

    Applies the same headroom ratio the built-in default encodes
    (:data:`_DEFAULT_DEEPTHINK_CONTEXT_BUDGET` / :data:`_DEEPTHINK_DEFAULT_WINDOW`),
    so a 64K role reproduces the hand-tuned 48000 default and any other window
    scales proportionally (thor's verified 262144 window → 192000). Floored at
    1; a non-positive window falls back to the default (never zero — that
    would disable the budget path). Mirrors :func:`_senses_budget_from_window`.
    """
    if window <= 0:
        return _DEFAULT_DEEPTHINK_CONTEXT_BUDGET
    ratio = _DEFAULT_DEEPTHINK_CONTEXT_BUDGET / _DEEPTHINK_DEFAULT_WINDOW
    return max(1, int(window * ratio))


def _deepthink_from_lobes_role(
    role: object, base_url: str, api_key: str
) -> "DeepthinkConfig | None":
    """Build a :class:`DeepthinkConfig` from the gateway's muse role (t5).

    The two-machines-two-minds arc's discovery rung — the sixth sanctioned
    increment at the router-exclusion boundary: resolution only, feeding the
    ALREADY-enumerated four-point escalation surface; no new decision point.
    Used only when deepthink is NOT otherwise declared (env/config.json win —
    the exact stance :func:`_senses_from_lobes_role` takes). *base_url* is the
    muse role's OWN resolved dial target (:func:`_role_dial_base_url`);
    api_key inherits the resolved MAIN endpoint's value. ``multimodal`` stays
    ``False`` — declaration, never a probe (the discovered-senses rule).
    Returns ``None`` on a blank model (presence is keyed solely on a resolved
    model, the t1 deepthink rule). The gateway's ``loaded``/``feasible`` flags
    are deliberately NOT consulted — for proxied roles they describe the
    gateway host, not the serving host (lobes-cli#146).
    """
    model = str(getattr(role, "model", "") or "").strip()
    if not model:
        return None
    return DeepthinkConfig(
        model=model,
        base_url=base_url,
        api_key=api_key,
        context_budget=_deepthink_budget_from_window(int(getattr(role, "context", 0) or 0)),
        multimodal=False,
    )


def _same_origin(a: str, b: str) -> bool:
    """True when *a* and *b* share scheme + host + port (case-insensitive netloc).

    The credential-hygiene predicate for the deepthink discovery rung: the
    MAIN api_key is inherited by a DISCOVERED deepthink only toward the same
    origin the main endpoint already talks to — never forwarded to a
    different host a wire payload advertised (Qodo finding on colleague#347).
    """
    sa, sb = urlsplit(a), urlsplit(b)
    return (sa.scheme.lower(), sa.netloc.lower()) == (sb.scheme.lower(), sb.netloc.lower())


def _deepthink_lobes_fallback(
    lobes_roles: object,
    lobes_gateway_url: str | None,
    main_base_url: str,
    main_api_key: str,
    file_deepthink: dict[str, str],
) -> "DeepthinkConfig | None":
    """The muse→deepthink discovery fallback, extracted from ``resolve()`` (t5).

    Extraction keeps ``resolve()`` under the SonarCloud S3776 cognitive-
    complexity ceiling — the same move :func:`_resolve_lobes_rung` made.
    Returns ``None`` when lobes did not resolve, no muse role is advertised,
    or the role carries a blank model.

    **api_key hygiene.** An explicitly declared deepthink key
    (``COLLEAGUE_DEEPTHINK_API_KEY`` env or config.json ``deepthink.api_key``
    — usable even without a declared model) always wins. Otherwise the MAIN
    key is inherited only when muse's dial target shares the main endpoint's
    origin (:func:`_same_origin`); a cross-origin muse gets
    :data:`_DEFAULT_API_KEY` instead, so the main Bearer token is never
    forwarded to a host a wire payload advertised. A wrong/absent key
    degrades visibly at the escalation point (the c13 ladder), never fails
    the run.
    """
    muse_role = getattr(lobes_roles, "muse", None) if lobes_roles is not None else None
    if muse_role is None or lobes_gateway_url is None:
        return None
    deepthink_base_url = _role_dial_base_url(muse_role, lobes_gateway_url)
    explicit_key = _pick(
        None,
        "COLLEAGUE_DEEPTHINK_API_KEY",
        "CONVERTIBLE_DEEPTHINK_API_KEY",
        default=file_deepthink.get("api_key", ""),
    )
    if explicit_key:
        api_key = explicit_key
    elif _same_origin(deepthink_base_url, main_base_url):
        api_key = main_api_key
    else:
        api_key = _DEFAULT_API_KEY
    return _deepthink_from_lobes_role(muse_role, deepthink_base_url, api_key)


def _senses_lobes_fallback(
    lobes_roles: object,
    lobes_gateway_url: str | None,
    main_base_url: str,
    main_api_key: str,
    file_senses: dict[str, str],
) -> "SensesConfig | None":
    """The senses discovery fallback, extracted from ``resolve()`` (colleague#348).

    Mirrors :func:`_deepthink_lobes_fallback` field-for-field — the same
    extraction keeps ``resolve()`` under the SonarCloud S3776 cognitive-
    complexity ceiling. Returns ``None`` when lobes did not resolve, no
    senses role is advertised, or the role carries a blank model.

    **api_key hygiene.** An explicitly declared senses key
    (``COLLEAGUE_SENSES_API_KEY`` env or config.json ``senses.api_key`` —
    usable even without a declared model) always wins. Otherwise the MAIN
    key is inherited only when senses's dial target shares the main
    endpoint's origin (:func:`_same_origin`); a cross-origin senses gets
    :data:`_DEFAULT_API_KEY` instead, so the main Bearer token is never
    forwarded to a host a wire payload advertised (the same Qodo finding on
    colleague#347 the deepthink rung already closed — colleague#348 extends
    it to senses). A wrong/absent key degrades visibly at the senses
    call site, never fails the run.
    """
    senses_role = getattr(lobes_roles, "senses", None) if lobes_roles is not None else None
    if senses_role is None or lobes_gateway_url is None:
        return None
    senses_base_url = _role_dial_base_url(senses_role, lobes_gateway_url)
    explicit_key = _pick(
        None,
        "COLLEAGUE_SENSES_API_KEY",
        "CONVERTIBLE_SENSES_API_KEY",
        default=file_senses.get("api_key", ""),
    )
    if explicit_key:
        api_key = explicit_key
    elif _same_origin(senses_base_url, main_base_url):
        api_key = main_api_key
    else:
        api_key = _DEFAULT_API_KEY
    return _senses_from_lobes_role(senses_role, senses_base_url, api_key)


def _voice_lobes_fallback(
    lobes_roles: object,
    lobes_gateway_url: str | None,
    main_base_url: str,
    main_api_key: str,
    file_voice: dict[str, str],
) -> "VoiceConfig | None":
    """The stt/tts discovery fallback, extracted from ``resolve()`` (colleague#348 t2).

    Same extraction shape as :func:`_senses_lobes_fallback` — keeps
    ``resolve()`` under the SonarCloud S3776 cognitive-complexity ceiling.
    Wraps the untouched :func:`_voice_from_lobes_roles` (which stays exactly
    as-is for its existing callers/tests), computing only the api_key it is
    fed. Returns ``None`` when lobes did not resolve, or neither stt nor tts
    carries a non-blank model (no role is "armed").

    **api_key hygiene — the conservative single-field rule.**
    :class:`VoiceConfig` keeps its single ``api_key`` field — there is no
    per-role ``stt_api_key``/``tts_api_key`` split. That split is a named,
    unbuilt follow-up (decision c15, colleague#348): it would need its own
    re-spec, so it stays parked here. Because one key must cover every armed
    role, the hygiene rule is deliberately conservative rather than
    per-role: an explicitly declared voice key (``COLLEAGUE_VOICE_API_KEY``
    env or config.json ``voice.api_key`` — usable even without a declared
    model; NO ``CONVERTIBLE_VOICE_API_KEY`` fallback, since voice postdates
    the CONVERTIBLE→COLLEAGUE rename) always wins. Otherwise the MAIN key is
    inherited only when EVERY armed role's dial target (armed = a non-blank
    model; an unarmed role's gateway-fallback base_url is excluded from the
    check) shares the main endpoint's origin (:func:`_same_origin`) — stt
    and tts both same-origin inherits, but a SINGLE cross-origin role sinks
    the whole VoiceConfig to :data:`_DEFAULT_API_KEY` instead, never a
    half-armed mix of the main key on one field and the default on the
    other (there is nowhere to put a per-role result with one shared field).
    This is the same Qodo finding on colleague#347 the deepthink and senses
    rungs already closed, extended here to voice's two-role shape. A
    wrong/absent key degrades visibly at the voice call site, never fails
    the run.
    """
    if lobes_roles is None or lobes_gateway_url is None:
        return None
    stt_role = getattr(lobes_roles, "stt", None)
    tts_role = getattr(lobes_roles, "tts", None)
    armed_roles = [
        role
        for role in (stt_role, tts_role)
        if role is not None and str(getattr(role, "model", "") or "").strip()
    ]
    if not armed_roles:
        return None
    explicit_key = _pick(
        None,
        "COLLEAGUE_VOICE_API_KEY",
        default=file_voice.get("api_key", ""),
    )
    if explicit_key:
        api_key = explicit_key
    else:
        dial_targets = (_role_dial_base_url(role, lobes_gateway_url) for role in armed_roles)
        if all(_same_origin(target, main_base_url) for target in dial_targets):
            api_key = main_api_key
        else:
            api_key = _DEFAULT_API_KEY
    return _voice_from_lobes_roles(lobes_roles, lobes_gateway_url, api_key)


def _voice_from_lobes_roles(roles: object, gateway_url: str, api_key: str) -> "VoiceConfig | None":
    """Build a :class:`VoiceConfig` from the gateway's stt/tts roles (t1).

    ``roles`` is the resolved :class:`~colleague.lobes.LobesRoles` (typed
    ``object`` here to avoid a module-level ``lobes`` import — the same lazy
    stance :func:`_resolve_lobes_rung` takes). Used only when voice is NOT
    otherwise declared (env/config.json win). ``stt_base_url``/``tts_base_url``
    are EACH resolved independently via :func:`_role_dial_base_url` (colleague#292,
    S1's follow-on: closes lobes-cli#87 — a role's own ``endpoint`` when
    reachable, *gateway_url* only as the documented fallback) — no longer a
    single blanket gateway-origin-for-all value, so a rig where stt/tts are
    served from genuinely different origins dials each correctly. api_key
    inherits the resolved MAIN endpoint's value. Returns ``None`` when neither
    stt nor tts is armed on the gateway.
    """
    stt_role = getattr(roles, "stt", None)
    tts_role = getattr(roles, "tts", None)
    stt_model = (str(getattr(stt_role, "model", "") or "").strip()) or None
    tts_model = (str(getattr(tts_role, "model", "") or "").strip()) or None

    if stt_model is None and tts_model is None:
        return None

    stt_base_url = (
        _role_dial_base_url(stt_role, gateway_url)
        if stt_role is not None
        else _lobes_base_url(gateway_url)
    )
    tts_base_url = (
        _role_dial_base_url(tts_role, gateway_url)
        if tts_role is not None
        else _lobes_base_url(gateway_url)
    )

    return VoiceConfig(
        stt_model=stt_model,
        tts_model=tts_model,
        stt_base_url=stt_base_url,
        tts_base_url=tts_base_url,
        api_key=api_key,
    )


def _worker_refusal(message: str, remediation: str) -> "CliError":
    """Build the loud three-tier worker refusal (c25/h21), lazily importing
    :class:`~colleague.cli._errors.CliError` (the same lazy-import stance
    :func:`_resolve_lobes_rung` takes for ``colleague.lobes`` — keeps
    ``config``'s module-level import graph unchanged).

    This is the ONE refusal path in this module: every other lobes-fed rung
    (deepthink/senses/voice/realtime) degrades to ``None`` on any resolution
    failure, but an EXPLICITLY armed three-tier config makes the worker role
    MANDATORY — see :func:`_resolve_worker`.
    """
    from colleague.cli._errors import EXIT_USER_ERROR, CliError

    return CliError(EXIT_USER_ERROR, message, remediation)


def _resolve_worker(
    three_tier: bool,
    lobes_roles: object,
    lobes_gateway_url: str | None,
    declared_lobes_url: str | None,
    main_base_url: str,
    main_api_key: str,
    file_worker: dict[str, str],
) -> "WorkerConfig | None":
    """Resolve the three-tier worker seat — REQUIRED when three-tier is armed
    (three-tier-execution arc, plan task t3; covers c3/h3/c25/h21).

    **Not armed (default): a strict no-op.** Returns ``None`` immediately
    without even inspecting ``lobes_roles.worker`` — an advertised worker
    role is read and discarded exactly like ``reranker``, byte-identical to
    today (acceptance criterion 3 of task t3).

    **Armed: the worker role is MANDATORY, never a silent fallback.** Unlike
    every other lobes-fed rung, which degrades to ``None`` on any resolution
    failure, an EXPLICITLY armed three-tier config raises
    :class:`~colleague.cli._errors.CliError` (via :func:`_worker_refusal`)
    naming exactly what is missing — no lobes gateway configured, an
    unreachable gateway, or the gateway advertising no READY worker role —
    rather than ever falling back to cortex silently acting as the worker.
    The refusal fires HERE, at resolution time (``EngineConfig.resolve()``),
    before any episode starts — both ``work`` and ``session`` call
    ``resolve()`` before dispatching any work, so the refusal is uniform
    across both CLI fronts.

    There is deliberately NO declared-worker-model rung (unlike
    deepthink/senses/voice): the worker seat is resolved ONLY by ROLE NAME
    from the lobes gateway — colleague never parses a model name to decide
    who the worker is (the t3 design boundary, "role NAMES only, never
    model-name parsing").

    *declared_lobes_url* is the RAW, no-network operator declaration
    (:func:`resolve_lobes_gateway_url`) — distinct from *lobes_gateway_url*,
    which :func:`_resolve_lobes_rung` already collapses to ``None`` on EITHER
    "nothing declared" OR "declared but unreachable/malformed" (every other
    lobes-fed rung treats those two states identically — they both just fall
    through to the next precedence rung). The refusal here tells them apart
    so the message names the real gap: "no gateway configured" vs "gateway
    `<url>` unreachable".

    **api_key hygiene** mirrors :func:`_senses_lobes_fallback` /
    :func:`_deepthink_lobes_fallback` (colleague#347/#348): an explicit
    ``COLLEAGUE_WORKER_API_KEY`` env or config.json ``worker.api_key`` —
    usable even though there is no declared worker model, since presence is
    keyed on the ARMED three-tier block instead — always wins. Otherwise the
    MAIN key is inherited only when the worker's resolved dial target shares
    the main endpoint's origin (:func:`_same_origin`); a cross-origin worker
    gets the withheld :data:`_DEFAULT_API_KEY` default instead, so the main
    Bearer token is never forwarded to a host a wire payload advertised — the
    SAME withheld-default mechanism the deepthink/senses/voice rungs already
    use (there is no separate notice function; the withheld default IS the
    mechanism, exactly as documented in ``docs/features/cortex-senses.md``'s
    api_key hygiene section). A wrong/absent key degrades visibly at the
    worker dial site (a later task), never fails resolution here.
    """
    if not three_tier:
        return None
    if declared_lobes_url is None:
        raise _worker_refusal(
            "three-tier execution is armed (three_tier) but no lobes gateway is "
            "configured — the worker role can only be discovered from a lobes "
            "gateway",
            "set COLLEAGUE_LOBES_URL or a 'lobes' section in .colleague/config.json "
            "to a gateway advertising a ready worker role, or unset three_tier",
        )
    if lobes_gateway_url is None or lobes_roles is None:
        raise _worker_refusal(
            f"three-tier execution is armed (three_tier) but the lobes gateway "
            f"{declared_lobes_url!r} is unreachable — the worker role could not be "
            "resolved",
            "check the lobes gateway is running and reachable, or unset three_tier",
        )
    worker_role = getattr(lobes_roles, "worker", None)
    if worker_role is None or not getattr(worker_role, "ready", False):
        raise _worker_refusal(
            f"three-tier execution is armed (three_tier) but the lobes gateway "
            f"{lobes_gateway_url!r} advertises no ready worker role",
            "arm a ready worker role on the lobes gateway, or unset three_tier",
        )
    worker_base_url = _role_dial_base_url(worker_role, lobes_gateway_url)
    explicit_key = _pick(
        None,
        "COLLEAGUE_WORKER_API_KEY",
        default=file_worker.get("api_key", ""),
    )
    if explicit_key:
        api_key = explicit_key
    elif _same_origin(worker_base_url, main_base_url):
        api_key = main_api_key
    else:
        api_key = _DEFAULT_API_KEY
    return WorkerConfig(
        model=worker_role.model,
        base_url=worker_base_url,
        api_key=api_key,
        context=int(getattr(worker_role, "context", 0) or 0),
    )


def _resolve_realtime_devices(file_realtime: dict[str, str]) -> tuple[str | None, str | None]:
    """Resolve the LOCAL-MACHINE input/output device knobs (plan task t4).

    Precedence per key: ``COLLEAGUE_REALTIME_INPUT_DEVICE``/
    ``COLLEAGUE_REALTIME_OUTPUT_DEVICE`` env > the ``realtime`` section of
    .colleague/config.json > absent (``None`` — the audio library's own
    default device). These are PURE LOCAL knobs — an id (e.g. ``"2"``) or a
    name substring (e.g. ``"Reachy Mini"``) naming a PortAudio device on THIS
    machine — so, unlike every other RealtimeConfig field, they are resolved
    IDENTICALLY on BOTH the explicit rung (:func:`_resolve_realtime`) and the
    lobes discovery fallback (:func:`_realtime_lobes_fallback`): a discovered
    dial target says nothing about which physical mic/speaker this box
    should use, so both rungs call this ONE helper with the same
    *file_realtime* dict. A blank/whitespace-only value resolves to ``None``,
    same stance as every other blank-string field in this module.
    """
    input_device = _pick(
        None,
        "COLLEAGUE_REALTIME_INPUT_DEVICE",
        default=file_realtime.get("input_device", ""),
    ).strip()
    output_device = _pick(
        None,
        "COLLEAGUE_REALTIME_OUTPUT_DEVICE",
        default=file_realtime.get("output_device", ""),
    ).strip()
    return (input_device or None, output_device or None)


def _resolve_realtime(
    file_realtime: dict[str, str],
    main_api_key: str,
) -> "RealtimeConfig | None":
    """Resolve the EXPLICIT operator-declared realtime dial-target knob
    (realtime-speech arc, plan task t1).

    Precedence per key: ``COLLEAGUE_REALTIME_URL``/``COLLEAGUE_REALTIME_API_KEY``
    env > the ``realtime`` section of .colleague/config.json > absent
    (``None``). No ``CONVERTIBLE_*`` fallback — realtime postdates the
    CONVERTIBLE->COLLEAGUE rename, the same stance
    ``COLLEAGUE_VOICE_API_KEY`` already takes (see :func:`_resolve_voice`).

    Realtime is PRESENT iff the resolved ``url`` is a non-empty,
    non-whitespace string — the "the url IS the presence signal" stance every
    sibling rung takes with its own model field (deepthink/senses/voice); an
    operator-set ``api_key`` with no ``url`` is not a realtime declaration on
    its own (mirrors :func:`_resolve_voice`'s ``stt_model``/``tts_model``
    gate) — it can still arm a DISCOVERED cross-origin role's key, see
    :func:`_realtime_lobes_fallback`.

    This is the OPERATOR-DECLARED rung ONLY — it never consults lobes; the
    discovery fallback (:func:`_realtime_lobes_fallback`) is a SEPARATE,
    lower-precedence rung consulted only when this resolves ``None``.
    ``api_key`` defaults to *main_api_key* with NO same-origin check — an
    explicit operator declaration is trusted intent (the same stance
    :func:`_resolve_voice`/:func:`_resolve_senses`/:func:`_resolve_deepthink`
    take for their own explicit config); same-origin hygiene (#348) applies
    ONLY to the lobes-derived fallback below, whose dial target comes from an
    untrusted wire payload.
    """
    url = _pick(None, "COLLEAGUE_REALTIME_URL", default=file_realtime.get("url", ""))
    if not url.strip():
        return None
    api_key = _pick(
        None,
        "COLLEAGUE_REALTIME_API_KEY",
        default=file_realtime.get("api_key") or main_api_key,
    )
    input_device, output_device = _resolve_realtime_devices(file_realtime)
    return RealtimeConfig(
        available=True,
        ws_url=_realtime_ws_url(url.strip()),
        api_key=api_key,
        input_device=input_device,
        output_device=output_device,
    )


def _realtime_lobes_fallback(
    lobes_roles: object,
    lobes_gateway_url: str | None,
    main_base_url: str,
    main_api_key: str,
    file_realtime: dict[str, str],
    voice: "VoiceConfig | None",
) -> "RealtimeConfig | None":
    """The stt ``realtime_vad_session`` -> RealtimeConfig discovery fallback
    (realtime-speech arc, plan task t1).

    Mirrors :func:`_voice_lobes_fallback`'s extraction shape and api_key
    hygiene. Returns ``None`` unless ALL of: lobes resolved (*lobes_roles*/
    *lobes_gateway_url* both non-``None``), voice is ALREADY armed (*voice* is
    not ``None`` — the spec requirement's "realtime arms only when voice is
    armed"), the gateway advertises an ``stt`` role, and that role carries
    :data:`colleague.lobes.REALTIME_VAD_RESPONSIBILITY` in its
    ``responsibilities`` (:func:`colleague.lobes.stt_supports_realtime` — the
    ONE live availability signal, probed 2026-07-22). In practice a
    successfully-parsed stt :class:`~colleague.lobes.RoleInfo` always carries
    a non-blank model, which already arms ``voice`` via
    :func:`_voice_lobes_fallback` — the *voice* check here is a stated,
    defensive gate matching the requirement text verbatim, not a
    reachable-in-practice branch through the public resolution path.

    **api_key hygiene (the #348 rule, extended to realtime).** An explicitly
    declared realtime key (``COLLEAGUE_REALTIME_API_KEY`` env or config.json
    ``realtime.api_key`` — usable even without a declared ``url``) always
    wins. Otherwise the MAIN key is inherited only when the stt role's OWN
    resolved dial origin (:func:`colleague.lobes.resolve_role_base_url`)
    shares the main endpoint's origin (:func:`_same_origin`); a cross-origin
    stt role gets :data:`_DEFAULT_API_KEY` instead, so the main Bearer token
    is never forwarded to a host a wire payload advertised — the identical
    Qodo finding on colleague#347/#348 the deepthink/senses/voice rungs
    already close. A wrong/absent key degrades visibly at the realtime dial
    site (a later task), never fails resolution here.
    """
    if voice is None or lobes_roles is None or lobes_gateway_url is None:
        return None
    stt_role = getattr(lobes_roles, "stt", None)
    # Lazy import mirrors every other lobes-consulting helper in this module
    # (keeps config's module import graph unchanged; lets tests monkeypatch it).
    from colleague import lobes as _lobes

    if not _lobes.stt_supports_realtime(stt_role):
        return None
    origin = _lobes.resolve_role_base_url(stt_role, lobes_gateway_url)
    explicit_key = _pick(
        None,
        "COLLEAGUE_REALTIME_API_KEY",
        default=file_realtime.get("api_key", ""),
    )
    if explicit_key:
        api_key = explicit_key
    elif _same_origin(origin, main_base_url):
        api_key = main_api_key
    else:
        api_key = _DEFAULT_API_KEY
    input_device, output_device = _resolve_realtime_devices(file_realtime)
    return RealtimeConfig(
        available=True,
        ws_url=_realtime_ws_url(origin),
        api_key=api_key,
        input_device=input_device,
        output_device=output_device,
    )


def _emit_lobes_unreachable_notice(gateway_url: str) -> None:
    """Emit ONE stderr notice that an armed lobes gateway was unreachable.

    Fires at most once per :meth:`EngineConfig.resolve` call (not once per field)
    — resolution proceeds on the next precedence rung, never hard-fails (h7).
    """
    print(
        f"colleague: lobes gateway {gateway_url!r} unreachable — proceeding on "
        "the next config precedence rung (config.json / builtin default)",
        file=sys.stderr,
    )


def _resolve_lobes_rung(
    repo_path: str | Path | None,
    discover_lobes: bool,
) -> "tuple[str | None, str | None, object | None, str | None, dict[str, str]]":
    """Consult the lobes gateway (task t4) and return its DEFAULTS-SOURCE bundle.

    Extracted from :meth:`EngineConfig.resolve` to hold its cognitive
    complexity under the SonarCloud S3776 ceiling (15) — pure extraction, no
    behavior change.

    When armed (``COLLEAGUE_LOBES_URL`` env or a ``lobes`` section in
    config.json), the gateway is consulted ONCE as a DEFAULTS SOURCE feeding
    cortex → the main model id + base_url, senses → a SensesConfig, voice →
    a VoiceConfig, and the embedder → ``embed_env`` overrides (S2, task t19).
    Unreachable degrades to the next precedence rung with ONE stderr notice
    (never a hard-fail, h7); unarmed (``discover_lobes=False``, or no gateway
    URL resolved) makes NO network call and returns an all-``None``/``{}``
    bundle — byte-identical to a pre-lobes resolve. ``discover_lobes=False`` is
    the OFFLINE seam the contractually no-network ``doctor`` provider group
    needs so an armed lobes gateway doesn't leak a network call into a plain
    ``colleague doctor``; the default (``True``) still discovers live per run.

    **Per-role dialing (colleague#292, S1's follow-on — closes lobes-cli#87
    end-to-end).** ``lobes_base_url`` is CORTEX's own resolved dial target
    (:func:`_role_dial_base_url`), not a blanket gateway-origin value — senses
    and voice each resolve their OWN dial target independently from the
    returned ``lobes_gateway_url``, below. The pre-0.38 "every role dials the
    gateway origin" workaround is gone; the gateway origin survives only as
    :func:`~colleague.lobes.resolve_role_base_url`'s documented per-role
    fallback for an unwired role or a disallowed scheme.

    Returns
    -------
    (lobes_base_url, lobes_model, lobes_roles, lobes_gateway_url, lobes_embed_env)
        ``lobes_base_url``/``lobes_model`` are the two values ``resolve()``
        folds into its own base_url/model defaults; ``lobes_roles`` is the
        raw resolved :class:`~colleague.lobes.LobesRoles` (or ``None``) the
        senses/voice rungs also consult; ``lobes_gateway_url`` is the armed
        gateway origin itself (needed by the senses/voice per-role resolution
        below, and as the documented fallback); ``lobes_embed_env`` is the
        embedder's env-var overrides (``{}`` when unarmed/unreachable/no
        embedder — see :func:`colleague.lobes.embed_env`).
    """
    if not discover_lobes:
        return None, None, None, None, {}
    lobes_gateway_url = resolve_lobes_gateway_url(repo_path)
    if lobes_gateway_url is None:
        return None, None, None, None, {}
    # Lazy import keeps config's module import graph unchanged (the
    # sanitize_model idiom) and lets tests monkeypatch resolve_roles.
    from colleague import lobes as _lobes

    lobes_roles = _lobes.resolve_roles(lobes_gateway_url)
    if lobes_roles is None:
        _emit_lobes_unreachable_notice(lobes_gateway_url)
        return None, None, None, None, {}
    # Per-role dialing (S1's follow-on, S2): cortex dials ITS OWN endpoint,
    # falling back to the gateway origin only when unwired/disallowed.
    lobes_base_url = _role_dial_base_url(lobes_roles.cortex, lobes_gateway_url)
    lobes_model = (lobes_roles.cortex.model or "").strip() or None
    lobes_embed_env = _lobes.embed_env(lobes_roles, lobes_gateway_url)
    return lobes_base_url, lobes_model, lobes_roles, lobes_gateway_url, lobes_embed_env


def _model_pin_source(model_arg: str | None, file_model: str | None) -> str | None:
    """Name which layer PINNED the main model id, or ``None`` when it came from
    lobes role discovery / the builtin default — i.e. it was never a pin at all
    (same-role stale-pin refresh, plan task t9, honesty h7).

    Mirrors ``_pick(model, "COLLEAGUE_MODEL", "CONVERTIBLE_MODEL",
    default=model_default)``'s OWN precedence exactly — flag > COLLEAGUE_MODEL
    env > CONVERTIBLE_MODEL env (the convertible->colleague rename back-compat
    fallback) > config.json — so a refresh warning's ``source`` is never wrong
    about which layer actually won. Reads NOTHING beyond these four inputs:
    no ``Task``/instruction parameter exists on this function or on
    :meth:`EngineConfig.resolve` at all, which is the structural half of h7's
    "model resolution inputs are exactly {flag, env, config.json, lobes role
    discovery} — no code path reads task content to pick a model."
    """
    if model_arg is not None:
        return "flag"
    if os.environ.get("COLLEAGUE_MODEL"):
        return "COLLEAGUE_MODEL"
    if os.environ.get("CONVERTIBLE_MODEL"):
        return "CONVERTIBLE_MODEL"
    if file_model is not None:
        return "config.json"
    return None


def _refresh_stale_model_pin(
    resolved_model: str,
    model_arg: str | None,
    file_model: str | None,
    lobes_gateway_url: str | None,
    lobes_roles: object,
    api_key: str = "",
) -> "tuple[str, ModelRefreshWarning | None]":
    """Same-role stale-pin refresh AT RESOLUTION TIME (plan task t9, spec
    c10/c11, honesty h7/h8): a main-model id pinned via flag/env/config.json
    that the lobes gateway's successfully-fetched ``/v1/models`` roster no
    longer carries is STALE CONFIG, not a reason to die — substitute
    CORTEX's own currently-discovered id (cortex is the role the MAIN model
    resolves from in the legacy/two-tier path this rung covers — see
    :class:`WorkerConfig`'s docstring: the three-tier worker seat has
    deliberately NO declared-pin rung of its own, so it can never go stale
    this way; a stale WORKER id is a ``/capabilities``-vs-actually-served
    advert mismatch instead, ``colleague/oilcheck/three_tier.py``'s
    territory, not a pin refresh) and record a warning naming the stale id,
    its source layer, and the refreshed id. This is a REFRESH, never a
    fallback/routing decision: the target role never changes, only its
    served id.

    Fires ONLY when ALL of:

    - the pin has a NAMEABLE source (:func:`_model_pin_source` returns
      non-``None``) — a value that already came from lobes discovery itself,
      or the builtin default with no pin at all, is already the freshest
      available id and needs no check (acceptance 2: unpinned resolves
      byte-identically, there is nothing to warn about);
    - lobes is armed AND reachable (*lobes_gateway_url*/*lobes_roles* both
      non-``None``) — unarmed/unreachable leaves the pin untouched (h8);
    - the gateway's ``/v1/models`` membership check actually RUNS
      (:func:`colleague.lobes.fetch_served_model_ids` returns non-``None`` —
      a fetch failure, including a bare 401, means NO refresh, per the
      spec's explicit "a membership check that cannot run means no refresh"
      rule — distinct from a successfully-fetched EMPTY list, which is a
      valid "nothing served" membership result);
    - the pinned id is absent from that fetched list (acceptance 2: a VALID
      pin — present in the list — resolves byte-identically, untouched);
    - cortex's OWN discovered id (from the SAME ``/capabilities`` call
      *lobes_roles* already carries — never a second network round trip) is
      present/non-blank (acceptance 2: "the role advertising no model" also
      leaves the original value in place).

    Returns ``(resolved_model, warning)`` — *resolved_model* is the
    refreshed id when a refresh fired, else *resolved_model* unchanged;
    *warning* is the structured :class:`~colleague.lobes.ModelRefreshWarning`
    (already emitted to stderr via
    :func:`colleague.lobes.emit_model_refresh_warning`), or ``None``.
    """
    pin_source = _model_pin_source(model_arg, file_model)
    if pin_source is None or lobes_gateway_url is None or lobes_roles is None:
        return resolved_model, None
    # Lazy import mirrors every other lobes-consulting helper in this module
    # (keeps config's module-level import graph unchanged; lets tests
    # monkeypatch it).
    from colleague import lobes as _lobes

    served_ids = _lobes.fetch_served_model_ids(lobes_gateway_url, api_key=api_key)
    if served_ids is None or resolved_model in served_ids:
        return resolved_model, None
    cortex_model = (getattr(lobes_roles.cortex, "model", "") or "").strip()
    if not cortex_model:
        return resolved_model, None
    warning = _lobes.ModelRefreshWarning(
        role="cortex",
        stale_id=resolved_model,
        source=pin_source,
        refreshed_id=cortex_model,
        point="resolution",
    )
    _lobes.emit_model_refresh_warning(warning)
    return cortex_model, warning


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
    data = _merged_config_json(repo_path)
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
    data = _merged_config_json(repo_path)
    enabled = data.get("testintegrity")
    retries = data.get("testintegrity_fix_retries")
    return (
        None if enabled is None else str(enabled),
        None if retries is None else str(retries),
    )


def _parse_bool(value: str) -> bool:
    """Parse a config/env boolean: ``0``/``false``/``no``/``off``/empty → False, else True.

    Case-insensitive and whitespace-tolerant so ``COLLEAGUE_LINT=0``,
    ``COLLEAGUE_LINT=false`` and a JSON ``"lint": false`` (which stringifies to
    ``"False"``) all disable the gate.
    """
    return value.strip().lower() not in ("", "0", "false", "no", "off")


def _resolve_lint_enabled(file_value: str | None) -> bool:
    """Resolve the lint-gate enabled flag: env ``COLLEAGUE_LINT`` > config.json > default-on.

    The ``--no-lint`` CLI flag is applied by the work path *after* ``resolve()``
    (it sets ``config.lint = False``), so this stays off the ``resolve()`` signature
    and the S107 parameter ceiling is held (the synthesis-reserve precedent).
    """
    for env_key in ("COLLEAGUE_LINT", "CONVERTIBLE_LINT"):
        env = os.environ.get(env_key)
        if env is not None and env.strip() != "":
            return _parse_bool(env)
    if file_value is not None:
        return _parse_bool(file_value)
    return _DEFAULT_LINT_ENABLED


def _load_watch_override(repo_path: str | Path) -> str | None:
    """Read the ``watch`` key from .colleague/config.json as a raw string (#307).

    Mirrors :func:`_load_coherence_override` — kept separate from
    :func:`load_config_file` (which owns only the endpoint keys). Reads via
    :func:`_merged_config_json` (the at-home per-key merge, #339): a repo-level
    file that omits the key no longer shadows a user-level default.
    """
    data = _merged_config_json(repo_path)
    value = data.get("watch")
    return None if value is None else str(value)


def _resolve_watch_enabled(file_value: str | None) -> bool:
    """Resolve the flight-plane armed flag: env ``COLLEAGUE_WATCH`` > config.json >
    default-on (#307).

    The ``--watch`` / ``--no-watch`` CLI flags override this post-resolve (the work
    path resolves the effective value against ``config.watch``), so this stays off
    the ``resolve()`` signature — the ``_resolve_lint_enabled`` precedent.
    """
    for env_key in ("COLLEAGUE_WATCH", "CONVERTIBLE_WATCH"):
        env = os.environ.get(env_key)
        if env is not None and env.strip() != "":
            return _parse_bool(env)
    if file_value is not None:
        return _parse_bool(file_value)
    return _DEFAULT_WATCH_ENABLED


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
    data = _merged_config_json(repo_path)
    until_done = data.get("until_done")
    max_episodes = data.get("max_episodes")
    compaction_cap = data.get("compaction_cap")
    return (
        None if until_done is None else str(until_done),
        None if max_episodes is None else str(max_episodes),
        None if compaction_cap is None else str(compaction_cap),
    )


def _resolve_until_done_enabled(file_value: str | None) -> bool:
    """Resolve the chain-arming flag: env ``COLLEAGUE_UNTIL_DONE`` > config.json >
    default-OFF (indefinite-run decision c21 — armed, never ambient).

    The ``--until-done`` CLI flag is applied by the work path *after*
    ``resolve()`` (t5), so this stays off the ``resolve()`` signature — the
    ``_resolve_lint_enabled`` precedent (S107 parameter ceiling).
    """
    for env_key in ("COLLEAGUE_UNTIL_DONE", "CONVERTIBLE_UNTIL_DONE"):
        env = os.environ.get(env_key)
        if env is not None and env.strip() != "":
            return _parse_bool(env)
    if file_value is not None:
        return _parse_bool(file_value)
    return _DEFAULT_UNTIL_DONE


def _load_coherence_override(repo_path: str | Path) -> str | None:
    """Read the ``coherence`` key from .colleague/config.json as a raw string.

    Mirrors :func:`_load_memory_override` (kept separate from
    :func:`load_config_file`, which owns only the endpoint keys). Reads via
    :func:`_merged_config_json` (the at-home per-key merge, #339): a repo-level
    file that omits the key no longer shadows a user-level default.
    """
    data = _merged_config_json(repo_path)
    value = data.get("coherence")
    return None if value is None else str(value)


def _resolve_coherence_enabled(file_value: str | None) -> bool:
    """Resolve the coherence-gate flag: env ``COLLEAGUE_COHERENCE`` > config.json > default-on.

    The ``--no-coherence`` CLI flag is applied by the work path *after*
    ``resolve()`` (it sets ``config.coherence = False``) — the exact --no-lint
    precedent (#294; operator decision on colleague#291: default-ON warn-only).
    """
    for env_key in ("COLLEAGUE_COHERENCE", "CONVERTIBLE_COHERENCE"):
        env = os.environ.get(env_key)
        if env is not None and env.strip() != "":
            return _parse_bool(env)
    if file_value is not None:
        return _parse_bool(file_value)
    return _DEFAULT_COHERENCE_ENABLED


def _load_memory_override(repo_path: str | Path) -> str | None:
    """Read the ``memory`` key from .colleague/config.json as a raw string.

    Mirrors :func:`_load_lint_overrides` (kept separate from
    :func:`load_config_file`, whose endpoint-string contract must not change).
    Returns the stringified value or ``None`` when absent; a missing/malformed
    file yields ``None`` and never raises. Reads via
    :func:`_merged_config_json` (the at-home per-key merge, #339): a repo-level
    file that omits the key no longer shadows a user-level default.
    """
    data = _merged_config_json(repo_path)
    value = data.get("memory")
    return None if value is None else str(value)


def _resolve_memory_enabled(file_value: str | None) -> bool:
    """Resolve memory-informed-runtime enablement (spec R1 / plan t2):
    env ``COLLEAGUE_MEMORY`` > config.json ``{"memory": ...}`` > default-on.

    Default-ON is safe because the loop additionally arms only when the repo
    contains a ``.eidetic/`` store AND the eidetic CLI is installed — a repo
    without a store (every tmp test repo) is a strict no-op regardless.
    """
    for env_key in ("COLLEAGUE_MEMORY", "CONVERTIBLE_MEMORY"):
        env = os.environ.get(env_key)
        if env is not None and env.strip() != "":
            return _parse_bool(env)
    if file_value is not None:
        return _parse_bool(file_value)
    return _DEFAULT_MEMORY_ENABLED


def _resolve_three_tier_enabled(file_value: str | None) -> bool:
    """Resolve the three-tier execution arming flag: env ``COLLEAGUE_THREE_TIER``
    > config.json ``three_tier`` > default-OFF (three-tier-execution arc,
    plan task t3).

    Default-OFF, never ambient — the ``until_done`` precedent (decision c21):
    an execution-mode change needs explicit operator intent. No CLI flag in
    this task (kept off the ``resolve()`` signature, the ``_resolve_lint_enabled``
    S107-ceiling precedent) — a later task may add one.
    """
    env = os.environ.get("COLLEAGUE_THREE_TIER")
    if env is not None and env.strip() != "":
        return _parse_bool(env)
    if file_value is not None:
        return _parse_bool(file_value)
    return _DEFAULT_THREE_TIER_ENABLED


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
    data = _merged_config_json(repo_path)
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


def _resolve_testintegrity_enabled(file_value: str | None) -> bool:
    """Resolve the test-integrity gate flag: env ``COLLEAGUE_TESTINTEGRITY`` > config > default-on.

    Kept off the ``resolve()`` signature (no CLI flag in v0), mirroring
    :func:`_resolve_lint_enabled` so the S107 parameter ceiling holds.
    """
    for env_key in ("COLLEAGUE_TESTINTEGRITY", "CONVERTIBLE_TESTINTEGRITY"):
        env = os.environ.get(env_key)
        if env is not None and env.strip() != "":
            return _parse_bool(env)
    if file_value is not None:
        return _parse_bool(file_value)
    return _DEFAULT_TESTINTEGRITY_ENABLED


def _resolve_affected_tests_enabled(file_value: str | None) -> bool:
    """Resolve the affected-tests gate flag: env ``COLLEAGUE_AFFECTED_TESTS`` > config > default-on.

    Mirrors :func:`_resolve_lint_enabled` so the S107 parameter ceiling holds.
    ``0``/``false`` disables; any truthy value enables.
    """
    env = os.environ.get("COLLEAGUE_AFFECTED_TESTS")
    if env is not None and env.strip() != "":
        return _parse_bool(env)
    if file_value is not None:
        return _parse_bool(file_value)
    return _DEFAULT_AFFECTED_TESTS_ENABLED


def _resolve_deepthink(
    file_deepthink: dict[str, str],
    main_base_url: str,
    main_api_key: str,
) -> "DeepthinkConfig | None":
    """Resolve the optional dual-model deepthink escalation target.

    Precedence per key: ``COLLEAGUE_DEEPTHINK_*`` env (``CONVERTIBLE_DEEPTHINK_*``
    honored as a deprecated fallback, matching every other knob in this module)
    > the ``deepthink`` section of .colleague/config.json > a default.

    Dual-model is PRESENT iff the resolved model is a non-empty, non-whitespace
    string; otherwise this returns ``None`` regardless of the other keys — an
    operator-set base_url/api_key/context_budget with no model is not a
    dual-model declaration (the model IS the presence signal, spec h1).

    ``base_url``/``api_key`` default to *main_base_url*/*main_api_key* — the
    ALREADY-resolved main endpoint values — so declaring dual-model needs only
    a model id unless deepthink truly lives at a different endpoint. An empty
    file value for ``base_url``/``api_key`` is treated as absent (falls
    through to the main endpoint), matching the env-var "empty is absent"
    convention used throughout this module.

    ``context_budget`` parses as an int; a malformed or absent value falls
    back to :data:`_DEFAULT_DEEPTHINK_CONTEXT_BUDGET` and never raises,
    mirroring every other numeric knob resolved via :func:`_try_int`.
    """
    model = _pick(
        None,
        "COLLEAGUE_DEEPTHINK_MODEL",
        "CONVERTIBLE_DEEPTHINK_MODEL",
        default=file_deepthink.get("model", ""),
    )
    if not model.strip():
        return None
    base_url = _pick(
        None,
        "COLLEAGUE_DEEPTHINK_BASE_URL",
        "CONVERTIBLE_DEEPTHINK_BASE_URL",
        default=file_deepthink.get("base_url") or main_base_url,
    )
    api_key = _pick(
        None,
        "COLLEAGUE_DEEPTHINK_API_KEY",
        "CONVERTIBLE_DEEPTHINK_API_KEY",
        default=file_deepthink.get("api_key") or main_api_key,
    )
    context_budget = _try_int(
        _pick(
            None,
            "COLLEAGUE_DEEPTHINK_CONTEXT_BUDGET",
            "CONVERTIBLE_DEEPTHINK_CONTEXT_BUDGET",
            default=file_deepthink.get("context_budget", ""),
        ),
        default=_DEFAULT_DEEPTHINK_CONTEXT_BUDGET,
    )
    # The media-bridge declaration (t8): truthy strings arm it, anything else
    # (absent, empty, junk) resolves False — a declaration, never a probe.
    multimodal = _pick(
        None,
        "COLLEAGUE_DEEPTHINK_MULTIMODAL",
        "CONVERTIBLE_DEEPTHINK_MULTIMODAL",
        default=file_deepthink.get("multimodal", ""),
    ).strip().lower() in ("1", "true", "yes")
    return DeepthinkConfig(
        model=model.strip(),
        base_url=base_url,
        api_key=api_key,
        context_budget=context_budget,
        multimodal=multimodal,
    )


def _resolve_senses(
    file_senses: dict[str, str],
    main_base_url: str,
    main_api_key: str,
) -> "SensesConfig | None":
    """Resolve the optional senses (multimodal front-door) escalation target.

    Mirrors :func:`_resolve_deepthink` field-for-field (cortex/senses arc,
    task t3). Precedence per key: ``COLLEAGUE_SENSES_*`` env
    (``CONVERTIBLE_SENSES_*`` honored as a deprecated fallback, matching
    every other knob in this module) > the ``senses`` section of
    .colleague/config.json > a default.

    Senses is PRESENT iff the resolved model is a non-empty, non-whitespace
    string; otherwise this returns ``None`` regardless of the other keys —
    an operator-set base_url/api_key/context_budget with no model is not a
    senses declaration (the model IS the presence signal, same as deepthink).

    ``base_url``/``api_key`` default to *main_base_url*/*main_api_key* — the
    ALREADY-resolved main endpoint values — so declaring senses needs only a
    model id unless senses truly lives at a different endpoint. An empty
    file value for ``base_url``/``api_key`` is treated as absent (falls
    through to the main endpoint), matching the env-var "empty is absent"
    convention used throughout this module.

    ``context_budget`` parses as an int; a malformed or absent value falls
    back to :data:`_DEFAULT_SENSES_CONTEXT_BUDGET` and never raises,
    mirroring every other numeric knob resolved via :func:`_try_int`.

    Scope note (task t3): this resolves ONLY env > config.json > absent — the
    lobes discovery rung (t4) is a separate, later task and is not consulted
    here.
    """
    model = _pick(
        None,
        "COLLEAGUE_SENSES_MODEL",
        "CONVERTIBLE_SENSES_MODEL",
        default=file_senses.get("model", ""),
    )
    if not model.strip():
        return None
    # INTENTIONAL (Qodo #2, cortex/senses PR #281): the ``or`` below treats an
    # explicitly-empty config.json ``senses.base_url``/``api_key`` string the
    # SAME as an absent key — both fall through to the main endpoint's already-
    # resolved value. This is not a lost override: a JSON string field cannot
    # distinguish "explicitly blank" from "omitted" any more usefully than
    # "absent" does here, and this is the field-for-field mirror of
    # ``_resolve_deepthink``'s identical ``file_x or main_x`` pattern a few
    # functions above — changing it here without changing deepthink would
    # split the two resolvers' behavior. See
    # ``tests/test_config_senses.py::test_config_file_empty_base_url_and_api_key_fall_through_to_main``
    # for the pinned regression test.
    base_url = _pick(
        None,
        "COLLEAGUE_SENSES_BASE_URL",
        "CONVERTIBLE_SENSES_BASE_URL",
        default=file_senses.get("base_url") or main_base_url,
    )
    api_key = _pick(
        None,
        "COLLEAGUE_SENSES_API_KEY",
        "CONVERTIBLE_SENSES_API_KEY",
        default=file_senses.get("api_key") or main_api_key,
    )
    context_budget = _try_int(
        _pick(
            None,
            "COLLEAGUE_SENSES_CONTEXT_BUDGET",
            "CONVERTIBLE_SENSES_CONTEXT_BUDGET",
            default=file_senses.get("context_budget", ""),
        ),
        default=_DEFAULT_SENSES_CONTEXT_BUDGET,
    )
    # A declaration, never a probe — truthy strings arm it, anything else
    # (absent, empty, junk) resolves False, mirroring deepthink.multimodal.
    multimodal = _pick(
        None,
        "COLLEAGUE_SENSES_MULTIMODAL",
        "CONVERTIBLE_SENSES_MULTIMODAL",
        default=file_senses.get("multimodal", ""),
    ).strip().lower() in ("1", "true", "yes")
    return SensesConfig(
        model=model.strip(),
        base_url=base_url,
        api_key=api_key,
        context_budget=context_budget,
        multimodal=multimodal,
    )


def _resolve_voice(
    file_voice: dict[str, str],
    main_base_url: str,
    main_api_key: str,
) -> "VoiceConfig | None":
    """Resolve the optional voice (stt/tts) escalation target.

    Mirrors :func:`_resolve_senses` field-for-field. Precedence per key:
    ``COLLEAGUE_STT_MODEL``/``COLLEAGUE_TTS_MODEL``/``COLLEAGUE_VOICE_*`` env
    > the ``voice`` section of .colleague/config.json > a default.

    Voice is PRESENT iff at least one of ``stt_model`` or ``tts_model`` is a
    non-empty, non-whitespace string; otherwise this returns ``None``.

    ``base_url``/``api_key`` default to *main_base_url*/*main_api_key* — the
    ALREADY-resolved main endpoint values. An empty file value for
    ``base_url``/``api_key`` is treated as absent (falls through to the main
    endpoint).
    """
    stt_model = _pick(
        None,
        "COLLEAGUE_STT_MODEL",
        default=file_voice.get("stt_model", ""),
    )
    tts_model = _pick(
        None,
        "COLLEAGUE_TTS_MODEL",
        default=file_voice.get("tts_model", ""),
    )
    stt_model = stt_model.strip() if stt_model else ""
    tts_model = tts_model.strip() if tts_model else ""
    if not stt_model and not tts_model:
        return None
    base_url = _pick(
        None,
        "COLLEAGUE_VOICE_BASE_URL",
        default=file_voice.get("base_url") or main_base_url,
    )
    api_key = _pick(
        None,
        "COLLEAGUE_VOICE_API_KEY",
        default=file_voice.get("api_key") or main_api_key,
    )
    return VoiceConfig(
        stt_model=stt_model or None,
        tts_model=tts_model or None,
        stt_base_url=base_url,
        tts_base_url=base_url,
        api_key=api_key,
    )


def _resolve_testintegrity_reviewer_model(
    explicit: str,
    deepthink: "DeepthinkConfig | None",
    main_base_url: str,
) -> str:
    """Default the test-integrity diverse-model reviewer to the deepthink model.

    Spec c10(d) (task t7): when dual-model deepthink (t1) is configured and the
    operator has NOT set an explicit ``COLLEAGUE_TESTINTEGRITY_REVIEWER_MODEL``
    (or its ``CONVERTIBLE_*`` fallback), the deepthink model becomes the
    reviewer default — the strong reasoner is the natural diverse reviewer for
    a mirrored-test finding (#203).

    *explicit* is the value already resolved from env (empty/whitespace means
    unconfigured, matching this module's convention throughout). An
    explicit value — even whitespace-only-vs-non-whitespace aside, ANY
    non-blank explicit value — always wins over the default; this function
    only ever fills in the ELSE branch.

    The default is guarded to the SAME endpoint: the reviewer subagent switch
    (``colleague/subagents.py``'s ``dataclasses.replace(parent_config,
    model=..., role=...)``) carries only a model name — the spawned child
    inherits the parent's ``base_url``/``api_key`` unchanged. Defaulting to a
    deepthink model served on a DIFFERENT endpoint would point the reviewer
    subagent at a model name the main endpoint likely doesn't serve, so when
    ``deepthink.base_url`` differs from *main_base_url* the reviewer model is
    left exactly as *explicit* (empty, or a caller-provided whitespace value
    from an already-empty resolution). Honest v1 limit: a cross-endpoint
    reviewer default is a documented follow-up that needs the subagent switch
    to carry an endpoint of its own — not built here.
    """
    if explicit.strip():
        return explicit
    if deepthink is not None and deepthink.base_url == main_base_url:
        return deepthink.model
    return explicit


def resolve_engine(explicit: str | None) -> str:
    """Resolve the backend plugin name to drive.

    Precedence, highest first: an explicit value (the ``--engine`` flag), the
    ``COLLEAGUE_ENGINE`` environment variable (legacy ``CONVERTIBLE_ENGINE`` is
    honored as a deprecated fallback), then the built-in default
    (:data:`_DEFAULT_ENGINE`). Engine selection is config too, so it mirrors the
    provider-field precedence — but it is a separate concern (the ``mock`` engine
    never reads provider config).

    An empty or whitespace-only candidate is treated as *absent*, not as a valid
    override: ``--engine ''`` (or ``--engine "$VAR"`` with ``VAR`` unset, or a
    blank ``COLLEAGUE_ENGINE``) falls through to the next source rather than
    resolving to an invalid engine name that would later raise ``UnknownEngine``.
    A non-blank value is returned stripped of surrounding whitespace.
    """
    for candidate in (
        explicit,
        os.environ.get("COLLEAGUE_ENGINE"),
        os.environ.get("CONVERTIBLE_ENGINE"),
    ):
        if candidate and candidate.strip():
            return candidate.strip()
    return _DEFAULT_ENGINE


def resolve_session_engine(explicit: str | None) -> str:
    """Resolve the backend for the *interactive session* (``colleague session``).

    The session is colleague-driving-colleague, so it defaults to colleague's own
    served backend exactly like :func:`resolve_engine`. This adds ONE session-scoped
    override slotted ahead of the global default: an explicit ``--engine`` flag wins,
    then ``COLLEAGUE_SESSION_ENGINE`` (a session-only override, so an operator can
    point the conversational session at a different backend than a bare
    ``colleague work`` without changing the global default), then the normal
    :func:`resolve_engine` chain (``COLLEAGUE_ENGINE`` → built-in default).

    An empty or whitespace-only candidate is treated as *absent* (not a valid
    override), matching :func:`resolve_engine`.
    """
    if explicit and explicit.strip():
        return explicit.strip()
    session_env = os.environ.get("COLLEAGUE_SESSION_ENGINE")
    if session_env and session_env.strip():
        return session_env.strip()
    return resolve_engine(None)


# ---------------------------------------------------------------------------
# Presence-lane ladder rung resolution (presence-default-everywhere arc,
# spec docs/specs/2026-07-08-colleague-s-middle-manager-presence-is-now-its-def.md,
# plan task t4).
# ---------------------------------------------------------------------------

# The presence lane's bounded degradation ladder, highest-fidelity rung first:
# "loop" is the senses agentic loop (t5, the DEFAULT rung whenever senses is
# armed); "beats" is today's fixed-beat lane (intake/ack/updates/talk, an
# explicit operator opt-down); "off" is cortex-only — no middle-manager
# presence at all, either because no senses model is resolved (nothing to
# talk to) or because the operator disarmed the lane. Downstream front tasks
# (t7-t11) consult :func:`resolve_presence_rung` to learn which rung to drive;
# this module only decides the rung, it never wires a front.
PRESENCE_RUNGS = ("loop", "beats", "off")

# Values that normalize to the "off" rung for COLLEAGUE_PRESENCE / the
# top-level "presence" config.json key — mirrors ``_parse_bool``'s falsy
# vocabulary so ``COLLEAGUE_PRESENCE=0`` behaves the same way every other
# boolean-shaped knob in this module does.
_PRESENCE_OFF_VALUES = frozenset({"off", "0", "false", "no"})


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
    data = _merged_config_json(repo_path)
    value = data.get("presence")
    return None if value is None else str(value)


def _normalize_presence_value(value: str) -> str | None:
    """Map a raw ``presence`` string to a canonical rung name, or ``None``.

    Case-insensitive and whitespace-tolerant, matching every other knob's
    parsing style in this module. ``"off"``/``"0"``/``"false"``/``"no"`` all
    normalize to ``"off"``; ``"beats"``/``"loop"`` pass straight through. A
    blank or unrecognised value (a typo, e.g. ``"loops"``) returns ``None`` so
    the caller falls through to the NEXT precedence rung instead of silently
    trusting a malformed value — never raises.
    """
    normalized = value.strip().lower()
    if not normalized:
        return None
    if normalized in _PRESENCE_OFF_VALUES:
        return "off"
    if normalized in ("beats", "loop"):
        return normalized
    return None


def resolve_presence_rung(
    config: "EngineConfig",
    *,
    cortex_only: bool = False,
    env: Optional[Mapping[str, str]] = None,
    repo_path: str | Path | None = None,
) -> str:
    """Resolve which presence-lane ladder rung is active for this work item.

    Returns one of :data:`PRESENCE_RUNGS` (``"loop"`` | ``"beats"`` | ``"off"``).
    *config* is an already-resolved :class:`EngineConfig` (any front — session,
    talk, background, resident, or a one-shot ``work`` item — resolves through
    the SAME ``EngineConfig``, so this one function serves every front).

    Precedence, highest first:

    1. *cortex_only* — the front's own ``--cortex-only`` bypass (a session-wide
       flag in ``colleague session``, a per-run flag in ``colleague work``,
       etc.) always forces ``"off"``, regardless of anything else below.
    2. ``config.senses is None`` — senses was never resolved at all (no
       operator-declared model, no lobes discovery). There is nothing to talk
       to, so the rung is ``"off"`` — byte-identical to pre-arc behaviour
       (honesty h1: an install with no senses resolved stays byte-identical on
       every front).
    3. ``COLLEAGUE_PRESENCE`` env var (``CONVERTIBLE_PRESENCE`` honored as a
       deprecated fallback, matching every other knob in this module) —
       ``"loop"``, ``"beats"``, or an off-shaped value (``"off"``/``"0"``/
       ``"false"``/``"no"``).
    4. a top-level ``presence`` key in ``.colleague/config.json`` (only
       consulted when *repo_path* is given) — same three values.
    5. the built-in default: ``"loop"`` — the senses agentic loop is the
       DEFAULT rung whenever senses is armed and not disarmed (the arc's
       "default state" requirement).

    Never raises: a malformed or unrecognised env/config value (a typo) is
    treated as absent and falls through to the next precedence rung, exactly
    like every other knob resolved in this module — it never silently wins
    with a nonsensical value, but it also never blocks resolution.

    This is a PURE function over its arguments (no I/O beyond the optional
    config-file read) — it does not mutate *config*, and it is not baked into
    :meth:`EngineConfig.resolve` or ``to_dict()``: a field would have to be
    included/omitted from the artifact snapshot, and *cortex_only* is a
    per-front, post-resolve decision (fronts apply it by nulling
    ``config.senses`` today) rather than a value known at ``resolve()`` time.
    Keeping this a standalone resolver keeps a senses-less or cortex-only
    config's ``to_dict()`` untouched (byte-identical, sacred per this repo's
    conventions) while still giving downstream tasks (the artifact/debug
    surface, t5-t11) one authoritative call to learn the active rung.
    """
    if env is None:
        env = os.environ

    if cortex_only:
        return "off"

    if config.senses is None:
        return "off"

    for env_key in ("COLLEAGUE_PRESENCE", "CONVERTIBLE_PRESENCE"):
        raw = env.get(env_key)
        if raw is not None:
            normalized = _normalize_presence_value(raw)
            if normalized is not None:
                return normalized

    if repo_path is not None:
        file_value = _load_presence_override(repo_path)
        if file_value is not None:
            normalized = _normalize_presence_value(file_value)
            if normalized is not None:
                return normalized

    return "loop"


@dataclass(frozen=True)
class DeepthinkConfig:
    """A resolved dual-model deepthink escalation target.

    Optional: present on :attr:`EngineConfig.deepthink` only when the
    operator has declared a deepthink model (env var or a ``deepthink``
    section in .colleague/config.json) — see :func:`_resolve_deepthink`. The
    deepthink endpoint speaks the same OpenAI surface as the main endpoint
    through the same ``vllm-openai`` adapter, so retargeting stays a config
    change, never a code change (h2 precedent). Nothing here hard-codes a
    specific pair of models (h1) — any two OpenAI-compatible endpoints can
    play main and deepthink.
    """

    model: str
    base_url: str
    api_key: str
    context_budget: int
    multimodal: bool = False
    """Operator declaration that THIS (second) model accepts media content
    parts while the main model is text-only (task t8, decision c24) — arming
    the runtime's media-comprehension bridge. Never probed or inferred from a
    model name; default ``False`` keeps a dual-model config byte-identical."""


@dataclass(frozen=True)
class SensesConfig:
    """A resolved senses (multimodal front-door) escalation target.

    Cortex/senses arc (spec
    docs/specs/2026-07-03-colleague-drives-with-a-cortex-and-senses-it-resol.md,
    plan task t3). Optional: present on :attr:`EngineConfig.senses` only when
    the operator has declared a senses model (env var or a ``senses`` section
    in .colleague/config.json) — see :func:`_resolve_senses`. Mirrors
    :class:`DeepthinkConfig` field-for-field: the senses endpoint speaks the
    same OpenAI surface as the main endpoint through the same
    ``vllm-openai`` adapter, so retargeting stays a config change, never a
    code change (h2 precedent). This task (t3) resolves ONLY
    env > config.json > absent — the lobes discovery rung is a separate,
    later task (t4).
    """

    model: str
    base_url: str
    api_key: str
    context_budget: int
    multimodal: bool = False
    """Operator declaration that the senses model accepts media content
    parts — senses is the natural multimodal front door (intake / speak-back
    on the operator-facing surfaces). Never probed or inferred from a model
    name; default ``False`` keeps a senses config byte-identical."""


@dataclass(frozen=True)
class WorkerConfig:
    """A resolved worker (three-tier bounded-tool-loop actor) dial target.

    Three-tier-execution arc (plan task t3). Present on
    :attr:`EngineConfig.worker` ONLY when three-tier execution is EXPLICITLY
    armed (the ``three_tier`` config/env block — see
    :func:`_resolve_three_tier_enabled`) AND the lobes gateway advertises a
    ready ``worker`` role — resolution REQUIRES the role; unlike
    :class:`DeepthinkConfig`/:class:`SensesConfig` there is NO
    env/config.json-declared worker *model* (role NAMES only, never
    model-name parsing — the t3 design boundary, see :func:`_resolve_worker`).
    An armed-but-unresolvable worker raises a loud refusal instead of ever
    degrading to ``None`` and falling back to cortex silently acting as the
    worker (c25/h21) — the opposite stance every other lobes-fed rung takes.

    ``base_url``/``api_key`` mirror the dial-target shape of every sibling
    config (:func:`_role_dial_base_url` / the #347/#348 same-origin key
    hygiene rule). ``context`` is the role's OWN advertised window, read
    verbatim off the wire (never scaled/derived — unlike
    deepthink/senses' ``context_budget``, since this task performs
    RESOLUTION ONLY; nothing yet consumes this field to window a prompt).

    RESOLUTION ONLY in this task — nothing in the loop consumes this field
    yet; a later task (t8) wires the worker into the bounded tool loop as the
    acting seat.
    """

    model: str
    base_url: str
    api_key: str
    context: int


@dataclass(frozen=True)
class VoiceConfig:
    """A resolved voice (stt/tts) escalation target.

    Senses live-presence + voice arc. Optional: present on
    :attr:`EngineConfig.voice` only when at least one of ``stt_model`` or
    ``tts_model`` is resolved. Mirrors :class:`SensesConfig` field-for-field
    (base_url/api_key default to the main endpoint). Precedence:
    ``COLLEAGUE_STT_MODEL``/``COLLEAGUE_TTS_MODEL`` env > ``voice`` section of
    .colleague/config.json > lobes discovery > absent (None).

    ``stt_base_url``/``tts_base_url`` are SEPARATE fields (colleague#292, S1's
    follow-on / S2): pre-0.38 both stt and tts were forced to dial a single
    blanket gateway-origin value (there was no other reachable target), but
    since lobes-cli 0.38.0 each role can report its OWN genuinely dialable
    endpoint (lobes-cli#87) — a rig serving stt/tts from different origins
    needs two independently-resolved dial targets, not one shared field. The
    non-lobes env/config.json path (:func:`_resolve_voice`) still sets both to
    the SAME value (there is only one declared voice base_url there), so this
    split is byte-identical for every caller that isn't the lobes rung.
    """

    stt_model: str | None
    tts_model: str | None
    stt_base_url: str
    tts_base_url: str
    api_key: str


@dataclass(frozen=True)
class RealtimeConfig:
    """A resolved realtime (server-VAD live speech session) dial target.

    Realtime-speech arc (spec docs/specs/2026-07-22-realtime-speech.md, plan
    task t1). Optional: present on :attr:`EngineConfig.realtime` only when
    realtime is genuinely AVAILABLE — either an EXPLICIT operator knob
    (``COLLEAGUE_REALTIME_URL``/``COLLEAGUE_REALTIME_API_KEY`` env, or a
    ``realtime`` section in .colleague/config.json — see
    :func:`_resolve_realtime`) declares a dial target, or the lobes discovery
    rung (:func:`_realtime_lobes_fallback`) finds the gateway's ``stt`` role
    advertising the ``realtime_vad_session`` responsibility AND voice is
    already armed. Absence (``None``) means the session lane (a later task)
    must make ZERO WebSocket dial attempts — nothing is resolved to dial.

    ``available`` is always ``True`` when this object exists — there is no
    "declared but unavailable" state; unavailability is represented entirely
    by ``EngineConfig.realtime is None``. The field exists so a downstream
    consumer (a later task's session front) can render an honest state
    without re-deriving presence from "is not None" wherever it reads this
    config, and so the resolved shape is self-documenting in the artifact
    snapshot (:meth:`EngineConfig.to_dict`).

    ``ws_url`` is the ws(s) ``/v1/realtime`` dial target (see
    :func:`_realtime_ws_url`) — never an http(s) URL, so a caller never has to
    re-derive the scheme swap. ``api_key`` follows the #348 same-origin
    hygiene rule on the discovery rung; the explicit rung inherits the main
    key unconditionally (trusted operator intent) unless it declares its own.

    ``input_device``/``output_device`` (plan task t4) are PURE LOCAL knobs —
    a PortAudio device id (e.g. ``"2"``) or a name substring (e.g.
    ``"Reachy Mini"``) naming which mic/speaker on THIS machine the session
    lane's capture/playback functions (``colleague/realtime.py``) should open.
    Unlike every other field on this class, they resolve IDENTICALLY
    regardless of which rung produced this object — a discovered dial target
    says nothing about which physical device this box should use, so both
    :func:`_resolve_realtime` and :func:`_realtime_lobes_fallback` read the
    SAME env/config.json knobs via :func:`_resolve_realtime_devices`.
    ``None`` (the default) means "let the audio library pick its own
    default device" — never a forced index.
    """

    available: bool
    ws_url: str
    api_key: str
    input_device: str | None = None
    output_device: str | None = None


@dataclass(frozen=True)
class ResolveOverrides:
    """Bundle of secondary numeric-knob explicit overrides for :meth:`EngineConfig.resolve`.

    Every knob here still resolves through the SAME ``COLLEAGUE_*`` env var >
    ``.colleague/config.json`` > built-in-default precedence as before when
    left ``None`` — nothing about resolution itself changed. The only thing
    that moved is WHERE an explicit override is expressed: no production CLI
    flow ever sets more than the six identity/sizing knobs that stayed
    top-level params on ``resolve()`` (``base_url``, ``api_key``, ``model``,
    ``max_steps``, ``repo_path``, ``discover_lobes``); these eight are
    exercised ONLY by tests that pin one knob's own precedence in isolation
    (e.g. "an explicit ``context_budget_tokens`` beats the env var"). Bundling
    them here holds ``resolve()``'s parameter list under the SonarCloud S107
    ceiling (13) without dropping that per-knob override capability. Pure
    extraction — no behavior change.
    """

    context_budget_tokens: int | None = None
    max_output_chars: int | None = None
    subagent_concurrency: int | None = None
    autosplit_target_tokens: int | None = None
    fillline_threshold: float | None = None
    fanout_files: int | None = None
    plan_offer_tokens: int | None = None
    max_continue_nudges: int | None = None


@dataclass
class EngineConfig:
    """Settings for an OpenAI-compatible engine driver."""

    base_url: str = _DEFAULT_BASE_URL
    api_key: str = _DEFAULT_API_KEY
    model: str = _DEFAULT_MODEL
    max_steps: int = _DEFAULT_MAX_STEPS
    temperature: float = _DEFAULT_TEMPERATURE
    timeout: float = _DEFAULT_TIMEOUT
    # Runtime-only (#268 escalation bookkeeping, Qodo PR #271): the OPERATOR's
    # configured timeout, recorded the moment a work item's bounded x2
    # escalation raises `timeout` in place. Presence means `timeout` may carry
    # escalated state — `loop._make_timeout_escalator` restores `timeout` from
    # it at every work-item start, so an escalation can never leak into a
    # subagent child config (derived via dataclasses.replace, which copies both
    # fields) or a session-reused config and compound past 2x the operator's
    # value. Never resolved from env/file, never serialized (absent from
    # to_dict), None on every fresh resolve().
    base_timeout: float | None = None
    context_budget_tokens: int = _DEFAULT_CONTEXT_BUDGET
    max_output_chars: int = _DEFAULT_MAX_OUTPUT_CHARS
    subagent_concurrency: int = _DEFAULT_SUBAGENT_CONCURRENCY
    subagent_depth: int = _DEFAULT_SUBAGENT_DEPTH
    subagent_total: int = _DEFAULT_SUBAGENT_TOTAL
    autosplit_target_tokens: int = _DEFAULT_AUTOSPLIT_TARGET_TOKENS
    fillline_threshold: float = _DEFAULT_FILLLINE_THRESHOLD
    fanout_files: int = _DEFAULT_FANOUT_FILES
    # Review fan-out advisory (#220b): the distinct-folders-read count at which a
    # review run is nudged ONCE to fan out per-folder read-only `reviewer` subagents.
    # ``None`` = dormant (the default) — a strict no-op, so a normal run is
    # byte-identical. Enabled per-run via ``COLLEAGUE_REVIEW_FANOUT_FOLDERS`` (the
    # ask-colleague ``review`` wrapper sets it).
    review_fanout_folders: int | None = None
    plan_offer_tokens: int = _DEFAULT_PLAN_OFFER_TOKENS
    max_continue_nudges: int = _DEFAULT_MAX_CONTINUE_NUDGES
    synthesis_reserve_steps: int = _DEFAULT_SYNTHESIS_RESERVE
    lint: bool = _DEFAULT_LINT_ENABLED
    coherence: bool = _DEFAULT_COHERENCE_ENABLED
    memory: bool = _DEFAULT_MEMORY_ENABLED
    # Flight plane armed by default (#307): work/drive/session default watch ON.
    # The work path resolves the effective value against the --watch/--no-watch
    # flags post-resolve; session default-arms from this. env COLLEAGUE_WATCH >
    # config.json {watch} > default-on.
    watch: bool = _DEFAULT_WATCH_ENABLED
    lint_fix_retries: int = _DEFAULT_LINT_FIX_RETRIES
    testintegrity: bool = _DEFAULT_TESTINTEGRITY_ENABLED
    testintegrity_fix_retries: int = _DEFAULT_TESTINTEGRITY_FIX_RETRIES
    testintegrity_reviewer_model: str = _DEFAULT_TESTINTEGRITY_REVIEWER_MODEL
    affected_tests: bool = _DEFAULT_AFFECTED_TESTS_ENABLED
    affected_tests_fix_retries: int = _DEFAULT_AFFECTED_TESTS_FIX_RETRIES
    affected_tests_depth: int = _DEFAULT_AFFECTED_TESTS_DEPTH
    affected_tests_max_files: int = _DEFAULT_AFFECTED_TESTS_MAX_FILES
    affected_tests_override: Optional[str] = None
    # Episode chaining (indefinite-run, decision c21): ``until_done`` arms the
    # chain driver (colleague/chain.py); default OFF = today's single-episode
    # behavior byte-identical. ``max_episodes`` caps an armed chain: default 5,
    # 0 = unlimited. Deliberately NOT in :meth:`to_dict` (the ``watch``
    # precedent) so a dormant run's artifact config snapshot stays
    # byte-identical (h1).
    until_done: bool = _DEFAULT_UNTIL_DONE
    max_episodes: int = _DEFAULT_MAX_EPISODES
    # Per-run compaction-turn cap (indefinite-run follow-up, issue #334):
    # bounds how many fill-line ``compact`` moves a single run may spend
    # before further compaction offers are suppressed (the anti-thrash floor
    # documented on :data:`colleague.fillline.DEFAULT_COMPACTION_CAP`).
    # Default 4, 0 = unlimited (the ``max_episodes`` convention). Precedence:
    # COLLEAGUE_COMPACTION_CAP env > .colleague/config.json {"compaction_cap":
    # ...} > the fillline default. Unlike ``max_episodes``/``until_done`` this
    # DOES appear in :meth:`to_dict` — the artifact snapshot is meant to
    # surface the effective cap (h4/h7), not stay byte-identical.
    compaction_cap: int = DEFAULT_COMPACTION_CAP
    # Dual-model deepthink escalation target (t1). ``None`` = single-model,
    # byte-identical to today (the pre-feature default). See
    # :class:`DeepthinkConfig` and :func:`_resolve_deepthink`.
    deepthink: Optional[DeepthinkConfig] = None
    # Senses (multimodal front-door) escalation target (cortex/senses arc,
    # task t3). ``None`` = no senses declared, byte-identical to today. See
    # :class:`SensesConfig` and :func:`_resolve_senses`.
    senses: Optional[SensesConfig] = None
    # Voice (stt/tts) escalation target (senses live-presence + voice arc).
    # ``None`` = no voice declared, byte-identical to today. See
    # :class:`VoiceConfig` and :func:`_resolve_voice`.
    voice: Optional[VoiceConfig] = None
    # Realtime (server-VAD live speech session) dial target (realtime-speech
    # arc, plan task t1). ``None`` = no realtime declared/discovered,
    # byte-identical to today. See :class:`RealtimeConfig`,
    # :func:`_resolve_realtime`, and :func:`_realtime_lobes_fallback`.
    realtime: Optional[RealtimeConfig] = None
    # Three-tier execution arming (three-tier-execution arc, plan task t3).
    # ``False`` (the default) = today's byte-identical behavior — a worker
    # advert is read and discarded exactly like reranker, never resolved.
    # See :func:`_resolve_three_tier_enabled`.
    three_tier: bool = False
    # Worker (three-tier bounded-tool-loop actor) dial target. ``None`` =
    # three-tier not armed, byte-identical to today. RESOLUTION ONLY when
    # present: an armed run with an unresolvable worker raises a loud
    # refusal instead of ever leaving this ``None`` with three_tier True (no
    # silent cortex-as-actor). See :class:`WorkerConfig` and
    # :func:`_resolve_worker`.
    worker: Optional[WorkerConfig] = None
    # The episode config-lifecycle attachment (change-content consumption
    # lane, plan task t3). ``None`` (the default) = no config plane armed,
    # byte-identical to today — the pre-existing state, since nothing has
    # ever set this field before this task. A runtime-only object set
    # imperatively by the work front once three-tier is armed (a later
    # task), never resolved from env/file — excluded from eq/repr/to_dict
    # like ``role``/``memory_root`` above. Typed here only to make a seam
    # ``colleague/loop.py`` already reads via
    # ``getattr(config, "config_lifecycle", None)`` (line 2934,
    # forward-compatible before this field existed) explicit; both engines'
    # ``work()`` read it the same way at episode-schema-resolution time.
    config_lifecycle: "Optional[EpisodeConfigLifecycle]" = field(
        default=None, compare=False, repr=False
    )

    # A runtime-only per-step progress sink ``(step_index, tool, target, ok)``
    # the loop fires per tool call (#38). Set by the CLI work path, not by
    # ``resolve()``; excluded from eq/repr and from ``to_dict`` (it is behavior,
    # not serializable config).
    progress: Optional[Callable[[int, str, str, bool], None]] = field(
        default=None, compare=False, repr=False
    )

    # Token-delta seam (feels-alive arc, task t3): an OPTIONAL per-completion
    # sink an engine MAY call with each ordered text delta of the model's
    # in-progress completion, before it returns the full ``ModelResponse``.
    # Mirrors ``progress`` immediately above: a runtime-only field set
    # imperatively by the caller (CLI/session/cockpit), never resolved from
    # env/file/``resolve()`` — excluded from eq/repr/``to_dict`` (behavior,
    # not serializable config). ``None`` (the default, and the ONLY state
    # reachable through ``resolve()``) is a strict no-op: an engine that never
    # checks ``on_delta``, or checks it and finds it ``None``, streams
    # nothing — an unarmed run is byte-identical to the pre-seam loop.
    #
    # Deliberately NOT threaded through ``ContextControls``/``colleague.loop``:
    # the loop only ever sees a completed ``ModelResponse`` (what ``complete``
    # returns), never the raw stream a live backend receives it from — so
    # there is nothing for the loop to forward. Each backend's OWN
    # completion-building code already receives this ``config`` object
    # directly (e.g. ``MockEngine.work(self, task, config)``, or the vLLM
    # adapter's ``_make_complete(self, config, tools)``), so it reads
    # ``config.on_delta`` itself and invokes it as the answer streams in,
    # still returning the same ``ModelResponse`` at the end exactly as today.
    #
    # Intended producer (task t4): the vLLM engine's SSE stream calls this
    # once per received content chunk as it arrives from the server.
    # Intended producer (this task, t3): the mock engine emits synthetic
    # word-chunk deltas of each scripted turn's ``content`` when armed (see
    # ``colleague/engines/mock.py``), so the seam is exercisable end to end
    # with no network.
    # Intended consumer (task t6): the session's live cockpit sinks arm this
    # to render tokens as they stream instead of only after a turn completes.
    on_delta: Optional[Callable[[str], None]] = field(default=None, compare=False, repr=False)

    # Runtime-only spawn callback for subagent delegation; set by the work item
    # path, not by ``resolve()``; excluded from eq/repr/to_dict (it is behavior,
    # not serializable config).
    subagent_spawn: Optional[Callable] = field(default=None, compare=False, repr=False)

    # Runtime-only batch-spawn callback for parallel subagent delegation; set by
    # the work path, not by ``resolve()``; excluded from eq/repr/to_dict (it is
    # behavior, not serializable config).
    subagent_batch_spawn: Optional[Callable] = field(default=None, compare=False, repr=False)

    # Typed-subagent role NAME this work item runs as (#t4). ``None`` = today's
    # full-surface behavior (byte-identical to pre-role). Set on a *child's* config
    # by the subagent launcher; the engine builds the child's curated tool schema +
    # role-composed prompt from it (t8). A runtime field, not env-resolved, so it is
    # excluded from eq/repr/to_dict like the spawn callbacks above.
    role: Optional[str] = field(default=None, compare=False, repr=False)

    # Memory root (spec R1 / plan t2): the OPERATOR repo the memory store lives
    # in. An isolated run works in a throwaway worktree, so a lesson written to
    # task.repo_path would die with it — execute_work sets this to the real repo
    # root so recall/remember target the durable store. A runtime field set by
    # the CLI layer (the ``role`` precedent); excluded from eq/repr/to_dict.
    memory_root: Optional[str] = field(default=None, compare=False, repr=False)

    # Mode-profile explicit-knob mask (t3 / spec R1): the EngineConfig field names
    # the caller set from explicit CLI flags (e.g. ``{"max_steps"}`` when
    # ``--max-steps`` was given), so ``apply_mode_profile`` never overwrites them.
    # A runtime field set by the CLI layer — the ``role`` precedent (keeps
    # ``execute_work`` under the S107 parameter ceiling); excluded from
    # eq/repr/to_dict.
    explicit_knobs: Collection[str] = field(default=(), compare=False, repr=False)

    # Embedder env overrides (one-embedder increment, S2, colleague#291/#292
    # task t19): built by :func:`_resolve_lobes_rung` from the gateway's
    # OPTIONAL ``embedder`` role via :func:`colleague.lobes.embed_env` — ``{}``
    # (the default) when lobes is unarmed/unreachable or the gateway doesn't
    # advertise an embedder (never fails resolution, mirroring stt/tts).
    # Threaded to the eidetic-CLI subprocess env in ``colleague/memory.py``
    # (never overwriting an operator-set env var — operator wins). A
    # runtime-derived plumbing value, not a declared override — excluded from
    # eq/repr/to_dict like ``memory_root``/``role`` above.
    embed_env: dict[str, str] = field(default_factory=dict, compare=False, repr=False)

    # The ARMED lobes gateway origin this config resolved against (self-knowledge
    # arc, t9): set by :meth:`resolve` from :func:`_resolve_lobes_rung`'s
    # ``lobes_gateway_url`` — ``None`` when the rung is unarmed OR degraded
    # (unreachable), so it reflects the state the run ACTUALLY resolved with,
    # never a dead URL presented as live. Read by the loop's self-knowledge
    # advisory (via ``ContextControls.from_config``) to render the honest
    # ``lobes:`` self-fact. A runtime-derived plumbing value like ``embed_env``
    # above — excluded from eq/repr/to_dict.
    lobes_gateway_url: Optional[str] = field(default=None, compare=False, repr=False)

    # Same-role stale-pin refresh records (plan task t9, spec c11/h8): every
    # :class:`~colleague.lobes.ModelRefreshWarning` this config's resolution
    # emitted (``()`` — the default — when the pin was valid, or lobes was
    # unarmed/unreachable/couldn't run the membership check, byte-identical
    # to today), PLUS any the vLLM engine's call-time 404 catch appends
    # in-place during ``work()`` (``colleague/engines/vllm_openai.py``
    # reassigns this to a NEW tuple — ``self.model_refresh_warnings +
    # (warning,)`` — rather than mutating a shared list, so a subagent child
    # sharing this field's value via ``dataclasses.replace`` never sees a
    # parent's later call-time append, and vice versa). A runtime-derived
    # plumbing value like ``lobes_gateway_url``/``embed_env`` above —
    # excluded from eq/repr/to_dict; a downstream task (t11) is the one that
    # folds this onto ``TaskResult``/the run artifact.
    model_refresh_warnings: "tuple[ModelRefreshWarning, ...]" = field(
        default=(), compare=False, repr=False
    )

    # Which seat the call-time stale-pin refresh may act for (d5, issue 375):
    # ``"main"`` — the default — arms the vLLM engine's 404 catch for the
    # acting MAIN seat only (the c8/c11 scoping). The replaced-config twins
    # (``deepthink_engine_config`` / ``senses_engine_config``) set ``None``
    # so a deepthink/senses 404 surfaces unchanged into that lane's own
    # degrade path instead of being silently retried on the main seat's
    # model (the muse->cortex cross-role event this field exists to stop).
    # Runtime-only plumbing like the fields above — excluded from
    # eq/repr/to_dict.
    refresh_seat: Optional[str] = field(default="main", compare=False, repr=False)

    # Chain-episode dispatch marker (indefinite-run follow-up, issue #335 /
    # decision c22): ``True`` exactly when THIS dispatch is one episode of an
    # armed ``--until-done`` chain (``execute_work`` sets it per-call from the
    # PRESENCE of its ``chain: ChainEpisodeOptions | None`` parameter — never
    # from ``config.until_done``, so a plain run with ``until_done=True`` but
    # no chain dispatch leaves it ``False``). ``chain_prior_changed`` carries
    # the UNION of every prior episode's ``result.changed_files`` (sorted,
    # deduped), ``()`` on the chain's first episode / any non-chained run. A
    # runtime field set imperatively by the CLI layer — the ``role``/
    # ``memory_root`` precedent — excluded from eq/repr/to_dict. c22 requires
    # a subagent child NOT inherit the marker even though ``dataclasses.
    # replace`` would otherwise copy it from the parent config object
    # ``execute_work`` mutated in place: :func:`colleague.subagents.
    # run_subagent` resets both fields to their dormant defaults in its
    # ``replace_kwargs`` (see that module), so every subagent child is
    # byte-identical to an unchained dispatch regardless of its parent.
    chain_episode: bool = field(default=False, compare=False, repr=False)
    chain_prior_changed: tuple[str, ...] = field(default=(), compare=False, repr=False)

    @classmethod
    def resolve(
        cls,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        max_steps: int | None = None,
        repo_path: str | Path | None = None,
        discover_lobes: bool = True,
        overrides: "ResolveOverrides | None" = None,
    ) -> "EngineConfig":
        """Build a config from explicit args, env vars, config file, then defaults.

        When *repo_path* is provided, values from ``.colleague/config.json``
        are loaded and used as the ``default=`` for the ``base_url``, ``api_key``
        and ``model`` fields. The resulting precedence is:

        explicit argument > COLLEAGUE_/OPENAI_ env var > .colleague/config.json > built-in default.

        When *repo_path* is ``None`` or no config file exists, behaviour is
        byte-identical to the prior (no config-file) implementation.

        ``temperature``, ``timeout``, ``subagent_depth`` and ``subagent_total``
        have no explicit-override keyword (and no CLI flag): no production caller
        passes them, so their precedence is simply ``COLLEAGUE_*`` env var >
        built-in default. Keeping them off the signature holds ``resolve`` under
        the parameter ceiling (SonarCloud S107); the dataclass still carries the
        fields, and the ``COLLEAGUE_TEMPERATURE`` / ``COLLEAGUE_TIMEOUT`` /
        ``COLLEAGUE_SUBAGENT_DEPTH`` / ``COLLEAGUE_SUBAGENT_TOTAL`` env vars (with
        ``CONVERTIBLE_*`` fallbacks) override them as before.

        *overrides* bundles eight secondary numeric-knob explicit-override slots
        (``context_budget_tokens``, ``max_output_chars``, ``subagent_concurrency``,
        ``autosplit_target_tokens``, ``fillline_threshold``, ``fanout_files``,
        ``plan_offer_tokens``, ``max_continue_nudges`` — see
        :class:`ResolveOverrides`) that used to be individual keyword params here;
        each still resolves ``COLLEAGUE_*`` env > ``.colleague/config.json`` >
        built-in default exactly as before when omitted from *overrides* (or when
        *overrides* itself is ``None``) — this bundling changed nothing about
        resolution, only how an explicit override is expressed.
        """
        ov = overrides if overrides is not None else ResolveOverrides()
        # Load config-file values once (empty dict when repo_path is None or
        # the file is absent/malformed).
        file_cfg: dict[str, str] = {}
        file_lint: str | None = None
        file_watch: str | None = None
        file_coherence: str | None = None
        file_memory: str | None = None
        file_lint_retries: str | None = None
        file_ti: str | None = None
        file_ti_retries: str | None = None
        file_at: str | None = None
        file_at_retries: str | None = None
        file_at_depth: str | None = None
        file_at_max_files: str | None = None
        file_until_done: str | None = None
        file_max_episodes: str | None = None
        file_compaction_cap: str | None = None
        file_deepthink: dict[str, str] = {}
        file_senses: dict[str, str] = {}
        file_voice: dict[str, str] = {}
        file_realtime: dict[str, str] = {}
        file_three_tier: str | None = None
        file_worker: dict[str, str] = {}
        if repo_path is not None:
            file_cfg = load_config_file(repo_path)
            file_lint, file_lint_retries = _load_lint_overrides(repo_path)
            file_watch = _load_watch_override(repo_path)
            file_coherence = _load_coherence_override(repo_path)
            file_memory = _load_memory_override(repo_path)
            file_ti, file_ti_retries = _load_testintegrity_overrides(repo_path)
            file_at, file_at_retries, file_at_depth, file_at_max_files = (
                _load_affected_tests_overrides(repo_path)
            )
            file_until_done, file_max_episodes, file_compaction_cap = _load_chain_overrides(
                repo_path
            )
            file_deepthink = _load_deepthink_overrides(repo_path)
            file_senses = _load_senses_overrides(repo_path)
            file_voice = _load_voice_overrides(repo_path)
            file_realtime = _load_realtime_overrides(repo_path)
            file_three_tier = _load_three_tier_override(repo_path)
            file_worker = _load_worker_overrides(repo_path)

        file_base_url: str | None = file_cfg.get("base_url")
        file_api_key: str | None = file_cfg.get("api_key")
        file_model: str | None = file_cfg.get("model")

        # Lobes discovery rung (task t4): see :func:`_resolve_lobes_rung` for the
        # full rationale (extracted to hold this method's cognitive complexity
        # under the SonarCloud S3776 ceiling — pure extraction, no behavior
        # change). It slots BELOW config.json and ABOVE the builtin default.
        # ``lobes_gateway_url`` (S1/S2 follow-on) lets the senses/voice rungs
        # below resolve EACH role's own dial target independently of cortex's.
        lobes_base_url, lobes_model, lobes_roles, lobes_gateway_url, lobes_embed_env = (
            _resolve_lobes_rung(repo_path, discover_lobes)
        )

        # Resolved once as locals (not just inline in the ``cls(...)`` call
        # below) so the deepthink resolution can default ITS base_url/api_key
        # to the MAIN endpoint's already-resolved values (spec requirement).
        # The default is a plain if/else (not a nested ternary, SonarCloud
        # S3358) over the two DEFAULTS-SOURCE rungs below the explicit
        # arg/env precedence: config.json, then the lobes discovery rung.
        if file_base_url is not None:
            base_url_default = file_base_url
        elif lobes_base_url is not None:
            base_url_default = lobes_base_url
        else:
            base_url_default = _DEFAULT_BASE_URL
        resolved_base_url = _pick(
            base_url,
            "COLLEAGUE_BASE_URL",
            "CONVERTIBLE_BASE_URL",
            "OPENAI_BASE_URL",
            default=base_url_default,
        )
        resolved_api_key = _pick(
            api_key,
            "COLLEAGUE_API_KEY",
            "CONVERTIBLE_API_KEY",
            "OPENAI_API_KEY",
            default=_file_or_default(file_api_key, _DEFAULT_API_KEY),
        )

        # Dual-model deepthink (t1) — resolved once as a local (like
        # resolved_base_url/resolved_api_key above) so the test-integrity
        # reviewer default backfill (t7) below can inspect the resolved
        # DeepthinkConfig before EngineConfig itself is constructed.
        resolved_deepthink = _resolve_deepthink(file_deepthink, resolved_base_url, resolved_api_key)
        # Deepthink discovery rung (two-machines-two-minds t5): when deepthink
        # is NOT declared via env/config.json but the lobes rung resolved a
        # muse role, the gateway supplies the DeepthinkConfig — muse's OWN
        # resolved dial target, budget from the role's window, and the main
        # api_key ONLY toward the main endpoint's own origin (see
        # :func:`_deepthink_lobes_fallback` for the key-hygiene rule).
        # Precedence: env > config.json > lobes discovery (muse) > absent —
        # the exact senses-rung stance below. Sits ABOVE the reviewer-default
        # backfill (t7) so a discovered deepthink feeds it identically to a
        # declared one.
        if resolved_deepthink is None:
            resolved_deepthink = _deepthink_lobes_fallback(
                lobes_roles, lobes_gateway_url, resolved_base_url, resolved_api_key, file_deepthink
            )
        # Senses (multimodal front-door) escalation target — resolved once as a
        # local like resolved_deepthink above. Precedence: env > config.json >
        # lobes discovery (t4) > absent. When senses is NOT declared via
        # env/config.json but the lobes rung resolved, the gateway's senses role
        # supplies the SensesConfig — its OWN resolved dial target (colleague#292,
        # S1's follow-on: senses no longer reuses cortex's ``lobes_base_url``;
        # closes lobes-cli#87 end-to-end), budget from the role's window, and
        # the main api_key ONLY toward the main endpoint's own origin (see
        # :func:`_senses_lobes_fallback` for the key-hygiene rule, colleague#348
        # — the exact stance :func:`_deepthink_lobes_fallback` takes).
        resolved_senses = _resolve_senses(file_senses, resolved_base_url, resolved_api_key)
        if resolved_senses is None:
            resolved_senses = _senses_lobes_fallback(
                lobes_roles, lobes_gateway_url, resolved_base_url, resolved_api_key, file_senses
            )
        # Voice (stt/tts) escalation target (senses live-presence + voice arc) —
        # resolved once as a local, mirroring senses. Precedence: env >
        # config.json > lobes discovery > absent. When voice is NOT declared via
        # env/config.json but the lobes rung resolved, the gateway's stt/tts roles
        # supply the VoiceConfig — EACH role's own resolved dial target
        # (colleague#292, S1's follow-on: closes lobes-cli#87 end-to-end), and
        # the main api_key ONLY toward roles whose dial target shares the main
        # endpoint's own origin (see :func:`_voice_lobes_fallback` for the
        # key-hygiene rule, colleague#348 t2 — the same conservative stance
        # :func:`_senses_lobes_fallback`/:func:`_deepthink_lobes_fallback`
        # take, extended to voice's two-role, single-key shape).
        resolved_voice = _resolve_voice(file_voice, resolved_base_url, resolved_api_key)
        if resolved_voice is None:
            resolved_voice = _voice_lobes_fallback(
                lobes_roles, lobes_gateway_url, resolved_base_url, resolved_api_key, file_voice
            )
        # Realtime (server-VAD live speech session) dial target
        # (realtime-speech arc, plan task t1) — resolved once as a local,
        # mirroring senses/voice. Precedence: env > config.json > lobes
        # discovery (the stt role's realtime_vad_session responsibility,
        # gated on voice already being armed) > absent. Resolved AFTER voice
        # since the discovery fallback consults the just-resolved
        # ``resolved_voice`` (see :func:`_realtime_lobes_fallback`).
        resolved_realtime = _resolve_realtime(file_realtime, resolved_api_key)
        if resolved_realtime is None:
            resolved_realtime = _realtime_lobes_fallback(
                lobes_roles,
                lobes_gateway_url,
                resolved_base_url,
                resolved_api_key,
                file_realtime,
                resolved_voice,
            )
        # Three-tier execution arming + worker seat resolution
        # (three-tier-execution arc, plan task t3; covers c3/h3/c25/h21).
        # ``resolved_three_tier`` gates whether the worker role is even
        # consulted — NOT armed is a strict no-op (an advertised worker role
        # is read and discarded exactly like reranker, byte-identical to
        # today). ARMED makes the worker role MANDATORY: :func:`_resolve_worker`
        # raises a loud, naming refusal (never falls back to cortex silently
        # acting) rather than ever returning with three_tier True and worker
        # None — the refusal fires HERE, at resolution time, before any
        # episode starts.
        resolved_three_tier = _resolve_three_tier_enabled(file_three_tier)
        resolved_worker = _resolve_worker(
            resolved_three_tier,
            lobes_roles,
            lobes_gateway_url,
            resolve_lobes_gateway_url(repo_path),
            resolved_base_url,
            resolved_api_key,
            file_worker,
        )
        # Deepthink absent in three-tier mode (plan task t8; covers c12/h12).
        # Once three_tier is armed, no DeepthinkConfig is EVER constructed —
        # neither a DECLARED (env/config.json) deepthink nor one discovered
        # from the lobes muse role above (``resolved_deepthink`` may already
        # hold either) survives. Three-tier's own strong-reasoning seat is
        # the worker itself (arc summary: "strategist absent, deepthink
        # absent") — forcing this HERE, before the reviewer-default backfill
        # just below reads ``resolved_deepthink``, means that backfill (t7)
        # also sees no deepthink to borrow a reviewer model from, staying
        # consistent with deepthink's total absence. Legacy (three_tier
        # False) is completely untouched: resolved_deepthink keeps whatever
        # _resolve_deepthink/_deepthink_lobes_fallback already computed above.
        if resolved_three_tier:
            resolved_deepthink = None
        # Test-integrity reviewer model (#203) — env > CONVERTIBLE fallback >
        # default (empty), then backfilled from the deepthink model when
        # unconfigured and same-endpoint (t7, spec c10(d)).
        resolved_testintegrity_reviewer_model = _resolve_testintegrity_reviewer_model(
            _pick(
                None,
                "COLLEAGUE_TESTINTEGRITY_REVIEWER_MODEL",
                "CONVERTIBLE_TESTINTEGRITY_REVIEWER_MODEL",
                default=_DEFAULT_TESTINTEGRITY_REVIEWER_MODEL,
            ),
            resolved_deepthink,
            resolved_base_url,
        )

        # Lobes rung (t4): the gateway's cortex model is the default only for the
        # main model id, below config.json and above the builtin. A plain if/else
        # (not a nested ternary, SonarCloud S3358), mirroring base_url_default above.
        if file_model is not None:
            model_default = file_model
        elif lobes_model is not None:
            model_default = lobes_model
        else:
            model_default = _DEFAULT_MODEL

        resolved_model = _pick(
            model,
            "COLLEAGUE_MODEL",
            "CONVERTIBLE_MODEL",
            default=model_default,
        )
        # Same-role stale-pin refresh AT RESOLUTION TIME (plan task t9, spec
        # c10/c11, honesty h7/h8) — see :func:`_refresh_stale_model_pin` for
        # the full gate. Skipped entirely when three-tier is armed
        # (``resolved_worker is not None``): the worker, not cortex, is the
        # ACTING seat there (the override just below), so a cortex pin
        # refresh would be inert work against a role that never drives —
        # never a network call this rung has no use for.
        model_refresh_warning: ModelRefreshWarning | None = None
        if resolved_worker is None:
            resolved_model, model_refresh_warning = _refresh_stale_model_pin(
                resolved_model,
                model,
                file_model,
                lobes_gateway_url,
                lobes_roles,
                api_key=resolved_api_key,
            )
        resolved_context_budget_tokens = int(
            _pick(
                _str(ov.context_budget_tokens),
                "COLLEAGUE_CONTEXT_BUDGET",
                "CONVERTIBLE_CONTEXT_BUDGET",
                default=str(_DEFAULT_CONTEXT_BUDGET),
            )
        )
        # Worker-as-actor wiring (three-tier-execution arc, plan task t8;
        # covers c12/h12). Once three_tier is ARMED and the worker seat
        # resolved above, the ACTING dial — model/base_url/api_key/
        # context_budget_tokens, exactly what the vllm-openai engine drives
        # the bounded tool loop with — becomes the WORKER's own resolution,
        # never cortex's ("the worker drives the tool loop and cortex does
        # not act"). cortex's own resolved base_url/api_key/model (the
        # ``resolved_*`` locals above) still feed the senses/voice/deepthink
        # default-to-main rungs UNCHANGED — this override happens only here,
        # at the very end of resolution, so it can never leak backwards into
        # another rung's "defaults to the main endpoint" precedent.
        # ``resolved_worker`` is guaranteed non-None whenever
        # ``resolved_three_tier`` is True (a broken worker already raised a
        # loud refusal above, via :func:`_resolve_worker`), so this is a
        # plain presence check, never a second refusal path. The loop itself
        # (colleague/loop.py) is UNTOUCHED by this task — it simply drives
        # whatever ``EngineConfig`` hands back, exactly as it always has.
        acting_model = resolved_model
        acting_base_url = resolved_base_url
        acting_api_key = resolved_api_key
        acting_context_budget_tokens = resolved_context_budget_tokens
        if resolved_worker is not None:
            acting_model = resolved_worker.model
            acting_base_url = resolved_worker.base_url
            acting_api_key = resolved_worker.api_key
            acting_context_budget_tokens = resolved_worker.context

        return cls(
            base_url=acting_base_url,
            api_key=acting_api_key,
            model=acting_model,
            max_steps=int(
                _pick(
                    _str(max_steps),
                    "COLLEAGUE_MAX_STEPS",
                    "CONVERTIBLE_MAX_STEPS",
                    default=str(_DEFAULT_MAX_STEPS),
                )
            ),
            temperature=float(
                _pick(
                    None,
                    "COLLEAGUE_TEMPERATURE",
                    "CONVERTIBLE_TEMPERATURE",
                    default=str(_DEFAULT_TEMPERATURE),
                )
            ),
            timeout=float(
                _pick(
                    None,
                    "COLLEAGUE_TIMEOUT",
                    "CONVERTIBLE_TIMEOUT",
                    default=str(_DEFAULT_TIMEOUT),
                )
            ),
            context_budget_tokens=acting_context_budget_tokens,
            max_output_chars=int(
                _pick(
                    _str(ov.max_output_chars),
                    "COLLEAGUE_MAX_OUTPUT_CHARS",
                    "CONVERTIBLE_MAX_OUTPUT_CHARS",
                    default=str(_DEFAULT_MAX_OUTPUT_CHARS),
                )
            ),
            subagent_concurrency=_try_int(
                _pick(
                    _str(ov.subagent_concurrency),
                    "COLLEAGUE_SUBAGENT_CONCURRENCY",
                    "CONVERTIBLE_SUBAGENT_CONCURRENCY",
                    default=str(_DEFAULT_SUBAGENT_CONCURRENCY),
                ),
                default=_DEFAULT_SUBAGENT_CONCURRENCY,
            ),
            subagent_depth=_try_int(
                _pick(
                    None,
                    "COLLEAGUE_SUBAGENT_DEPTH",
                    "CONVERTIBLE_SUBAGENT_DEPTH",
                    default=str(_DEFAULT_SUBAGENT_DEPTH),
                ),
                default=_DEFAULT_SUBAGENT_DEPTH,
            ),
            subagent_total=_try_int(
                _pick(
                    None,
                    "COLLEAGUE_SUBAGENT_TOTAL",
                    "CONVERTIBLE_SUBAGENT_TOTAL",
                    default=str(_DEFAULT_SUBAGENT_TOTAL),
                ),
                default=_DEFAULT_SUBAGENT_TOTAL,
            ),
            autosplit_target_tokens=int(
                _pick(
                    _str(ov.autosplit_target_tokens),
                    "COLLEAGUE_AUTOSPLIT_TARGET",
                    "CONVERTIBLE_AUTOSPLIT_TARGET",
                    default=str(_DEFAULT_AUTOSPLIT_TARGET_TOKENS),
                )
            ),
            fillline_threshold=_try_float(
                _pick(
                    _str(ov.fillline_threshold),
                    "COLLEAGUE_FILLLINE_THRESHOLD",
                    "CONVERTIBLE_FILLLINE_THRESHOLD",
                    default=str(_DEFAULT_FILLLINE_THRESHOLD),
                ),
                default=_DEFAULT_FILLLINE_THRESHOLD,
            ),
            fanout_files=_try_int(
                _pick(
                    _str(ov.fanout_files),
                    "COLLEAGUE_FANOUT_FILES",
                    "CONVERTIBLE_FANOUT_FILES",
                    default=str(_DEFAULT_FANOUT_FILES),
                ),
                default=_DEFAULT_FANOUT_FILES,
            ),
            review_fanout_folders=_try_int_or_none(
                _pick(
                    None,
                    "COLLEAGUE_REVIEW_FANOUT_FOLDERS",
                    "CONVERTIBLE_REVIEW_FANOUT_FOLDERS",
                    default="",
                )
            ),
            plan_offer_tokens=_try_int(
                _pick(
                    _str(ov.plan_offer_tokens),
                    "COLLEAGUE_PLAN_OFFER_TOKENS",
                    "CONVERTIBLE_PLAN_OFFER_TOKENS",
                    default=str(_DEFAULT_PLAN_OFFER_TOKENS),
                ),
                default=_DEFAULT_PLAN_OFFER_TOKENS,
            ),
            max_continue_nudges=_try_int(
                _pick(
                    _str(ov.max_continue_nudges),
                    "COLLEAGUE_MAX_CONTINUE_NUDGES",
                    "CONVERTIBLE_MAX_CONTINUE_NUDGES",
                    default=str(_DEFAULT_MAX_CONTINUE_NUDGES),
                ),
                default=_DEFAULT_MAX_CONTINUE_NUDGES,
            ),
            # Env-only (no CLI flag / explicit override) — keeping it off the
            # parameter list holds resolve() at 13 params (Sonar S107, PR #207).
            synthesis_reserve_steps=_try_int(
                _pick(
                    None,
                    "COLLEAGUE_SYNTHESIS_RESERVE_STEPS",
                    "CONVERTIBLE_SYNTHESIS_RESERVE_STEPS",
                    default=str(_DEFAULT_SYNTHESIS_RESERVE),
                ),
                default=_DEFAULT_SYNTHESIS_RESERVE,
            ),
            # Lint gate (#200) — env > config.json > default-on. Kept off the
            # signature (the --no-lint flag overrides post-resolve) to hold the
            # S107 parameter ceiling, mirroring synthesis_reserve_steps above.
            lint=_resolve_lint_enabled(file_lint),
            watch=_resolve_watch_enabled(file_watch),
            coherence=_resolve_coherence_enabled(file_coherence),
            memory=_resolve_memory_enabled(file_memory),
            lint_fix_retries=_try_int(
                _pick(
                    None,
                    "COLLEAGUE_LINT_FIX_RETRIES",
                    "CONVERTIBLE_LINT_FIX_RETRIES",
                    default=_file_or_default(file_lint_retries, str(_DEFAULT_LINT_FIX_RETRIES)),
                ),
                default=_DEFAULT_LINT_FIX_RETRIES,
            ),
            # Test-integrity gate (#203) — env > config.json > default-on, mirroring
            # lint. Kept off the signature (no CLI flag in v0) for the S107 ceiling.
            testintegrity=_resolve_testintegrity_enabled(file_ti),
            testintegrity_fix_retries=_try_int(
                _pick(
                    None,
                    "COLLEAGUE_TESTINTEGRITY_FIX_RETRIES",
                    "CONVERTIBLE_TESTINTEGRITY_FIX_RETRIES",
                    default=_file_or_default(
                        file_ti_retries, str(_DEFAULT_TESTINTEGRITY_FIX_RETRIES)
                    ),
                ),
                default=_DEFAULT_TESTINTEGRITY_FIX_RETRIES,
            ),
            testintegrity_reviewer_model=resolved_testintegrity_reviewer_model,
            # Affected-tests gate (#213) — env > config.json > default-on, mirroring
            # lint. Kept off the signature (no CLI flag in v0) for the S107 ceiling.
            affected_tests=_resolve_affected_tests_enabled(file_at),
            affected_tests_fix_retries=_try_int(
                _pick(
                    None,
                    "COLLEAGUE_AFFECTED_TESTS_FIX_RETRIES",
                    default=_file_or_default(
                        file_at_retries, str(_DEFAULT_AFFECTED_TESTS_FIX_RETRIES)
                    ),
                ),
                default=_DEFAULT_AFFECTED_TESTS_FIX_RETRIES,
            ),
            affected_tests_depth=_try_int(
                _pick(
                    None,
                    "COLLEAGUE_AFFECTED_TESTS_DEPTH",
                    default=_file_or_default(file_at_depth, str(_DEFAULT_AFFECTED_TESTS_DEPTH)),
                ),
                default=_DEFAULT_AFFECTED_TESTS_DEPTH,
            ),
            affected_tests_max_files=_try_int(
                _pick(
                    None,
                    "COLLEAGUE_AFFECTED_TESTS_MAX_FILES",
                    default=_file_or_default(
                        file_at_max_files, str(_DEFAULT_AFFECTED_TESTS_MAX_FILES)
                    ),
                ),
                default=_DEFAULT_AFFECTED_TESTS_MAX_FILES,
            ),
            # affected_tests_override has no env var (set later from a CLI flag).
            affected_tests_override=None,
            # Episode chaining (indefinite-run, decision c21) — env > config.json
            # > default (dormant OFF / cap 5, 0 = unlimited). The --until-done /
            # --max-episodes CLI flags are applied post-resolve by the work path
            # (t5), keeping both off the signature (the S107 ceiling, the lint
            # precedent).
            until_done=_resolve_until_done_enabled(file_until_done),
            max_episodes=_try_int(
                _pick(
                    None,
                    "COLLEAGUE_MAX_EPISODES",
                    "CONVERTIBLE_MAX_EPISODES",
                    default=_file_or_default(file_max_episodes, str(_DEFAULT_MAX_EPISODES)),
                ),
                default=_DEFAULT_MAX_EPISODES,
            ),
            # Per-run compaction-turn cap (issue #334) — env > config.json >
            # the fillline default (4), 0 = unlimited (the max_episodes
            # convention above). Malformed input falls back to the default.
            compaction_cap=_try_int(
                _pick(
                    None,
                    "COLLEAGUE_COMPACTION_CAP",
                    "CONVERTIBLE_COMPACTION_CAP",
                    default=_file_or_default(file_compaction_cap, str(DEFAULT_COMPACTION_CAP)),
                ),
                default=DEFAULT_COMPACTION_CAP,
            ),
            # Dual-model deepthink (t1) — env > config.json `deepthink` section >
            # absent (None). base_url/api_key default to the resolved MAIN
            # endpoint values computed above.
            deepthink=resolved_deepthink,
            # Senses (multimodal front-door, cortex/senses arc task t3) —
            # env > config.json `senses` section > absent (None). Scope: no
            # lobes discovery rung yet (t4); base_url/api_key default to the
            # resolved MAIN endpoint values computed above.
            senses=resolved_senses,
            voice=resolved_voice,
            # Realtime dial target (realtime-speech arc, task t1) — env >
            # config.json `realtime` section > lobes discovery (stt's
            # realtime_vad_session responsibility) > absent (None).
            realtime=resolved_realtime,
            # Three-tier execution arming (three-tier-execution arc, plan task
            # t3) — env `COLLEAGUE_THREE_TIER` > config.json `three_tier` >
            # default-OFF.
            three_tier=resolved_three_tier,
            # Worker (three-tier bounded-tool-loop actor) dial target — None
            # when three_tier is not armed (byte-identical to today); when
            # armed, resolution above already raised a loud refusal on any
            # gap, so a returned config never carries three_tier True with
            # worker None.
            worker=resolved_worker,
            # Embedder env overrides (S2, task t19) — {} when lobes is
            # unarmed/unreachable or the gateway doesn't advertise an embedder
            # (see :func:`_resolve_lobes_rung` / :func:`colleague.lobes.embed_env`).
            embed_env=lobes_embed_env,
            # Armed lobes gateway origin (t9 self-knowledge) — None when the rung
            # is unarmed or degraded, so the self-facts ``lobes:`` line reflects
            # the state this run actually resolved with.
            lobes_gateway_url=lobes_gateway_url,
            # Same-role stale-pin refresh records (plan task t9) — the
            # resolution-time rung's own finding (if any); the vLLM engine's
            # call-time 404 catch appends to this same field in place during
            # ``work()``.
            model_refresh_warnings=(
                (model_refresh_warning,) if model_refresh_warning is not None else ()
            ),
        )

    def to_dict(self) -> dict[str, object]:
        """Config snapshot for the result artifact, with the api_key redacted."""
        data: dict[str, object] = {
            "base_url": self.base_url,
            "model": self.model,
            "max_steps": self.max_steps,
            "temperature": self.temperature,
            "timeout": self.timeout,
            "context_budget_tokens": self.context_budget_tokens,
            "autosplit_target_tokens": self.autosplit_target_tokens,
            "fillline_threshold": self.fillline_threshold,
            "fanout_files": self.fanout_files,
            "review_fanout_folders": self.review_fanout_folders,
            "plan_offer_tokens": self.plan_offer_tokens,
            "max_continue_nudges": self.max_continue_nudges,
            "synthesis_reserve_steps": self.synthesis_reserve_steps,
            "max_output_chars": self.max_output_chars,
            "subagent_depth": self.subagent_depth,
            "subagent_total": self.subagent_total,
            "lint": self.lint,
            "coherence": self.coherence,
            "memory": self.memory,
            "lint_fix_retries": self.lint_fix_retries,
            "testintegrity": self.testintegrity,
            "testintegrity_fix_retries": self.testintegrity_fix_retries,
            "testintegrity_reviewer_model": self.testintegrity_reviewer_model,
            "affected_tests": self.affected_tests,
            "affected_tests_fix_retries": self.affected_tests_fix_retries,
            "affected_tests_depth": self.affected_tests_depth,
            "affected_tests_max_files": self.affected_tests_max_files,
            "compaction_cap": self.compaction_cap,
            "three_tier": self.three_tier,
        }
        # Dual-model deepthink (t1): present ONLY when configured, so a
        # single-model snapshot is byte-identical to today (omit-when-None,
        # the destination/lint_report/capacity_decision convention). The
        # deepthink api_key is redacted exactly like the main api_key above —
        # simply absent from the sub-dict, never included.
        if self.deepthink is not None:
            data["deepthink"] = {
                "model": self.deepthink.model,
                "base_url": self.deepthink.base_url,
                "context_budget": self.deepthink.context_budget,
            }
        # Senses (multimodal front-door, cortex/senses arc task t3): present
        # ONLY when configured, so an unconfigured snapshot is byte-identical
        # to today (omit-when-None, same convention as deepthink above). The
        # senses api_key is likewise simply absent from the sub-dict, never
        # included.
        if self.senses is not None:
            data["senses"] = {
                "model": self.senses.model,
                "base_url": self.senses.base_url,
                "context_budget": self.senses.context_budget,
            }
        # Voice (stt/tts, senses live-presence + voice arc): present ONLY when
        # configured (omit-when-None, same convention as senses/deepthink above).
        # The voice api_key is absent from the sub-dict, never included.
        if self.voice is not None:
            data["voice"] = {
                "stt_model": self.voice.stt_model,
                "tts_model": self.voice.tts_model,
                "stt_base_url": self.voice.stt_base_url,
                "tts_base_url": self.voice.tts_base_url,
            }
        # Realtime (server-VAD live speech session, realtime-speech arc):
        # present ONLY when configured (omit-when-None, same convention as
        # voice/senses/deepthink above). The realtime api_key is absent from
        # the sub-dict, never included.
        if self.realtime is not None:
            data["realtime"] = {
                "available": self.realtime.available,
                "ws_url": self.realtime.ws_url,
            }
        # Worker (three-tier bounded-tool-loop actor, three-tier-execution
        # arc): present ONLY when three-tier resolved a worker (omit-when-None,
        # same convention as deepthink/senses/voice/realtime above). The
        # worker api_key is absent from the sub-dict, never included.
        if self.worker is not None:
            data["worker"] = {
                "model": self.worker.model,
                "base_url": self.worker.base_url,
                "context": self.worker.context,
            }
        return data


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
# presence means the operator already decided the knob (env > profile).
_PROFILE_ENV_KEYS: dict[str, tuple[str, ...]] = {
    "max_steps": ("COLLEAGUE_MAX_STEPS", "CONVERTIBLE_MAX_STEPS"),
    "timeout": ("COLLEAGUE_TIMEOUT", "CONVERTIBLE_TIMEOUT"),
    "context_budget_tokens": (
        "COLLEAGUE_CONTEXT_BUDGET",
        "CONVERTIBLE_CONTEXT_BUDGET",
    ),
    "fillline_threshold": (
        "COLLEAGUE_FILLLINE_THRESHOLD",
        "CONVERTIBLE_FILLLINE_THRESHOLD",
    ),
    "synthesis_reserve_steps": (
        "COLLEAGUE_SYNTHESIS_RESERVE_STEPS",
        "CONVERTIBLE_SYNTHESIS_RESERVE_STEPS",
    ),
}

# Operator overlay file: .colleague/profiles.json (repo/user via configdir) and
# .colleague/<sanitize_model(model)>/profiles.json (exact-path, per-model-first
# — the hooks/approvals overlay convention).
_PROFILES_FILENAME = "profiles.json"


def _env_present(env_keys: tuple[str, ...]) -> bool:
    """True when any of the env vars is set non-empty (mirrors ``_pick``)."""
    return any(os.environ.get(key) for key in env_keys)


def _read_profiles_file(path: Path | None) -> dict[str, dict]:
    """Parse a profiles overlay file into ``{mode: {knob: value}}``.

    Missing file, malformed JSON, or a non-dict payload is a strict no-op
    (empty dict) — the malformed-config convention shared with hooks,
    approvals, and config.json. Non-dict mode entries are dropped.
    """
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {key: value for key, value in data.items() if isinstance(value, dict)}


def _load_profile_overlays(
    repo_path: str | Path | None, model: str | None
) -> tuple[dict[str, dict], dict[str, dict]]:
    """Load ``(per_model_overlay, repo_overlay)`` profiles files.

    The per-model path is built by exact construction through
    :func:`colleague.layers.sanitize_model` — sibling ``.colleague/*/``
    directories are never globbed, so model X can never load model Y's
    overlay (honesty condition h7).
    """
    if repo_path is None:
        return {}, {}
    repo_overlay = _read_profiles_file(configdir.resolve_file(repo_path, _PROFILES_FILENAME))
    per_model: dict[str, dict] = {}
    if model:
        # Lazy: keeps config's module import graph unchanged (layers is the
        # sanctioned per-model sanitizer, same idiom as the hooks overlay).
        from colleague.layers import sanitize_model

        per_model = _read_profiles_file(
            configdir.resolve_file(repo_path, f"{sanitize_model(model)}/{_PROFILES_FILENAME}")
        )
    return per_model, repo_overlay


def _coerce_profile_int(value: object, *, minimum: int) -> int | None:
    """An int >= minimum, or None; bool is explicitly not an int here."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= minimum else None


def _coerce_profile_seconds(value: object) -> float | None:
    """A positive number of seconds as float, or None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    seconds = float(value)
    return seconds if seconds > 0 else None


def _coerce_unit_fraction(value: object) -> float | None:
    """A fraction in (0, 1], or None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    fraction = float(value)
    return fraction if 0 < fraction <= 1 else None


def _profile_as_source(profile: object) -> dict[str, object]:
    """Adapt a ModeProfile-shaped object to the overlay-dict field interface."""
    return {
        "max_steps": getattr(profile, "max_steps", None),
        "context_budget_fraction": getattr(profile, "context_budget_fraction", None),
        "synthesis_reserve_steps": getattr(profile, "synthesis_reserve_steps", None),
        "timeout": getattr(profile, "timeout", None),
        "fillline_threshold": getattr(profile, "fillline_threshold", None),
    }


def _field_from_source(
    field_name: str, source: dict[str, object], base_budget_tokens: int
) -> object | None:
    """Extract + validate one knob from one source; None when absent/invalid.

    ``context_budget_tokens`` accepts either an absolute
    ``context_budget_tokens`` int or a ``context_budget_fraction`` in (0, 1]
    applied to the *resolved default* budget — the fraction composes with the
    per-model/default budget rather than competing with an operator override
    (an env/flag-set budget never reaches this code path at all).
    """
    if field_name == "context_budget_tokens":
        absolute = _coerce_profile_int(source.get("context_budget_tokens"), minimum=1)
        if absolute is not None:
            return absolute
        fraction = _coerce_unit_fraction(source.get("context_budget_fraction"))
        if fraction is not None:
            # Floor at 1: a tiny base budget must TIGHTEN, never truncate to 0
            # — a non-positive budget would disable the context-budget path
            # entirely, the opposite of what a profile fraction means (Qodo
            # PR #260 review).
            return max(1, int(base_budget_tokens * fraction))
        return None
    raw = source.get(field_name)
    if field_name == "max_steps":
        return _coerce_profile_int(raw, minimum=1)
    if field_name == "synthesis_reserve_steps":
        return _coerce_profile_int(raw, minimum=0)
    if field_name == "timeout":
        return _coerce_profile_seconds(raw)
    if field_name == "fillline_threshold":
        return _coerce_unit_fraction(raw)
    return None


def _resolve_builtin_profile(mode: str, resolve: Callable | None) -> object | None:
    """Look up the built-in catalog profile (the t1 module), or None."""
    if resolve is None:
        try:
            # Lazy: profiles.py is a leaf catalog module; importing it here
            # keeps config importable during partial checkouts/transitions.
            from colleague.profiles import resolve_profile as resolve
        except ImportError:  # pragma: no cover - transition guard
            return None
    return resolve(mode)


def _profile_updates(
    config: "EngineConfig",
    sources: list[dict[str, object]],
    explicit_fields: set[str],
) -> dict[str, object]:
    """The knob updates the profile sources yield for *config* (S3776 extract).

    Per knob: an explicit CLI flag or a set env var means the operator already
    decided it (skipped); otherwise the FIRST source (per-model overlay > repo
    overlay > built-in profile) that yields a valid value wins, and a value
    equal to the resolved one is dropped (no-op replace avoidance).
    """
    updates: dict[str, object] = {}
    for field_name, env_keys in _PROFILE_ENV_KEYS.items():
        if field_name in explicit_fields or _env_present(env_keys):
            continue
        for source in sources:
            value = _field_from_source(field_name, source, config.context_budget_tokens)
            if value is not None:
                if value != getattr(config, field_name):
                    updates[field_name] = value
                break
    return updates


def apply_mode_profile(
    config: "EngineConfig",
    mode: str | None,
    *,
    explicit: Collection[str] = (),
    repo_path: str | Path | None = None,
    resolve: Callable | None = None,
) -> "EngineConfig":
    """Fill mode-profile defaults for constraint knobs the operator left untouched.

    The R1 (#254) profile layer, applied AFTER :meth:`EngineConfig.resolve` so
    the full precedence per knob is::

        explicit flag > COLLEAGUE_*/CONVERTIBLE_* env > per-model overlay
        > repo overlay > built-in mode profile > resolved value untouched

    *explicit* names the EngineConfig fields the caller set from CLI flags
    (e.g. ``{"max_steps"}`` when ``--max-steps`` was given); a set env var is
    detected here directly (mirroring ``_pick``'s non-empty semantics). The
    knobs a profile may fill are exactly ``_PROFILE_ENV_KEYS``.

    Strict no-op guarantees (h1): returns *config* itself for a falsy or
    unknown mode, when no profile/overlay defines the mode, or when every
    knob is already operator-decided — so a run with no mode selected is
    byte-identical to today.
    """
    if not mode:
        return config
    profile = _resolve_builtin_profile(mode, resolve)
    per_model_overlay, repo_overlay = _load_profile_overlays(repo_path, config.model)
    sources: list[dict[str, object]] = [
        source
        for source in (per_model_overlay.get(mode), repo_overlay.get(mode))
        if isinstance(source, dict)
    ]
    if profile is not None:
        sources.append(_profile_as_source(profile))
    if not sources:
        return config
    updates = _profile_updates(config, sources, set(explicit))
    if not updates:
        return config
    return replace(config, **updates)
