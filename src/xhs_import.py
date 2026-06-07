from __future__ import annotations

import html
import ipaddress
import json
import os
import re
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


ALLOWED_HOSTS = ("xiaohongshu.com", "xhslink.com")


def ssl_context() -> ssl.SSLContext:
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


class MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, str] = {}
        self.json_ld: list[str] = []
        self._in_json_ld = False
        self._json_ld_parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "meta":
            raw_key = (
                attributes.get("property")
                or attributes.get("name")
                or attributes.get("itemprop")
            )
            key = raw_key.lower() if raw_key else ""
            content = attributes.get("content", "").strip()
            if key and content and key not in self.meta:
                self.meta[key] = html.unescape(content)
        if (
            tag.lower() == "script"
            and attributes.get("type", "").lower() == "application/ld+json"
        ):
            self._in_json_ld = True
            self._json_ld_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_json_ld:
            self._json_ld_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._in_json_ld:
            value = "".join(self._json_ld_parts).strip()
            if value:
                self.json_ld.append(value)
            self._in_json_ld = False
            self._json_ld_parts = []


def validate_xhs_url(url: str) -> str:
    cleaned = url.strip()
    parsed = urllib.parse.urlparse(cleaned)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not any(
        host == allowed or host.endswith(f".{allowed}") for allowed in ALLOWED_HOSTS
    ):
        raise ValueError("Expected a xiaohongshu.com or xhslink.com note URL.")
    return cleaned


def canonicalize_xhs_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if (parsed.hostname or "").lower().endswith("xiaohongshu.com"):
        return urllib.parse.urlunparse(
            (parsed.scheme or "https", parsed.netloc, parsed.path, "", "", "")
        )
    return url


def fetch_xhs_note(url: str, timeout: int = 20) -> dict[str, Any]:
    source_url = validate_xhs_url(url)
    request = urllib.request.Request(
        source_url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 Chrome/136.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        },
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout,
            context=ssl_context(),
        ) as response:
            final_url = response.geturl()
            charset = response.headers.get_content_charset() or "utf-8"
            page = response.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"XHS page returned HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not open XHS link: {exc.reason}") from exc

    parsed = parse_xhs_html(page)
    if not parsed["text"] and not parsed["video_url"]:
        raise RuntimeError(
            "The XHS page exposed neither note text nor a downloadable video. "
            "It may require login or be blocked; provide --text/--text-file or "
            "--video-file."
        )
    return parsed | {"url": canonicalize_xhs_url(final_url)}


def parse_xhs_html(page: str) -> dict[str, Any]:
    parser = MetadataParser()
    parser.feed(page)

    json_ld = extract_json_ld(parser.json_ld)
    title = first_nonempty(
        json_ld.get("headline"),
        json_ld.get("name"),
        parser.meta.get("og:title"),
        parser.meta.get("twitter:title"),
        best_embedded_string(page, ("title",)),
    )
    text = first_nonempty(
        json_ld.get("articleBody"),
        json_ld.get("description"),
        best_embedded_string(page, ("desc", "articleBody", "description")),
        parser.meta.get("og:description"),
        parser.meta.get("description"),
    )
    author = first_nonempty(
        author_name(json_ld.get("author")),
        parser.meta.get("article:author"),
        embedded_string(page, "nickname"),
    )
    video_url = first_nonempty(
        parser.meta.get("og:video:url"),
        parser.meta.get("og:video"),
        best_video_url(page),
    )

    cleaned_title = clean_text(title)
    cleaned_text = clean_text(text)
    if cleaned_text == cleaned_title:
        cleaned_text = ""
    return {
        "title": cleaned_title,
        "text": cleaned_text,
        "author": clean_text(author),
        "kind": "video" if video_url else "article",
        "video_url": decode_embedded_url(video_url),
    }


def decode_embedded_url(value: str) -> str:
    cleaned = html.unescape(value or "").replace("\\/", "/")
    try:
        decoded = json.loads(f'"{cleaned}"') if "\\" in cleaned else cleaned
    except json.JSONDecodeError:
        decoded = cleaned
    return decoded.strip()


def best_video_url(page: str) -> str:
    keys = (
        "masterUrl",
        "originVideoUrl",
        "videoUrl",
        "url",
    )
    candidates = [
        decode_embedded_url(value)
        for key in keys
        for value in embedded_strings(page, key)
    ]
    useful = [
        value
        for value in candidates
        if value.startswith(("http://", "https://"))
        and (
            ".mp4" in value.lower()
            or "video" in urllib.parse.urlparse(value).netloc.lower()
            or "sns-video" in value.lower()
        )
    ]
    return useful[0] if useful else ""


def download_xhs_video(
    video_url: str,
    destination: Path,
    referer: str,
    timeout: int = 120,
) -> Path:
    max_bytes = int(os.environ.get("VOICE_NOTES_MAX_VIDEO_BYTES", 500_000_000))
    validate_media_url(video_url)
    request = urllib.request.Request(
        video_url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 Chrome/136.0 Safari/537.36"
            ),
            "Referer": referer,
        },
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout,
            context=ssl_context(),
        ) as response:
            content_type = response.headers.get("Content-Type", "")
            if "video" not in content_type and "octet-stream" not in content_type:
                raise RuntimeError(
                    f"XHS media URL returned unexpected content type: {content_type}"
                )
            content_length = int(response.headers.get("Content-Length") or 0)
            if content_length > max_bytes:
                raise RuntimeError(
                    f"XHS video exceeds {max_bytes} byte download limit."
                )
            written = 0
            with destination.open("wb") as handle:
                while chunk := response.read(1024 * 1024):
                    written += len(chunk)
                    if written > max_bytes:
                        raise RuntimeError(
                            f"XHS video exceeds {max_bytes} byte download limit."
                        )
                    handle.write(chunk)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"XHS video download returned HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not download XHS video: {exc.reason}") from exc
    return destination


def validate_media_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    hostname = parsed.hostname or ""
    if parsed.scheme not in {"http", "https"} or not hostname:
        raise RuntimeError("XHS media URL must be HTTP(S).")
    if hostname.lower() == "localhost":
        raise RuntimeError("XHS media URL cannot target localhost.")
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(
                hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
            )
        }
    except socket.gaierror as exc:
        raise RuntimeError(f"Could not resolve XHS media host: {hostname}") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise RuntimeError("XHS media URL resolved to a non-public address.")


def extract_json_ld(blocks: list[str]) -> dict[str, Any]:
    for block in blocks:
        try:
            value = json.loads(block)
        except json.JSONDecodeError:
            continue
        candidates = value if isinstance(value, list) else [value]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            graph = candidate.get("@graph")
            if isinstance(graph, list):
                candidates.extend(item for item in graph if isinstance(item, dict))
            if any(candidate.get(key) for key in ("articleBody", "description", "headline")):
                return candidate
    return {}


def embedded_string(page: str, key: str) -> str:
    values = embedded_strings(page, key)
    return values[0] if values else ""


def embedded_strings(page: str, key: str) -> list[str]:
    matches = re.finditer(
        rf'"{re.escape(key)}"\s*:\s*"((?:\\.|[^"\\])*)"',
        page,
        re.IGNORECASE,
    )
    values = []
    for match in matches:
        try:
            values.append(json.loads(f'"{match.group(1)}"'))
        except json.JSONDecodeError:
            values.append(html.unescape(match.group(1)))
    return values


def best_embedded_string(page: str, keys: tuple[str, ...]) -> str:
    boilerplate = {
        "3 亿人的生活经验，都在小红书",
        "3亿人的生活经验，都在小红书",
        "小红书",
        "搜索小红书",
    }
    candidates = [
        clean_text(value)
        for key in keys
        for value in embedded_strings(page, key)
    ]
    useful = [
        value
        for value in candidates
        if value and value not in boilerplate and not value.startswith("小红书网页版")
    ]
    return max(useful, key=len, default="")


def author_name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or "")
    if isinstance(value, list):
        for item in value:
            name = author_name(item)
            if name:
                return name
    if isinstance(value, str):
        return value
    return ""


def first_nonempty(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value
    return ""


def clean_text(value: str) -> str:
    cleaned = html.unescape(value or "")
    cleaned = cleaned.replace("\\n", "\n").replace("\\t", " ")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()
