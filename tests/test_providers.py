from pathlib import Path

from animexe.config import AppConfig, ProviderConfig
from animexe.models import EpisodeRef
from animexe.providers import AnimeParadiseProvider, LocalProvider, ProviderRegistry, build_registry


def test_local_provider_returns_normalized_file_source(tmp_path: Path) -> None:
    sample = tmp_path / "episode.mp4"
    sample.write_bytes(b"test")

    provider = LocalProvider(tmp_path)
    episode = EpisodeRef(
        anime_id="demo-s1",
        season=1,
        episode=1,
        external_id="episode.mp4",
    )

    source = provider.get_source(episode)

    assert source.provider == "local"
    assert source.protocol == "file"
    assert source.reference == str(sample.resolve())
    assert "seekable" in source.capabilities


def test_provider_registry_is_explicit() -> None:
    registry = ProviderRegistry()
    registry.register(LocalProvider())

    assert registry.names() == ("local",)
    assert registry.get("LOCAL").name == "local"



def test_animeparadise_is_opt_in_without_kuhi_url(tmp_path: Path) -> None:
    config = AppConfig(provider=ProviderConfig(name="animeparadise"))

    registry = build_registry(config, tmp_path)

    assert registry.names() == ("animeparadise", "local")
    assert isinstance(registry.get("animeparadise"), AnimeParadiseProvider)
