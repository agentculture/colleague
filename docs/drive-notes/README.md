# Drive evaluations

A log of experiments in which **colleague drives itself** — the engine does the
work, the operator only guides (instruction + config), observes, and records.
The goal is to be able to **repeat** a drive and **evaluate results over time**
as colleague (and the engines/models it runs) change.

Two kinds of content live here, side by side:

- **Information** — qualitative, factual observations per run (`notes.md`).
  Observations only: what was run, what was produced, what was recorded — no
  assessments or prescribed fixes.
- **Statistics** — machine-readable metrics per run (`stats.json`) plus a
  cross-run time series (`index.csv`).

## Layout

```text
docs/drive-notes/
  README.md                     # this file
  index.csv                     # one row per run — the cross-run time series
  <date>-<experiment>/
    notes.md                    # qualitative observations
    stats.json                  # machine-readable metrics + findings (schema_version 1)
    repro.sh                    # exact command(s) to repeat the run
    output/                     # the produced artifact ("the test"), preserved
      index.html  style.css  render.png
    artifacts/                  # raw colleague drive artifacts (evidence)
      success-<task>.json  success-<task>.trace.jsonl  fail-<task>-*.json
```

> `site/` is gitignored (`.gitignore` `/site`, from the mkdocs template section),
> so a drive's output is copied into `output/` here to preserve it for comparison.

## `index.csv` columns

`date, experiment, engine, model, attempts, nudges, guidance_rewrites,
final_status, success_timeout_s, success_wall_clock_s, success_steps,
model_self_revisions, prompt_tokens, completion_tokens, total_tokens,
index_html_bytes, style_css_bytes, html_valid, css_undefined, external_refs,
findings, preflight_s, run_dir`

Key metrics the runs track (the "stats like time it took, iterations, how much
you had to nudge it"):

- **time** — `success_wall_clock_s` (and per-attempt `wall_clock_s` in `stats.json`), `preflight_s`.
- **iterations** — `attempts` (drive launches), `success_steps` (loop steps in
  the successful run), `model_self_revisions` (in-loop rewrites).
- **nudges** — `nudges` = operator interventions between attempts (config and/or
  guidance changes); `guidance_rewrites` counts how many changed the instruction.
  Each nudge is itemized in `stats.json` with the change and the observation that
  prompted it.
- **cost** — token usage of the successful run.
- **quality** — `html_valid`, `css_undefined`, `external_refs` (validation), plus
  the rendered `output/render.png`.
- **findings** — count of factual observations recorded for the run (the
  actionable list lives in `stats.json.findings`, each with an `id` and
  `evidence`, so they can be acted on and re-checked over time).

## How to repeat a run

Each run folder has a `repro.sh` with the exact invocation. In general:

```bash
# requires a live OpenAI-compatible server with tool calling enabled
COLLEAGUE_BASE_URL=… COLLEAGUE_MODEL=… COLLEAGUE_TIMEOUT=… \
  uv run colleague drive "<instruction>" \
  --repo . --engine vllm-openai --model <model> --max-steps 50 --no-pr --json
```

Method constraints held constant across runs: only the engine writes files; the
operator provides pointers-only guidance and records observations factually.

## How to evaluate over time

1. Run the experiment (see the run's `repro.sh`).
2. Create a new `<date>-<experiment>/` folder; write `notes.md` + `stats.json`
   (copy an existing one as the template) and preserve `output/` + `artifacts/`.
3. Append one row to `index.csv`.
4. Re-check each prior `findings[]` entry: does it still reproduce on this
   engine/model/version? Record its `status` in the new run's `stats.json`.

Comparing rows in `index.csv` (and findings status across runs) shows whether a
change to colleague, the engine, or the model moved time, iterations, nudges,
cost, or quality.
