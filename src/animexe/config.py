from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), m.group(0)), value)
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    return value


@dataclass(frozen=True)
class ProviderConfig:
    name: str = "kuhi"
    api_base_url: str | None = None
    language: str = "sub"


@dataclass(frozen=True)
class MetadataConfig:
    anilist_endpoint: str = "https://graphql.anilist.co"
    jikan_base_url: str = "https://api.jikan.moe/v4"
    search_limit: int = 10


@dataclass(frozen=True)
class SchedulerConfig:
    max_active_anime: int = 4
    daily_output_limit: int = 2
    count_mode: str = "successful_outputs"
    strategy: str = "balanced"


@dataclass(frozen=True)
class EpisodeConfig:
    input_mode: str = "local_or_provider"
    scene_detection: bool = True
    scene_threshold: float = 27.0
    scene_min_duration: float = 0.5
    scene_frame_width: int = 640
    transcript: str = "auto"


@dataclass(frozen=True)
class LLMConfig:
    provider: str = "gemini"
    model: str = "gemini-3.8-flash"
    api_key_env: str = "GEMINI_API_KEY"
    temperature: float = 0.2
    max_output_tokens: int = 12000
    max_frames: int = 32


@dataclass(frozen=True)
class NarrationConfig:
    style: str = "conversational"
    language: str = "hinglish"
    script: str = "roman"
    target_duration_seconds: float = 120.0
    min_duration_seconds: float = 105.0
    max_duration_seconds: float = 135.0
    words_per_minute: int = 145
    speed: float = 1.0


@dataclass(frozen=True)
class TTSConfig:
    provider: str = "synthetic"
    voice: str | None = None
    command: tuple[str, ...] = ()
    timeout_seconds: int = 180


@dataclass(frozen=True)
class VideoConfig:
    width: int = 1920
    height: int = 1080
    fps: int = 30
    max_clip_duration: float = 8.0


@dataclass(frozen=True)
class AudioConfig:
    mute_source: bool = True
    bgm: bool = True
    sfx: str = "optional"


@dataclass(frozen=True)
class SubtitleConfig:
    enabled: bool = True
    burn_in: bool = True


@dataclass(frozen=True)
class PublishingConfig:
    enabled: bool = False


@dataclass(frozen=True)
class AppConfig:
    name: str = "AniMeXe"
    language: str = "hinglish"
    provider: ProviderConfig = ProviderConfig()
    metadata: MetadataConfig = MetadataConfig()
    scheduler: SchedulerConfig = SchedulerConfig()
    episode: EpisodeConfig = EpisodeConfig()
    llm: LLMConfig = LLMConfig()
    narration: NarrationConfig = NarrationConfig()
    tts: TTSConfig = TTSConfig()
    video: VideoConfig = VideoConfig()
    audio: AudioConfig = AudioConfig()
    subtitles: SubtitleConfig = SubtitleConfig()
    publishing: PublishingConfig = PublishingConfig()


def _section(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    return value if isinstance(value, dict) else {}


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    if not value or (value.startswith("${") and value.endswith("}")):
        return None
    return value


def load_config(path: Path) -> AppConfig:
    """Load YAML config and expand environment references."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    expanded = _expand_env(raw)

    project = _section(expanded, "project")
    provider = _section(expanded, "provider")
    metadata = _section(expanded, "metadata")
    scheduler = _section(expanded, "scheduler")
    episode = _section(expanded, "episode")
    llm = _section(expanded, "llm")
    narration = _section(expanded, "narration")
    tts = _section(expanded, "tts")
    video = _section(expanded, "video")
    audio = _section(expanded, "audio")
    subtitles = _section(expanded, "subtitles")
    publishing = _section(expanded, "publishing")

    config = AppConfig(
        name=str(project.get("name", "AniMeXe")),
        language=str(project.get("language", "hinglish")),
        provider=ProviderConfig(
            name=str(provider.get("name", "kuhi")),
            api_base_url=_optional_string(provider.get("api_base_url")),
            language=str(provider.get("language", "sub")),
        ),
        metadata=MetadataConfig(
            anilist_endpoint=str(metadata.get("anilist_endpoint", "https://graphql.anilist.co")),
            jikan_base_url=str(metadata.get("jikan_base_url", "https://api.jikan.moe/v4")),
            search_limit=int(metadata.get("search_limit", 10)),
        ),
        scheduler=SchedulerConfig(
            max_active_anime=int(scheduler.get("max_active_anime", 4)),
            daily_output_limit=int(scheduler.get("daily_output_limit", 2)),
            count_mode=str(scheduler.get("count_mode", "successful_outputs")),
            strategy=str(scheduler.get("strategy", "balanced")),
        ),
        episode=EpisodeConfig(
            input_mode=str(episode.get("input_mode", "local_or_provider")),
            scene_detection=bool(episode.get("scene_detection", True)),
            scene_threshold=float(episode.get("scene_threshold", 27.0)),
            scene_min_duration=float(episode.get("scene_min_duration", 0.5)),
            scene_frame_width=int(episode.get("scene_frame_width", 640)),
            transcript=str(episode.get("transcript", "auto")),
        ),
        llm=LLMConfig(
            provider=str(llm.get("provider", "gemini")),
            model=str(llm.get("model", "gemini-3.8-flash")),
            api_key_env=str(llm.get("api_key_env", "GEMINI_API_KEY")),
            temperature=float(llm.get("temperature", 0.2)),
            max_output_tokens=int(llm.get("max_output_tokens", 12000)),
            max_frames=int(llm.get("max_frames", 32)),
        ),
        narration=NarrationConfig(
            style=str(narration.get("style", "conversational")),
            language=str(narration.get("language", "hinglish")).lower(),
            script=str(narration.get("script", "roman")).lower(),
            target_duration_seconds=float(narration.get("target_duration_seconds", 120.0)),
            min_duration_seconds=float(narration.get("min_duration_seconds", 105.0)),
            max_duration_seconds=float(narration.get("max_duration_seconds", 135.0)),
            words_per_minute=int(narration.get("words_per_minute", 145)),
            speed=float(narration.get("speed", 1.0)),
        ),
        tts=TTSConfig(
            provider=str(tts.get("provider", "synthetic")).lower(),
            voice=_optional_string(tts.get("voice")),
            command=tuple(str(item) for item in tts.get("command", []) if str(item).strip()),
            timeout_seconds=int(tts.get("timeout_seconds", 180)),
        ),
        video=VideoConfig(
            width=int(video.get("width", 1920)),
            height=int(video.get("height", 1080)),
            fps=int(video.get("fps", 30)),
            max_clip_duration=float(video.get("max_clip_duration", 8)),
        ),
        audio=AudioConfig(
            mute_source=bool(audio.get("mute_source", True)),
            bgm=bool(audio.get("bgm", True)),
            sfx=str(audio.get("sfx", "optional")),
        ),
        subtitles=SubtitleConfig(
            enabled=bool(subtitles.get("enabled", True)),
            burn_in=bool(subtitles.get("burn_in", True)),
        ),
        publishing=PublishingConfig(
            enabled=bool(publishing.get("enabled", False)),
        ),
    )

    if config.metadata.search_limit < 1 or config.metadata.search_limit > 50:
        raise ValueError("metadata.search_limit must be between 1 and 50")
    if config.scheduler.max_active_anime < 1:
        raise ValueError("scheduler.max_active_anime must be at least 1")
    if config.scheduler.daily_output_limit < 1:
        raise ValueError("scheduler.daily_output_limit must be at least 1")
    if config.video.width <= 0 or config.video.height <= 0 or config.video.fps <= 0:
        raise ValueError("video dimensions and fps must be positive")
    if config.narration.language not in {"english", "hinglish"}:
        raise ValueError("narration.language must be english or hinglish")
    if config.narration.script not in {"latin", "roman"}:
        raise ValueError("narration.script must be latin or roman")
    if config.narration.language == "english" and config.narration.script != "latin":
        raise ValueError("English narration must use narration.script=latin")
    if config.narration.language == "hinglish" and config.narration.script != "roman":
        raise ValueError("Hinglish narration must use narration.script=roman")
    if config.narration.target_duration_seconds <= 0:
        raise ValueError("narration.target_duration_seconds must be positive")
    if config.narration.min_duration_seconds <= 0:
        raise ValueError("narration.min_duration_seconds must be positive")
    if config.narration.max_duration_seconds <= 0:
        raise ValueError("narration.max_duration_seconds must be positive")
    if config.narration.min_duration_seconds > config.narration.max_duration_seconds:
        raise ValueError("narration.min_duration_seconds cannot exceed max_duration_seconds")
    if not config.narration.min_duration_seconds <= config.narration.target_duration_seconds <= config.narration.max_duration_seconds:
        raise ValueError("narration.target_duration_seconds must be within the duration bounds")
    if config.narration.words_per_minute < 60 or config.narration.words_per_minute > 220:
        raise ValueError("narration.words_per_minute must be between 60 and 220")
    if config.narration.speed <= 0:
        raise ValueError("narration.speed must be positive")
    if config.tts.provider not in {"synthetic", "command"}:
        raise ValueError("tts.provider must be synthetic or command")
    if config.tts.provider == "command" and not config.tts.command:
        raise ValueError("tts.command is required when tts.provider=command")
    if config.tts.timeout_seconds < 1:
        raise ValueError("tts.timeout_seconds must be positive")
    if config.episode.scene_threshold <= 0:
        raise ValueError("episode.scene_threshold must be positive")
    if config.episode.scene_min_duration <= 0:
        raise ValueError("episode.scene_min_duration must be positive")
    if config.episode.scene_frame_width <= 0:
        raise ValueError("episode.scene_frame_width must be positive")
    if not config.llm.provider.strip():
        raise ValueError("llm.provider cannot be empty")
    if not config.llm.model.strip():
        raise ValueError("llm.model cannot be empty")
    if not config.llm.api_key_env.strip():
        raise ValueError("llm.api_key_env cannot be empty")
    if config.llm.temperature < 0:
        raise ValueError("llm.temperature cannot be negative")
    if config.llm.max_output_tokens < 1:
        raise ValueError("llm.max_output_tokens must be positive")
    if config.llm.max_frames < 0:
        raise ValueError("llm.max_frames cannot be negative")

    return config
