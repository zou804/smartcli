"""Agent access to the existing local note store."""

from __future__ import annotations

import json
from dataclasses import asdict

from ..commands.note import NoteManager
from .base import Tool, ToolContext, ToolResult


class NoteSearchTool(Tool):
    name = "note_search"
    description = "Search local SmartCLI notes by title, content, or tag."
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer"},
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    def __init__(self, manager: NoteManager) -> None:
        self.manager = manager

    def execute(self, arguments: dict[str, object], context: ToolContext) -> ToolResult:
        del context
        self.validate(arguments)
        limit = max(1, min(int(arguments.get("limit", 10)), 50))
        notes = self.manager.search(str(arguments["query"]))[:limit]
        return ToolResult(True, json.dumps([asdict(note) for note in notes], ensure_ascii=False))
