"""Rich rendering for interactive output with plain-text fallbacks."""

from __future__ import annotations

import re
from typing import TextIO

from rich.console import Console, ConsoleOptions, RenderResult
from rich.markdown import Heading, ListItem, Markdown
from rich.text import Text
from rich.theme import Theme

_SHORT_TERM_RE = re.compile(r"([\uFF08(])([A-Za-z][A-Za-z0-9+./# -]{0,30})([\uFF09)])")
_TERMINAL_THEME = Theme(
    {
        "markdown.h3": "bold bright_cyan",
        "markdown.heading.marker": "bold cyan",
        "markdown.strong": "bold bright_white",
        "markdown.code": "bold bright_cyan",
        "markdown.item.bullet": "bold cyan",
    }
)


class _CompactHeading(Heading):
    """A compact heading with a stable visual marker."""

    new_line = False

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        heading = Text("| ", style="markdown.heading.marker")
        heading.append_text(self.text)
        yield heading


class _CompactListItem(ListItem):
    """Prevent swallowed list paragraphs from adding leading whitespace."""

    new_line = False


class _TerminalMarkdown(Markdown):
    elements = {
        **Markdown.elements,
        "heading_open": _CompactHeading,
        "list_item_open": _CompactListItem,
    }


def render_markdown(value: str, stream: TextIO) -> None:
    """Render Markdown on a terminal and preserve source Markdown when redirected."""
    text = str(value)
    if not getattr(stream, "isatty", lambda: False)():
        print(text, file=stream)
        return

    terminal_text = _SHORT_TERM_RE.sub(_keep_short_term_together, text)
    console = Console(file=stream, highlight=False, theme=_TERMINAL_THEME)
    console.print(_TerminalMarkdown(terminal_text))


def _keep_short_term_together(match: re.Match[str]) -> str:
    term = match.group(2).replace(" ", "\N{NO-BREAK SPACE}")
    return f"{match.group(1)}{term}{match.group(3)}"
