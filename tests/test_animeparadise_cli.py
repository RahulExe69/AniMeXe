from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import animexe.cli as cli
from animexe.config import AppConfig
from animexe.models import MediaSource


def _fake_paths(tmp_path: Path):
    return SimpleNamespace(
        config=tmp_path / "config",
        workspace=tmp_path / "workspace",
        data=tmp_path / "data",
    )


def test_acquisition_command_requires_authorization_before_provider_access(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sys, "argv", [
        "animexe", "episode", "acquire-animeparadise",
        "--anilist-id", "21", "--episode-number", "1",
    ])
    monkeypatch.setattr(cli, "_project_paths", lambda: _fake_paths(tmp_path))
    monkeypatch.setattr(cli, "StateStore", lambda *_: object())

    class UnexpectedMetadataService:
        @classmethod
        def create(cls, **kwargs):
            raise AssertionError("metadata must not be contacted before authorization")

    monkeypatch.setattr(cli, "MetadataService", UnexpectedMetadataService)

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 2
    assert "--authorized-use" in capsys.readouterr().err


def test_acquisition_command_rejects_invalid_anilist_id_before_network(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sys, "argv", [
        "animexe", "episode", "acquire-animeparadise",
        "--anilist-id", "0", "--episode-number", "1", "--authorized-use",
    ])
    monkeypatch.setattr(cli, "_project_paths", lambda: _fake_paths(tmp_path))
    monkeypatch.setattr(cli, "StateStore", lambda *_: object())

    class UnexpectedMetadataService:
        @classmethod
        def create(cls, **kwargs):
            raise AssertionError("invalid IDs must be rejected before metadata access")

    monkeypatch.setattr(cli, "MetadataService", UnexpectedMetadataService)

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 2
    assert "--anilist-id must be a positive integer" in capsys.readouterr().err


def test_acquisition_can_hand_off_saved_file_to_existing_pipeline(monkeypatch, tmp_path, capsys):
    output_path = tmp_path / "episode.mkv"
    monkeypatch.setattr(sys, "argv", [
        "animexe", "episode", "acquire-animeparadise",
        "--anilist-id", "21", "--episode-number", "1",
        "--authorized-use", "--output", str(output_path), "--run-pipeline",
    ])
    paths = _fake_paths(tmp_path)
    monkeypatch.setattr(cli, "_project_paths", lambda: paths)
    monkeypatch.setattr(cli, "StateStore", lambda *_: object())
    monkeypatch.setattr(cli, "load_config", lambda *_: AppConfig())

    class FakeMetadataService:
        @classmethod
        def create(cls, **kwargs):
            return cls()

        def get_anime(self, provider, anime_id):
            assert provider == "anilist"
            assert anime_id == 21
            return SimpleNamespace(title="Test Anime")

    monkeypatch.setattr(cli, "MetadataService", FakeMetadataService)

    class FakeProvider:
        def resolve_anilist_episode(self, metadata, episode_number):
            assert metadata.title == "Test Anime"
            assert episode_number == 1
            return MediaSource(
                provider="animeparadise",
                protocol="hls",
                reference="https://stream.animeparadise.moe/m3u8?url=opaque",
                headers=(("Referer", "https://animeparadise.moe/"),),
            )

    monkeypatch.setattr(cli, "AnimeParadiseProvider", FakeProvider)
    captured = {}

    def fake_download(url, output, **kwargs):
        captured["url"] = url
        captured["output"] = Path(output)
        captured["kwargs"] = kwargs
        return {
            "provider": "animeparadise",
            "source_kind": "hls",
            "output_path": str(output),
            "size_bytes": 123,
        }

    monkeypatch.setattr(cli, "download_media_source", fake_download)

    class FakePipeline:
        def __init__(self, supplied_paths, config):
            assert supplied_paths is paths

        def run(self, input_path, **kwargs):
            assert input_path == output_path
            assert kwargs == {
                "anime_id": "anilist:21",
                "episode_number": 1,
                "season": 1,
            }
            return SimpleNamespace(to_dict=lambda: {"status": "rendered"})

    monkeypatch.setattr(cli, "EpisodePipeline", FakePipeline)

    cli.main()

    result = json.loads(capsys.readouterr().out)
    assert captured["url"] == "https://stream.animeparadise.moe/m3u8?url=opaque"
    assert captured["kwargs"]["source_provider"] == "animeparadise"
    assert captured["kwargs"]["headers"] == {"Referer": "https://animeparadise.moe/"}
    assert result["output_path"] == str(output_path)
    assert result["pipeline_result"] == {"status": "rendered"}
    assert result["anime"]["anilist_id"] == 21
