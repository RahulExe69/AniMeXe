from __future__ import annotations

from pathlib import Path

from ..config import AppConfig
from .anivault import AnivaultProvider
from .animeparadise import AnimeParadiseProvider
from .anivexa import AnivexaProvider
from .kuhi import KuhiProvider
from .local import LocalProvider
from .registry import ProviderRegistry


def build_registry(config: AppConfig, project_root: Path) -> ProviderRegistry:
    """Build the configured provider set without leaking implementations."""
    registry = ProviderRegistry()
    registry.register(LocalProvider(project_root))

    configured = [config.provider, *config.provider_fallbacks]
    for provider_config in configured:
        name = provider_config.name.strip().lower()
        if name == "animeparadise":
            provider = AnimeParadiseProvider(api_base_url=provider_config.api_base_url)
        elif not provider_config.api_base_url:
            continue
        elif name == "kuhi":
            provider = KuhiProvider(provider_config.api_base_url)
        elif name == "anivexa":
            provider = AnivexaProvider(provider_config.api_base_url)
        elif name == "anivault":
            provider = AnivaultProvider(provider_config.api_base_url)
        else:
            raise ValueError(f"unsupported configured provider: {name}")
        registry.register(provider)

    return registry
