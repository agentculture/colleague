"""Thought→action→evaluation mode arming: independent opt-in, seats by ROLE NAME.

Plan: docs/plans/2026-08-09-post-387-program-evaluator-rename-self-learn-speci.md,
task t12 (covers c26, h19, c17, h10). Issue #397.

Mirrors ``tests/test_config_worker.py`` (the landed three-tier arming suite)
fixture-for-fixture — the same live ``/capabilities`` HTTP server, the same
sentinel-model stance (real SHAPE, test ids), the same refusal-message asserts.

The four load-bearing decisions this suite pins:

* **An INDEPENDENT opt-in, distinct from ``three_tier``.** ``COLLEAGUE_THOUGHT_ACTION_EVALUATION``
  env > a ``thought_action_evaluation`` key in .colleague/config.json > default-OFF.
  Arming one mode never arms the other, and arming BOTH refuses loudly (two
  execution modes cannot both own the acting seat).
* **Byte-identical when unarmed.** ``EngineConfig.resolve() == EngineConfig()``
  and the ``to_dict()`` key set is unchanged — the new keys are
  omit-when-unarmed (the deepthink/senses/worker convention), never a new
  always-present key.
* **Seats resolve BY ROLE NAME from the lobes /capabilities contract.**
  front ← ``senses``, worker ← ``worker``, evaluator ← ``cortex``. A rig
  missing (or not-ready on) any required role REFUSES to arm with a legible
  reason naming the seat and the role — never model-name parsing, never a
  silent fallback.
* **Deepthink stays absent in this mode**, exactly as in three-tier — neither a
  declared deepthink nor one discovered from the lobes ``muse`` role survives.

Plus the authority-separation seam (spec c38/h30): arming populates
``evaluator_checkpoint`` (and supports a declared, distinct
``distiller_checkpoint``) so ``colleague/distill.py``'s guard has real data to
refuse the evaluator seat distillation authority.
"""

from __future__ import annotations

import contextlib
import http.server
import json
import threading
from pathlib import Path
from typing import Iterator

import pytest

from colleague import distill, lobes
from colleague.cli._errors import CliError
from colleague.config import (
    _DEFAULT_API_KEY,
    EngineConfig,
    EvaluationSeats,
    SeatConfig,
)

# Sentinel role ids — real SHAPE, test ids (the test_config_worker.py stance).
# Deliberately NOT model names a heuristic could parse: role NAME is the only
# resolution input (spec c40 — the reference rig's Gemma/Qwen ids are a
# CANDIDATE, never an architectural requirement).
_CORTEX_MODEL = "lobes-cortex-sentinel-model"
_SENSES_MODEL = "lobes-senses-sentinel-model"
_WORKER_MODEL = "lobes-worker-sentinel-model"
_MUSE_MODEL = "lobes-muse-sentinel-model"

_ROLE_ENDPOINT = "http://localhost:8000"

_CORTEX_WINDOW = 131072
_SENSES_WINDOW = 32768
_WORKER_WINDOW = 262144


def _cortex_role(*, model: str = _CORTEX_MODEL, ready: bool = True) -> dict[str, object]:
    return {
        "role": "cortex",
        "model": model,
        "runtime": "vllm",
        "endpoint": _ROLE_ENDPOINT,
        "path": "/v1/chat/completions",
        "context": _CORTEX_WINDOW,
        "quant": "modelopt",
        "mtp": True,
        "responsibilities": ["reasoning", "tool_use"],
        "forbidden_responsibilities": [],
        "ready": ready,
        "loaded": True,
    }


def _senses_role(*, model: str = _SENSES_MODEL, ready: bool = True) -> dict[str, object]:
    return {
        "role": "senses",
        "model": model,
        "runtime": "vllm",
        "endpoint": _ROLE_ENDPOINT,
        "path": "/v1/chat/completions",
        "context": _SENSES_WINDOW,
        "quant": "compressed-tensors",
        "mtp": True,
        "responsibilities": ["intake"],
        "forbidden_responsibilities": ["final_decision", "repo_action"],
        "ready": ready,
        "loaded": True,
    }


def _worker_role(
    *,
    model: str = _WORKER_MODEL,
    endpoint: str = _ROLE_ENDPOINT,
    ready: bool = True,
) -> dict[str, object]:
    return {
        "role": "worker",
        "model": model,
        "runtime": "vllm",
        "endpoint": endpoint,
        "path": "/v1/chat/completions",
        "context": _WORKER_WINDOW,
        "quant": "modelopt",
        "mtp": True,
        "responsibilities": ["reasoning", "tool_use", "code_repo_actions"],
        "forbidden_responsibilities": [],
        "ready": ready,
        "loaded": ready,
    }


def _muse_role() -> dict[str, object]:
    return {
        "role": "muse",
        "model": _MUSE_MODEL,
        "runtime": "vllm",
        "endpoint": _ROLE_ENDPOINT,
        "path": "/v1/chat/completions",
        "context": 262144,
        "quant": "modelopt",
        "mtp": True,
        "responsibilities": ["ideation", "divergent_second_opinion"],
        "forbidden_responsibilities": ["final_decision", "repo_action"],
        "ready": True,
        "loaded": False,
    }


#: cortex + senses only — no worker seat available.
BASE_PAYLOAD: dict[str, object] = {"cortex": _cortex_role(), "senses": _senses_role()}
#: The full three-seat rig this mode needs.
SEATED_PAYLOAD: dict[str, object] = {**BASE_PAYLOAD, "worker": _worker_role()}
#: The full rig plus a muse advert (the deepthink-discovery control).
SEATED_MUSE_PAYLOAD: dict[str, object] = {**SEATED_PAYLOAD, "muse": _muse_role()}


@pytest.fixture(autouse=True)
def _isolate_user_home(tmp_path_factory, monkeypatch):
    # Prevent a real ~/.colleague/config.json leaking into a resolution
    # (belt-and-braces over conftest's COLLEAGUE_HOME isolation).
    monkeypatch.setattr(Path, "home", lambda: tmp_path_factory.mktemp("home"))


def _write_config(repo: Path, payload: dict) -> None:
    cfg_dir = repo / ".colleague"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(json.dumps(payload), encoding="utf-8")


class _CapabilitiesHandler(http.server.BaseHTTPRequestHandler):
    body: bytes = b"{}"

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler method name
        if self.path != "/capabilities":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


@contextlib.contextmanager
def _serving(payload: object) -> Iterator[str]:
    handler_cls = type(
        "_ScopedHandler",
        (_CapabilitiesHandler,),
        {"body": json.dumps(payload).encode("utf-8")},
    )
    server = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


# The to_dict() key set as it stands BEFORE this feature — copied verbatim from
# tests/test_config_subagent.py::test_to_dict_has_expected_keys and
# tests/test_config_senses.py::test_absent_to_dict_matches_pre_senses_keys, the
# two landed pins this mode must not disturb.
_PRE_MODE_TO_DICT_KEYS = {
    "base_url",
    "model",
    "max_steps",
    "temperature",
    "timeout",
    "context_budget_tokens",
    "autosplit_target_tokens",
    "fillline_threshold",
    "fanout_files",
    "review_fanout_folders",
    "plan_offer_tokens",
    "max_continue_nudges",
    "synthesis_reserve_steps",
    "max_output_chars",
    "subagent_depth",
    "subagent_total",
    "lint",
    "coherence",
    "memory",
    "lint_fix_retries",
    "testintegrity",
    "testintegrity_fix_retries",
    "testintegrity_reviewer_model",
    "affected_tests",
    "affected_tests_fix_retries",
    "affected_tests_depth",
    "affected_tests_max_files",
    "compaction_cap",
    "three_tier",
    "reasoning_effort",  # thinking-effort ladder, #416 t2
    "reasoning_effort_seats",  # thinking-effort ladder, #416 t2
    "too_long_min",  # thinking-effort ladder, #416 t2
}


# ---------------------------------------------------------------------------
# Acceptance criterion 1a: unarmed is BYTE-IDENTICAL (h19/h10).
# ---------------------------------------------------------------------------


def test_unarmed_resolve_equals_the_bare_dataclass_default() -> None:
    """resolve() with nothing configured reproduces the dataclass's own bare
    defaults field-for-field — the new fields changed nothing about resolution."""
    assert EngineConfig.resolve() == EngineConfig()


def test_unarmed_to_dict_key_set_is_unchanged() -> None:
    """The mode's keys are omit-when-unarmed (deepthink/senses/worker
    convention), so an unarmed snapshot carries EXACTLY the pre-mode keys —
    zero diffs against the landed three-tier/subagent/senses key pins."""
    snapshot = EngineConfig.resolve().to_dict()
    assert set(snapshot.keys()) == _PRE_MODE_TO_DICT_KEYS


def test_unarmed_defaults_are_absent_on_the_dataclass() -> None:
    cfg = EngineConfig.resolve()
    assert cfg.thought_action_evaluation is False
    assert cfg.evaluation_seats is None
    assert cfg.evaluator_checkpoint is None
    assert cfg.distiller_checkpoint is None


def test_unarmed_with_a_full_seat_advert_resolves_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A gateway advertising every seat role never resolves them unless the
    mode is explicitly armed — read and discarded, exactly like ``reranker``."""
    with _serving(SEATED_MUSE_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MODEL", "lobes")  # discovery opt-in
        cfg = EngineConfig.resolve()
    assert cfg.thought_action_evaluation is False
    assert cfg.evaluation_seats is None
    assert cfg.evaluator_checkpoint is None
    # ...and the legacy lobes behavior is untouched: cortex still drives the
    # main dial and the muse advert still resolves a deepthink.
    assert cfg.model == _CORTEX_MODEL
    assert cfg.deepthink is not None
    assert cfg.deepthink.model == _MUSE_MODEL
    assert cfg.three_tier is False
    assert cfg.worker is None


def test_explicit_disarm_with_a_full_seat_advert_is_a_no_op(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _serving(SEATED_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_THOUGHT_ACTION_EVALUATION", "0")
        cfg = EngineConfig.resolve()
    assert cfg.thought_action_evaluation is False
    assert cfg.evaluation_seats is None


# ---------------------------------------------------------------------------
# Acceptance criterion 1b: the arming key is DISTINCT from three_tier —
# arming one never arms the other.
# ---------------------------------------------------------------------------


def test_arming_the_mode_does_not_arm_three_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    with _serving(SEATED_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_THOUGHT_ACTION_EVALUATION", "1")
        cfg = EngineConfig.resolve()
    assert cfg.thought_action_evaluation is True
    assert cfg.evaluation_seats is not None
    # three-tier's own surface stays exactly as it is when unarmed.
    assert cfg.three_tier is False
    assert cfg.worker is None


def test_arming_three_tier_does_not_arm_the_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    with _serving(SEATED_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")
        cfg = EngineConfig.resolve()
    assert cfg.three_tier is True
    assert cfg.worker is not None
    assert cfg.thought_action_evaluation is False
    assert cfg.evaluation_seats is None
    assert cfg.evaluator_checkpoint is None


def test_arming_both_modes_refuses_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two execution modes cannot both own the acting seat — an operator who
    arms both gets a naming refusal, never a silent precedence winner."""
    with _serving(SEATED_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")
        monkeypatch.setenv("COLLEAGUE_THOUGHT_ACTION_EVALUATION", "1")
        with pytest.raises(CliError) as exc_info:
            EngineConfig.resolve()
    message = exc_info.value.message.lower()
    assert "three_tier" in message
    assert "thought_action_evaluation" in message


# ---------------------------------------------------------------------------
# Arming precedence: env > config.json (bool or object) > default-OFF.
# ---------------------------------------------------------------------------


def test_env_arms_the_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    with _serving(SEATED_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_THOUGHT_ACTION_EVALUATION", "1")
        cfg = EngineConfig.resolve()
    assert cfg.thought_action_evaluation is True


def test_config_json_bool_arms_the_mode(tmp_path: Path) -> None:
    with _serving(SEATED_PAYLOAD) as gateway:
        _write_config(tmp_path, {"lobes": gateway, "thought_action_evaluation": True})
        cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.thought_action_evaluation is True
    assert cfg.evaluation_seats is not None


def test_config_json_object_presence_arms_the_mode(tmp_path: Path) -> None:
    """A bare ``{}`` object — no explicit ``enabled`` key — is itself armed
    (the ``lobes``/``three_tier`` bare-string-or-object tolerance)."""
    with _serving(SEATED_PAYLOAD) as gateway:
        _write_config(tmp_path, {"lobes": gateway, "thought_action_evaluation": {}})
        cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.thought_action_evaluation is True


def test_config_json_object_enabled_false_does_not_arm(tmp_path: Path) -> None:
    with _serving(SEATED_PAYLOAD) as gateway:
        _write_config(
            tmp_path,
            {"lobes": gateway, "thought_action_evaluation": {"enabled": False}},
        )
        cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.thought_action_evaluation is False


def test_config_json_object_enabled_string_false_does_not_arm(tmp_path: Path) -> None:
    """The Qodo #367 regression class: ``bool("false")`` is True, so the RAW
    value must survive to ``_parse_bool``."""
    from colleague.config import _load_thought_action_evaluation_override, _parse_bool

    _write_config(tmp_path, {"thought_action_evaluation": {"enabled": "false"}})
    raw = _load_thought_action_evaluation_override(tmp_path)
    assert raw is not None
    assert _parse_bool(raw) is False


def test_env_wins_over_config_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    with _serving(SEATED_PAYLOAD) as gateway:
        _write_config(tmp_path, {"lobes": gateway, "thought_action_evaluation": True})
        monkeypatch.setenv("COLLEAGUE_THOUGHT_ACTION_EVALUATION", "0")
        cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.thought_action_evaluation is False


def test_user_level_config_json_arms_via_the_per_key_merge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The at-home global per-key merge (#339): a machine-wide
    ``~/.colleague/config.json`` arms the mode even when the repo-level file
    exists but never mentions the key."""
    user_home = tmp_path / "home"
    (user_home / ".colleague").mkdir(parents=True)
    repo = tmp_path / "repo"
    repo.mkdir()
    with _serving(SEATED_PAYLOAD) as gateway:
        (user_home / ".colleague" / "config.json").write_text(
            json.dumps({"lobes": gateway, "thought_action_evaluation": True}),
            encoding="utf-8",
        )
        _write_config(repo, {"model": "repo-level-pin"})
        monkeypatch.setenv("COLLEAGUE_HOME", str(user_home))
        cfg = EngineConfig.resolve(repo_path=repo)
    assert cfg.thought_action_evaluation is True
    assert cfg.evaluation_seats is not None


# ---------------------------------------------------------------------------
# Acceptance criterion 2: seats resolve BY ROLE NAME; a missing required role
# refuses to arm with a legible reason — never model-name parsing, never a
# silent fallback.
# ---------------------------------------------------------------------------


def test_armed_resolves_every_seat_by_role_name(monkeypatch: pytest.MonkeyPatch) -> None:
    with _serving(SEATED_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_THOUGHT_ACTION_EVALUATION", "1")
        cfg = EngineConfig.resolve()
    seats = cfg.evaluation_seats
    assert isinstance(seats, EvaluationSeats)
    assert isinstance(seats.front, SeatConfig)
    # front <- senses, worker <- worker, evaluator <- cortex.
    assert seats.front.model == _SENSES_MODEL
    assert seats.worker.model == _WORKER_MODEL
    assert seats.evaluator.model == _CORTEX_MODEL
    assert seats.front.context == _SENSES_WINDOW
    assert seats.worker.context == _WORKER_WINDOW
    assert seats.evaluator.context == _CORTEX_WINDOW
    dial = _ROLE_ENDPOINT.rstrip("/") + "/v1"
    assert (seats.front.base_url, seats.worker.base_url, seats.evaluator.base_url) == (
        dial,
        dial,
        dial,
    )


def test_seat_mapping_is_role_name_only_never_model_name_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Swap every advertised model id for a deliberately misleading one (the
    'evaluator-looking' id sits on the worker role, and vice versa). Resolution
    must follow the ROLE NAME regardless — spec c40: the reference rig's model
    names are a CANDIDATE, never an architectural requirement."""
    payload = {
        "cortex": _cortex_role(model="looks-like-a-worker-35b"),
        "senses": _senses_role(model="looks-like-an-evaluator-27b"),
        "worker": _worker_role(model="looks-like-a-front-12b"),
    }
    with _serving(payload) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_THOUGHT_ACTION_EVALUATION", "1")
        cfg = EngineConfig.resolve()
    seats = cfg.evaluation_seats
    assert seats is not None
    assert seats.front.model == "looks-like-an-evaluator-27b"  # the senses ROLE
    assert seats.worker.model == "looks-like-a-front-12b"  # the worker ROLE
    assert seats.evaluator.model == "looks-like-a-worker-35b"  # the cortex ROLE


def test_armed_without_a_lobes_gateway_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_THOUGHT_ACTION_EVALUATION", "1")
    with pytest.raises(CliError) as exc_info:
        EngineConfig.resolve()
    message = exc_info.value.message.lower()
    assert "thought_action_evaluation" in message
    assert "lobes" in message
    assert "front" in message
    assert "worker" in message
    assert "evaluator" in message


def test_armed_with_an_unreachable_gateway_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_THOUGHT_ACTION_EVALUATION", "1")
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://127.0.0.1:1")
    with pytest.raises(CliError) as exc_info:
        EngineConfig.resolve()
    message = exc_info.value.message.lower()
    assert "thought_action_evaluation" in message
    assert "unreachable" in message


def test_armed_without_a_worker_role_refuses_naming_the_seat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _serving(BASE_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_THOUGHT_ACTION_EVALUATION", "1")
        with pytest.raises(CliError) as exc_info:
            EngineConfig.resolve()
    message = exc_info.value.message.lower()
    assert "no ready worker role" in message
    assert "worker seat" in message


def test_armed_with_a_not_ready_worker_role_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {**BASE_PAYLOAD, "worker": _worker_role(ready=False)}
    with _serving(payload) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_THOUGHT_ACTION_EVALUATION", "1")
        with pytest.raises(CliError) as exc_info:
            EngineConfig.resolve()
    assert "no ready worker role" in exc_info.value.message.lower()


def test_armed_with_a_not_ready_senses_role_refuses_naming_the_front_seat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "cortex": _cortex_role(),
        "senses": _senses_role(ready=False),
        "worker": _worker_role(),
    }
    with _serving(payload) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_THOUGHT_ACTION_EVALUATION", "1")
        with pytest.raises(CliError) as exc_info:
            EngineConfig.resolve()
    message = exc_info.value.message.lower()
    assert "no ready senses role" in message
    assert "front seat" in message


def test_armed_with_a_not_ready_cortex_role_refuses_naming_the_evaluator_seat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "cortex": _cortex_role(ready=False),
        "senses": _senses_role(),
        "worker": _worker_role(),
    }
    with _serving(payload) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_THOUGHT_ACTION_EVALUATION", "1")
        with pytest.raises(CliError) as exc_info:
            EngineConfig.resolve()
    message = exc_info.value.message.lower()
    assert "no ready cortex role" in message
    assert "evaluator seat" in message


def test_armed_with_a_malformed_worker_role_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    broken = dict(_worker_role())
    del broken["context"]
    payload = {**BASE_PAYLOAD, "worker": broken}
    with _serving(payload) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_THOUGHT_ACTION_EVALUATION", "1")
        with pytest.raises(CliError):
            EngineConfig.resolve()


def test_the_refusal_names_the_disarm_remediation(monkeypatch: pytest.MonkeyPatch) -> None:
    with _serving(BASE_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_THOUGHT_ACTION_EVALUATION", "1")
        with pytest.raises(CliError) as exc_info:
            EngineConfig.resolve()
    assert "thought_action_evaluation" in (exc_info.value.remediation or "").lower()


# ---------------------------------------------------------------------------
# Same-origin api_key hygiene (colleague#347/#348), per seat.
# ---------------------------------------------------------------------------


def test_same_origin_seats_inherit_the_main_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    with _serving(SEATED_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_THOUGHT_ACTION_EVALUATION", "1")
        monkeypatch.setenv("COLLEAGUE_API_KEY", "main-secret-token")
        cfg = EngineConfig.resolve()
    seats = cfg.evaluation_seats
    assert seats is not None
    assert seats.front.api_key == "main-secret-token"
    assert seats.worker.api_key == "main-secret-token"
    assert seats.evaluator.api_key == "main-secret-token"


def test_cross_origin_seat_does_not_inherit_the_main_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {**BASE_PAYLOAD, "worker": _worker_role(endpoint="http://other-host:9000")}
    with _serving(payload) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_THOUGHT_ACTION_EVALUATION", "1")
        monkeypatch.setenv("COLLEAGUE_API_KEY", "main-secret-token")
        cfg = EngineConfig.resolve()
    seats = cfg.evaluation_seats
    assert seats is not None
    assert seats.worker.base_url == "http://other-host:9000/v1"
    assert seats.worker.api_key == _DEFAULT_API_KEY
    assert seats.worker.api_key != "main-secret-token"


def test_explicit_seat_api_key_env_wins_even_cross_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {**BASE_PAYLOAD, "worker": _worker_role(endpoint="http://other-host:9000")}
    with _serving(payload) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_THOUGHT_ACTION_EVALUATION", "1")
        monkeypatch.setenv("COLLEAGUE_API_KEY", "main-secret-token")
        monkeypatch.setenv("COLLEAGUE_WORKER_API_KEY", "worker-own-token")
        monkeypatch.setenv("COLLEAGUE_EVALUATOR_API_KEY", "evaluator-own-token")
        monkeypatch.setenv("COLLEAGUE_FRONT_API_KEY", "front-own-token")
        cfg = EngineConfig.resolve()
    seats = cfg.evaluation_seats
    assert seats is not None
    assert seats.worker.api_key == "worker-own-token"
    assert seats.evaluator.api_key == "evaluator-own-token"
    assert seats.front.api_key == "front-own-token"


def test_config_json_seat_sections_supply_api_keys(tmp_path: Path) -> None:
    """Each seat's config.json section recognises ``api_key`` ONLY — there is
    no declared seat *model* anywhere (role NAMES only)."""
    with _serving(SEATED_PAYLOAD) as gateway:
        _write_config(
            tmp_path,
            {
                "lobes": gateway,
                "thought_action_evaluation": True,
                "front": {"api_key": "file-front-token", "model": "ignored-entirely"},
                "evaluator": {"api_key": "file-evaluator-token"},
            },
        )
        cfg = EngineConfig.resolve(repo_path=tmp_path)
    seats = cfg.evaluation_seats
    assert seats is not None
    assert seats.front.api_key == "file-front-token"
    assert seats.evaluator.api_key == "file-evaluator-token"
    # the ignored "model" key never becomes a seat model
    assert seats.front.model == _SENSES_MODEL


# ---------------------------------------------------------------------------
# Acceptance criterion 3: deepthink stays absent in this mode (as in three-tier).
# ---------------------------------------------------------------------------


def test_armed_with_a_muse_advert_constructs_no_deepthink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _serving(SEATED_MUSE_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_THOUGHT_ACTION_EVALUATION", "1")
        cfg = EngineConfig.resolve()
    assert cfg.thought_action_evaluation is True
    assert cfg.deepthink is None


def test_armed_with_a_declared_deepthink_env_constructs_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _serving(SEATED_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_THOUGHT_ACTION_EVALUATION", "1")
        monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MODEL", "declared-deepthink-model")
        cfg = EngineConfig.resolve()
    assert cfg.deepthink is None


def test_armed_with_a_declared_deepthink_config_json_constructs_none(tmp_path: Path) -> None:
    with _serving(SEATED_PAYLOAD) as gateway:
        _write_config(
            tmp_path,
            {
                "lobes": gateway,
                "thought_action_evaluation": True,
                "deepthink": {"model": "declared-deepthink-model"},
            },
        )
        cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.deepthink is None


def test_not_armed_muse_advert_still_resolves_deepthink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Byte-identical control: WITHOUT the mode armed the same muse advert
    still resolves a DeepthinkConfig exactly as the two-machines-two-minds
    rung already does."""
    with _serving(SEATED_MUSE_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MODEL", "lobes")  # discovery opt-in
        cfg = EngineConfig.resolve()
    assert cfg.deepthink is not None
    assert cfg.deepthink.model == _MUSE_MODEL


# ---------------------------------------------------------------------------
# The authority-separation seam (spec c38/h30): arming populates
# ``evaluator_checkpoint``; a distinct ``distiller_checkpoint`` is declarable.
# ---------------------------------------------------------------------------


def test_armed_populates_the_evaluator_checkpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    with _serving(SEATED_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_THOUGHT_ACTION_EVALUATION", "1")
        cfg = EngineConfig.resolve()
    assert cfg.evaluator_checkpoint == _CORTEX_MODEL
    assert cfg.evaluation_seats is not None
    assert cfg.evaluator_checkpoint == cfg.evaluation_seats.evaluator.model


def test_armed_evaluator_checkpoint_collides_with_the_distill_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The PRECONDITION t4's guard exists for: in the armed mode the lobes
    cortex role serves the evaluator seat AND is what distill.py's author
    resolution would otherwise pick. Without a declared distiller the evaluator
    would silently gain memory-write authority — hence the guard, hence this pin.

    UPDATED BY PLAN TASK t13. t12 pinned the collision through ``config.model``,
    which was then still the cortex id because t12 deliberately did not repoint
    the acting dial. t13 repoints it: with the mode armed, ``config.model`` is
    the WORKER seat (``colleague/config.py``'s ``elif resolved_seats is not
    None`` branch, mirroring three-tier's t8 worker-as-actor override), because
    the worker acts and the evaluator does not.

    The collision the guard exists for is UNCHANGED and still live — it simply
    lives where it always really lived: ``distill.resolve_distill_author``'s
    rung 2 reads ``lobes_roles.cortex`` DIRECTLY, and the cortex role is the
    evaluator seat. So the guard must key on ``evaluator_checkpoint``, never on
    ``config.model`` — which is exactly what the two guard tests below already
    assert (``guard(cfg, cfg.evaluator_checkpoint)``)."""
    with _serving(SEATED_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_THOUGHT_ACTION_EVALUATION", "1")
        cfg = EngineConfig.resolve()
        roles = lobes.resolve_roles(gateway)
    assert cfg.lobes_gateway_url is not None
    # The acting dial is the WORKER (t13) — the evaluator never acts.
    assert cfg.model == _WORKER_MODEL
    assert cfg.evaluator_checkpoint == _CORTEX_MODEL
    # The collision is real: the candidate rung 2 would otherwise pick — the
    # cortex role read DIRECTLY off lobes — IS the evaluator checkpoint.
    assert roles is not None
    assert roles.cortex.model == cfg.evaluator_checkpoint
    # ...and because it is, the guard refuses outright: no author, so the run
    # falls honestly to the rung-1 floor rather than letting the evaluator
    # seat write durable memory (spec c38/h30).
    assert distill.resolve_distill_author(cfg, roles) is None


def test_declared_distiller_checkpoint_env(monkeypatch: pytest.MonkeyPatch) -> None:
    with _serving(SEATED_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_THOUGHT_ACTION_EVALUATION", "1")
        monkeypatch.setenv("COLLEAGUE_DISTILLER_MODEL", "a-distinct-distiller")
        cfg = EngineConfig.resolve()
    assert cfg.evaluator_checkpoint == _CORTEX_MODEL
    assert cfg.distiller_checkpoint == "a-distinct-distiller"


def test_declared_distiller_checkpoint_config_json_object(tmp_path: Path) -> None:
    with _serving(SEATED_PAYLOAD) as gateway:
        _write_config(
            tmp_path,
            {
                "lobes": gateway,
                "thought_action_evaluation": True,
                "distiller": {"model": "a-distinct-distiller"},
            },
        )
        cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.distiller_checkpoint == "a-distinct-distiller"


def test_declared_distiller_checkpoint_config_json_bare_string(tmp_path: Path) -> None:
    with _serving(SEATED_PAYLOAD) as gateway:
        _write_config(
            tmp_path,
            {
                "lobes": gateway,
                "thought_action_evaluation": True,
                "distiller": "a-distinct-distiller",
            },
        )
        cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.distiller_checkpoint == "a-distinct-distiller"


def test_distiller_env_wins_over_config_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with _serving(SEATED_PAYLOAD) as gateway:
        _write_config(
            tmp_path,
            {
                "lobes": gateway,
                "thought_action_evaluation": True,
                "distiller": {"model": "from-file"},
            },
        )
        monkeypatch.setenv("COLLEAGUE_DISTILLER_MODEL", "from-env")
        cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.distiller_checkpoint == "from-env"


def test_distill_guard_refuses_the_evaluator_as_distiller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live integration with ``colleague/distill.py``'s authority-separation
    guard (task t4, spec c38/h30). Skips until t4 merges — the guard reads
    ``evaluator_checkpoint``/``distiller_checkpoint`` via ``getattr``, and THIS
    task is what populates them."""
    from colleague import distill

    guard = getattr(distill, "_refuses_evaluator_as_distiller", None)
    if guard is None:
        pytest.skip(
            "distill._refuses_evaluator_as_distiller (plan task t4) is not on this "
            "branch yet; the arming fields it reads are pinned by the tests above"
        )
    with _serving(SEATED_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_THOUGHT_ACTION_EVALUATION", "1")
        cfg = EngineConfig.resolve()
    assert guard(cfg, cfg.evaluator_checkpoint) is True
    assert distill.resolve_distill_author_from_config(cfg) is None


def test_distill_guard_lifts_with_a_declared_distinct_distiller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from colleague import distill

    guard = getattr(distill, "_refuses_evaluator_as_distiller", None)
    if guard is None:
        pytest.skip("distill._refuses_evaluator_as_distiller (plan task t4) not merged yet")
    with _serving(SEATED_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_THOUGHT_ACTION_EVALUATION", "1")
        monkeypatch.setenv("COLLEAGUE_DISTILLER_MODEL", "a-distinct-distiller")
        cfg = EngineConfig.resolve()
    assert guard(cfg, cfg.evaluator_checkpoint) is False


def test_unarmed_leaves_the_distill_guard_inert(monkeypatch: pytest.MonkeyPatch) -> None:
    """Byte-identical: with the mode unarmed there is no evaluator checkpoint,
    so the guard cannot fire and distillation resolves exactly as today."""
    from colleague import distill

    with _serving(SEATED_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        cfg = EngineConfig.resolve()
    assert cfg.evaluator_checkpoint is None
    author = distill.resolve_distill_author_from_config(cfg)
    assert author is not None
    assert author.model == _CORTEX_MODEL


# ---------------------------------------------------------------------------
# to_dict(): armed shape, api_key redaction preserved.
# ---------------------------------------------------------------------------


def test_to_dict_when_armed_carries_seats_and_redacts_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _serving(SEATED_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_THOUGHT_ACTION_EVALUATION", "1")
        monkeypatch.setenv("COLLEAGUE_API_KEY", "sk-evaluation-secret")
        monkeypatch.setenv("COLLEAGUE_DISTILLER_MODEL", "a-distinct-distiller")
        snapshot = EngineConfig.resolve().to_dict()
    dial = _ROLE_ENDPOINT.rstrip("/") + "/v1"
    assert snapshot["thought_action_evaluation"] is True
    assert snapshot["evaluation_seats"] == {
        "front": {"model": _SENSES_MODEL, "base_url": dial, "context": _SENSES_WINDOW},
        "worker": {"model": _WORKER_MODEL, "base_url": dial, "context": _WORKER_WINDOW},
        "evaluator": {"model": _CORTEX_MODEL, "base_url": dial, "context": _CORTEX_WINDOW},
    }
    assert snapshot["evaluator_checkpoint"] == _CORTEX_MODEL
    assert snapshot["distiller_checkpoint"] == "a-distinct-distiller"
    assert "sk-evaluation-secret" not in str(snapshot)
