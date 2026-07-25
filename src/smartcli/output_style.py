"""Terminal-friendly Markdown rules and response normalization."""

from __future__ import annotations

import re

TERMINAL_MARKDOWN_GUIDELINES = """Format the user-facing answer as lightweight Markdown.
- Optimize the layout for a narrow terminal.
- Use only `###` headings, short paragraphs, and flat `-` lists.
- Use selective `**bold**` and inline code with single backticks.
- Do not use fenced code blocks, tables, rules, blockquotes, or numbered or nested lists.
- Keep exactly one blank line between sections and split long content into short, readable lines.
- Bold only key terms, never an entire paragraph.
- Return only the final user-facing answer without wrapper labels.
- Never expose hidden reasoning or chain-of-thought.
- Prefer plain Markdown that works both in a Rich terminal and in exported text.
"""

_FENCE_RE = re.compile(r"^\s*(?:`{3,}|~{3,}).*$")
_HEADING_RE = re.compile(r"^\s*#{1,6}\s*(.*?)\s*#*\s*$")
_LIST_RE = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+(.*)$")
_QUOTE_RE = re.compile(r"^\s*(?:>\s*)+(.*)$")
_RULE_RE = re.compile(r"^\s*(?:(?:-\s*){3,}|(?:_\s*){3,}|(?:\*\s*){3,})$")
_WHOLE_LINE_BOLD_RE = re.compile(r"^\*\*(\S(?:.*\S)?)\*\*$")
_TABLE_RULE_CELL_RE = re.compile(r"^:?-{3,}:?$")


def normalize_terminal_markdown(value: str) -> str:
    """Normalize model text to SmartCLI's small terminal Markdown subset."""
    source = str(value).replace("\r\n", "\n").replace("\r", "\n")
    lines = source.split("\n")
    normalized: list[str] = []
    index = 0
    in_fence = False

    while index < len(lines):
        line = lines[index].rstrip()
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            index += 1
            continue
        if in_fence:
            normalized.append(line.replace("```", "").replace("~~~", ""))
            index += 1
            continue

        table = _consume_table(lines, index)
        if table is not None:
            table_lines, index = table
            normalized.extend(table_lines)
            continue

        quote = _QUOTE_RE.match(line)
        if quote:
            line = quote.group(1).strip()
        if _RULE_RE.match(line):
            index += 1
            continue

        heading = _HEADING_RE.match(line)
        if heading and heading.group(1):
            line = f"### {heading.group(1)}"
        else:
            list_item = _LIST_RE.match(line)
            if list_item:
                line = f"- {list_item.group(1).strip()}"

        whole_line_bold = _WHOLE_LINE_BOLD_RE.match(line.strip())
        if whole_line_bold:
            line = whole_line_bold.group(1)

        normalized.append(line.replace("```", "").replace("~~~", ""))
        index += 1

    return _collapse_blank_lines(normalized)


def _consume_table(lines: list[str], start: int) -> tuple[list[str], int] | None:
    if start + 1 >= len(lines) or "|" not in lines[start]:
        return None
    headers = _table_cells(lines[start])
    rule_cells = _table_cells(lines[start + 1])
    if not headers or len(headers) != len(rule_cells):
        return None
    if not all(_TABLE_RULE_CELL_RE.fullmatch(cell) for cell in rule_cells):
        return None

    rows: list[list[str]] = []
    index = start + 2
    while index < len(lines) and "|" in lines[index] and lines[index].strip():
        cells = _table_cells(lines[index])
        if len(cells) != len(headers):
            break
        rows.append(cells)
        index += 1

    if not rows:
        return [f"- {header}" for header in headers if header], index

    output = []
    for row in rows:
        fields = [
            f"**{header}**: {cell}"
            for header, cell in zip(headers, row, strict=True)
            if header and cell
        ]
        if fields:
            output.append(f"- {'; '.join(fields)}")
    return output, index


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _collapse_blank_lines(lines: list[str]) -> str:
    output: list[str] = []
    previous_blank = True
    for line in lines:
        blank = not line.strip()
        if blank:
            if not previous_blank:
                output.append("")
        else:
            leading_spaces = len(line) - len(line.lstrip(" "))
            output.append(line.lstrip(" ") if 0 < leading_spaces < 4 else line)
        previous_blank = blank
    while output and not output[-1]:
        output.pop()
    return "\n".join(output)
