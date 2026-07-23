"""Local knowledge note storage."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import asdict
from pathlib import Path

from platformdirs import user_data_path

from ..models import Note


class NoteStorageError(RuntimeError):
    """Raised when note data cannot be read or written."""


class NoteNotFoundError(LookupError):
    """Raised when a note ID does not exist."""


class NoteManager:
    def __init__(self, filepath: str | Path | None = None) -> None:
        self.filepath = Path(filepath) if filepath else user_data_path("smartcli") / "notes.json"
        self._notes = self._load()

    def _load(self) -> list[Note]:
        if not self.filepath.exists():
            return []
        try:
            data = json.loads(self.filepath.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise NoteStorageError(f"Cannot read notes: {exc}") from exc
        if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
            raise NoteStorageError("Notes file must contain a JSON array of objects")
        notes = [Note.from_dict(item) for item in data]
        if any(not note.id for note in notes):
            raise NoteStorageError("Every note must have an ID")
        return notes

    def _save(self, notes: list[Note]) -> None:
        try:
            self.filepath.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(
                prefix=f".{self.filepath.name}.", dir=self.filepath.parent
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(
                        [asdict(note) for note in notes], stream, ensure_ascii=False, indent=2
                    )
                    stream.write("\n")
                os.replace(temp_name, self.filepath)
            except BaseException:
                Path(temp_name).unlink(missing_ok=True)
                raise
        except OSError as exc:
            raise NoteStorageError(f"Cannot write notes: {exc}") from exc

    def add(
        self,
        content: str,
        tags: list[str] | None = None,
        *,
        title: str | None = None,
        source: str = "manual",
        model: str | None = None,
        role: str | None = None,
    ) -> Note:
        clean_content = content.strip()
        if not clean_content:
            raise ValueError("Note content cannot be empty")
        note = Note(
            id=uuid.uuid4().hex[:8],
            title=(title or clean_content.splitlines()[0])[:80],
            content=clean_content,
            tags=list(dict.fromkeys(tags or [])),
            source=source,
            model=model,
            role=role,
        )
        updated_notes = [*self._notes, note]
        self._save(updated_notes)
        self._notes = updated_notes
        return note

    def list_all(self) -> list[Note]:
        return sorted(self._notes, key=lambda note: note.created_at, reverse=True)

    def get(self, note_id: str) -> Note:
        for note in self._notes:
            if note.id == note_id:
                return note
        raise NoteNotFoundError(f"Note not found: {note_id}")

    def search(self, keyword: str) -> list[Note]:
        needle = keyword.casefold()
        return [
            note
            for note in self._notes
            if needle in "\n".join((note.title, note.content, *note.tags)).casefold()
        ]

    def delete(self, note_id: str) -> None:
        note = self.get(note_id)
        updated_notes = [existing for existing in self._notes if existing is not note]
        self._save(updated_notes)
        self._notes = updated_notes
