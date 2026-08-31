"""Built-in configuration defaults and caps for :mod:`colleague.config`.

The leaf of the config package: every ``_DEFAULT_*`` builtin, the subagent /
agent-message caps, the seat→role map and the ``config.json`` key allow-lists,
with nothing but stdlib behind them. Split out of ``config.py`` (hard
1000-line file limit, plan ``hard-1000-line-file-limit`` t14) — a pure move,
no value changed. Every name here is re-exported from :mod:`colleague.config`,
so ``from colleague.config import _DEFAULT_MAX_OUTPUT_CHARS`` (tools.py) and
``from colleague.config import MAX_SUBAGENT_FANOUT`` (loop.py) resolve exactly
as before.
"""

from __future__ import annotations

# vLLM ignores the key, but the OpenAI wire format wants a non-empty string.
_DEFAULT_API_KEY = "EMPTY"
_DEFAULT_BASE_URL = "http://localhost:8001/v1"
# Built-in fallback model id. Points at the model the reference rig actually
# serves at _DEFAULT_BASE_URL so a bare work item (no COLLEAGUE_MODEL / --model)
# reaches a live model instead of a 404 "model does not exist". Override per
# environment with COLLEAGUE_MODEL or --model.
#
# Flipped from unsloth/Qwen3.6-27B-NVFP4 to unsloth/Qwen3.8-27B-NVFP4 (issue
# #404): an authed GET of the lobes gateway /capabilities on 2026-08-20 showed
# the rig now serves cortex model unsloth/Qwen3.8-27B-NVFP4 at a 1048576-token
# (1M via YaRN) context, ready=true, tools=true — the old 3.6 id 404s.
_DEFAULT_MODEL = "unsloth/Qwen3.8-27B-NVFP4"
_DEFAULT_MAX_STEPS = 40
_DEFAULT_TEMPERATURE = 0.0
_DEFAULT_TIMEOUT = 120.0
# t8's "too long" advisory threshold, in minutes (#416 t2).
_DEFAULT_TOO_LONG_MIN = 20
# Proactive context budget in tokens. Counted exactly via the served model's
# /tokenize endpoint when reachable; char-based fallback otherwise (best-effort
# exact, char-approximate fallback, never token-exact-guaranteed — no tokenizer
# library is bundled). Sized for the window the reference rig now serves the
# default model at: the 2026-08-20 /capabilities probe (issue #404) shows the
# rig serving unsloth/Qwen3.8-27B-NVFP4 at a 1048576-token (1M via YaRN)
# window — 131072 (128K) is the conservative end of the sanctioned 128K-256K
# range (decision c10), ~2.7x the old 48000/65536-window sizing, leaving deep
# headroom below the served window for the completion + system/tools prompt
# without chasing the full 1M (streaming/latency at that size is unproven).
# Override per environment with COLLEAGUE_CONTEXT_BUDGET.
_DEFAULT_CONTEXT_BUDGET = 131072
# Cap on each tool result (read_file / run_command / list_dir / subagent) fed
# back to the model, in characters. Scaled with the context budget at the same
# ~13% ratio as the previous 48000-token/25000-char sizing: 131072 tokens * ~4
# chars/token * 13% ≈ 68000, so one large read still cannot evict half the
# working history. Tunable per environment with COLLEAGUE_MAX_OUTPUT_CHARS.
_DEFAULT_MAX_OUTPUT_CHARS = 68000

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

# Rung-2 lesson distillation (self-learning t9). Default-ON but effective only
# when the runtime resolves a distillation author (t10); without one the loop
# stays at the rung-1 floor, so default-ON never adds a model call by itself.
_DEFAULT_MEMORY_DISTILL = True

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

# Thought→action→evaluation execution arming (post-#387 program, plan task
# t12; issue #397; spec claims c17/c26, honesty h10/h19).
#
# An INDEPENDENT opt-in, deliberately DISTINCT from ``three_tier``:
# ``COLLEAGUE_THOUGHT_ACTION_EVALUATION`` env > a ``thought_action_evaluation``
# key in .colleague/config.json (bool, or an object whose presence — absent an
# explicit ``{"enabled": false}`` — itself means armed, the ``lobes``/
# ``three_tier`` bare-string-or-object precedent) > default-OFF. Arming one
# mode never arms the other; arming BOTH refuses loudly (two execution modes
# cannot both own the acting seat — see :func:`_resolve_evaluation_seats`).
#
# Unarmed is a strict no-op: no seat is resolved, no field changes, and the
# ``to_dict()`` key set is byte-identical to the pre-feature snapshot (the
# mode's keys are omit-when-unarmed, the deepthink/senses/worker convention).
_DEFAULT_THOUGHT_ACTION_EVALUATION = False

# Model-bound agents arming (#411, the ELEVENTH sanctioned increment; plan task
# t7). A THIRD, INDEPENDENT opt-in: ``COLLEAGUE_AGENTS`` env > an ``agents``
# key in .colleague/config.json (bool, or an object whose presence — absent an
# explicit ``{"enabled": false}`` — itself means armed, the ``three_tier``/
# ``thought_action_evaluation`` precedent) > default-OFF. Arming it together
# with EITHER of the other two execution modes refuses loudly (one mode owns
# the acting seat). Unarmed is a strict no-op: the ``agents`` key is omitted
# from ``to_dict()`` and every armed-only surface stays dormant.
_DEFAULT_AGENTS_ENABLED = False

# The seat → lobes ROLE NAME map for the thought→action→evaluation mode.
#
# Every seat is resolved BY ROLE NAME from the gateway's ``/capabilities``
# contract — colleague NEVER parses a model name to decide who fills a seat
# (spec c40: the reference rig's Gemma 12B / Qwen 35B / Qwen 27B ids are a
# CANDIDATE, never an architectural requirement). The mapping mirrors the
# landed three-tier seats:
#
# - ``front`` ← the ``senses`` role: the operator-facing front door, here
#   promoted from relaying to committing typed Thoughts;
# - ``worker`` ← the ``worker`` role: the bounded-tool-loop actor that
#   realizes a Thought;
# - ``evaluator`` ← the ``cortex`` role: the tools-off seat that judges
#   thought↔action fidelity (three-tier's configurator seat, re-tasked).
#
# The evaluator sharing the ``cortex`` role is EXACTLY why the authority
# separation of spec c38/h30 matters: distillation's own author resolution
# would otherwise pick that same checkpoint and silently hand the evaluator
# memory-write authority. Arming therefore populates
# :attr:`EngineConfig.evaluator_checkpoint`, which
# ``colleague/distill.py``'s ``_refuses_evaluator_as_distiller`` guard reads.
#
# Ordered (not a dict literal at use time) so a refusal always names the seats
# in a deterministic order.
_EVALUATION_SEAT_ROLES: tuple[tuple[str, str], ...] = (
    ("front", "senses"),
    ("worker", "worker"),
    ("evaluator", "cortex"),
)

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
MAX_AGENT_MESSAGES = 64

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
# Recognised key inside each NESTED seat section (``front``/``worker``/
# ``evaluator``) of .colleague/config.json for the thought→action→evaluation
# mode (plan task t12). Deliberately the SAME narrow set as
# :data:`_WORKER_CONFIG_KEYS`: a seat has no declared model/base_url — seats
# resolve ONLY by lobes role NAME — so the key-hygiene override is the only
# thing an operator can say about a seat here.
_SEAT_CONFIG_KEYS = _WORKER_CONFIG_KEYS
# Recognised key inside the NESTED "distiller" section of .colleague/config.json
# (plan task t12; spec c38/h30). A bare string is also accepted (the ``lobes``
# precedent). This declares that lesson DISTILLATION is a distinct authority
# from evaluation — see :func:`_resolve_distiller_checkpoint`.
_DISTILLER_CONFIG_KEYS = frozenset({"model"})

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
