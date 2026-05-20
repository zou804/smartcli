from dataclasses import asdict

from ..models import WeatherData
from ..utils.cache import CacheManager
from ..utils.http import safe_request


def handle_weather(city: str) -> None:
    cache = CacheManager()

    cached = cache.get(f"weather_{city}")
    if cached:
        print(f"{city} 天气（缓存）")
        _display(cached)
        return

    data = safe_request(f"https://wttr.in/{city}?format=j1")
    if not data:
        print("获取天气失败")
        return

    current = data["current_condition"][0]
    weather = WeatherData(
        city=city,
        temperature=current["temp_C"],
        description=current["weatherDesc"][0]["value"],
        humidity=current["humidity"],
    )

    cache.set(f"weather_{city}", weather)
    print(f"{city} 天气（实时）")
    _display(asdict(weather))


def _display(weather: dict) -> None:
    print(f"   天气: {weather['description']}")
    print(f"   温度: {weather['temperature']}°C")
    print(f"   湿度: {weather['humidity']}%")
    print(f"   更新: {weather['fetched_at']}")
