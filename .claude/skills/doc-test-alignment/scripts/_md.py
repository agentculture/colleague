"""_md.py — Markdown utilities for doc-test-alignment.

Provides:
  iter_fenced_blocks(text, lang) — iterate over fenced code blocks of a given language.
  parse_frontmatter(text)        — parse YAML-ish frontmatter, including folded scalars.
"""

from __future__ import annotations

from typing import Iterator

__all__ = ["iter_fenced_blocks", "parse_frontmatter"]


def iter_fenced_blocks(text: str, lang: str = "bash") -> Iterator[tuple[int, str]]:
    """Yield (opening_line_1based, body_text) for each fenced code block.

    A block opens on a line whose content is ``` followed by an info string that
    starts with `lang`. When lang=="bash", blocks with info string "sh" are also
    accepted (```sh is a common alias for ```bash). A block closes on the next
    line that is exactly ```.

    The body_text does NOT include the fence lines themselves.
    """
    lines = text.splitlines()
    in_block = False
    block_start = 0
    body_lines: list[str] = []

    # Languages treated as equivalent to "bash"
    if lang == "bash":
        accepted = frozenset({"bash", "sh"})
    else:
        accepted = frozenset({lang})

    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not in_block:
            # Check for opening fence: starts with ```<lang-info>
            if stripped.startswith("```"):
                info = stripped[3:].strip()
                if info in accepted:
                    in_block = True
                    block_start = i
                    body_lines = []
        else:
            # Inside a block: closing fence is exactly ```
            if stripped == "```":
                yield (block_start, "\n".join(body_lines) + "\n" if body_lines else "")
                in_block = False
                body_lines = []
            else:
                body_lines.append(line)
    # Unclosed block: not yielded (malformed markdown)


def parse_frontmatter(text: str) -> dict:
    """Parse simple YAML-ish frontmatter from the start of a Markdown file.

    If the file starts with a ``---`` line, reads key: value pairs until the
    closing ``---``. Handles:
      - Plain scalars: ``key: value``
      - Quoted scalars: surrounding ``"`` or ``'`` are stripped.
      - Folded scalars for description: when the value after ``key:`` is
        ``>``, ``|``, ``>-``, or ``|-`` (or empty), subsequent indented lines
        are consumed:
          - Folded (``>``, ``>-``): lines joined with spaces.
          - Literal (``|``, ``|-``): lines joined with newlines.

    Returns a dict of parsed keys (at minimum ``description`` when present).
    Returns ``{}`` when no frontmatter is found.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}

    result: dict = {}
    i = 1
    n = len(lines)

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if stripped == "---":
            # End of frontmatter
            break

        # Look for key: value
        if ":" in stripped:
            key, _, raw_value = stripped.partition(":")
            key = key.strip()
            raw_value = raw_value.strip()

            # Detect folded/literal scalar indicators
            if raw_value in (">", ">-", "|", "|-", ""):
                # Block scalar: consume subsequent indented lines
                style = raw_value  # ">" / ">-" / "|" / "|-" / ""
                i += 1
                block_lines: list[str] = []
                while i < n:
                    block_line = lines[i]
                    # Check indentation: block scalar lines must be more indented
                    # than the key (or have at least one leading space)
                    if block_line == "---" or (block_line and not block_line[0].isspace()):
                        break
                    # Strip consistent leading indent (2 spaces typical)
                    block_lines.append(block_line.strip())
                    i += 1
                # Join according to style
                if style in ("|", "|-"):
                    value = "\n".join(block_lines)
                else:
                    # Folded: join with spaces
                    value = " ".join(part for part in block_lines if part)
                result[key] = value
                continue
            else:
                # Plain or quoted scalar
                value = _strip_quotes(raw_value)
                result[key] = value

        i += 1

    return result


def _strip_quotes(s: str) -> str:
    """Strip surrounding double or single quotes from a scalar value."""
    if len(s) >= 2:
        if (s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'"):
            return s[1:-1]
    return s
