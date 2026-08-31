"""The artifact snapshot of a resolved :class:`colleague.config.EngineConfig`.

``EngineConfig.to_dict`` is the config as it lands in the run artifact: the
always-present scalar knobs plus the omit-when-unarmed sub-dicts, with every
``api_key`` simply absent rather than masked. Split out of ``config.py`` (hard
1000-line file limit, plan ``hard-1000-line-file-limit`` t14) — a pure move;
the method now delegates here, so the emitted key set is byte-identical.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from colleague.config import EngineConfig


def config_to_dict(config: "EngineConfig") -> "dict[str, object]":
    """Config snapshot for the result artifact, with the api_key redacted."""
    data: dict[str, object] = {
        "base_url": config.base_url,
        "model": config.model,
        "max_steps": config.max_steps,
        "temperature": config.temperature,
        "timeout": config.timeout,
        "context_budget_tokens": config.context_budget_tokens,
        "autosplit_target_tokens": config.autosplit_target_tokens,
        "fillline_threshold": config.fillline_threshold,
        "fanout_files": config.fanout_files,
        "review_fanout_folders": config.review_fanout_folders,
        "plan_offer_tokens": config.plan_offer_tokens,
        "max_continue_nudges": config.max_continue_nudges,
        "synthesis_reserve_steps": config.synthesis_reserve_steps,
        "max_output_chars": config.max_output_chars,
        "subagent_depth": config.subagent_depth,
        "subagent_total": config.subagent_total,
        "lint": config.lint,
        "coherence": config.coherence,
        "memory": config.memory,
        "lint_fix_retries": config.lint_fix_retries,
        "testintegrity": config.testintegrity,
        "testintegrity_fix_retries": config.testintegrity_fix_retries,
        "testintegrity_reviewer_model": config.testintegrity_reviewer_model,
        "affected_tests": config.affected_tests,
        "affected_tests_fix_retries": config.affected_tests_fix_retries,
        "affected_tests_depth": config.affected_tests_depth,
        "affected_tests_max_files": config.affected_tests_max_files,
        "compaction_cap": config.compaction_cap,
        "three_tier": config.three_tier,
        # Per-seat thinking-effort ladder (#416 t2): always present (never
        # None/{} omitted) so the snapshot is identical on mock/vllm-openai.
        "reasoning_effort": config.reasoning_effort,
        "reasoning_effort_seats": config.reasoning_effort_seats,
        "reasoning_effort_purposes": config.reasoning_effort_purposes,
        "too_long_min": config.too_long_min,
    }
    # Model-bound agents (#411 t7): present ONLY when armed, so an unarmed
    # snapshot is byte-identical (omit-when-unarmed, the TAE convention).
    if config.agents:
        data["agents"] = True
    # hire (t4): present ONLY when armed; the add-set ONLY when non-empty —
    # the artifact snapshot attests both knobs, byte-identical when unset.
    if config.hire:
        data["hire"] = True
    if config.acting_add_tools:
        data["acting_add_tools"] = list(config.acting_add_tools)
    # Dual-model deepthink (t1): present ONLY when configured, so a
    # single-model snapshot is byte-identical to today (omit-when-None,
    # the destination/lint_report/capacity_decision convention). The
    # deepthink api_key is redacted exactly like the main api_key above —
    # simply absent from the sub-dict, never included.
    if config.deepthink is not None:
        data["deepthink"] = {
            "model": config.deepthink.model,
            "base_url": config.deepthink.base_url,
            "context_budget": config.deepthink.context_budget,
        }
    # Senses (multimodal front-door, cortex/senses arc task t3): present
    # ONLY when configured, so an unconfigured snapshot is byte-identical
    # to today (omit-when-None, same convention as deepthink above). The
    # senses api_key is likewise simply absent from the sub-dict, never
    # included.
    if config.senses is not None:
        data["senses"] = {
            "model": config.senses.model,
            "base_url": config.senses.base_url,
            "context_budget": config.senses.context_budget,
        }
    # Voice (stt/tts, senses live-presence + voice arc): present ONLY when
    # configured (omit-when-None, same convention as senses/deepthink above).
    # The voice api_key is absent from the sub-dict, never included.
    if config.voice is not None:
        data["voice"] = {
            "stt_model": config.voice.stt_model,
            "tts_model": config.voice.tts_model,
            "stt_base_url": config.voice.stt_base_url,
            "tts_base_url": config.voice.tts_base_url,
        }
    # Realtime (server-VAD live speech session, realtime-speech arc):
    # present ONLY when configured (omit-when-None, same convention as
    # voice/senses/deepthink above). The realtime api_key is absent from
    # the sub-dict, never included.
    if config.realtime is not None:
        data["realtime"] = {
            "available": config.realtime.available,
            "ws_url": config.realtime.ws_url,
        }
    # Worker (three-tier bounded-tool-loop actor, three-tier-execution
    # arc): present ONLY when three-tier resolved a worker (omit-when-None,
    # same convention as deepthink/senses/voice/realtime above). The
    # worker api_key is absent from the sub-dict, never included.
    if config.worker is not None:
        data["worker"] = {
            "model": config.worker.model,
            "base_url": config.worker.base_url,
            "context": config.worker.context,
        }
    # Thought→action→evaluation mode (plan task t12): omit-when-UNARMED —
    # deliberately NOT the always-present key ``three_tier`` is, so an
    # unarmed snapshot's key set is byte-identical to the pre-mode one
    # (honesty h19; pinned by tests/test_config_evaluation_mode.py and the
    # landed key-set pins in test_config_subagent.py / test_config_senses.py).
    # Every seat's api_key is simply absent from its sub-dict, never
    # included — the same redaction convention as worker/senses/deepthink.
    if config.thought_action_evaluation:
        data["thought_action_evaluation"] = True
    if config.evaluation_seats is not None:
        data["evaluation_seats"] = {
            seat: {
                "model": dial.model,
                "base_url": dial.base_url,
                "context": dial.context,
            }
            for seat, dial in (
                ("front", config.evaluation_seats.front),
                ("worker", config.evaluation_seats.worker),
                ("evaluator", config.evaluation_seats.evaluator),
            )
        }
    # Checkpoint IDS, never credentials — safe to surface, and the operator
    # needs to see which authority each contract resolved to (spec c38/h30).
    if config.evaluator_checkpoint is not None:
        data["evaluator_checkpoint"] = config.evaluator_checkpoint
    if config.distiller_checkpoint is not None:
        data["distiller_checkpoint"] = config.distiller_checkpoint
    return data
