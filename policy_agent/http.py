"""HTTP collection with retries and evidence-safe response handling."""
from dataclasses import dataclass
import time
from typing import Optional
import requests

@dataclass
class FetchResult:
    url: str
    final_url: str
    status: Optional[int]
    content_type: str
    text: str
    content: bytes
    elapsed_ms: int
    error: str = ""

DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"

def fetch(url: str, timeout: int = 20, retries: int = 2, backoff: float = 1.5, user_agent: str = DEFAULT_UA) -> FetchResult:
    last_error = ""
    for attempt in range(retries + 1):
        started = time.perf_counter()
        try:
            response = requests.get(url, timeout=timeout, headers={"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8"}, allow_redirects=True)
            if response.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                response.close()
                time.sleep(backoff * (attempt + 1))
                continue
            raw = response.content
            encoding = response.encoding or response.apparent_encoding or "utf-8"
            if str(encoding).lower() in ("iso-8859-1", "latin-1"):
                encoding = response.apparent_encoding or "utf-8"
            try:
                text = raw.decode(encoding, errors="replace")
            except LookupError:
                text = raw.decode("utf-8", errors="replace")
            error = "" if 200 <= response.status_code < 300 else f"HTTP_{response.status_code}"
            return FetchResult(url, response.url, response.status_code, response.headers.get("content-type", ""), text, raw, int((time.perf_counter()-started)*1000), error)
        except Exception as exc:
            last_error = str(exc)
            if attempt < retries:
                time.sleep(backoff * (attempt + 1))
    return FetchResult(url, url, None, "", "", b"", 0, last_error)
