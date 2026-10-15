"""Acquire an already-resolved, directly accessible episode media URL.

This deliberately does not scrape player pages, bypass access controls, or handle DRM.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

import requests

CHUNK_SIZE = 1024 * 1024
DEFAULT_MAX_BYTES = 4 * 1024 * 1024 * 1024
TIMEOUT_SECONDS = (15, 60)


class MediaDownloadError(RuntimeError):
    """Raised when a direct media source cannot be safely acquired."""


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise MediaDownloadError("source must be a direct HTTP(S) media URL")
    if parsed.username or parsed.password:
        raise MediaDownloadError("credentials embedded in media URLs are not supported")
    host = parsed.hostname.lower()
    if host in {"localhost", "localhost.localdomain"}:
        raise MediaDownloadError("localhost sources are not supported")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and (
        address.is_private or address.is_loopback or address.is_link_local
        or address.is_multicast or address.is_reserved or address.is_unspecified
    ):
        raise MediaDownloadError("private or non-routable media URLs are not supported")


def _looks_like_hls(url: str, content_type: str = "") -> bool:
    return urlparse(url).path.lower().endswith(".m3u8") or "mpegurl" in content_type.lower()


def _reject_protected_hls(manifest: str) -> None:
    # Only clear HLS is supported. Do not attempt to retrieve keys or decrypt media.
    for line in manifest.splitlines():
        line = line.strip()
        if line.upper().startswith("#EXT-X-KEY:"):
            method = re.search(r'METHOD\s*=\s*([^,\s]+)', line, re.IGNORECASE)
            if method and method.group(1).strip('"').upper() != "NONE":
                raise MediaDownloadError(
                    "encrypted HLS is unsupported; use an authorized clear-media source"
                )
        if line.upper().startswith("#EXT-X-SESSION-KEY:"):
            raise MediaDownloadError("HLS session keys are unsupported")


def download_media(
    url: str,
    output: Path,
    *,
    provider: str = "direct",
    max_bytes: int = DEFAULT_MAX_BYTES,
    timeout: tuple[int, int] = TIMEOUT_SECONDS,
) -> dict[str, object]:
    """Download direct MP4 or unencrypted HLS to a temporary sibling then atomically move it."""
    _validate_url(url)
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")
    output = output.expanduser().resolve()
    if output.suffix.lower() not in {".mp4", ".mkv", ".mov"}:
        raise MediaDownloadError("output extension must be .mp4, .mkv, or .mov")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".part")
    temporary.unlink(missing_ok=True)
    try:
        with requests.get(url, stream=True, allow_redirects=True, timeout=timeout) as response:
            response.raise_for_status()
            final_url = response.url
            _validate_url(final_url)
            content_type = response.headers.get("Content-Type", "")
            if _looks_like_hls(final_url, content_type):
                manifest = response.text
                if len(manifest) > 2 * 1024 * 1024:
                    raise MediaDownloadError("HLS manifest is unexpectedly large")
                if "<html" in manifest[:1000].lower() or "#EXTM3U" not in manifest:
                    raise MediaDownloadError(
                        "provider returned a webpage, not an HLS manifest; embedded players cannot be downloaded as media"
                    )
                _reject_protected_hls(manifest)
                if not shutil.which("ffmpeg"):
                    raise MediaDownloadError("ffmpeg is required for HLS acquisition")
                # FFmpeg receives the direct manifest only. No browser automation, extractor,
                # proxy, or key/decryption handling is used.
                command = [
                    "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                    "-y", "-i", final_url, "-map", "0:v:0", "-map", "0:a?",
                    "-c", "copy", "-movflags", "+faststart", str(temporary),
                ]
                result = subprocess.run(
                    command, capture_output=True, text=True, timeout=60 * 60, check=False
                )
                if result.returncode != 0:
                    detail = (result.stderr or "ffmpeg failed").strip()[-1200:]
                    raise MediaDownloadError(f"HLS acquisition failed: {detail}")
            else:
                if "text/html" in content_type.lower():
                    raise MediaDownloadError(
                        "provider returned HTML, not media; iframe/embed URLs are not downloadable sources"
                    )
                length = response.headers.get("Content-Length")
                if length and int(length) > max_bytes:
                    raise MediaDownloadError(f"media exceeds configured limit ({max_bytes} bytes)")
                total = 0
                with temporary.open("wb") as target:
                    for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > max_bytes:
                            raise MediaDownloadError(
                                f"media exceeded configured limit ({max_bytes} bytes)"
                            )
                        target.write(chunk)
                if total == 0:
                    raise MediaDownloadError("source returned an empty response")
                # A direct non-HLS source must be recognizable as video or explicitly end in
                # a common media extension; never save an arbitrary HTML/error page as MP4.
                media_path = urlparse(final_url).path.lower()
                video_type = content_type.lower().startswith("video/")
                known_extension = media_path.endswith((".mp4", ".m4v", ".mkv", ".mov"))
                with temporary.open("rb") as sample:
                    signature = sample.read(32)
                recognized = (
                    video_type or known_extension
                    or b"ftyp" in signature or signature.startswith(b"\x1aE\xdf\xa3")
                )
                if not recognized:
                    raise MediaDownloadError(
                        "response is not recognizable video media; provider may have returned an embed or error page"
                    )
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise MediaDownloadError("media acquisition produced no output")
        temporary.replace(output)
        return {
            "status": "downloaded",
            "provider": provider,
            "source_kind": "hls" if _looks_like_hls(url) else "direct_file",
            "output": str(output),
            "bytes": output.stat().st_size,
            "source_url": final_url,
            "audio_required": False,
        }
    except (requests.RequestException, OSError, subprocess.TimeoutExpired) as exc:
        raise MediaDownloadError(str(exc)) from exc
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="animexe-media-download",
        description="Acquire a directly accessible clear MP4/HLS source for AniMeXe processing.",
    )
    parser.add_argument("url", help="direct MP4 or unencrypted HLS manifest URL; not an embed/player page")
    parser.add_argument("--output", type=Path, required=True, help="temporary workspace destination")
    parser.add_argument("--provider", default="direct", help="provider label for the manifest")
    parser.add_argument("--max-gb", type=float, default=4.0, help="maximum download size in GiB (default: 4)")
    args = parser.parse_args()
    try:
        result = download_media(
            args.url,
            args.output,
            provider=args.provider,
            max_bytes=int(args.max_gb * 1024**3),
        )
    except (MediaDownloadError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2), file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
