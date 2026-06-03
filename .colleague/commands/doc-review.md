---
description: Audit colleague's docs for accuracy vs the actual code/CLI; flag staleness, missing pages, and undocumented operability gaps
arg-hint: "[area, e.g. 'tui' or 'README' — optional; default: all docs]"
constraints: investigation only — do not modify any files, itemize every finding with a concrete file path, distinguish stale-doc from missing-doc
---
You are giving colleague a standing, read-only documentation review — a
*different mind* checking whether the docs still describe what the code does.

Scope: $ARGUMENTS
(If the scope above is empty, audit ALL docs.)

Read and cross-check these against the actual code and CLI behavior:
- README.md and CLAUDE.md (the two narrative surfaces)
- every docs/features/*.md page (and docs/features/README.md, the index)
- CHANGELOG.md (what shipped) vs what the narratives mention
- colleague/explain/catalog.py (the in-CLI `explain` entries) — every verb
  and noun should have one

Report a concrete, itemized list. For each finding give the file path and say
which category it is:
  (a) STALE  — a doc describes behavior the code no longer matches
  (b) MISSING-FROM-README — a feature in code/CHANGELOG that the README narrative
      omits (watch for: the tui command, the feedback/ROI loop, subagents/convoy)
  (c) NO-FEATURE-PAGE — a feature with an explain entry / CLAUDE.md coverage but
      no docs/features/ page
  (d) UNDOCUMENTED-OPERABILITY — something an operator needs in order to RUN
      colleague that is not documented anywhere
  (e) MODERN-UX-GAP — what's missing to make colleague feel modern, accessible
      and convenient: a live cockpit during a drive, popups wired to real events,
      colored/TTY-aware output, an agent-operable TAUI event stream

Do not propose code changes or edit anything — this is an audit.

You MUST deliver the audit by calling the `finish` tool with your report: the
itemized findings (each with a file path and a category a–e), then a short
ranked list of the highest-impact doc fixes. A drive that ends WITHOUT calling
`finish` returns NOTHING and wastes the whole audit — so do not stop after
reading. The moment you have read enough to judge the docs (or you are within a
few steps of your budget), STOP reading and call `finish` with the full report.
Read efficiently — don't re-read a file you've already seen.

If the docs are too large to audit fully within your budget, do NOT silently run
out. Finish with an **INCOMPLETE** report: name the surfaces you covered, the
ones still to do, and suggest how to split the rest (e.g. one sub-audit per doc
surface). A clear "here's what's left and how to split it" is far more useful
than a drive that dies mid-read.
