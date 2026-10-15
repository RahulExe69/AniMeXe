from pathlib import Path

import pytest

from animexe.media_download import MediaDownloadError, _reject_protected_hls, _validate_url


def test_rejects_embed_page_url_as_non_media_when_html_is_returned(monkeypatch, tmp_path: Path) -> None:
    import animexe.media_download as module

    class Response:
        url = "https://example.test/embed/episode/1"
        headers = {"Content-Type": "text/html"}
        text = "<html><body>player</body></html>"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def raise_for_status(self):
            return None

    monkeypatch.setattr(module.requests, "get", lambda *args, **kwargs: Response())
    with pytest.raises(MediaDownloadError, match="HTML"):
        module.download_media("https://example.test/embed/episode/1", tmp_path / "episode.mp4")


def test_rejects_non_http_url() -> None:
    with pytest.raises(MediaDownloadError, match="HTTP"):
        _validate_url("file:///tmp/episode.mp4")


def test_rejects_private_ip_source() -> None:
    with pytest.raises(MediaDownloadError, match="private"):
        _validate_url("http://127.0.0.1/episode.mp4")


def test_allows_clear_hls_manifest() -> None:
    _reject_protected_hls("#EXTM3U\n#EXT-X-VERSION:3\n")


def test_rejects_encrypted_hls() -> None:
    with pytest.raises(MediaDownloadError, match="encrypted HLS"):
        _reject_protected_hls('#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key.bin"\n')


def test_rejects_hls_master_playlist() -> None:
    with pytest.raises(MediaDownloadError, match="master playlists"):
        _reject_protected_hls(chr(10).join(["#EXTM3U", "#EXT-X-STREAM-INF:BANDWIDTH=1000", "variant.m3u8"]))
