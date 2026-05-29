# Convertible knows its destination before it drives: a curated devague tool lets an engine set and converge a goal-frame when a task warrants one, drive toward it, and declare the announcement on arrival — so convertible knows where it's going, not just where it is.

> Convertible knows its destination before it drives: a curated devague tool lets an engine set and converge a goal-frame when a task warrants one, drive toward it, and declare the announcement on arrival — so convertible knows where it's going, not just where it is.

## Audience

- Convertible operators who issue tasks, and the engines (the driving LLM) that carry them out — both need a shared, converged notion of the goal before repo changes begin.

## Before → After

- Before: Today convertible drives straight from a one-line instruction with no notion of a converged destination: it can report where it IS (GPS/telemetry) but not where it is GOING, and 'done' just means the bounded tool-loop finished or hit its step budget, not that a stated goal was reached.
- After: When a task warrants it, the engine sets a destination — captures and converges a devague goal-frame via a curated devague loop tool — before changing the repo, drives toward it, and declares that frame's announcement when the work arrives at the goal.

## Why it matters

- Without a destination, vague tasks get built on vibes and 'done' means 'ran out of steps'. Converging on a goal before driving, and declaring arrival, makes a drive aim at a stated goal — 'converge, don't vibe' applied to repo work, mirroring how devague already specs convertible's own features.

## Requirements

- The devague tool lives in the chassis tool surface (convertible/tools.py + a new convertible module, exactly like culture.py) and is offered to every engine identically — no engine module touches it (the all-engines rule). cwd and resolved identity are injected into every devague subprocess, like the culture tool already does.
  - honesty: The devague tool is wired exactly once in the chassis (tools.py + a new convertible/devague.py) and inherited by mock and vllm-openai identically; adding a third engine needs zero devague code, and identity injection reuses the existing CONVERTIBLE_IDENTITY path.
- Setting a destination is OPTIONAL and engine-judged, not a forced gate on every drive: the engine decides when a task is vague/new enough to need a destination versus when it can just drive. Convertible never blocks a drive purely for lack of a converged destination in this increment.
  - honesty: There is a workable, testable signal for the engine to decide 'this task needs a destination' vs 'just drive' — e.g. a system-prompt instruction plus the devague tool being available — that does NOT require convertible to classify task vagueness in its own code.

## Honesty conditions

- A drive can BOTH set a destination up front AND declare an announcement on arrival within convertible's bounded tool-loop, without breaking the termination guarantee (loop.py h3) and without adding a socket or daemon.
- Operators and engines share ONE goal representation — the same devague frame under .devague/ — not two divergent notions: the operator can set/confirm it, the engine can read and extend it.
- In a non-interactive 'convertible drive', a destination authoritatively CONVERGES only from operator-confirmed claims (set up front); the engine's own proposed claims never self-confirm, preserving devague's user-only confirmation discipline. Engine-only convergence with no human is at most ADVISORY (gaps surfaced), never authoritative.
- Convertible today genuinely has no destination/goal concept — no frame, claim, or convergence anywhere in the Task contract or the loop; GPS/telemetry reports the run, never a stated goal. (Verifiable against contract.py + loop.py.)
- There exist real convertible tasks vague enough that converging first measurably changes the outcome versus driving straight — the destination earns its keep, it is not ceremony bolted onto already-clear tasks.
- Everything convertible needs from devague is reachable through the devague CLI with --json (create/extend/converge/status/export/show a frame); no required capability forces a Python import or a long-lived process.
- The curated allow-list EXCLUDES the user-only moves (confirm/reject): the engine can create/extend/converge/status/export a frame but cannot confirm its own claims through the tool — the user-only discipline is enforced structurally, exactly like the culture tool's agtag/agex allow-list.
- With no destination set, the drive path is provably unchanged: TaskResult shape is identical and no devague subprocess runs — the e2e shape test and zero-deps guard pass untouched; destination data rides in ADDITIVE artifact fields only.

## Success signals

- A drive that set a destination records the converged goal-frame reference and the declared announcement in the JSON artifact (the dashboard); a drive with no destination set is byte-identical to today — the e2e shape test (tests/test_e2e_mock.py) and the zero-deps guard (tests/test_zero_deps.py) both still pass, preserving the all-engines rule.

## Scope / boundaries

- Convertible consumes devague ONLY by shelling out to the operator-installed devague CLI through a curated allow-list of moves (the culture-tool pattern): no runtime dependency, no library import, no socket, no daemon. The .devague/ directory is the persistence; convertible reads no devague Python API and adds no devague.* import.

## Non-goals

- This increment adds the destination tool + chassis wiring only. It does NOT build a devague plan-executor (driving plan waves through engines), a multi-engine router/gearbox, an execution sandbox, or a daemon/server mode — those stay out of v0 scope and need their own re-spec.
