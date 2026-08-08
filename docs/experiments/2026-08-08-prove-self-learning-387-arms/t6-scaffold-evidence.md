# t6 evidence — arm scaffolding (h21) — 2026-08-07/08

Template: ~/git/transformer @ 15eb0b9 (c30ca2c + pre-arm state.lastError
amendment; docs/correction-rules.md frozen at 0438ec4, untouched).
Scaffold commit 5e60888 built ONCE in staging, pushed to both remotes:

- ON:  https://github.com/OriNachum/transformer-arm-on  @ 5e60888
- OFF: https://github.com/OriNachum/transformer-arm-off @ 5e60888

h21: identical BY CONSTRUCTION — same commit SHA both arms;
`diff -r --exclude=.git` over the two clones: EMPTY (verified).
Scaffolding adds: .colleague/approvals.json (run_command allow exactly
node/npm/webglass), .colleague/webglass-profile.json (declared_targets
127.0.0.1:8080 + localhost:8080), .eidetic/memory/.gitkeep.
The ONLY arm difference is dispatch-time env (COLLEAGUE_MEMORY=0 on OFF).

## Store-isolation finding (probe in throwaway copies, arms untouched)

eidetic 0.13 recall MERGES the $HOME store and its reinforcement write
MIGRATES matched $HOME records into the repo store (reproduced live:
work-lesson-afb67b0a3116, a July $HOME record, landed in a probe copy's
.eidetic/memory after one no-env recall). Under EIDETIC_DATA_DIR set before
ANY eidetic op, recall returns zero $HOME records and writes stay in the one
store (reproduced: fresh copy, "work item finished" recall -> items: []).

PROTOCOL RULE for t7/t8: every colleague dispatch AND every grading command
runs with EIDETIC_DATA_DIR=<that arm's>/.eidetic/memory exported first.
Env otherwise identical across arms: WEBGLASS_ALLOW_UNSANDBOXED=1,
WEBGLASS_POLICY_PROFILE=<arm>/.colleague/webglass-profile.json,
COLLEAGUE_TIMEOUT=300, pinned COLLEAGUE_MODEL (35B worker).
