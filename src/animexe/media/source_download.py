"""Save directly accessible, unencrypted episode media for AniMeXe processing.

This module deliberately does not scrape cross-origin player iframes, extract
hidden provider APIs, or handle DRM/encrypted HLS. Several 7xAnime sources are
embed pages, not downloadable media URLs.
"""
from __future__ import annotations

import ipaddress
import re
import shutil
import subprocess
from pathlib import Path
from typing import Mapping
from urllib.parse import urljoin, urlsplit

import requests


class SourceDownloadError(RuntimeError):
    """Raised when a supplied media URL cannot be saved safely."""


SEVENX_PROVIDER_MODES: dict[str, str] = {
    "anixo": "embed-only",
    "megavid": "embed-only",
    "animeparadise": "direct-hls-candidate",
    "megaflix": "embed-only",
    "tryembed": "embed-only",
    "cinexstream": "embed-only",
    "nontongo": "embed-only",
}

_EMBED_HOST_PROVIDER = {
    "anixo.buzz": "anixo",
    "megavid.buzz": "megavid",
    "megaflix.buzz": "megaflix",
    "www.megaflix.buzz": "megaflix",
    "tryembed.us.cc": "tryembed",
    "cinextream.cc": "cinexstream",
    "nontongo.win": "nontongo",
    "animeparadise.moe": "animeparadise",
    "www.animeparadise.moe": "animeparadise",
}
_VIDEO_SUFFIXES = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi"}
_HLS_CONTENT_TYPES = {
    "application/vnd.apple.mpegurl",
    "application/x-mpegurl",
    "audio/mpegurl",
    "audio/x-mpegurl",
}
_KEY_TAG = re.compile(r"^#EXT-X-(?:SESSION-)?KEY\s*:\s*(.*)$", re.IGNORECASE)
_URI_ATTRIBUTE = re.compile(r'(?:^|,)\s*URI="([^"]+)"', re.IGNORECASE)
_DEFAULT_USER_AGENT = "AniMeXe/0.1"
_MAX_PLAYLIST_BYTES = 2 * 1024 * 1024


def _validated_url(url: str) -> str:
    value = url.strip()
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise SourceDownloadError("Source must be a valid HTTP(S) media URL.")
    if parsed.username or parsed.password:
        raise SourceDownloadError("URLs containing embedded credentials are not supported.")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
        raise SourceDownloadError("Localhost URLs are not allowed.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise SourceDownloadError("Private or non-public IP addresses are not allowed.")
    return value


def _provider_embed_error(url: str) -> str | None:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    path = parsed.path.lower()
    # AnimeParadise is only treated as an HLS candidate at its stream endpoint.
    if host == "stream.animeparadise.moe" and (
        path == "/m3u8" or path.endswith(".m3u8")
    ):
        return None
    if host in _EMBED_HOST_PROVIDER:
        provider = _EMBED_HOST_PROVIDER[host]
        return (
            f"{provider} URL is an embedded player/catalog page, not a direct media file. "
            "AniMeXe will not scrape the iframe to extract a hidden stream. Supply a direct, "
            "permitted MP4 or unencrypted HLS URL instead."
        )
    return None


def _kind_from_url(url: str, content_type: str | None = None) -> str | None:
    parsed = urlsplit(url)
    path = parsed.path.lower()
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if path.endswith(".mpd") or "dash+xml" in mime:
        raise SourceDownloadError(
            "DASH sources are not supported by this saver; DRM/access-control handling is intentionally excluded."
        )
    if path.endswith(".m3u8") or path == "/m3u8" or mime in _HLS_CONTENT_TYPES:
        return "hls"
    if Path(path).suffix in _VIDEO_SUFFIXES or mime.startswith("video/"):
        return "file"
    if mime in {"application/octet-stream", "binary/octet-stream"}:
        return "file"
    return None


def _request_headers(extra: Mapping[str, str] | None) -> dict[str, str]:
    headers = {"User-Agent": _DEFAULT_USER_AGENT}
    for key, value in (extra or {}).items():
        name = str(key).strip()
        text = str(value).strip()
        if not name or not text:
            continue
        if any(char in name + text for char in "\r\n"):
            raise SourceDownloadError("HTTP header names and values cannot contain newlines.")
        headers[name] = text
    return headers


def _playlist_text(url: str, headers: Mapping[str, str], timeout: int) -> tuple[str, str]:
    try:
        response = requests.get(url, headers=dict(headers), timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise SourceDownloadError(f"Could not read the HLS playlist ({type(exc).__name__}).") from exc
    final_url = _validated_url(response.url or url)
    content_type = response.headers.get("Content-Type", "")
    body = response.content
    if len(body) > _MAX_PLAYLIST_BYTES:
        raise SourceDownloadError("HLS playlist is unexpectedly large; refusing to inspect it.")
    text = body.decode(response.encoding or "utf-8", errors="replace")
    if text.lstrip().lower().startswith(("<!doctype html", "<html")) or "text/html" in content_type.lower():
        raise SourceDownloadError("The URL returned an HTML page, not an HLS playlist.")
    if not text.lstrip().startswith("#EXTM3U"):
        raise SourceDownloadError("The URL did not return a valid HLS playlist.")
    return text, final_url


def _check_unencrypted_hls(
    url: str,
    headers: Mapping[str, str],
    timeout: int,
    *,
    depth: int = 0,
    seen: set[str] | None = None,
) -> None:
    """Reject encrypted playlists and inspect nested variant/media playlists."""
    if depth > 4:
        raise SourceDownloadError("HLS playlist nesting exceeded the safety limit.")
    visited = seen if seen is not None else set()
    if url in visited:
        return
    if len(visited) >= 32:
        raise SourceDownloadError("HLS playlist has too many nested variants.")
    visited.add(url)
    text, final_url = _playlist_text(url, headers, timeout)
    for line in text.splitlines():
        match = _KEY_TAG.match(line.strip())
        if match:
            method = re.search(r"(?:^|,)\s*METHOD=([^,\s]+)", match.group(1), re.IGNORECASE)
            if not method or method.group(1).strip('"').upper() != "NONE":
                raise SourceDownloadError(
                    "Encrypted or ambiguous HLS key signaling is unsupported. AniMeXe only saves clearly unencrypted streams."
                )

    lines = [line.strip() for line in text.splitlines()]
    children: list[str] = []
    next_is_variant = False
    for line in lines:
        if not line or line.startswith("#"):
            if line.upper().startswith("#EXT-X-STREAM-INF:"):
                next_is_variant = True
            elif line.upper().startswith("#EXT-X-I-FRAME-STREAM-INF:") or line.upper().startswith("#EXT-X-MEDIA:"):
                match = _URI_ATTRIBUTE.search(line)
                if match:
                    candidate = urljoin(final_url, match.group(1))
                    candidate_path = urlsplit(candidate).path.lower()
                    if candidate_path.endswith(".m3u8") or candidate_path == "/m3u8":
                        children.append(candidate)
            continue
        if next_is_variant:
            children.append(urljoin(final_url, line))
        next_is_variant = False

    for child in children:
        child = _validated_url(child)
        _check_unencrypted_hls(
            child, headers, timeout, depth=depth + 1, seen=visited
        )


def _temp_path(target: Path, suffix: str) -> Path:
    return target.with_name(f".{target.stem}.partial{suffix}")


def download_media_source(
    media_url: str,
    output_path: str | Path,
    *,
    source_provider: str | None = None,
    headers: Mapping[str, str] | None = None,
    timeout_seconds: int = 60,
    max_bytes: int = 8 * 1024**3,
) -> dict[str, object]:
    """Save a direct video file or unencrypted HLS playlist to a local episode file.

    Callers must only supply media they are entitled to download and process.
    HLS is remuxed with FFmpeg; source audio is kept for analysis, while the
    later visual-cut/render stages are responsible for removing source audio.
    """
    url = _validated_url(media_url)
    embed_error = _provider_embed_error(url)
    if embed_error:
        raise SourceDownloadError(embed_error)
    if source_provider:
        provider_key = source_provider.strip().lower()
        if provider_key not in SEVENX_PROVIDER_MODES:
            raise SourceDownloadError(f"Unknown 7xAnime source provider: {source_provider}")

    if timeout_seconds < 1:
        raise SourceDownloadError("timeout_seconds must be positive.")
    if max_bytes < 1:
        raise SourceDownloadError("max_bytes must be positive.")

    request_headers = _request_headers(headers)
    kind = _kind_from_url(url)
    head_response = None
    if kind is None:
        try:
            head_response = requests.head(
                url, headers=request_headers, timeout=timeout_seconds, allow_redirects=True
            )
            if head_response.ok:
                final_url = _validated_url(head_response.url or url)
                kind = _kind_from_url(final_url, head_response.headers.get("Content-Type"))
        except requests.RequestException:
            kind = None
        finally:
            if head_response is not None:
                head_response.close()
    if kind is None:
        raise SourceDownloadError(
            "Could not identify a direct video file or HLS playlist. Embed pages and unknown content types are not downloadable."
        )

    target = Path(output_path).expanduser().resolve()
    if not target.suffix:
        target = target.with_suffix(".mkv" if kind == "hls" else ".mp4")
    target.parent.mkdir(parents=True, exist_ok=True)

    if kind == "hls":
        if target.suffix.lower() not in {".mkv", ".mp4"}:
            raise SourceDownloadError("HLS output must use .mkv or .mp4.")
        # Validate the playlist before checking local tooling so encrypted
        # streams fail closed even on machines without FFmpeg installed.
        _check_unencrypted_hls(url, request_headers, timeout_seconds)
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise SourceDownloadError("FFmpeg is required to save HLS sources.")
        muxer = "matroska" if target.suffix.lower() == ".mkv" else "mp4"
        tmp = _temp_path(target, target.suffix)
        tmp.unlink(missing_ok=True)
        command = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
        header_text = "".join(f"{name}: {value}\r\n" for name, value in request_headers.items())
        if header_text:
            command.extend(["-headers", header_text])
        command.extend([
            "-i", url,
            "-map", "0:v:0",
            "-map", "0:a?",
            "-map", "0:s?",
            "-c", "copy",
        ])
        if muxer == "mp4":
            command.extend(["-movflags", "+faststart"])
        command.extend(["-f", muxer, str(tmp)])
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=timeout_seconds * 30
            )
            if completed.returncode != 0:
                detail = (completed.stderr or "").strip().splitlines()
                message = detail[-1][:300] if detail else "FFmpeg could not read the media."
                raise SourceDownloadError(f"HLS download failed: {message}")
            if not tmp.is_file() or tmp.stat().st_size == 0:
                raise SourceDownloadError("FFmpeg finished without producing a media file.")
            if tmp.stat().st_size > max_bytes:
                raise SourceDownloadError(f"Downloaded media exceeds the {max_bytes} byte limit.")
            tmp.replace(target)
        except subprocess.TimeoutExpired as exc:
            raise SourceDownloadError("HLS download timed out.") from exc
        finally:
            tmp.unlink(missing_ok=True)
    else:
        tmp = _temp_path(target, target.suffix)
        tmp.unlink(missing_ok=True)
        response = None
        total = 0
        try:
            response = requests.get(
                url, headers=request_headers, timeout=(10, timeout_seconds), stream=True
            )
            response.raise_for_status()
            final_url = _validated_url(response.url or url)
            if _provider_embed_error(final_url):
                raise SourceDownloadError("The media URL redirected to an embedded player page.")
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
            if content_type in {"text/html", "application/json", "text/json"}:
                raise SourceDownloadError("The URL returned a webpage or JSON, not a video file.")
            content_length = response.headers.get("Content-Length")
            if content_length and content_length.isdigit() and int(content_length) > max_bytes:
                raise SourceDownloadError(f"Source exceeds the {max_bytes} byte limit.")
            with tmp.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_bytes:
                        raise SourceDownloadError(f"Source exceeds the {max_bytes} byte limit.")
                    handle.write(chunk)
            if total == 0:
                raise SourceDownloadError("The source returned an empty response.")
            tmp.replace(target)
        except requests.RequestException as exc:
            raise SourceDownloadError(f"Direct video download failed ({type(exc).__name__}).") from exc
        finally:
            if response is not None:
                response.close()
            tmp.unlink(missing_ok=True)

    return {
        "provider": source_provider or "direct-url",
        "source_kind": kind,
        "output_path": str(target),
        "size_bytes": target.stat().st_size,
        "source_audio_preserved_for_analysis": True,
        "final_render_audio_policy": "visual-cut/render stages remove source episode audio",
    }


__all__ = [
    "SEVENX_PROVIDER_MODES",
    "SourceDownloadError",
    "download_media_source",
]
