# Session modes — pin or cycle the active session context

> The interactive `colleague session` cockpit carries an **active mode** that
> controls how free-text input is routed to verbs. Five modes cycle in a fixed
> order; the operator cycles with **shift-tab** (live ANSI) or the **`/mode`**
> slash (keyboard-free equivalent). A pinned mode overrides the classifier;
> `auto` is byte-identical to the pre-mode behaviour.

Session modes are **purely additive**: with no mode set the session defaults to
`auto`, which delegates every free-text input to `classify_intent` — the same
behaviour as before modes existed.

## The five modes and cycle order

The canonical definition lives in `colleague/session_modes.py`:

```python
MODES = ("auto", "work", "plan", "explore", "review")
```

The cycle wraps: `review` → `auto`.

| Mode    | Routing behaviour                                                    |
|---------|----------------------------------------------------------------------|
| `auto`  | Delegate to `classify_intent(text)` verbatim (pre-mode behaviour)     |
| `work`  | Pin every free-text input to the `work` verb                         |
| `plan`  | Pin every free-text input to the `plan` verb                         |
| `explore` | Pin to `work` under the `explorer` read-only role                  |
| `review`  | Pin to `work` under the `reviewer` read-only role                   |

## Cycling: shift-tab and `/mode`

### Shift-tab (live ANSI only)

On the dynamic ANSI interactive path, pressing **shift-tab** at the prompt
cycles the mode to the next entry in `MODES`. The sentinel `CYCLE_MODE` is
distinct from any string or `None`, so it is never treated as a submitted line
or a quit token. The session echoes `mode → <new>` into the feed and redraws
the cockpit chrome.

**Shift-tab only works on the live-ANSI interactive path.** Non-TTY callers
(piped, `--json`, agent pipelines) use `/mode` instead.

### `/mode` slash (keyboard-free equivalent)

The `/mode` slash is the keyboard-free equivalent of shift-tab, available on
every render tier:

- **`/mode`** (no argument) — cycle to the next mode (identical to shift-tab)
- **`/mode <name>`** — set the mode explicitly (case-insensitive, e.g. `/mode PLAN`)
- **`/mode <bad>`** — raise `ValueError` with the valid-mode hint
  (`"unknown mode 'bogus'; valid: auto, work, plan, explore, review"`), leaving
  the mode unchanged

The `/mode` command appears in the slash-command catalog (`_SLASH_COMMANDS`)
under the `controls` group with the `interactive` tag.

## Visibility: how the active mode is seen

The active mode is visible across all three render tiers:

- **TAUI JSON** — `CockpitState.mode` serialises as `"mode"` in the JSON mirror
  (`colleague.tui.taui.serialize`), so an agent or pipeline reads the same mode
  value from the machine-readable surface.
- **Markdown** — `render_markdown(state)` includes the mode in the cockpit
  section (`- **mode**: <mode>`), so an agent reading the Markdown tier sees
  the same value.
- **Flat ANSI** — the status line carries the affordance from
  `mode_affordance_line(mode)`, e.g.:
  ```
  mode: [auto] work plan explore review  ·  shift-tab to cycle
  ```
  The active mode is bracketed (`[auto]`), others are plain text.

## Mode-aware routing

When the operator types free text, the session decides the verb via
`route_for(mode, text, classify)`:

- **`auto`** — calls `classify(text)` and returns its result verbatim. This is
  **byte-identical** to the pre-mode behaviour: the same `classify_intent` call,
  the same `→ work:` / `→ plan:` routing log line.
- **`work` / `plan`** — return the mode name without calling `classify`. A
  planning-phrased input in `work` mode runs as work; a plain task in `plan`
  mode routes to plan.
- **`explore` / `review`** — pin the route and dispatch under the `explorer` /
  `reviewer` read-only role (see below).

**A number or template pick is never reclassified.** A bare number selects a
palette entry; an exact name selects a command template. These are always work
regardless of mode — only genuinely free text is routed.

## Read-only explore and review

The `explore` and `review` modes run **in-place** under the `explorer` /
`reviewer` role, which structurally withholds `write_file`, `edit_file`, and
`run_command`. The read-only role provably cannot mutate the tree — no commit,
no branch, no PR.

- **Explore** — the `explorer` role inspects the repo to answer a free-text
  question. The instruction is the request verbatim.
- **Review** — the `reviewer` role critiques the committed `<base>...HEAD` diff.
  The diff is **sourced operator-side** (`handoff.diff_range`) and injected into
  the task text because the read-only reviewer role withholds `run_command` and
  so cannot run `git` itself. The reviewer reads files as needed and produces a
  candid second opinion.

Both run with `open_pr=False` (no push/PR handoff). The role is set on a **copy**
of the config so the session's default writer surface is left untouched.

## Non-goals

Session modes deliberately do **not**:

- **Change `colleague work` / `colleague plan` subcommands.** Modes only affect
  the interactive `colleague session` cockpit. The standalone subcommands are
  unaffected.
- **Add any new runtime dependency, socket, or daemon.** The feature is stdlib
  only (`colleague/session_modes.py` imports only `typing`); no third-party
  package, no network call, no background process.
- **Alter the classifier code.** `classify_intent` is unchanged — modes wrap
  it, never modify it.
- **Make shift-tab work outside the live-ANSI path.** Non-TTY callers use
  `/mode`; the shift-tab KEY is a live-ANSI-only affordance.
