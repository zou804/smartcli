from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List

@dataclass
class Note:
    id: str
    content: str
    tags: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

@dataclass
class WeatherData:
    city: str
    temperature: str
    description: str
    humidity: str
    fetched_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M"))
