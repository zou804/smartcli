from __future__ import annotations

import json

import pytest

from smartcli.commands.note import NoteManager, NoteNotFoundError, NoteStorageError
from smartcli.config import ConfigManager, ConfigurationError


def test_note_add_search_show_and_delete(tmp_path):
    manager = NoteManager(tmp_path / "notes.json")
    note = manager.add("Body", ["PyThOn"], title="Title")
    assert manager.get(note.id) == note
    assert manager.search("title") == [note]
    assert manager.search("python") == [note]
    manager.delete(note.id)
    with pytest.raises(NoteNotFoundError):
        manager.get(note.id)


def test_legacy_notes_are_loaded(tmp_path):
    path = tmp_path / "notes.json"
    path.write_text(
        json.dumps([{"id": "old", "content": "Legacy", "tags": ["v1"], "created_at": "2020"}]),
        encoding="utf-8",
    )
    note = NoteManager(path).get("old")
    assert note.title == "Legacy" and note.source == "manual"
    assert note.model is None and note.role is None


@pytest.mark.parametrize("value", ["not json", "{}", '[{"content": "missing id"}]'])
def test_corrupt_or_invalid_note_data_is_reported(tmp_path, value):
    path = tmp_path / "notes.json"
    path.write_text(value, encoding="utf-8")
    with pytest.raises(NoteStorageError):
        NoteManager(path)


def test_config_defaults_update_and_validation(tmp_path):
    manager = ConfigManager(tmp_path / "config.json")
    assert manager.load() == {"default_model": "deepseek", "default_role": "default"}
    assert manager.set("default_model", "glm")["default_model"] == "glm"
    assert manager.set("default_role", "review")["default_role"] == "review"
    with pytest.raises(ConfigurationError, match="Unsupported"):
        manager.set("secret", "value")
    with pytest.raises(ConfigurationError, match="Unknown model"):
        manager.set("default_model", "missing")


def test_note_memory_is_not_updated_when_persist_fails(tmp_path, monkeypatch):
    manager = NoteManager(tmp_path / "notes.json")
    monkeypatch.setattr(manager, "_save", lambda notes: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        manager.add("not persisted")
    assert manager.list_all() == []


def test_note_memory_is_not_deleted_when_persist_fails(tmp_path, monkeypatch):
    manager = NoteManager(tmp_path / "notes.json")
    note = manager.add("keep me")
    monkeypatch.setattr(manager, "_save", lambda notes: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        manager.delete(note.id)
    assert manager.get(note.id) == note


def test_corrupt_config_is_reported(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="JSON object"):
        ConfigManager(path).load()


def test_empty_legacy_note_does_not_raise_an_internal_error(tmp_path):
    path = tmp_path / "notes.json"
    path.write_text(
        json.dumps([{"id": "empty", "content": "", "tags": None}]), encoding="utf-8"
    )
    note = NoteManager(path).get("empty")
    assert note.title == "Untitled" and note.tags == []


def test_invalid_note_fields_are_reported_as_storage_errors(tmp_path):
    path = tmp_path / "notes.json"
    path.write_text(json.dumps([{"id": "bad", "tags": "python"}]), encoding="utf-8")
    with pytest.raises(NoteStorageError, match="tags"):
        NoteManager(path)
