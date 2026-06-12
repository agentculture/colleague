"""Opt-in tool-calling round-trip probe (``colleague doctor --probe``).

Like :mod:`colleague.oilcheck.reachability`, this is a **deliberate exception** to
the oilcheck check-group rule that groups open no socket. It is NOT registered in
:data:`colleague.oilcheck.CHECK_GROUPS`; :func:`colleague.oilcheck.diagnose`
invokes it only when ``probe=True``, so the default diagnosis stays no-network.

Why it exists (issue #182): ``provider_reachable`` only confirms the server
answers ``GET /v1/models`` — it can be fully green while the server *crashes* on
the tool-calling requests Colleague actually sends (e.g. a vLLM ``EngineCore``
500 on a build that can't handle tools + speculative-decoding/FP4). A caller of
``ask-colleague`` should never have to discover that by hand-curling the model.
This check POSTs ONE minimal ``tools`` + ``tool_choice`` request and classifies:

``tool_calling`` (info | warning | error)
    * **WORKS** — the server **emitted a ``tool_call``** for the probe's
      tool-demanding prompt (``info``/passed). The probe reads the response and
      verifies the tool call; a 2xx alone is not enough (#184).
    * **ACCEPTED-BUT-IGNORED** — a 2xx with no ``tool_call`` (``warning``): the
      server took the tools payload but didn't act on it (tool calling unsupported/
      ignored, or the model declined). Visible, not a silent green.
    * **TIMED-OUT** — the tool-calling POST hung past the probe timeout
      (``warning``): the server is reachable but stalled on the tool path (#184).
    * **TOOL-CALLS-UNSUPPORTED** — an HTTP 400 / tool-parser rejection
      (``error``): start vLLM with ``--enable-auto-tool-choice`` + a
      ``--tool-call-parser``.
    * **SERVER-CRASHED** — an HTTP 500 whose body names ``EngineCore`` /
      ``InternalServerError`` (``error``): the server crashed on a tool-calling
      request; this build cannot serve Colleague.

These two failures are ``error`` (not the advisory ``warning`` that
``reachability`` uses for "server down") on purpose: a server that can't serve a
tool-calling request is a *hard* incompatibility — Colleague cannot work against
it — so ``doctor --probe`` should go unhealthy (exit 1) and say so, which is the
"it was green and then crashed" gap from #182.

**Honest limit:** the probe sends a *minimal* request to keep its blast radius
small (it pokes the same path that can crash a fragile engine — risk r1). The
#182 crash is prompt-size-dependent — the server handled small tool calls and
crashed only on the large diff-bearing turn — so a size-dependent crash can
*pass* this minimal probe and surface later at work time. That residual case is
caught by the engine's legible-error mapping (a 500/``EngineCore`` becomes an
actionable message), not here. WORKS therefore means "tool calling is wired up,"
not "every request will succeed."

Stdlib ``urllib`` only (the surface the vLLM driver speaks) — no third-party dep,
no raw ``socket`` import; never raises (any unexpected error becomes a failed
``warning`` check).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from colleague.config import EngineConfig
from colleague.oilcheck import make_check

_PROBE_TIMEOUT = 10.0

# A deliberately tiny tools request: one no-op tool + a one-line message. Minimal
# blast radius (see the honest-limit note in the module docstring) while still
# exercising the server's tool-calling / guided-decoding path.
_PROBE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "ping",
            "description": "A no-op probe tool.",
            "parameters": {"type": "object", "properties": {}},
        },
    }
]
# The prompt DEMANDS the tool so a working server emits a tool_call we can verify
# (#184): with a non-demanding prompt a server that ignores tools returns plain
# text and the probe can't tell. max_tokens is generous enough for a reasoning
# model to think *and* emit the call (16 was too small) while staying minimal.
_PROBE_MESSAGES = [{"role": "user", "content": "Call the ping tool now."}]
_PROBE_MAX_TOKENS = 128


def checks(repo_path=None) -> list[dict]:
    """Return the tool-calling round-trip check (see module docstring).

    Never raises: any unexpected error becomes a single failed ``warning`` check,
    matching the reachability group's safety net.
    """
    try:
        return _checks(repo_path)
    except Exception as exc:  # pragma: no cover - safety net; normal paths classify below
        return [
            make_check(
                "tool_calling",
                False,
                "warning",
                f"tool-calling probe failed unexpectedly: {exc}",
                remediation="re-run 'colleague doctor --probe'; check COLLEAGUE_BASE_URL",
            )
        ]


def _checks(repo_path) -> list[dict]:
    config = EngineConfig.resolve(repo_path=repo_path)
    url = config.base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": config.model,
        "messages": _PROBE_MESSAGES,
        "tools": _PROBE_TOOLS,
        "tool_choice": "auto",
        "max_tokens": _PROBE_MAX_TOKENS,
        "temperature": 0.0,
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api_key}",
        },
    )
    try:
        with urllib.request.urlopen(  # nosec B310 - operator-configured endpoint
            request, timeout=_PROBE_TIMEOUT
        ) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return [_classify_http_error(exc, url)]
    except TimeoutError:
        # A tool-calling POST that HANGS (server alive, `/models` reachable, but the
        # tool path stalls — #182's ~199s churn precursor) is a distinct signal from
        # "server down". TimeoutError is an OSError subclass, so catch it FIRST and
        # report it rather than letting the OSError clause swallow it (#184).
        return [
            make_check(
                "tool_calling",
                False,
                "warning",
                f"tool-calling probe timed out after {_PROBE_TIMEOUT:.0f}s at {url!r}",
                remediation=(
                    "the server is reachable but stalled on a tool-calling request; "
                    "check server load / speculative-decoding, or raise COLLEAGUE_TIMEOUT"
                ),
            )
        ]
    except OSError:
        # Connection refused / unreachable — `provider_reachable` already reports
        # that, so don't double-report it as a tool-calling failure.
        return []
    # 2xx: a working server EMITS a tool_call for the demanding prompt. A 200 with
    # no tool_call means the server accepted but ignored the tools — the false-green
    # this probe exists to catch (#184).
    if _response_has_tool_call(data):
        return [
            make_check(
                "tool_calling",
                True,
                "info",
                f"tool-calling round-trip OK at {url!r} (server emitted a tool_call)",
            )
        ]
    return [
        make_check(
            "tool_calling",
            False,
            "warning",
            f"the server accepted a tools request at {url!r} but returned no tool_call",
            remediation=(
                "tool calling may be unsupported/ignored (or the model declined a "
                "trivial tool) — verify --enable-auto-tool-choice + a --tool-call-parser "
                "and a model that emits tool calls"
            ),
        )
    ]


def _response_has_tool_call(data: object) -> bool:
    """True iff the chat-completion response's first choice carries a ``tool_calls``."""
    if not isinstance(data, dict):
        return False
    # `choices` is always non-empty (the `or [{}]` guarantees it), so index [0] is
    # safe and a guarding `if choices` would be dead code (Sonar S2583).
    choices = data.get("choices") or [{}]
    message = choices[0].get("message", {})
    return bool(isinstance(message, dict) and message.get("tool_calls"))


def _classify_http_error(exc: urllib.error.HTTPError, url: str) -> dict:
    """Map an HTTPError from the probe POST to a contract-shaped check."""
    body = _read_body(exc)
    crash_markers = "EngineCore" in body or "InternalServerError" in body
    if exc.code == 500 and crash_markers:
        return make_check(
            "tool_calling",
            False,
            "error",
            f"the model server crashed (500) on a tool-calling request at {url!r}: "
            f"{_snippet(body)}",
            remediation=(
                "this vLLM build likely cannot handle tools + speculative-decoding/FP4 — "
                "disable MTP/speculative decoding or verify --tool-call-parser; "
                "this server cannot serve Colleague's requests"
            ),
        )
    if exc.code == 400 or _looks_like_tool_parser_error(body):
        return make_check(
            "tool_calling",
            False,
            "error",
            f"the server rejected a tool-calling request ({exc.code}) at {url!r}: "
            f"{_snippet(body)}",
            remediation=(
                "start the server with tool calling enabled (for vLLM: "
                "--enable-auto-tool-choice plus a --tool-call-parser, e.g. hermes or "
                "qwen3_coder)"
            ),
        )
    # Any other HTTP status (401 auth, 404 model, …) is explained by other probe
    # checks; report inconclusive as a warning rather than a false tool-calling error.
    return make_check(
        "tool_calling",
        False,
        "warning",
        f"tool-calling probe inconclusive: HTTP {exc.code} at {url!r}: {_snippet(body)}",
        remediation="resolve the provider/auth/model checks above, then re-run --probe",
    )


def _read_body(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", "replace")
    except Exception:  # nosec B110 - body is advisory; never mask the classification
        return ""


def _snippet(body: str, limit: int = 300) -> str:
    body = body.strip()
    return body if len(body) <= limit else body[:limit] + "…"


def _looks_like_tool_parser_error(body: str) -> bool:
    low = body.lower()
    return "tool" in low and ("parser" in low or "auto" in low or "tool_choice" in low)
