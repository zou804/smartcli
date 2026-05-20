import json
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import List

try:
    from ..models import Note
except ImportError:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from smartcli.models import Note


class NoteManager:
    def __init__(self, filepath: str = "data/notes.json"):
        self.filepath = Path(filepath)
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        self._notes: List[Note] = self._load()

    def _load(self) -> List[Note]:
        if not self.filepath.exists():
            return []
        data = json.loads(self.filepath.read_text(encoding="utf-8"))
        return [Note(**item) for item in data]

    def _save(self) -> None:
        self.filepath.write_text(
            json.dumps([asdict(n) for n in self._notes], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add(self, content: str, tags: List[str] = None) -> Note:
        note = Note(id=str(uuid.uuid4())[:8], content=content, tags=tags or [])
        self._notes.append(note)
        self._save()
        return note

    def list_all(self) -> List[Note]:
        return sorted(self._notes, key=lambda n: n.created_at, reverse=True)

    def search(self, keyword: str) -> List[Note]:
        keyword = keyword.lower()
        return [n for n in self._notes if keyword in n.content.lower()]


def handle_note(args) -> None:
    manager = NoteManager()
    if args.action == "add":
        note = manager.add(args.content)
        print(f"笔记已保存 [{note.id}]")
    elif args.action == "list":
        notes = manager.list_all()
        if not notes:
            print("暂无笔记")
        for note in notes:
            print(f"[{note.id}] {note.created_at[:10]} | {note.content[:40]}...")
    elif args.action == "search":
        results = manager.search(args.keyword)
        if not results:
            print(f"未找到 '{args.keyword}'")
        for note in results:
            print(f"[{note.id}] {note.content}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="note", description="笔记管理")
    subparsers = parser.add_subparsers(dest="action", required=True)
    add_parser = subparsers.add_parser("add", help="添加笔记")
    add_parser.add_argument("content", help="笔记内容")
    subparsers.add_parser("list", help="查看笔记")
    search_parser = subparsers.add_parser("search", help="搜索笔记")
    search_parser.add_argument("keyword", help="关键词")
    handle_note(parser.parse_args())


if __name__ == "__main__":
    main()
