from __future__ import annotations

import io

from rich.text import Text

from smartcli.rendering import render_markdown


class TerminalBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_render_markdown_uses_rich_for_terminal_output():
    output = TerminalBuffer()
    render_markdown(
        "### Result\n\nUse **doctor** and `--json` for (AI Agent)."
        "\n\n### Components\n\n- model",
        output,
    )
    rendered = Text.from_ansi(output.getvalue()).plain
    assert rendered.startswith("| Result\nUse")
    assert f"| Components\n {chr(0x2022)} model" in rendered
    assert "doctor" in rendered
    assert "--json" in rendered
    assert "AI\N{NO-BREAK SPACE}Agent" in rendered
    assert "###" not in rendered
    assert "**" not in rendered


def test_render_markdown_preserves_source_when_redirected():
    output = io.StringIO()
    render_markdown("### Result\n\nUse **doctor**.", output)
    assert output.getvalue() == "### Result\n\nUse **doctor**.\n"
