import json
import time
from pathlib import Path
from typing import Optional, Any

class CacheManager:
    def __init__(self, cache_dir: str = "data/cache", ttl: int = 3600):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl

    def get(self, key: str) -> Optional[dict]:
        filepath = self.cache_dir / f"{key}.json"
        if not filepath.exists():
            return None
        data = json.loads(filepath.read_text(encoding="utf-8"))
        if time.time() - data.get("timestamp", 0) > self.ttl:
            filepath.unlink()
            return None
        return data.get("value")

    def set(self, key: str, value: Any):
        filepath = self.cache_dir / f"{key}.json"
        filepath.write_text(
            json.dumps({
                "timestamp": time.time(),
                "value": value if isinstance(value, dict) else value.__dict__
            }, ensure_ascii=False),
            encoding="utf-8"
        )
