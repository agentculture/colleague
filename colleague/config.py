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
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Collection, Optional

from colleague import configdir

# vLLM ignores the key, but the OpenAI wire format wants a non-empty string.
_DEFAULT_API_KEY = "EMPTY"
_DEFAULT_BASE_URL = "http://localhost:8001/v1"
# Built-in fallback model id. Points at the model the reference rig actually
# serves at _DEFAULT_BASE_URL so a bare work item (no COLLEAGUE_MODEL / --model)
# reaches a live model instead of a 404 "model does not exist". Override per
# environment with COLLEAGUE_MODEL or --model.
_DEFAULT_MODEL = "sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP"
_DEFAULT_MAX_STEPS = 40
_DEFAULT_TEMPERATURE = 0.0
_DEFAULT_TIMEOUT = 120.0
# Proactive context budget in tokens. Counted exactly via the served model's
# /tokenize endpoint when reachable; char-based fallback otherwise (best-effort
# exact, char-approximate fallback, never token-exact-guaranteed — no tokenizer
# library is bundled). Sized for the 256k (262144-token) reference rig, leaving
# headroom for the completion + system/tools prompt. Override per environment
# with COLLEAGUE_CONTEXT_BUDGET (e.g. lower it for a small-context model).
_DEFAULT_CONTEXT_BUDGET = 192000
# Cap on each tool result (read_file / run_command / list_dir / subagent) fed
# back to the model, in characters. Raised from the old hardcoded 20000 to suit
# the 256k window so a large file read isn't truncated. Tunable per environment
# with COLLEAGUE_MAX_OUTPUT_CHARS.
_DEFAULT_MAX_OUTPUT_CHARS = 100000

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
# 64K-window-sized share — the same proportion as the main
# 192000-for-256K default (192000/262144 ≈ 0.73 ≈ 48000/65536). Override per
# environment with COLLEAGUE_DEEPTHINK_MODEL / _BASE_URL / _API_KEY /
# _CONTEXT_BUDGET, or a ``deepthink`` section in .colleague/config.json.
_DEFAULT_DEEPTHINK_CONTEXT_BUDGET = 48000

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
_DEEPTHINK_CONFIG_KEYS = frozenset({"model", "base_url", "api_key", "context_budget"})


def _pick(explicit: str | None, *env_keys: str, default: str) -> str:
    if explicit is not None:
        return explicit
    for key in env_keys:
        value = os.environ.get(key)
        if value:
            return value
    return default


def load_config_file(repo_path: str | Path) -> dict[str, str]:
    """Load a persistent config file from .colleague/config.json.

    Uses :func:`colleague.configdir.resolve_file` to locate the file, honouring
    the repo-over-user precedence and the legacy .convertible fallback.

    Returns a dict containing only the recognised keys (``base_url``,
    ``api_key``, ``model``). On a missing file, malformed JSON, or any read
    error, returns an empty dict and never raises.
    """
    path = configdir.resolve_file(repo_path, _CONFIG_FILENAME)
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: str(v) for k, v in data.items() if k in _CONFIG_KEYS and v is not None}


def _load_deepthink_overrides(repo_path: str | Path) -> dict[str, str]:
    """Read the NESTED ``deepthink`` section of .colleague/config.json.

    Mirrors :func:`load_config_file`'s malformed-input handling but reads a
    *nested* object (``{"deepthink": {...}}``) instead of top-level keys —
    ``load_config_file``'s ``dict[str, str]`` endpoint contract (base_url/
    api_key/model) must not change. Returns a dict of stringified values for
    the recognised keys (``model``, ``base_url``, ``api_key``,
    ``context_budget``). A missing file, malformed JSON, a non-dict payload,
    or an absent/non-dict ``deepthink`` section all yield an empty dict and
    never raise.
    """
    path = configdir.resolve_file(repo_path, _CONFIG_FILENAME)
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    section = data.get("deepthink")
    if not isinstance(section, dict):
        return {}
    return {
        key: str(value)
        for key, value in section.items()
        if key in _DEEPTHINK_CONFIG_KEYS and value is not None
    }


def _load_lint_overrides(repo_path: str | Path) -> tuple[str | None, str | None]:
    """Read ``lint`` / ``lint_fix_retries`` from .colleague/config.json as raw strings.

    Kept separate from :func:`load_config_file` (whose ``dict[str, str]`` endpoint
    contract — base_url/api_key/model — must not change): the lint keys carry a
    bool / int, not an endpoint string. Returns ``(lint, lint_fix_retries)`` where
    each is the stringified config value or ``None`` when absent. A missing or
    malformed file yields ``(None, None)`` and never raises.
    """
    path = configdir.resolve_file(repo_path, _CONFIG_FILENAME)
    if path is None:
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    if not isinstance(data, dict):
        return None, None
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
    yields ``(None, None)`` and never raises.
    """
    path = configdir.resolve_file(repo_path, _CONFIG_FILENAME)
    if path is None:
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    if not isinstance(data, dict):
        return None, None
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
    never raises.
    """
    path = configdir.resolve_file(repo_path, _CONFIG_FILENAME)
    if path is None:
        return None, None, None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None, None, None
    if not isinstance(data, dict):
        return None, None, None, None
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
    return DeepthinkConfig(
        model=model.strip(),
        base_url=base_url,
        api_key=api_key,
        context_budget=context_budget,
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


@dataclass
class EngineConfig:
    """Settings for an OpenAI-compatible engine driver."""

    base_url: str = _DEFAULT_BASE_URL
    api_key: str = _DEFAULT_API_KEY
    model: str = _DEFAULT_MODEL
    max_steps: int = _DEFAULT_MAX_STEPS
    temperature: float = _DEFAULT_TEMPERATURE
    timeout: float = _DEFAULT_TIMEOUT
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
    lint_fix_retries: int = _DEFAULT_LINT_FIX_RETRIES
    testintegrity: bool = _DEFAULT_TESTINTEGRITY_ENABLED
    testintegrity_fix_retries: int = _DEFAULT_TESTINTEGRITY_FIX_RETRIES
    testintegrity_reviewer_model: str = _DEFAULT_TESTINTEGRITY_REVIEWER_MODEL
    affected_tests: bool = _DEFAULT_AFFECTED_TESTS_ENABLED
    affected_tests_fix_retries: int = _DEFAULT_AFFECTED_TESTS_FIX_RETRIES
    affected_tests_depth: int = _DEFAULT_AFFECTED_TESTS_DEPTH
    affected_tests_max_files: int = _DEFAULT_AFFECTED_TESTS_MAX_FILES
    affected_tests_override: Optional[str] = None
    # Dual-model deepthink escalation target (t1). ``None`` = single-model,
    # byte-identical to today (the pre-feature default). See
    # :class:`DeepthinkConfig` and :func:`_resolve_deepthink`.
    deepthink: Optional[DeepthinkConfig] = None

    # A runtime-only per-step progress sink ``(step_index, tool, target, ok)``
    # the loop fires per tool call (#38). Set by the CLI work path, not by
    # ``resolve()``; excluded from eq/repr and from ``to_dict`` (it is behavior,
    # not serializable config).
    progress: Optional[Callable[[int, str, str, bool], None]] = field(
        default=None, compare=False, repr=False
    )

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

    # Mode-profile explicit-knob mask (t3 / spec R1): the EngineConfig field names
    # the caller set from explicit CLI flags (e.g. ``{"max_steps"}`` when
    # ``--max-steps`` was given), so ``apply_mode_profile`` never overwrites them.
    # A runtime field set by the CLI layer — the ``role`` precedent (keeps
    # ``execute_work`` under the S107 parameter ceiling); excluded from
    # eq/repr/to_dict.
    explicit_knobs: Collection[str] = field(default=(), compare=False, repr=False)

    @classmethod
    def resolve(
        cls,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        max_steps: int | None = None,
        context_budget_tokens: int | None = None,
        max_output_chars: int | None = None,
        subagent_concurrency: int | None = None,
        autosplit_target_tokens: int | None = None,
        fillline_threshold: float | None = None,
        fanout_files: int | None = None,
        plan_offer_tokens: int | None = None,
        max_continue_nudges: int | None = None,
        repo_path: str | Path | None = None,
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
        """
        # Load config-file values once (empty dict when repo_path is None or
        # the file is absent/malformed).
        file_cfg: dict[str, str] = {}
        file_lint: str | None = None
        file_lint_retries: str | None = None
        file_ti: str | None = None
        file_ti_retries: str | None = None
        file_at: str | None = None
        file_at_retries: str | None = None
        file_at_depth: str | None = None
        file_at_max_files: str | None = None
        file_deepthink: dict[str, str] = {}
        if repo_path is not None:
            file_cfg = load_config_file(repo_path)
            file_lint, file_lint_retries = _load_lint_overrides(repo_path)
            file_ti, file_ti_retries = _load_testintegrity_overrides(repo_path)
            file_at, file_at_retries, file_at_depth, file_at_max_files = (
                _load_affected_tests_overrides(repo_path)
            )
            file_deepthink = _load_deepthink_overrides(repo_path)

        file_base_url: str | None = file_cfg.get("base_url")
        file_api_key: str | None = file_cfg.get("api_key")
        file_model: str | None = file_cfg.get("model")

        # Resolved once as locals (not just inline in the ``cls(...)`` call
        # below) so the deepthink resolution can default ITS base_url/api_key
        # to the MAIN endpoint's already-resolved values (spec requirement).
        resolved_base_url = _pick(
            base_url,
            "COLLEAGUE_BASE_URL",
            "CONVERTIBLE_BASE_URL",
            "OPENAI_BASE_URL",
            default=file_base_url if file_base_url is not None else _DEFAULT_BASE_URL,
        )
        resolved_api_key = _pick(
            api_key,
            "COLLEAGUE_API_KEY",
            "CONVERTIBLE_API_KEY",
            "OPENAI_API_KEY",
            default=file_api_key if file_api_key is not None else _DEFAULT_API_KEY,
        )

        # Dual-model deepthink (t1) — resolved once as a local (like
        # resolved_base_url/resolved_api_key above) so the test-integrity
        # reviewer default backfill (t7) below can inspect the resolved
        # DeepthinkConfig before EngineConfig itself is constructed.
        resolved_deepthink = _resolve_deepthink(file_deepthink, resolved_base_url, resolved_api_key)
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

        return cls(
            base_url=resolved_base_url,
            api_key=resolved_api_key,
            model=_pick(
                model,
                "COLLEAGUE_MODEL",
                "CONVERTIBLE_MODEL",
                default=file_model if file_model is not None else _DEFAULT_MODEL,
            ),
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
            context_budget_tokens=int(
                _pick(
                    _str(context_budget_tokens),
                    "COLLEAGUE_CONTEXT_BUDGET",
                    "CONVERTIBLE_CONTEXT_BUDGET",
                    default=str(_DEFAULT_CONTEXT_BUDGET),
                )
            ),
            max_output_chars=int(
                _pick(
                    _str(max_output_chars),
                    "COLLEAGUE_MAX_OUTPUT_CHARS",
                    "CONVERTIBLE_MAX_OUTPUT_CHARS",
                    default=str(_DEFAULT_MAX_OUTPUT_CHARS),
                )
            ),
            subagent_concurrency=_try_int(
                _pick(
                    _str(subagent_concurrency),
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
                    _str(autosplit_target_tokens),
                    "COLLEAGUE_AUTOSPLIT_TARGET",
                    "CONVERTIBLE_AUTOSPLIT_TARGET",
                    default=str(_DEFAULT_AUTOSPLIT_TARGET_TOKENS),
                )
            ),
            fillline_threshold=_try_float(
                _pick(
                    _str(fillline_threshold),
                    "COLLEAGUE_FILLLINE_THRESHOLD",
                    "CONVERTIBLE_FILLLINE_THRESHOLD",
                    default=str(_DEFAULT_FILLLINE_THRESHOLD),
                ),
                default=_DEFAULT_FILLLINE_THRESHOLD,
            ),
            fanout_files=_try_int(
                _pick(
                    _str(fanout_files),
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
                    _str(plan_offer_tokens),
                    "COLLEAGUE_PLAN_OFFER_TOKENS",
                    "CONVERTIBLE_PLAN_OFFER_TOKENS",
                    default=str(_DEFAULT_PLAN_OFFER_TOKENS),
                ),
                default=_DEFAULT_PLAN_OFFER_TOKENS,
            ),
            max_continue_nudges=_try_int(
                _pick(
                    _str(max_continue_nudges),
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
            lint_fix_retries=_try_int(
                _pick(
                    None,
                    "COLLEAGUE_LINT_FIX_RETRIES",
                    "CONVERTIBLE_LINT_FIX_RETRIES",
                    default=(
                        file_lint_retries
                        if file_lint_retries is not None
                        else str(_DEFAULT_LINT_FIX_RETRIES)
                    ),
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
                    default=(
                        file_ti_retries
                        if file_ti_retries is not None
                        else str(_DEFAULT_TESTINTEGRITY_FIX_RETRIES)
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
                    default=(
                        file_at_retries
                        if file_at_retries is not None
                        else str(_DEFAULT_AFFECTED_TESTS_FIX_RETRIES)
                    ),
                ),
                default=_DEFAULT_AFFECTED_TESTS_FIX_RETRIES,
            ),
            affected_tests_depth=_try_int(
                _pick(
                    None,
                    "COLLEAGUE_AFFECTED_TESTS_DEPTH",
                    default=(
                        file_at_depth
                        if file_at_depth is not None
                        else str(_DEFAULT_AFFECTED_TESTS_DEPTH)
                    ),
                ),
                default=_DEFAULT_AFFECTED_TESTS_DEPTH,
            ),
            affected_tests_max_files=_try_int(
                _pick(
                    None,
                    "COLLEAGUE_AFFECTED_TESTS_MAX_FILES",
                    default=(
                        file_at_max_files
                        if file_at_max_files is not None
                        else str(_DEFAULT_AFFECTED_TESTS_MAX_FILES)
                    ),
                ),
                default=_DEFAULT_AFFECTED_TESTS_MAX_FILES,
            ),
            # affected_tests_override has no env var (set later from a CLI flag).
            affected_tests_override=None,
            # Dual-model deepthink (t1) — env > config.json `deepthink` section >
            # absent (None). base_url/api_key default to the resolved MAIN
            # endpoint values computed above.
            deepthink=resolved_deepthink,
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
            "lint_fix_retries": self.lint_fix_retries,
            "testintegrity": self.testintegrity,
            "testintegrity_fix_retries": self.testintegrity_fix_retries,
            "testintegrity_reviewer_model": self.testintegrity_reviewer_model,
            "affected_tests": self.affected_tests,
            "affected_tests_fix_retries": self.affected_tests_fix_retries,
            "affected_tests_depth": self.affected_tests_depth,
            "affected_tests_max_files": self.affected_tests_max_files,
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
