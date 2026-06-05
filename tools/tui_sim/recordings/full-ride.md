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
/engine mock
engine → mock
Wire the cockpit status bar severity to drive failures
[read_file] colleague/tui/widgets/status_bar.py
[write_file] colleague/tui/widgets/status_bar.py
[run_command] pytest -q tests/test_tui_render.py
[finish] status bar severity wired to drive failures
done: status bar severity wired to drive failures [colleague/tui/widgets/status_bar.py] -> colleague/7f3a2c-status-severity

## Status

- **severity**: info
- **message**: colleague session · engine mock · model sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP · local

## Drive

- **task_id**: t-7f3a2c
- **engine**: mock
- **step_count**: 4
- **running**: True

## Available Actions

- `input.prompt` (type) — Send instruction to current agent
