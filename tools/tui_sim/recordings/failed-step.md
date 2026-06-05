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
[read_file] colleague/policy.py
[run_command] pytest -q tests/test_policy.py

## Popups

### Error [popup.error.run_command]

run_command failed: pytest -q tests/test_policy.py

**Actions:**

- `popup.error.run_command.dismiss` (esc) — Dismiss

## Status

- **severity**: info
- **message**: colleague session · engine mock · model sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP · local

## Drive

- **task_id**: t-7f3a2c
- **engine**: mock
- **step_count**: 2
- **running**: True

## Available Actions

- `popup.error.run_command.dismiss` (esc) — Dismiss
- `input.prompt` (type) — Send instruction to current agent
