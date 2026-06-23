# Colleague is agent-native by default: launch it and you are talking to the colleague agent, which drives colleague under the hood, shows every action it takes in a readable feed, and checks a tool's AgentFront surface before reaching for it

> Colleague is agent-native by default: launch it and you are talking to the colleague agent, which drives colleague under the hood, shows every action it takes in a readable feed, and checks a tool's AgentFront surface before reaching for it

## Audience

- Anyone who operates colleague -- a human at the keyboard and a calling agent alike. Per #234 the conversational default is 'true for humans and agents'.

## Before → After

- Before: Today bare colleague already opens an interactive session and already prints help when piped (scripts/agents are safe). But that session is not yet colleague-driving-colleague: it does not default to colleague's own backend orchestrating colleague's own verbs. Its action feed is also noisy -- repeated [culture] lines and '...'-truncated commands (issue #233's paste) -- so you cannot reconstruct what ran. And it has no habit of reading an unfamiliar tool's agent-facing surface before using it.
- After: Launching colleague drops you into a conversation with the colleague agent, running on colleague's OWN backend (its served model). You state intent in natural language and it fulfills it by invoking colleague's own verbs (work, review, explore, plan ...) under the hood -- you get value without naming a subcommand, and the same conversational entry serves a human and a calling agent.

## Why it matters

- Colleague is best operated by an agent (its whole design), so the default experience should BE the agent -- not a subcommand cheat-sheet. For that to be trustworthy you must be able to follow every action it takes, and trust how it picks up tools it has not used.

## Requirements

- [#233] The action feed is legible: repeated mesh events are grouped not spammed, tool commands are not silently truncated past the point of understanding, and each action reads as 'what ran + on what'.
  - honesty: The #233 failure modes are reproducibly gone: no Nx duplicated [culture] lines, no command shown only as 'grep ... ...' with the operative part cut -- checked against a replay of that exact session.
- [#234] The default interactive session is driven by colleague's OWN backend (its served model) and fulfills intent by invoking colleague's own verbs (work/review/plan/...) under the hood -- 'colleague manages colleague'. Same conversational entry for a human operator and a calling agent; the prior backend remains selectable via flag/env.
  - honesty: A fresh `colleague` session, given a free-text goal, (a) runs on colleague's own backend by default and (b) reaches the underlying verb (e.g. work/review) without the user typing it -- both verifiable by a headless tui scenario asserting the backend + the fired verb.
- [#235] colleague's runtime prompt/policy instructs it to check an unfamiliar tool's AgentFront surface (its learn/explain/--help/--json affordances) before its first real use, and to act on what it finds. This spec ships the prompt reflex; an enforced harness-level probe is a named follow-up, not in scope here.
  - honesty: Given a tool colleague has not used before, a session trace shows an AgentFront-surface probe (e.g. `<tool> learn` / `--help`) before the first substantive invocation -- the prompt reflex is observable even though it is not yet machine-enforced.

## Honesty conditions

- The three facets actually ship as one default experience: a fresh colleague session is conversational (not verb-first), its action feed is legible, and it probes a new tool's AgentFront surface first -- demonstrable in a single end-to-end session, not three disconnected features.
- One default serves both: an agent that invokes colleague conversationally reaches the same agent-native session a human does at a TTY -- no human-only path and no separate agent-only path.
- The agent-native default is only worth shipping if it is trustworthy -- so this rationale holds only when #233 (followable actions) and #235 (principled tool pickup) ship alongside #234, not #234 alone.
- Exactly the interactive default-session surface changes (#234 driver, #233 feed, #235 probe-reflex); the explicit verbs' own behavior and backend internals are untouched -- a diff reaching outside the session layer is out of bounds.
- All three signals are checkable from a recorded session with no insider knowledge: a subcommand-naive goal completes; the feed alone reconstructs what ran; the trace shows the AgentFront probe before first use.
- Reachable end-to-end on real infra (not a mock): a fresh session defaults to colleague's own backend AND routes a natural-language goal to the correct verb.
- Accurate against today's main: bare colleague opens an interactive session and prints help when piped; the session does not yet default to colleague's own backend driving its own verbs; the feed shows the #233 noise; there is no AgentFront-probe habit.

## Success signals

- (1) A user who knows no subcommands types a free-text goal and colleague completes it. (2) From the action feed alone a human can say exactly which tools ran and why -- no dedupe noise, no hidden truncation. (3) Facing an unfamiliar CLI, colleague's trace shows it probed that CLI's agent surface (learn/explain/--help/--json) before its first real call.

## Scope / boundaries

- Scope is the default conversational session and the agent running under it: the default entry behavior (#234), the action feed's legibility (#233), and the pre-use AgentFront probe reflex (#235). Nothing else about colleague's internals.

## Non-goals

- Not removing the explicit colleague work/review/... verbs -- they stay for scripting and for agents that call colleague directly. Not removing backend choice: colleague's own backend becomes the DEFAULT session driver, but an operator can still override it (flag/env). Not a new GUI or web TUI. The AgentFront reflex is about READING a tool's surface, not auto-installing, auto-approving, or trusting it.

## Open / follow-up

- Enforced harness-level AgentFront probe: the harness intercepts first-use of an unknown tool and runs/records the probe before the real call (the 'enforce later' half of #235). Needs the parked AgentFront-surface definition resolved first.
