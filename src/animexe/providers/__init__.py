"""Provider interfaces and implementations."""

from .base import Provider, ProviderHealth
from .broker import ProviderBroker, ProviderProbe
from .anivault import AnivaultProvider
from .animeparadise import AnimeParadiseError, AnimeParadiseProvider
from .anivexa import AnivexaProvider
from .factory import build_registry
from .kuhi import KuhiProvider
from .local import LocalProvider
from .registry import ProviderRegistry

__all__ = [
    "KuhiProvider",
    "AnivexaProvider",
    "AnivaultProvider",
    "AnimeParadiseProvider",
    "AnimeParadiseError",
    "ProviderBroker",
    "ProviderProbe",
    "build_registry",
    "LocalProvider",
    "Provider",
    "ProviderHealth",
    "ProviderRegistry",
]
