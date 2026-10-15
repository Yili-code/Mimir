from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx

from mimir.errors import PermanentError, RetryableError


@dataclass(frozen=True)
class FetchedPage:
    requested_url: str
    final_url: str
    canonical_url: str
    title: str
    author: str
    published_at: str
    text: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


class _ReadableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.author = ""
        self.published_at = ""
        self.canonical = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attributes = {key.lower(): value or "" for key, value in attrs}
        if tag in {"script", "style", "noscript", "svg", "canvas"}:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag == "link" and attributes.get("rel", "").lower() == "canonical":
            self.canonical = attributes.get("href", "")
        if tag == "meta":
            name = (attributes.get("name") or attributes.get("property") or "").lower()
            content = attributes.get("content", "").strip()
            if name in {"author", "article:author"} and content and not self.author:
                self.author = content
            if name in {"article:published_time", "date", "datepublished", "pubdate"} and content:
                self.published_at = self.published_at or content
        if tag in {"p", "br", "li", "h1", "h2", "h3", "article", "section"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg", "canvas"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag in {"p", "li", "article", "section"}:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
        self.text_parts.append(data)


def _public_addresses(hostname: str) -> list[str]:
    try:
        records = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise RetryableError("URL_DNS_FAILURE", "Unable to resolve URL host") from exc
    addresses = sorted({record[4][0] for record in records})
    if not addresses:
        raise RetryableError("URL_DNS_EMPTY", "URL host resolved to no addresses")
    for address in addresses:
        parsed = ipaddress.ip_address(address)
        if not parsed.is_global:
            raise PermanentError("URL_PRIVATE_ADDRESS", "URL resolves to a non-public address")
    return addresses


def validate_public_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise PermanentError("URL_INVALID", "Only public HTTP and HTTPS URLs are supported")
    if parts.username or parts.password:
        raise PermanentError("URL_CREDENTIALS", "URLs containing credentials are not supported")
    try:
        port = parts.port
    except ValueError as exc:
        raise PermanentError("URL_INVALID_PORT", "Invalid URL port") from exc
    if port not in {None, 80, 443}:
        raise PermanentError("URL_PORT_BLOCKED", "Only ports 80 and 443 are supported")
    _public_addresses(parts.hostname)


def _clean_text(parts: list[str], max_chars: int) -> str:
    raw = " ".join(parts)
    raw = re.sub(r"[\t\r\f\v ]+", " ", raw)
    raw = re.sub(r" *\n *", "\n", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw).strip()
    return raw[:max_chars]


class SafeURLFetcher:
    def __init__(self, *, max_bytes: int, max_chars: int, max_redirects: int = 3) -> None:
        self._max_bytes = max_bytes
        self._max_chars = max_chars
        self._max_redirects = max_redirects

    def fetch(self, url: str) -> FetchedPage:
        requested_url = url
        current = url
        with httpx.Client(follow_redirects=False, timeout=20.0) as client:
            for redirect_count in range(self._max_redirects + 1):
                validate_public_url(current)
                try:
                    with client.stream(
                        "GET",
                        current,
                        headers={"User-Agent": "Mimir/0.1 evidence-first reader"},
                    ) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("location")
                            if not location:
                                raise PermanentError("URL_BAD_REDIRECT", "Redirect has no location")
                            if redirect_count >= self._max_redirects:
                                raise PermanentError("URL_TOO_MANY_REDIRECTS")
                            current = urljoin(current, location)
                            continue
                        if response.status_code in {408, 425, 429} or response.status_code >= 500:
                            raise RetryableError("URL_TRANSIENT_HTTP", str(response.status_code))
                        if response.status_code >= 400:
                            raise PermanentError("URL_UNAVAILABLE", str(response.status_code))
                        content_type = response.headers.get("content-type", "").lower()
                        if (
                            "text/html" not in content_type
                            and "application/xhtml+xml" not in content_type
                        ):
                            raise PermanentError("URL_UNSUPPORTED_TYPE", content_type[:80])
                        body = bytearray()
                        for chunk in response.iter_bytes():
                            body.extend(chunk)
                            if len(body) > self._max_bytes:
                                raise PermanentError("URL_TOO_LARGE")
                        encoding = response.encoding or "utf-8"
                        html = bytes(body).decode(encoding, errors="replace")
                        final_url = str(response.url)
                        break
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    raise RetryableError("URL_NETWORK_FAILURE", type(exc).__name__) from exc
            else:  # pragma: no cover - loop always exits through break or exception
                raise PermanentError("URL_TOO_MANY_REDIRECTS")

        parser = _ReadableHTMLParser()
        parser.feed(html)
        text = _clean_text(parser.text_parts, self._max_chars)
        if len(text) < 80:
            raise PermanentError("URL_INSUFFICIENT_CONTENT")
        canonical = urljoin(final_url, parser.canonical) if parser.canonical else final_url
        if urlsplit(canonical).scheme not in {"http", "https"}:
            canonical = final_url
        return FetchedPage(
            requested_url=requested_url,
            final_url=final_url,
            canonical_url=canonical,
            title=_clean_text(parser.title_parts, 300),
            author=parser.author[:200],
            published_at=parser.published_at[:100],
            text=text,
        )
