# Resident promotion — colleague joins Culture persistently

`colleague promote` graduates colleague from a **born-and-trained task runner**
into a **resident** member of the Culture mesh: the same colleague that drives
bounded `colleague work` items is elevated *in place* into a persistent peer that
owns a channel and answers messages over a long-lived session. It is a lifecycle
transition (born → trained → resident), not a fresh build.

Spec + plan (authored via `/think` → `/spec-to-plan`):
[`docs/specs/2026-06-10-colleague-graduates-from-a-born-and-trained-task-r.md`](../specs/2026-06-10-colleague-graduates-from-a-born-and-trained-task-r.md)
and
[`docs/plans/2026-06-12-colleague-graduates-from-a-born-and-trained-task-r.md`](../plans/2026-06-12-colleague-graduates-from-a-born-and-trained-task-r.md).

## How it works

The resident is built on **agent-lifecycle**'s asyncio runtime seam and the
**agentirc-cli** wire — both opt-in, behind the `[culture]` extra:

- **Harness** (`colleague/resident/harness.py`) — `ColleagueHarness` adapts
  colleague's bounded tool-loop (`Engine.work`) onto agent-lifecycle's
  `Harness` Protocol (`start`/`feed_message`/`replies`/`stop`). Each inbound
  message is one bounded turn (no git handoff — the resident converses, it does
  not open PRs). The session outlives any single turn, so a step-cap-exhausted
  turn never ends the resident's presence.
- **Transport** (`colleague/resident/transport.py`) — `IRCTransportAdapter`
  wraps an IRC connection behind agent-lifecycle's `Transport` + `Presence`
  Protocols. The concrete wire (`colleague/resident/connection.py`,
  `IRCConnection` over `asyncio.open_connection`) is colleague-owned, citing
  cultureagent's `IRCTransportAdapter` as the reference pattern (cite-don't-import).
- **Supervisor** (`colleague/resident/supervisor.py`) — agent-lifecycle's
  in-process `Supervisor` bridges transport ↔ harness (inbound
  `receive`→`feed_message`; outbound `replies`→`send`). `serve_resident` owns the
  `asyncio.run` so the CLI layer stays async-free.
- **Identity** (`colleague/resident/identity_mint.py`) — mints `culture.yaml`
  (`suffix` + `backend=colleague` + `model`) + a prompt, reusing colleague's own
  `colleague/identity.py` resolution (no new identity source).
- **Channels** (`colleague/resident/channels.py`) — queries the Culture
  roster/steward, ranks candidates, owns `#<nick>` by default.
- **Registration** (`colleague/resident/register.py`) — writes the minted
  identity where the steward discovers it and signals arrival, through the one
  sanctioned subprocess consumer (`colleague/resident/steward.py`).

## Install the `[culture]` extra

The resident deps (`agent-lifecycle` + `agentirc-cli`) ship only in the opt-in
`[culture]` extra, **which requires Python >=3.12**:

```bash
# Installed CLI (global tool):
uv tool install --python 3.12 'colleague[culture]'   # the --python is load-bearing
pip install 'colleague[culture]'                      # pip equivalent (on a >=3.12 interpreter)

# In a checkout (editable / dev):
uv sync --extra culture
```

The `--python 3.12` matters: `uv tool install 'colleague[culture]'` with no
`--python` defaults to whatever interpreter uv has on hand, which may be <3.12.
When it is, resolution fails with
`the current Python version (…) does not satisfy Python>=3.12` — that is the
interpreter, not the extra.

## Usage

```bash
colleague promote --repo .                     # mint + register, report (no network)
colleague promote --repo . --json              # machine-readable report
colleague promote --repo . --suffix spark-colleague
colleague promote --repo . --force             # overwrite an existing differing culture.yaml
colleague promote --repo . --serve --irc-host localhost --irc-port 6667  # go live
```

Without `--serve`, `promote` prepares and reports (idempotent) — the
consequential network step is explicit.

Promoting inside a repo that already declares a *different* `culture.yaml` (e.g.
colleague's own checkout, which ships a `backend: claude` agent) is a recoverable
conflict, not a bug: `promote` stops with an actionable message — re-run with
`--force` to overwrite it, or pass `--suffix`/`--repo` to mint under a separate
identity.

## Honest limits

- **Opt-in dependency, not a base dep.** `agent-lifecycle` + `agentirc-cli` ship
  only in the `[culture]` extra; the base install stays `dependencies = []`. The
  resident's import-clean core (`__init__`, `steward`) pulls nothing third-party;
  only the async seam adapters import the extra, lazily. Running `promote`
  without the extra fails cleanly with an install hint.
- **Separate process, never on the work path.** The resident is a separate,
  explicitly-opted-in long-lived process. The bounded `colleague work` path is
  byte-identical and async-free; a bare work item never starts the resident
  (guarded by `tests/test_resident_no_work_path.py`). `colleague/resident/` is
  the *sanctioned* async/networked exception in the boundary guard
  (`tests/test_boundary.py`): `asyncio` is permitted there only; `socket` stays
  forbidden everywhere (agentirc-cli owns the wire); `subprocess` is confined to
  `resident/steward.py`.
- **Operator-gated.** Promotion is operator-initiated and idempotent; it is not
  auto-registration of arbitrary agents — one agent (this colleague) is promoted.
- **The live mesh proof is manual.** The runtime seam (Harness/Transport/
  Supervisor) and the pure wire helpers are unit-tested against fakes; the actual
  IRC network handshake (`--serve`) is exercised by hand against a running mesh —
  there is no IRC server in the automated suite.
- **Cross-repo follow-up.** colleague writes its own thin IRC adapter over
  `agentirc-cli` rather than depending on `cultureagent[backend-claude]` (which
  would drag in `claude-agent-sdk`). [cultureagent#40](https://github.com/agentculture/cultureagent/issues/40)
  tracks exposing a light, backend-agnostic cultureagent core so the proven
  adapter could be cited/depended-on directly later.
