"""Live smoke test for the real AnimeParadise API and one decodable video frame.

This deliberately uses a public, non-authenticated sample and never saves a
full episode. It verifies the real provider API, episode lookup, HLS playlist,
and a single frame from the resolved stream.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
import requests

from animexe.metadata.models import AnimeMetadata
from animexe.providers.animeparadise import AnimeParadiseProvider


@pytest.mark.live
def test_live_animeparadise_fetches_episode_and_decodes_a_frame() -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.fail("Live AnimeParadise verification requires ffmpeg on PATH.")

    provider = AnimeParadiseProvider(timeout_seconds=20)
    # Frieren's first season is a stable, well-known catalogue entry.
    metadata = AnimeMetadata(
        id="anilist:52991",
        title="Frieren: Beyond Journey's End",
        titles=("Frieren: Beyond Journey's End", "Sousou no Frieren", "Frieren"),
        anilist_id=52991,
        episodes=28,
        source_provider="anilist",
    )
    source = provider.resolve_anilist_episode(metadata, 1)
    assert source.provider == "animeparadise"
    assert source.protocol == "hls"
    assert source.reference.startswith("https://stream.animeparadise.moe/m3u8?")

    headers = dict(source.headers)
    response = requests.get(source.reference, headers=headers, timeout=(10, 20))
    try:
        response.raise_for_status()
        playlist = response.text
        assert playlist.lstrip().startswith("#EXTM3U"), (
            "Resolved stream URL did not return an HLS manifest; "
            f"content-type={response.headers.get('Content-Type')!r}"
        )
    finally:
        response.close()

    with TemporaryDirectory(prefix="animexe-animeparadise-live-") as directory:
        frame = Path(directory) / "frame.png"
        header_text = "".join(f"{name}: {value}\r\n" for name, value in headers.items())
        command = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
        if header_text:
            command.extend(["-headers", header_text])
        command.extend([
            "-i", source.reference,
            "-t", "8",
            "-map", "0:v:0",
            "-frames:v", "1",
            "-an",
            str(frame),
        ])
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=75,
        )
        assert completed.returncode == 0, (
            "AnimeParadise returned an HLS manifest, but FFmpeg could not decode "
            f"a frame: {(completed.stderr or '').strip()[-800:]}"
        )
        assert frame.is_file() and frame.stat().st_size > 1024, (
            "FFmpeg did not produce a valid-looking frame from the resolved episode."
        )
