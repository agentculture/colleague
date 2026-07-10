# Colleague now feels at home on your machine: arm the lobes gateway once globally and every repo gets cortex+senses; type mid-run without the cockpit eating your words; and ask colleague anything about itself — it answers from its own live guide, through senses or cortex.

> Colleague now feels at home on your machine: arm the lobes gateway once globally and every repo gets cortex+senses; type mid-run without the cockpit eating your words; and ask colleague anything about itself — it answers from its own live guide, through senses or cortex.
> instruction: Verify by the three success-signal proofs in c14 — each is a runnable live check on the reference rig

## Audience

- The operator running colleague across many repos on one machine (Ori's rig today), plus any agent driving colleague session interactively
  - instruction: Validate on the real workflow: one machine, many repos, interactive session on the reference rig

## Before → After

- Before: Arming is per-repo or per-shell (repo .colleague/config.json or COLLEAGUE_LOBES_URL env); a repo-level config.json silently shadows the user-level one whole-file, so a global lobes default dies the moment a repo has any config.json of its own; typing mid-run is visually destroyed by cockpit update lines (cooked-mode tty echo vs repaints); self-questions get a thin hardcoded fact-set via senses only — cortex knows nothing about colleague itself (#306)
  - instruction: Reproduce each friction as the failing test before fixing it (TDD gate)
- After: One user-level ~/.colleague/config.json arms lobes (and other defaults) for every repo on the machine, with repo-level keys overriding per-key instead of shadowing whole-file; the session owns its input line so mid-run updates print above it and the operator's partial typing stays visible; a self-knowledge turn — through the senses front door OR dispatched to cortex — answers from colleague's live guide plus resolved runtime facts (model ids, armed gateway, gates)
  - instruction: Accept only when all three c14 proofs pass live

## Why it matters

- The cortex/senses split only earns its keep if it is actually armed and conversable: today a machine-wide default silently breaks, mid-run conversation punishes typing, and 'what model are you?' gets a deferral — three frictions that make the presence lane feel broken even when the machinery works
  - instruction: Cite the operator complaint in the spec motivation; no synthetic justification

## Requirements

- R1 config merge: load_config_file and _load_lobes_override (and the senses/voice/deepthink section loaders) merge config across configdir roots per-KEY (repo keys win over user keys; within a level .colleague over .convertible) instead of first-file-wins whole-file shadowing — a user-level lobes default survives a repo-level config.json that doesn't mention lobes
  - instruction: Implement per-key merge in load_config_file/_load_lobes_override + section loaders over configdir.config_roots; pin with the shadow test (repo config without lobes + user config with lobes => armed)
  - honesty: A repo-level config.json that carries a key behaves byte-identically to today (merge only FILLS keys absent at the repo level, never overrides a present one); malformed JSON at any level skips that level and never raises
  - honesty: Merge granularity is TOP-LEVEL KEY (a repo-level senses section wholly replaces a user-level senses section — no deep merge inside sections), so precedence stays explainable in one sentence
- R2 introspection honesty: colleague lobes show reads the SAME precedence the runtime resolves (env > repo config > user config), gains --repo, and can never contradict colleague config show — the widening its own docstring deferred until t4 landed
  - instruction: Widen lobes.py CLI noun to resolve_lobes_gateway_url(repo_path) + add --repo; drift test asserts lobes show and config show agree in both armed and unarmed states
  - honesty: lobes show and config show consult ONE shared resolver (resolve_lobes_gateway_url with repo_path threaded); a drift test pins that they can never disagree about the armed state
- R3 owned input line: on a colour TTY, the session's mid-run talk lane owns its input line (raw-mode reader + owned buffer, reusing _session_input.py) so senses/cortex update lines print ABOVE the pending input and the operator's partial typing is repainted, not destroyed
  - instruction: Reader thread + locked print-above helper in session.py's colour-TTY talk lane; reuse _session_input.py raw-mode machinery; extend test_boundary.py thread allow-list with recorded rationale; pytest the repaint helper, live-verify the felt fix
  - honesty: Off a colour TTY (piped, --json, --no-tui, Windows) the session is byte-identical — the owned input line exists only on the live-ANSI path, exactly like the slash-autocomplete popup precedent
  - honesty: Zero new dependencies and no curses: the owned line is the existing termios/tty raw-mode reader plus ANSI repaint, the _session_input.py machinery already shipped
  - honesty: The reader thread never outlives the run it serves: started only when the colour-TTY talk lane arms, joined (bounded) at run end; a thread failure degrades to today's cooked-mode behavior, never a crashed session
- R4 cortex self-knowledge: a self-knowledge turn that reaches cortex (dispatched repo-adjacent question, or asked mid-work via the talk lane) answers from colleague's own guide — not just the senses front door's thin fact-set (#306)
  - instruction: Deterministic self-knowledge classifier + one advisory guide-index message (doc paths + resolved facts) injected before the cortex turn; cortex reads live docs via existing read_file
  - honesty: Cortex's self-knowledge rides its EXISTING read tools: a deterministic self-knowledge trigger injects one advisory guide-index message (paths to CLAUDE.md architecture bullets + docs/features/*) and cortex reads the live docs itself — always current, no frozen snapshot, no new tool surface
- R5 runtime self-facts: 'what model are you / what's armed?' returns the RESOLVED state (cortex+senses model ids, gateway, active gates) on both senses and cortex paths — real answers, not deferrals
  - instruction: Build the facts block from EngineConfig.resolve output (cortex/senses model ids, gateway, gates); test pins unarmed => honest 'not armed', never a fabricated id
  - honesty: Self-facts report RESOLVED state only: an unarmed lobes answers 'not armed' honestly; the facts block is built from EngineConfig.resolve output, never from model memory — a fabricated model id is a test failure
- R6 guide loaded only when relevant: the self-knowledge corpus (docs/features/*, CLAUDE.md architecture bullets) is injected only when a deterministic trigger routes a self-knowledge turn — base-context prompt size unchanged for ordinary turns (#306's acceptance)
  - instruction: Pin byte-identical system prompt + initial messages for an ordinary turn with the feature present (the #306 acceptance test)
  - honesty: A test pins that an ordinary (non-self-knowledge) turn's system prompt + initial messages are byte-identical with the feature present — the guide index is injected ONLY on the deterministic trigger

## Honesty conditions

- All three legs are LIVE-PROVEN on the real rig before the announcement ships: global arming survives a repo config, mid-run typing survives updates, and self-questions get guide-grounded answers on both minds
- The arc's surfaces are operator-facing (session, config, introspection); nothing here changes the programmatic Task/TaskResult contract
- Every named friction is reproducible today: the whole-file shadow test, the mid-run typing clobber, and the 'I don't know which model' deferral were each demonstrated live on 2026-07-09
- The after-state is exactly the three success-signal proofs of c14 — no claim beyond what those proofs demonstrate
- The frictions are the operator's felt complaint, recorded verbatim ('I don't feel like I talk with Gemma'; typing 'clears my text, so I have to type really fast')
- No per-input model decision picks any route in this arc: the self-knowledge trigger is a deterministic stdlib-re classifier (the classify_frontdoor sibling), pinned by tests exactly like #305
- The merge composes the EXISTING configdir.config_roots order and EngineConfig.resolve precedence — no new file location, no new format key, no daemon; the input line adds no dependency beyond stdlib threading
- Each proof is runnable evidence, not narration: (a)+(c) as livecheck classifiers grading real transcripts (SKIP honestly when the rig is down), (b) as a pytest over the print-above helper plus a recorded live session
- Echo latency is graded by the reader-thread design itself (echo happens on keypress, not at boundaries) — a boundary-wait regression is a test failure; the model-id exact match is graded by a livecheck classifier from the transcript

## Success signals

- The three live proofs: (a) a repo with its own lobes-less config.json still arms from ~/.colleague/config.json and lobes show agrees with config show; (b) typing a sentence while cortex streams updates leaves the sentence visible and submittable; (c) 'what model are you?' answers with the real resolved ids via senses AND via cortex mid-work, and 'how does the affected-tests gate work?' answers from the guide
  - instruction: Add the three proofs to docs/live-testing.md as graded rows before announcing
- Measurable: mid-run keystroke echo is instant (<100ms perceived — no boundary wait) while cortex drives; 'what model are you?' answers containing the EXACT resolved model id string (exact-match gradable); the shadow test flips lobes from not-armed to armed with zero env vars set
  - instruction: Grade via livecheck classifier + the print-above pytest; record in docs/live-testing.md

## Scope / boundaries

- NOT a general retrieval/RAG lane: self-knowledge stays a fixed, enumerated, deterministically-routed surface (the #305 precedent); the #277 embedder/reranker retrieval lane stays parked; no per-input model decision picks the route; senses/guide still cannot act — cortex remains the only repo actor
  - instruction: Boundary test pins the classifier is deterministic and that ambiguous input routes to the default (never to the guide surface)
- NOT a config rewrite: key-merge composes the EXISTING configdir roots and EngineConfig.resolve precedence (flag > env > repo config > user config > lobes discovery > builtin) — no new config format, no new file locations, no daemon; and NOT a full TUI editor: the owned input line is one repainted line, not a curses app or a new dependency
  - instruction: test_zero_deps.py and the configdir precedence tests stay green unchanged except the deliberate thread-sanction edit

## Non-goals

- No N-role generalization, no senses-decides-to-answer beyond the enumerated surface, no automatic task-to-model routing — the router-exclusion line holds exactly as drawn in #305/#306
  - instruction: Restate the router-exclusion line in the spec's boundary section; any widening needs its own re-spec

## Decisions

- q1 RESOLVED (operator): the owned input line gets a SANCTIONED READER THREAD — the 4th recorded convention break (after agentfront base dep, LLM self-summary, c17 residency). A tiny thread owns raw stdin + instant echo; sink prints route through a locked print-above helper (hand-rolled patch_stdout). Confined to session.py's colour-TTY live path ONLY (never the runtime loop, never off-TTY), joined at run end; test_boundary.py's thread allow-list extended with the stated reason
  - instruction: Record the thread sanction in CLAUDE.md conventions as the 4th deliberate break, with confinement + join semantics stated
- Cortex self-knowledge mechanism (operator): deterministic trigger + guide-index injection — ONE advisory message naming the live guide paths + resolved runtime facts; cortex reads the docs with existing tools. No new role in this arc; a named guide/docent role stays available as a follow-up if injection proves shallow (senses side still gets the tools-off digest + facts block)
  - instruction: Ship injection in this arc; file the named guide/docent role as a follow-up issue if answers prove shallow

## Hard questions

- Between sink boundaries the main thread is blocked inside one HTTP completion — no code runs to echo raw-mode keystrokes, so an owned input line types BLIND during a long silent completion; cooked mode echoes instantly but the buffer is invisible to the program. Which do we accept: boundary-only echo, or a sanctioned input thread (a 4th recorded convention break)?

## Open / follow-up

- config show's config_file line should list ALL contributing files post-merge (repo + user) — cosmetic follow-up alongside R2
- The #277 embedder/reranker retrieval lane over the guide corpus — powerful for self-knowledge but stays parked pending its own router-boundary re-spec (#306's own boundary note)
