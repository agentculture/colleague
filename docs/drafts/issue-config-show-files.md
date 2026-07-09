# `colleague config show` should list every config file that contributed a key, not just the first match

## Background

The at-home arc (`docs/features/at-home-on-your-machine.md`, spec
`docs/specs/2026-07-09-colleague-now-feels-at-home-on-your-machine-arm-th.md`,
task t1) changed `.colleague/config.json` resolution from whole-file
shadowing to a **per-key merge** across up to four roots, in precedence order:
`repo/.colleague`, `repo/.convertible`, `user/.colleague`,
`user/.convertible` (`colleague/config.py`'s `_merged_config_json`, built on
`colleague/configdir.py`'s `resolve_files`). A repo-level `config.json` that
never mentions `lobes` no longer hides a user-level `lobes` default — the
whole point of the fix.

## The gap

`colleague config show` (`colleague/cli/_commands/config.py` `_config_show`)
still reports provenance from a single first-matched file:

```python
file_cfg = load_config_file(repo)
if file_cfg:
    keys = ", ".join(sorted(file_cfg.keys()))
    lines.append(f"config_file: .colleague/config.json sets [{keys}]")
```

`load_config_file` already reads the *merged* result (so the reported `keys`
list is correct post-merge), but the `config_file:` line still implies a
single file, and does not say *which* of the (possibly several) resolved
files actually supplied each key. An operator debugging "why isn't my
user-level default taking effect" has no way to see, from `config show`
alone, that (for example) `base_url` came from the repo file while `lobes`
came from the user file.

## Proposed fix

Extend `_config_show` to report, for each recognised top-level key
(`base_url`, `api_key`, `model`, `lobes`, `senses`, `voice`, `deepthink`,
`lint`, `testintegrity`, `affected_tests`, `memory`, `coherence`, `watch`),
which resolved file it came from — reusing
`colleague.configdir.resolve_files(repo_path, "config.json")` (already public)
to enumerate every existing file in precedence order, then walking them
lowest-to-highest exactly like `_merged_config_json` does, to attribute each
key to its winning file. Render as one line per contributing file (e.g.
`config_file: .colleague/config.json sets [base_url, model]` +
`config_file: ~/.colleague/config.json sets [lobes]`) instead of a single
line naming only the first match.

## Scope note

Cosmetic / introspection-only — this does not change resolution behavior,
only what `config show` reports about it. No change to `EngineConfig.resolve`,
no change to precedence.
