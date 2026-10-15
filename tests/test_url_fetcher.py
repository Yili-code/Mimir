import socket

import pytest

from mimir.errors import PermanentError, RetryableError
from mimir.url_fetcher import _clean_text, _ReadableHTMLParser, validate_public_url


def test_blocks_private_and_non_http_urls(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))],
    )

    with pytest.raises(PermanentError, match="non-public"):
        validate_public_url("http://example.test/")
    with pytest.raises(PermanentError, match="HTTP"):
        validate_public_url("file:///etc/passwd")


def test_rejects_credentials_and_custom_ports(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0))],
    )

    with pytest.raises(PermanentError):
        validate_public_url("https://user:pass@example.com/")
    with pytest.raises(PermanentError):
        validate_public_url("https://example.com:8080/")


def test_dns_failure_is_retryable(monkeypatch):
    def fail(*args, **kwargs):
        raise socket.gaierror("no dns")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    with pytest.raises(RetryableError) as captured:
        validate_public_url("https://example.test/")
    assert captured.value.code == "URL_DNS_FAILURE"


def test_html_parser_discards_scripts_and_extracts_metadata():
    parser = _ReadableHTMLParser()
    parser.feed(
        """<html><head><title>Evidence &amp; Value</title>
        <meta name="author" content="YiLi">
        <meta property="article:published_time" content="2026-10-15">
        <link rel="canonical" href="/canonical"></head>
        <body><script>ignore me</script><main><h1>Claim</h1>
        <p>Useful body.</p></main></body></html>"""
    )

    assert _clean_text(parser.title_parts, 300) == "Evidence & Value"
    assert "ignore me" not in _clean_text(parser.text_parts, 1000)
    assert "Useful body." in _clean_text(parser.text_parts, 1000)
    assert parser.author == "YiLi"
    assert parser.canonical == "/canonical"
