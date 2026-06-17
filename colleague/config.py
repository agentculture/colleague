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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

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

# Engine SELECTION default (distinct from the provider config below — mock
# ignores provider config entirely). The default is the real bundled engine,
# never the no-op ``mock`` contract reference: a bare ``drive``/``session`` must
# not silently fake work (issue #53, "Mock shouldn't be default"). ``mock`` is
# reachable only by an explicit ``--engine mock`` / ``COLLEAGUE_ENGINE=mock``.
_DEFAULT_ENGINE = "vllm-openai"

# Subagent delegation bounds.
MAX_SUBAGENT_DEPTH = 2
MAX_SUBAGENT_FANOUT = 4

# The persistent per-repo config file, resolved under .colleague/ (configdir).
_CONFIG_FILENAME = "config.json"
# Recognised keys in .colleague/config.json.
_CONFIG_KEYS = frozenset({"base_url", "api_key", "model"})


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
    autosplit_target_tokens: int = _DEFAULT_AUTOSPLIT_TARGET_TOKENS
    fillline_threshold: float = _DEFAULT_FILLLINE_THRESHOLD
    fanout_files: int = _DEFAULT_FANOUT_FILES
    plan_offer_tokens: int = _DEFAULT_PLAN_OFFER_TOKENS
    max_continue_nudges: int = _DEFAULT_MAX_CONTINUE_NUDGES
    synthesis_reserve_steps: int = _DEFAULT_SYNTHESIS_RESERVE
    lint: bool = _DEFAULT_LINT_ENABLED
    lint_fix_retries: int = _DEFAULT_LINT_FIX_RETRIES
    testintegrity: bool = _DEFAULT_TESTINTEGRITY_ENABLED
    testintegrity_fix_retries: int = _DEFAULT_TESTINTEGRITY_FIX_RETRIES
    testintegrity_reviewer_model: str = _DEFAULT_TESTINTEGRITY_REVIEWER_MODEL

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

        ``temperature`` and ``timeout`` have no explicit-override keyword (and no
        CLI flag): no caller in the codebase passes them, so their precedence is
        simply ``COLLEAGUE_*`` env var > built-in default. Keeping them off the
        signature holds ``resolve`` under the parameter ceiling (SonarCloud S107);
        the dataclass still carries the fields, and the ``COLLEAGUE_TEMPERATURE`` /
        ``COLLEAGUE_TIMEOUT`` env vars (with ``CONVERTIBLE_*`` fallbacks) override
        them as before.
        """
        # Load config-file values once (empty dict when repo_path is None or
        # the file is absent/malformed).
        file_cfg: dict[str, str] = {}
        file_lint: str | None = None
        file_lint_retries: str | None = None
        file_ti: str | None = None
        file_ti_retries: str | None = None
        if repo_path is not None:
            file_cfg = load_config_file(repo_path)
            file_lint, file_lint_retries = _load_lint_overrides(repo_path)
            file_ti, file_ti_retries = _load_testintegrity_overrides(repo_path)

        file_base_url: str | None = file_cfg.get("base_url")
        file_api_key: str | None = file_cfg.get("api_key")
        file_model: str | None = file_cfg.get("model")

        return cls(
            base_url=_pick(
                base_url,
                "COLLEAGUE_BASE_URL",
                "CONVERTIBLE_BASE_URL",
                "OPENAI_BASE_URL",
                default=file_base_url if file_base_url is not None else _DEFAULT_BASE_URL,
            ),
            api_key=_pick(
                api_key,
                "COLLEAGUE_API_KEY",
                "CONVERTIBLE_API_KEY",
                "OPENAI_API_KEY",
                default=file_api_key if file_api_key is not None else _DEFAULT_API_KEY,
            ),
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
            testintegrity_reviewer_model=_pick(
                None,
                "COLLEAGUE_TESTINTEGRITY_REVIEWER_MODEL",
                "CONVERTIBLE_TESTINTEGRITY_REVIEWER_MODEL",
                default=_DEFAULT_TESTINTEGRITY_REVIEWER_MODEL,
            ),
        )

    def to_dict(self) -> dict[str, object]:
        """Config snapshot for the result artifact, with the api_key redacted."""
        return {
            "base_url": self.base_url,
            "model": self.model,
            "max_steps": self.max_steps,
            "temperature": self.temperature,
            "timeout": self.timeout,
            "context_budget_tokens": self.context_budget_tokens,
            "autosplit_target_tokens": self.autosplit_target_tokens,
            "fillline_threshold": self.fillline_threshold,
            "fanout_files": self.fanout_files,
            "plan_offer_tokens": self.plan_offer_tokens,
            "max_continue_nudges": self.max_continue_nudges,
            "synthesis_reserve_steps": self.synthesis_reserve_steps,
            "max_output_chars": self.max_output_chars,
            "lint": self.lint,
            "lint_fix_retries": self.lint_fix_retries,
            "testintegrity": self.testintegrity,
            "testintegrity_fix_retries": self.testintegrity_fix_retries,
            "testintegrity_reviewer_model": self.testintegrity_reviewer_model,
        }


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
