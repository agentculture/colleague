# A colleague drive never reports an empty-looking success: when the model doesn't call finish, the result still carries the model's actual produced content, and a genuinely empty drive is explicitly signalled rather than disguised as a normal completion

> A colleague drive never reports an empty-looking success: when the model doesn't call finish, the result still carries the model's actual produced content, and a genuinely empty drive is explicitly signalled rather than disguised as a normal completion

## Audience

- an agent or operator who outsourced a drive (explore/review/write/doc-review) and folds the --json result back — they need the model's actual output IN the result, not a step count that hides it in the artifact

## Before → After

- Before: result.summary is set only from the finish tool (loop.py:305) or a no-tool-call terminating turn's content (loop.py:564-565); assistant prose on a turn that ALSO made a tool call is appended to history (loop.py:568) but is never a summary candidate, so a no-finish drive falls back to content-free 'completed in N step(s)' / 'stopped at the N-step budget' (loop.py:782-790) even when stats.answer_chars proves content existed
- After: on a no-finish exit the result surfaces the model's last substantive assistant content as the summary (or a clearly-labelled 'no result produced' when there genuinely was none), so a folded-back --json result is informative without parsing the artifact JSON

## Why it matters

- the --json result is the contract a caller folds back; a successful drive that reads as empty forces every caller to parse steps[] or lose the output — the exact failure that made the #106 explore and doc-review run 1 look empty despite generating content

## Requirements

- track the last substantive assistant content during the loop (a last_assistant candidate updated on every turn with non-empty content, INCLUDING tool-call turns) and use it as the no-finish summary fallback ahead of the generic step-count text
  - honesty: the last-substantive candidate is updated on EVERY turn with non-empty content including tool-call turns, so multi-turn narration that ends on a tool-call turn is still recoverable
- the generic fallback explicitly signals absence: when no content was ever produced, the result marks 'no result produced' (distinguishable by a caller) instead of a step-count that looks like a normal completion
  - honesty: a caller can programmatically distinguish 'no result produced' from a real summary (a stable sentinel/flag), not by string-matching a step count
- all-engines: identical result shape for mock and vllm-openai (pinned by the e2e shape test); no new runtime dep; the artifact records the recovered last-assistant content so the answer is never lost
  - honesty: mock and vllm-openai produce the identical result shape (e2e shape test passes); zero new runtime deps; the artifact persists the recovered last-assistant content

## Honesty conditions

- a drive that generated content but did not call finish surfaces that content in --json result.summary; a drive that generated nothing prints an explicit empty marker — neither reads as a bare step count
- the outsource/explore/review/write caller reads the model's actual output from the --json result without opening .colleague/<id>.json
- verifiable in code: result.summary has exactly the three sources at loop.py:305 / 564-565 / 782-790, and prose on a tool-call turn (line 568) never reaches summary — reproduced by a drive with answer_chars>0 but a step-count summary
- a no-finish drive's result.summary equals the model's last substantive message (not a step count); when no content existed it equals an explicit 'no result produced' marker
- without this a caller folding the result gets nothing actionable on a no-finish drive; with it the same transcript's result carries the answer — shown on a previously-empty-looking explore
- the change touches only result/summary finalization in loop.py; it adds NO finish nudge and NO agtag/escalation call; with the model's finish suppressed, a useful result still comes purely from already-emitted content
- no new model request is issued to build the summary; for a given transcript the turn/token counts are unchanged vs today — only the summary string differs
- a regression test reproduces the old empty-summary case and asserts the new behavior: last-substantive content surfaced when present, explicit empty marker when absent

## Success signals

- a no-finish doc-review/explore that previously printed 'completed in N step(s)' with answer_chars>0 instead surfaces the model's last substantive message in result.summary and --json; a genuinely empty drive prints an explicit 'no result produced' marker a caller can branch on

## Scope / boundaries

- this only changes how the runtime turns an already-produced (or absent) answer into the result/artifact; it does NOT make the model call finish (that is #104 prompt discipline) and does NOT signal a limit (that is #106 escalation)
- no LLM-generated summary and no extra model call to synthesize a result — the fallback reuses content the model already emitted, zero extra turns (consistent with the no-summary-in-degradation rule in CLAUDE.md)

## Non-goals

- not changing finish-discipline prompts (#104), not adding escalation (#106), and not storing full per-turn content beyond what is needed to recover the answer

## Decisions

- summary precedence is finish_summary > last substantive assistant content > explicit 'no result produced' marker; prefer the model's own words over any synthesized text (no extra model call)
