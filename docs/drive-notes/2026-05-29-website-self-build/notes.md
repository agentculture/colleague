# Drive notes — convertible builds its own website (2026-05-29)

Factual record of a session driving `convertible` to build a website for itself.
Observations only: what was run, what was produced, what was recorded. No
assessments or recommendations.

## Setup

- Engine: `vllm-openai`.
- Model: `mmangkad/Qwen3.6-27B-NVFP4` (the only model the live server listed at
  `GET http://localhost:8001/v1/models`; `max_model_len` 32768).
- Server: `http://localhost:8001/v1` (already convertible's default `base_url`).
  Convertible's default model is `Qwen/Qwen3-32B`; overridden with `--model` each
  run.
- Target dir: `site/`. Guidance level: pointers-only (instruction names target +
  deliverables + source files; the model authored all content). No AGENTS.md or
  command template authored.
- Constant flags: `--engine vllm-openai --model mmangkad/Qwen3.6-27B-NVFP4
  --max-steps 50 --no-pr --json`.

## Pre-flight

- Command: `CONVERTIBLE_VLLM_E2E=1 CONVERTIBLE_BASE_URL=… CONVERTIBLE_MODEL=… uv
  run pytest tests/test_vllm_live.py -v`.
- Result: 1 passed in 16.83s. The test created `HELLO.txt` in its own temp repo
  via the live model (confirms the server emits tool calls).

## Drive attempts

| # | task_id | `CONVERTIBLE_TIMEOUT` | status | artifact steps | artifact usage | files on disk after run |
|---|---------|----------------------|--------|----------------|----------------|-------------------------|
| 1 | `b196789edc2f` | 120s (default) | error: `TimeoutError: timed out` | `[]` | 0 | `site/` created, empty |
| 2 | `4639d5ab4871` | 600s | error: `TimeoutError: timed out` | `[]` | 0 | `site/style.css` (9016 bytes) |
| 3 | `bdd455519da0` | 900s | ok | 8 | prompt 72523 / completion 4108 | `site/index.html` (5582 bytes, 143 lines) |

- Attempts 1 and 2 used the identical pointers-only instruction (read `README.md`
  and `docs/features/`; build index.html, a features page, and a stylesheet).
- Attempt 3 used a refined instruction: read only `site/style.css` + `README.md`
  (not `docs/features/`), car-metaphor content given inline, "target about 150
  lines, avoid long prose", build a single concise `index.html`. `style.css` from
  attempt 2 was left in place.
- Process exit code each time: attempts 1 & 2 → 2 (`CliError`, EXIT_ENV_ERROR);
  attempt 3 → 0.
- Wall-clock attempt 2: `site/` dir mtime 09:27, `site/style.css` mtime 09:34,
  error artifact mtime 09:44 (≈600s between the last write and the timeout).

## Timing, iterations, and nudges

(Companion machine-readable copy: `stats.json`; cross-run row: `../index.csv`.)

- **Pre-flight:** 16.83s (measured by pytest).
- **Per-attempt wall-clock** (derived from background-task file birth times and
  drive artifact mtimes — second resolution, not wrapped in `time`):
  - Attempt 1 (120s timeout): ~121s (`site/` mkdir 09:20:48 → error 09:22:49).
  - Attempt 2 (600s): ~1129s / ~18.8 min (09:26:09 → 09:44:58); one completion
    ran the full 600s (`style.css` 09:34:58 → error 09:44:58).
  - Attempt 3 (900s, ok): ~578s / ~9.6 min (09:47:26 → 09:57:04).
  - Sum of drive execution: ~1828s (~30.5 min).
- **Iterations:** 3 drive attempts; the successful run took 8 loop steps; the
  model revised its own `index.html` once (write → `wc -l` → rewrite → `wc -l`).
- **Nudges (operator interventions between attempts): 2.**
  - After attempt 1: raised `CONVERTIBLE_TIMEOUT` 120 → 600 (config only; same
    instruction).
  - After attempt 2: raised it 600 → 900 **and** rewrote the instruction (read
    only `style.css` + README, not `docs/features/`; car-metaphor given inline;
    "~150 lines, avoid long prose"; single concise `index.html`; keep the
    existing `style.css`).
  - The initial guidance is the seed, not counted as a nudge.
- **Tokens (successful run):** prompt 72523, completion 4108, total 76631 (prompt
  count is cumulative across the 8 completions).

## Attempt 3 step trace (status ok)

```text
 0: read_file    site/style.css      ok  (7972 bytes returned)
 1: read_file    README.md           ok  (20031 bytes returned)
 2: write_file   site/index.html     ok
 3: list_dir     site                ok
 4: run_command  wc -l site/index.html  ok
 5: write_file   site/index.html     ok   (rewrote)
 6: run_command  wc -l site/index.html  ok
 7: finish       (summary)           ok
```

- Tool tally: read_file ×2, write_file ×2, list_dir ×1, run_command ×2, finish ×1.
- No step had `ok=false`.
- The model verified its own output with `wc -l` and `list_dir`, wrote
  `index.html`, then rewrote it once before finishing.
- `usage.prompt_tokens` 72523 across 8 completions (the 20031-byte README read at
  step 1 is carried in the message history for every later completion).

## What convertible produced

- `site/style.css` (9016 bytes): dark theme, CSS custom properties under `:root`,
  reset, component classes.
- `site/index.html` (5582 bytes, 143 lines): `<!DOCTYPE html>`, lang attr,
  viewport meta, skip-link, header nav, hero with tagline, 7 car-metaphor cards
  (engine, driver, chassis, tool-loop, wheels, dashboard, GPS), 6 feature cards,
  a quickstart `<pre>` block with `convertible` CLI commands, footer linking
  `../README.md`.
- Validation (`html.parser` + class cross-check): HTML parses with no unclosed
  tags; 24 distinct CSS classes are referenced in the HTML and all 24 are defined
  in `style.css`; no `http(s)://` references in the HTML; the only `<link>` is
  `./style.css`.
- Live browser render: captured. Served `site/` over `python3 -m http.server
  8777` (HTTP 200) and screenshotted with headless chromium
  (`~/.cache/ms-playwright/chromium-1208`); the page displays as built — header
  nav, hero + tagline, 7 metaphor cards, 6 feature cards, quickstart block,
  footer. (Earlier the claude-in-chrome `navigate` rewrote the `file://` path to
  `https://file:///…` → error page, and the `http://127.0.0.1:8777` nav was
  denied; the playwright MCP defaults to the `chrome` channel, absent here.)

## Recorded harness behavior

1. **Per-request timeout governs a single completion.** `EngineConfig` default
   `timeout` is 120.0s (`convertible/config.py:27`), overridable via
   `CONVERTIBLE_TIMEOUT`. `_post_json` passes it to `urllib` per request
   (`convertible/engines/vllm_openai.py`). Attempts 1 and 2 raised `TimeoutError`;
   attempt 3 (900s) did not.
2. **On any engine exception the artifact is rebuilt fresh.** `complete()` at
   `convertible/loop.py:252` has no surrounding try/except; the exception
   propagates out of `run()` and `drive()` (`vllm_openai.py:96`) to
   `convertible/cli/_commands/drive.py:124`, which sets
   `result = failed_result(...)`. The partial `result` accumulated inside `run()`
   (its `steps`, `usage`, `changed_files`) is not carried into the written
   artifact. Attempts 1 and 2 recorded `steps=[]`, `usage=0`, `changed_files=[]`
   while `site/` (attempt 1) and `site/style.css` 9016 bytes (attempt 2) existed
   on disk.
3. **`*.trace.jsonl` was 0 bytes on the failed runs** (`b196789edc2f.trace.jsonl`,
   `4639d5ab4871.trace.jsonl`); the successful run's trace was populated.
4. **No incremental progress output.** `drive*.stderr.log` for each run contained
   only the final line (the error JSON, or nothing on success); stdout carried the
   final `--json` TaskResult only. No per-step output is emitted during a drive.
5. **`/site` is gitignored** (`.gitignore:168`, under the template's "# mkdocs
   documentation" section). `git check-ignore` confirms `site/index.html` and
   `site/style.css` are ignored. `*.log` (`.gitignore:59`) ignores the drive log
   files.
6. **Handoff staging is `git add -A`** (`convertible/handoff.py:96-99`:
   `checkout -B` → `add -A` → `commit`). Commit `6818f55` (attempt 3) contains
   `.convertible/4639d5ab4871.json`, `.convertible/4639d5ab4871.trace.jsonl`,
   `.convertible/b196789edc2f.json`, `.convertible/b196789edc2f.trace.jsonl`
   (36 insertions) — the two earlier failed runs' untracked artifacts. It does
   not contain `site/index.html` or `site/style.css` (gitignored). The artifact's
   `changed_files` is `["site/index.html"]`. The current run's artifact
   `bdd455519da0.json` is untracked (written after the commit).
7. **Commit message is the full instruction verbatim.** `handoff.py:98`:
   `message = f"convertible: {instruction or task_id}"`. Commit `6818f55`'s
   subject is the entire ~140-word attempt-3 instruction string.
8. **`site/` was created during attempts that recorded zero steps.** Created on
   disk while the artifact showed `steps=[]` (see #2). `write_file`
   (`convertible/tools.py:276`) runs `path.parent.mkdir(parents=True)`. The
   specific tool call that created `site/` in attempt 1 is not identifiable from
   the artifact (steps were discarded).

## What worked

- Pre-flight live test passed; tool calling functioned against the server.
- File reads, writes, `list_dir`, and `run_command` all returned `ok` in the
  successful run; paths stayed inside the repo.
- The model read `site/style.css` and used class names defined there; output had
  no undefined classes and no external dependencies.
- The model ran its own verification (`wc -l`, `list_dir`) and one revision before
  `finish`.

## Repo state left by the session

- HEAD: branch `convertible/bdd455519da0` (created by attempt-3 handoff),
  commit `6818f55` on top of `dac5bc9` (`main`).
- Working tree: `site/index.html` + `site/style.css` present (gitignored);
  untracked `.convertible/bdd455519da0.json`, `.convertible/bdd455519da0.trace.jsonl`,
  `drive3.exit`; gitignored drive logs (`drive*.log`).
- `main` is unchanged at `dac5bc9`.
