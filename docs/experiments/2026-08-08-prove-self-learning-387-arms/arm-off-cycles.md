# OFF-arm per-task cycle records (consolidated)

All tasks: COLLEAGUE_MEMORY=0, EIDETIC_DATA_DIR=`<arm-off>`/.eidetic/memory,
byte-identical briefs, same frozen correction rules (0438ec4) + rubric,
memory:null verified on every artifact. Verifier evidence files (per task:
console lenses, state extracts, screenshots, press logs) in the session
records; summary series in arm-off-summary.tsv.

- **g1** (79a3fcd81507, 1 leg/27 steps): 3/3 PASS, 0 lines, grade 5 — parity
  with ON g1. Root-caused the recurring leaked-server anomaly (shell $! is a
  wrapper pid; kill by port).
- **g2** (9fc1e8accedb, 1 leg/22): C1 partial fail — walls clipped out of the
  fixed ortho camera (frustum 12 vs wall extent 10.5; ON's same-viewport shot
  showed walls). 2-line frustum correction, wall pixels 0→665 verified.
  Grade 3.
- **g3** (4-leg chain, 195 steps — the run's longest): 4/4 PASS, 0 lines,
  grade 5. THE KEY CELL: the worker rediscovered the discrete-press/
  physics-frame defect in-run (verbatim: "press dispatches keydown+keyup
  instantly... needs the key held"), hunted a nonexistent webglass evaluate
  verb, then self-built an 8-frame moveHold latch with the discovery as a
  code comment. Cost in steps, not correction lines.
- **g4** (3 legs incl. a 0-step flap casualty, 75 steps): keyed Space
  CORRECTLY via its e.code convention (ON's naming trap avoided) — jump dead
  anyway via frame-1 landing recapture (no vy<=0 guard) + dead fall-damage
  accounting (lastGroundedY clobbered pre-read). 11-line correction, arc
  re-verified (y -2.1→-1.997→-1.222→-2.1). Grade 3. Same symptom as ON g4,
  disjoint cause, zero shared lines.
- **g5** (2 legs/73): wiring correct (ON's state.dummies defect NOT
  reproduced); counting wrong — +18 hits/swing (no per-swing dedup, the ON-g7
  class earlier). 9-line struckIds correction, hits 0→1→2 verified. Grade 3.
- **g6** (2 legs/69): WORST CELL, grade 2 — all three criteria failed:
  function-scoped consts crashed the plate handler before d1 could open
  (uncaught ReferenceError; state.lastError non-null — the t2 mitigation
  caught what the window-scoped console lens missed), duplicate loadLevel
  masked door animation, and the lever repeated ON g6's behind-its-own-door
  reachability defect with an apex-infeasible route on top. 12-line
  correction across 2 files; full plate→lever→pass-through flow re-verified.
- **g7** (2 legs/92): 5/5 PASS, 0 lines, grade 5 — the sharpest ON/OFF
  contrast (ON: 27 lines). Reused its OWN g5 struckIds for enemies,
  ground-level spawn (reachable by construction), exact 3-hits-per-life,
  clean restart. Out-of-bar anomalies recorded uncorrected (negative lives
  after death, point-blank dead zone).
- **g8** (1 leg/48): grades 4 — timed playthrough boot→won 55.8s with no
  lives lost, win/lose/restart + zero-errors PASS, beauty passes with the
  inert-fog caveat (fog params can't matter in an ortho single-plane scene —
  recorded, not polished); README schema missed two live keys (struckIds,
  lastGroundedY) — 4-line doc correction.

OFF totals: 38 correction lines, mean grade 3.75, 601 steps / 493 turns,
memory:null 16/16.
