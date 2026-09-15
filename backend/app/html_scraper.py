from __future__ import annotations

import html
import ipaddress
import re
from urllib.parse import urlparse

import httpx


BLOCKED_HOSTNAMES = {"localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254", "::1"}


def is_safe_url(url: str) -> bool:
    """Validate that the URL uses HTTP(S) and does not point to internal/loopback addresses."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        hostname = (parsed.hostname or "").lower().strip()
        if not hostname or hostname in BLOCKED_HOSTNAMES:
            return False
        # Disallow loopback and private IP addresses
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_loopback or ip.is_private or ip.is_reserved or ip.is_link_local:
                return False
        except ValueError:
            pass  # Domain name, not a raw IP
        return True
    except Exception:
        return False


def clean_html(raw_html: str) -> tuple[str, str]:
    """Extract the page title and clean article/body text from raw HTML."""
    # 1. Extract title
    title = ""
    title_match = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.IGNORECASE | re.DOTALL)
    if title_match:
        title = html.unescape(title_match.group(1)).strip()
        title = re.sub(r"\s+", " ", title)

    # 2. Strip non-content tags
    text = re.sub(r"<(script|style|noscript|svg|nav|footer|header|iframe)[^>]*>.*?</\1>", " ", raw_html, flags=re.IGNORECASE | re.DOTALL)

    # 3. Format breaks and blocks
    text = re.sub(r"<(h[1-6]|p|div|section|article|li|tr)[^>]*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)

    # 4. Strip remaining HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)

    # 5. Normalize whitespace
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    cleaned = text.strip()

    if not title:
        # Fallback to first line if available
        first_line = cleaned.split("\n", 1)[0][:60].strip()
        title = first_line or "Web page"

    return title, cleaned


async def fetch_and_clean_url(
    url: str,
    timeout: float = 10.0,
    max_bytes: int = 10 * 1024 * 1024,
) -> tuple[str, str, bytes]:
    """Fetch URL contents safely and return (title, cleaned_text, raw_bytes)."""
    if not is_safe_url(url):
        raise ValueError("The provided URL is invalid or points to a restricted address.")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Personagraph/1.0"
    }
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        response = await client.get(url, headers=headers)
        if response.status_code >= 400:
            raise ValueError(f"URL returned HTTP status {response.status_code}")
        raw_bytes = response.content
        if len(raw_bytes) > max_bytes:
            raise ValueError("The content from the URL exceeds the 10 MB size limit.")
        content_type = response.headers.get("content-type", "").lower()
        if "text/html" in content_type or not content_type:
            raw_text = response.text
            title, cleaned_text = clean_html(raw_text)
        else:
            cleaned_text = response.text.strip()
            title = urlparse(url).path.split("/")[-1] or urlparse(url).hostname or "Document"

    if not cleaned_text:
        raise ValueError("No readable text content found at the URL.")

    return title, cleaned_text, raw_bytes
