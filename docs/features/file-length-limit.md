# File length limit — the hard 1000-line ceiling

> `tests/test_file_length_limit.py` fails the suite when a tracked source file
> exceeds 1000 physical lines, with one narrow, shrink-only escape hatch. Born
> from the `hard-1000-line-file-limit` arc (2026-08-31), which split 21
> oversized modules (`loop.py`, `config.py`, `cli/_commands/session.py`,
> `cli/_commands/work.py`, `contract.py`, `subagents.py`, `tools.py`,
> `explain/catalog.py`, `senses.py`, `livecheck.py`, `engines/vllm_openai.py`,
> `resident/appserver.py`, `memory.py`, `tae_loop.py`, `handoff.py`, plus 5
> oversized test files) into ~60 siblings, each under the ceiling.

## The gate (`tests/test_file_length_limit.py`)

Ported from culture-nodes' `tests/lint/filelength_test.go` — the same
contract, expressed as pytest. Three tests:

- **`test_tracked_source_files_stay_within_the_hard_line_limit`** — scans every
  `git ls-files`-tracked file with a source extension (`.py` first and
  foremost, plus `.c`/`.cc`/`.go`/`.h`/`.js`/`.jsx`/`.mjs`/`.sh`/`.sql`/`.ts`/
  `.tsx`, so the gate does not quietly stop applying if the repo grows one of
  those) and fails if any file exceeds `MAX_SOURCE_FILE_LINES = 1000` — unless
  it is in `GRANDFATHERED`, in which case it may not exceed its pinned length
  either.
- **`test_the_grandfather_list_is_reaped`** — fails if a pinned entry now fits
  under 1000 lines (or the file is gone): the exception list cannot silently
  outlive the problem it documents.
- **`test_the_scanner_actually_scans`** — the gate on the gate: plants files
  that must and must not be caught in a `tmp_path`, so a broken scanner (wrong
  root, empty extension set, off-by-one) cannot pass silently the way an
  already-clean tree would.

**Physical lines, comments included.** The limit is about how much a reviewer
has to hold in their head at once — a 1400-line file does not become
reviewable because 500 of those lines are comments explaining the other 900.

## `GRANDFATHERED` — empty, shrink-only

```python
GRANDFATHERED: dict[str, int] = {}
```

The arc that landed this gate (2026-08-31) split every file that exceeded the
limit *before* the gate went in, so the list ships **empty** — every tracked
source file is under 1000 lines on day one, with no exception carried forward.
The dict shape stays as the escape hatch for a future file that must
temporarily cross the limit: a pinned entry records the file's length at the
day it was grandfathered, may never be raised, and must be deleted once the
file drops back at or under 1000 lines (enforced by
`test_the_grandfather_list_is_reaped`). Nothing may be *added* to it without a
deliberate, reviewed edit to the test file itself.

## Relationship to the file-length ratchet

`tests/test_file_length_ratchet.py` (approved deviation d6, 2026-08-21) is the
**soft**, complementary gate: a checked-in per-file baseline
(`tests/file_length_baseline.json`) that only tightens — a module that grows
past its baseline fails, one that shrinks updates the baseline, and any module
over 1000 lines only warns. The ratchet stops a 400-line module drifting to
900 unnoticed; this hard gate stops anything crossing 1000 at all. They run
together, not as duplicates of each other.

## `scripts/pin_audit.py` — the pre-split safety net

Before splitting an oversized module, `scripts/pin_audit.py <path>` answers
"what in the test suite is coupled to this exact file, and how?" — read-only,
stdlib-only, never writes or edits anything. It reports:

1. **Path literals** — every test file that contains the module path as a
   string literal (e.g. `"colleague/loop.py"`), which a split can silently
   invalidate.
2. **Module-object source reads** — tests that import the module and then read
   its source (`__file__`, `getsource`, a `Path(...).read_text()`), which
   change meaning if the read code moves to a sibling.
3. **Monkeypatch targets** — every `monkeypatch.setattr` / `mock.patch` target
   string naming the module's import path — a target whose implementation
   moves to another module stays green while silently testing nothing.
4. **Allow-list membership** — whether the path appears in
   `tests/test_boundary.py`'s `_SUBPROCESS_ALLOWED` or `_THREADS_ALLOWED`,
   which must move with a subprocess/thread owner that gets split out.
5. A **monkeypatch-effectiveness checklist** flagging every target from (2)
   and (2b) as needing a manual re-check after the split.

Run it before starting a split (`python scripts/pin_audit.py colleague/loop.py`)
to know which tests need updating alongside the code, rather than discovering
a silently-neutered monkeypatch after the fact.

## See also

- [work-and-loop.md](work-and-loop.md) — the tool loop, now split across the
  21 `loop_*` siblings this gate forced.
- [config-resolution.md](config-resolution.md) — config resolution, split
  across the 10 `config_*` siblings.
