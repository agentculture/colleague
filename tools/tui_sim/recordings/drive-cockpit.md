# Cockpit

- **screen**: main
- **mode**: planning
- **focused**: input.prompt

## Zones

- top.status
- left.skills
- main.conversation
- bottom.input

## Panels

### Commands

- doc-review — Audit colleague's docs for accuracy vs the actual code/CLI; flag staleness, missing pages, and undocumented operability gaps (available)

### Session

Type a number / template name / free-text task, or /help for commands.
Add a retry-on-overflow guard to the drive loop
[read_file] colleague/loop.py
[read_file] colleague/context.py
[write_file] colleague/loop.py
[run_command] pytest -q tests/test_loop.py
[finish] retry-on-overflow guard added
done: retry-on-overflow guard added [colleague/loop.py] -> colleague/7f3a2c-add-retry-guard

## Status

- **severity**: info
- **message**: colleague session · engine mock · model sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP · local

## Drive

- **task_id**: t-7f3a2c
- **engine**: mock
- **step_count**: 5
- **running**: True

## Available Actions

- `input.prompt` (type) — Send instruction to current agent
