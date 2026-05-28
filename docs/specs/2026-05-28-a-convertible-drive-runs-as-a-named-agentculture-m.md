# A convertible drive runs as a named AgentCulture mesh member: it acts under a specific mesh identity and natively reaches the sibling agent-ops CLIs — agtag (file/fetch/reply to mesh issues), agex/devex (inspect a repo's agent-first surface), culture (mesh presence) — so a worker both contributes to and learns from the agents around it, instead of being a sealed single-repo box.

> A convertible drive runs as a named AgentCulture mesh member: it acts under a specific mesh identity and natively reaches the sibling agent-ops CLIs — agtag (file/fetch/reply to mesh issues), agex/devex (inspect a repo's agent-first surface), culture (mesh presence) — so a worker both contributes to and learns from the agents around it, instead of being a sealed single-repo box.

## Audience

- operators running convertible workers inside an AgentCulture workspace, and the mesh agents/humans those workers coordinate with

## Before → After

- Before: a convertible drive is a sealed single-repo box: it can shell out to agtag/agex via run_command or the communicate/cicd skills, but there is no first-class identity, no native verb, and nothing it learns from sibling agents flows back into the drive
- After: a drive can be attributed to a specific mesh identity, and convertible exposes the sibling CLIs through its own agent-first surface so reaching them is structural, not an ad-hoc shell string

## Why it matters

- convertible's value is one harness across many engines; if a worker can be a real mesh participant (attributed, coordinating, learning) it becomes a peer in the Organic Development system instead of an isolated tool

## Requirements

- the new loop tools shell out to operator-installed CLIs (agtag/agex/culture) only — no socket, no daemon, no runtime dep; this stays an explicit re-spec of the loop's tool surface, not an MCP runtime
  - honesty: every culture integration shells out to an operator-installed CLI via subprocess — no socket, no daemon, no import; convertible reads no mcp.json and adds no live client
- clones live in a gitignored path UNDER the working repo (e.g. .convertible/neighbours/) so the existing read_file confinement naturally permits reading them; the read-only rule must be enforced/honoured so a drive never writes into or pushes a clone
  - honesty: clones resolve under the gitignored path; the read path permits them while writes/commits/pushes into a clone are prevented or provably never occur
- the neighbour set is operator-configured (a .convertible/ allow-list of repos/remotes), not auto-discovered — convertible clones only what the operator lists
  - honesty: with no operator allow-list configured, convertible clones nothing — the neighbour set defaults to empty

## Honesty conditions

- a drive run under identity X yields mesh artifacts (issue posts, replies) attributed to X, with zero new runtime deps and the zero-deps + e2e-shape guards still green
- an operator already running convertible in a workspace can use this by installing only the culture CLIs they want — no bespoke wiring
- verifiable at HEAD: convertible today has no identity concept and no native culture surface — only generic run_command and the communicate/cicd skills
- after shipping, reaching a culture tool is a declared capability the model sees, not an ad-hoc run_command string it improvises
- an attributed, neighbour-aware worker completes at least one real cross-repo mesh task (e.g. file an issue as itself, informed by a neighbour clone) that a sealed drive cannot
- no new code path opens a socket, forks a daemon, or adds a runtime dep; existing zero-deps + e2e-shape guards stay green and a no-socket/no-daemon check holds
- an e2e test shows a drive-as-X producing an X-attributed artifact and reading a neighbour clone, guards green
- the process-level identity resolves once and propagates to every culture subcommand (and zehut sub-identities) without a per-call flag
- cloning + refreshing is subprocess git only and reading is via the existing confined read path; no clone is ever modified, committed, or pushed by a drive
- no drive code path executes anything inside a clone — clones are a static read surface; run_command is confined away from clone paths or clones are otherwise non-executable

## Success signals

- a drive run as identity X produces issue posts / mesh artifacts attributed to X, and convertible can inspect a sibling repo's agent-first surface, with zero new runtime deps and the zero-deps + e2e-shape guards still green

## Scope / boundaries

- convertible does NOT become a live mesh client: no IRC socket, no daemon, no long-lived presence, no MCP runtime, no runtime dependency on culture/agtag/agex — integration is shelling out to operator-installed CLIs from within convertible's existing subprocess/conventions

## Non-goals

- replacing the existing communicate/cicd skills — those stay; native integration is for what belongs in the contract/loop, not what a skill already does well

## Decisions

- convertible runs AS a user/identity at the PROCESS level (convertible itself only runs with a user); every culture subcommand it invokes inherits that identity, or a zehut SUB-identity of it. Identity propagates downward, it is not a per-call flag.
- the culture tool is UNGATED — it extends the trusted-operator-env model (D2), exactly like run_command today; no operator review per call.
- the integration set is BUILDER-CURATED from the culture ecosystem: as convertible's builder I survey what culture tools exist (agtag, devex/agex, culture, zehut, ...) and wire in only the ones that clearly make sense — starting with agtag (mesh issues) and devex/agex (inspect/learn). 'Less tools is good' bounds the OUTPUT; builder judgment drives the SELECTION. Whether each lands as its own tool or one shared culture tool is an implementation detail, kept minimal.
- learning from neighbours = convertible can git-clone neighbour repos into a GITIGNORED folder and READ/watch them, strictly READ-ONLY (never commit/push/modify a clone). This is a read cache of sibling source, alongside the inward culture-CLI subcommands.
- neighbour clones are INERT: read-only AND never executed. Convertible reads their files for learning but never runs neighbour code/scripts/builds (no run_command targeting a clone path). Reading is safe; executing untrusted neighbour code is not.
- 'watch' = refresh ON DEMAND: a drive runs git pull/fetch then reads. No background process, no daemon (resolves the watch hard-question, stays inside c6).
- neighbour clones are EPHEMERAL: cleaned up when the drive FINISHES (natural home: the finish lifecycle event in loop.py). A drive shallow-clones what it needs and removes it on exit; nothing persists between drives.

## Hard questions

- expanding the closed five-tool contract breaks a stated v0 invariant and the e2e-shape guard — is the all-engines re-spec of the loop surface worth it vs operator-facing verbs that leave the loop untouched?
- outward mesh tools (file an issue, post to a channel) mid-drive = AUTONOMOUS outward communication with no operator gate, unlike today's gated handoff. Acceptable, or must they be hook-gated / dry-run by default?
- 'watch' implies staying current. A live filesystem/poll watcher is a daemon, which c6 forbids. Is 'watch' = git pull/refresh + read ON DEMAND (no daemon), or a genuine background watcher (re-spec)?
