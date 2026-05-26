# CLAUDE.md — seed / bootstrap placeholder

> **This is a self-initializing seed, not a finished runtime prompt.**
> Run `/init` (or describe the agent's domain to your AI assistant) to
> re-initialize this file into a full runtime prompt, using the description
> below and the scaffolded repo as context.

## Agent

This repository hosts the **convertible** agent.

## Description

Convertible CLI is a swappable coder-agent harness that turns different models into repo workers behind one shared task contract.

## Re-init instruction

This file is a seed. To expand it into your full runtime prompt:

1. Open this repo in Claude Code (or your preferred AI assistant).
2. Run `/init` — the assistant will read the repo, incorporate the description
   above, and replace this seed with a complete `CLAUDE.md`.
3. Commit the result.

Until you run `/init`, `convertible` satisfies the `steward doctor`
`prompt-file-present` and `backend-consistency` invariants (a `CLAUDE.md`
exists and `culture.yaml` declares `backend: claude`) but the prompt is not
yet tailored to this agent's domain.
