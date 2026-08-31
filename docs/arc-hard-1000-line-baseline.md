# Hard 1000-Line File Limit — Baseline Measurement

**Date:** 2026-08-31  
**Commit:** 824c2dc (spec+plan: hard 1000-line file limit — the culture-nodes gate ported to pytest)  
**Command:** `uv run pytest -n auto`

## Test Results

- **Passed:** 10715
- **Skipped:** 51
- **Duration:** 26.93s

All 4 file-length gate tests pass:

- `test_tracked_source_files_stay_within_the_hard_line_limit` ✓
- `test_the_grandfather_list_is_reaped` ✓
- `test_the_scanner_actually_scans` ✓
- `test_the_gate_covers_python` ✓

## Grandfathered Files (21 total)

These files exceeded the 1000-line hard limit when the gate landed. They are pinned at their line counts on this date. The list is **shrink-only** — no entry may grow, and must be removed once the file fits.

| File | Lines |
|------|-------|
| colleague/cli/_commands/session.py | 3979 |
| colleague/cli/_commands/work.py | 2854 |
| colleague/config.py | 4442 |
| colleague/contract.py | 2479 |
| colleague/engines/vllm_openai.py | 1445 |
| colleague/explain/catalog.py | 1507 |
| colleague/handoff.py | 1037 |
| colleague/livecheck.py | 1481 |
| colleague/loop.py | 5392 |
| colleague/memory.py | 1147 |
| colleague/resident/appserver.py | 1206 |
| colleague/senses.py | 1483 |
| colleague/subagents.py | 1703 |
| colleague/tae_loop.py | 1043 |
| colleague/tools.py | 1552 |
| tests/test_ask_colleague_skill.py | 1467 |
| tests/test_boundary.py | 1144 |
| tests/test_configurator.py | 1145 |
| tests/test_loop.py | 1002 |
| tests/test_loop_memory.py | 1240 |
| tests/test_plan_orchestrator.py | 1002 |
