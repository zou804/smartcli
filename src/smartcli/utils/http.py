import json
import random
import time
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import urlopen


def safe_request(url: str, params: Optional[dict] = None) -> Optional[dict]:
    if params:
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}{urlencode(params)}"
    url = _quote_url(url)

    for attempt in range(3):
        try:
            with urlopen(url, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            if attempt == 2:
                return None
            time.sleep(2**attempt + random.uniform(0, 0.5))

    return None


def _quote_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            quote(parts.path),
            quote(parts.query, safe="=&?/:"),
            parts.fragment,
        )
    )
