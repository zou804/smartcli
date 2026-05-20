import time


def handle_timer(minutes: int) -> None:
    seconds = minutes * 60
    print(f"番茄钟开始: {minutes} 分钟")

    try:
        for remaining in range(seconds, 0, -1):
            mins, secs = divmod(remaining, 60)
            print(f"\r   剩余: {mins:02d}:{secs:02d}", end="", flush=True)
            time.sleep(1)
        print("\n时间到!")
    except KeyboardInterrupt:
        print("\n已取消")
