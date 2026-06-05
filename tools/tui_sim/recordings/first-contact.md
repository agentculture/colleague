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
/help
slash commands:
  /help                 this list
  /commands             list command templates
  /skills               resolved skill docs
  /agents               resolved AGENTS layers
  /config               configuration readiness (doctor)
  /engines              discovered backend plugins
  /telemetry            telemetry configuration
  /feedback             feedback for the last drive
  /engine <name>        switch the engine for the next drive
  /model <name>         switch the model
  /base <branch>        set the PR base branch
  /pr                   toggle push + open PR on each drive
  /quit                 end the session
plain text (a number / template name / free-text task) runs a drive.

## Status

- **severity**: info
- **message**: colleague session · engine mock · model sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP · local

## Available Actions

- `input.prompt` (type) — Send instruction to current agent
