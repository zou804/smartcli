import argparse


def main() -> None:
    parser = argparse.ArgumentParser(prog="smartcli", description="个人智能命令行助手")
    subparsers = parser.add_subparsers(dest="command", required=True)

    weather = subparsers.add_parser("weather", help="查询天气")
    weather.add_argument("city", nargs="?", default="广州", help="城市名称")

    note = subparsers.add_parser("note", help="笔记管理")
    note_sub = note.add_subparsers(dest="action", required=True)
    note_add = note_sub.add_parser("add", help="添加笔记")
    note_add.add_argument("content", help="笔记内容")
    note_sub.add_parser("list", help="查看笔记")
    note_search = note_sub.add_parser("search", help="搜索笔记")
    note_search.add_argument("keyword", help="关键词")

    timer = subparsers.add_parser("timer", help="番茄钟")
    timer.add_argument("minutes", type=int, help="分钟数")

    args = parser.parse_args()

    if args.command == "weather":
        from .commands.weather import handle_weather

        handle_weather(args.city)
    elif args.command == "note":
        from .commands.note import handle_note

        handle_note(args)
    elif args.command == "timer":
        from .commands.timer import handle_timer

        handle_timer(args.minutes)


if __name__ == "__main__":
    main()
