from __future__ import annotations

import argparse
import json
from pathlib import Path

from .analysis import (
    EpisodeAnalysisManifest,
    EpisodeInspector,
    SceneAnalysisManifest,
    InspectionError,
    SceneDetectionError,
    SceneIndexer,
    SubtitleTranscriptExtractor,
    TranscriptAnalysisManifest,
    TranscriptError,
    EpisodeStoryManifest,
    ExtractiveStoryAnalyzer,
    StoryAnalysisError,
    GeminiStoryAnalyzer,
    GeminiStoryError,
)
from .config import load_config
from .editing import EditPlanError, EditPlanManifest, EditPlanner
from .logging import configure_logging
from .metadata import MetadataLibrary, MetadataService
from .media.source_download import SEVENX_PROVIDER_MODES, SourceDownloadError, download_media_source
from .providers.animeparadise import AnimeParadiseError, AnimeParadiseProvider
from .models import AnimeRecord, EpisodeRecord
from .narration import (
    GeminiNarrationScriptGenerator,
    NarrationScriptError,
    NarrationScriptManifest,
)
from .tts import CommandTTSSynthesizer, GeminiTTSSynthesizer, SyntheticTTSSynthesizer, TTSError
from .matching import MatchError, SceneMatchManifest, SceneMatcher
from .render import FFmpegRenderer, RenderError, TimelineBuilder, TimelineManifest, VisualCutError, VisualCutRenderer
from .paths import ProjectPaths
from .pipeline import EpisodePipeline, PipelineError
from .providers import ProviderBroker, build_registry
from .scheduler import Scheduler
from .state import StateStore


def _project_paths() -> ProjectPaths:
    paths = ProjectPaths.discover()
    paths.ensure()
    return paths



def _find_background_music(paths: ProjectPaths, music_dir: str) -> Path | None:
    root = Path(music_dir)
    if not root.is_absolute():
        root = paths.root / root
    if not root.is_dir():
        return None
    candidates = sorted(
        item for item in root.iterdir()
        if item.is_file() and item.suffix.lower() in {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
    )
    return candidates[0] if candidates else None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="animexe",
        description="AniMeXe anime episode automation engine",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="logging level (default: INFO)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create the canonical AniMeXe directories and state files")
    sub.add_parser("status", help="show current persisted state")

    anime = sub.add_parser("anime", help="manage anime records")
    anime_sub = anime.add_subparsers(dest="anime_command", required=True)
    anime_sub.add_parser("list", help="list anime records")

    add_anime = anime_sub.add_parser("add", help="add one anime record")
    add_anime.add_argument("id")
    add_anime.add_argument("title")
    add_anime.add_argument("--season", type=int, default=1)
    add_anime.add_argument("--priority", type=int, default=0)

    episode = sub.add_parser("episode", help="inspect episode records")
    episode_sub = episode.add_subparsers(dest="episode_command", required=True)
    episode_list = episode_sub.add_parser("list", help="list episodes")
    episode_list.add_argument("--anime-id")

    episode_download = episode_sub.add_parser(
        "download-source",
        help="save a permitted direct video file or unencrypted HLS stream for episode analysis",
    )
    episode_download.add_argument("media_url", help="direct MP4/MKV/WebM or unencrypted HLS playlist URL (not an embed page)")
    episode_download.add_argument("--output", type=Path, default=None, help="local episode output path")
    episode_download.add_argument(
        "--source-provider",
        choices=tuple(SEVENX_PROVIDER_MODES),
        default=None,
        help="optional 7xAnime provider label; embed-only URLs remain unsupported",
    )
    episode_download.add_argument("--referer", default=None, help="Referer header when legitimately required by the media host")
    episode_download.add_argument("--user-agent", default=None, help="optional User-Agent header")
    episode_download.add_argument("--timeout", type=int, default=60, help="request timeout in seconds (default: 60)")
    episode_download.add_argument("--max-size-mb", type=int, default=8192, help="maximum saved media size in MiB (default: 8192)")
    episode_download.add_argument(
        "--authorized-use",
        action="store_true",
        help="confirm you have permission to download and process this media",
    )

    episode_acquire = episode_sub.add_parser(
        "acquire-animeparadise",
        help="resolve an AniList episode through AnimeParadise and acquire its HLS media",
    )
    episode_acquire.add_argument("--anilist-id", type=int, required=True)
    episode_acquire.add_argument("--episode-number", type=int, required=True)
    episode_acquire.add_argument("--season", type=int, default=1)
    episode_acquire.add_argument("--output", type=Path, default=None, help="destination for the acquired episode")
    episode_acquire.add_argument("--timeout", type=int, default=60, help="media acquisition timeout in seconds")
    episode_acquire.add_argument("--max-size-mb", type=int, default=8192, help="maximum output size in MiB")
    episode_acquire.add_argument("--run-pipeline", action="store_true", help="run the existing explanation pipeline after acquisition")
    episode_acquire.add_argument(
        "--authorized-use",
        action="store_true",
        help="confirm you have permission to download and process this media",
    )

    episode_inspect = episode_sub.add_parser(
        "inspect",
        help="run ffprobe inspection and write an analysis manifest",
    )
    episode_inspect.add_argument("input_path", type=Path)
    episode_inspect.add_argument("--anime-id")
    episode_inspect.add_argument("--episode-number", type=int)
    episode_inspect.add_argument("--season", type=int, default=1)
    episode_inspect.add_argument("--output", type=Path)
    episode_inspect.add_argument(
        "--no-hash-input",
        action="store_true",
        help="skip the full SHA-256 input fingerprint",
    )

    episode_scenes = episode_sub.add_parser(
        "scenes",
        help="detect scenes and extract representative frames",
    )
    episode_scenes.add_argument("input_path", type=Path)
    episode_scenes.add_argument("--analysis-manifest", type=Path)
    episode_scenes.add_argument("--anime-id")
    episode_scenes.add_argument("--episode-number", type=int)
    episode_scenes.add_argument("--season", type=int, default=1)
    episode_scenes.add_argument("--output", type=Path)
    episode_scenes.add_argument(
        "--no-frames",
        action="store_true",
        help="build the scene index without extracting representative frames",
    )

    episode_transcript = episode_sub.add_parser(
        "transcript",
        help="extract embedded subtitles and align them to scenes",
    )
    episode_transcript.add_argument("input_path", type=Path)
    episode_transcript.add_argument("--analysis-manifest", type=Path)
    episode_transcript.add_argument("--scene-manifest", type=Path)
    episode_transcript.add_argument("--anime-id")
    episode_transcript.add_argument("--episode-number", type=int)
    episode_transcript.add_argument("--season", type=int, default=1)
    episode_transcript.add_argument("--output", type=Path)
    episode_transcript.add_argument(
        "--allow-missing-subtitles",
        action="store_true",
        help="continue with a READY empty transcript so visual-only story analysis can proceed",
    )

    episode_story = episode_sub.add_parser(
        "story",
        help="assemble structured story evidence from transcript and scenes",
    )
    episode_story.add_argument("input_path", type=Path)
    episode_story.add_argument("--transcript-manifest", type=Path)
    episode_story.add_argument("--scene-manifest", type=Path)
    episode_story.add_argument("--analysis-manifest", type=Path)
    episode_story.add_argument("--anime-id")
    episode_story.add_argument("--episode-number", type=int)
    episode_story.add_argument("--season", type=int, default=1)
    episode_story.add_argument("--output", type=Path)
    episode_story.add_argument(
        "--mode",
        choices=("extractive", "gemini"),
        default="extractive",
        help="story analysis backend (default: extractive)",
    )

    episode_visual_cut = episode_sub.add_parser(
        "visual-cut",
        help="select important scenes and render a narration-free visual cut",
    )
    episode_visual_cut.add_argument("input_path", type=Path)
    episode_visual_cut.add_argument("--story-manifest", type=Path)
    episode_visual_cut.add_argument("--scene-manifest", type=Path)
    episode_visual_cut.add_argument("--output", type=Path)
    episode_visual_cut.add_argument("--edit-plan", type=Path)
    episode_visual_cut.add_argument("--target-duration-seconds", type=float, default=None)
    episode_visual_cut.add_argument("--min-duration-seconds", type=float, default=None)
    episode_visual_cut.add_argument("--max-duration-seconds", type=float, default=None)
    episode_visual_cut.add_argument("--max-clip-duration", type=float, default=None)
    episode_visual_cut.add_argument(
        "--visual-only",
        action="store_true",
        help="build the cut directly from detected scenes without a story/Gemini manifest",
    )

    episode_script = episode_sub.add_parser(
        "script",
        help="generate an original narration script from story understanding",
    )
    episode_script.add_argument("input_path", type=Path)
    episode_script.add_argument("--story-manifest", type=Path)
    episode_script.add_argument("--transcript-manifest", type=Path)
    episode_script.add_argument("--anime-id")
    episode_script.add_argument("--episode-number", type=int)
    episode_script.add_argument("--season", type=int, default=1)
    episode_script.add_argument("--output", type=Path)
    episode_script.add_argument(
        "--provider",
        choices=("gemini",),
        default=None,
        help="narration-script provider (default: configured llm provider)",
    )
    episode_script.add_argument(
        "--language",
        choices=("english", "hinglish"),
        default=None,
        help="narration language (default: configured narration.language)",
    )
    episode_script.add_argument(
        "--script",
        choices=("latin", "roman"),
        default=None,
        help="writing system: latin for English, roman for Hinglish",
    )

    episode_tts = episode_sub.add_parser(
        "tts",
        help="synthesize narration audio and write the TTS checkpoint",
    )
    episode_tts.add_argument("input_path", type=Path)
    episode_tts.add_argument("--script-manifest", type=Path)
    episode_tts.add_argument("--anime-id")
    episode_tts.add_argument("--episode-number", type=int)
    episode_tts.add_argument("--season", type=int, default=1)
    episode_tts.add_argument("--output", type=Path)
    episode_tts.add_argument(
        "--provider",
        choices=("synthetic", "command", "gemini"),
        default=None,
        help="TTS backend (default: configured tts.provider)",
    )

    episode_match = episode_sub.add_parser(
        "match",
        help="match measured narration audio to source scenes",
    )
    episode_match.add_argument("input_path", type=Path)
    episode_match.add_argument("--scene-manifest", type=Path)
    episode_match.add_argument("--tts-manifest", type=Path)
    episode_match.add_argument("--anime-id")
    episode_match.add_argument("--episode-number", type=int)
    episode_match.add_argument("--season", type=int, default=1)
    episode_match.add_argument("--output", type=Path)
    episode_match.add_argument("--max-clip-duration", type=float, default=None)

    episode_timeline = episode_sub.add_parser(
        "timeline",
        help="build the declarative render timeline",
    )
    episode_timeline.add_argument("input_path", type=Path)
    episode_timeline.add_argument("--matching-manifest", type=Path)
    episode_timeline.add_argument("--tts-manifest", type=Path)
    episode_timeline.add_argument("--anime-id")
    episode_timeline.add_argument("--episode-number", type=int)
    episode_timeline.add_argument("--season", type=int, default=1)
    episode_timeline.add_argument("--output", type=Path)

    episode_render = episode_sub.add_parser(
        "render",
        help="render the final MP4 from the declarative timeline",
    )
    episode_render.add_argument("input_path", type=Path)
    episode_render.add_argument("--timeline-manifest", type=Path)
    episode_render.add_argument("--tts-dir", type=Path)
    episode_render.add_argument("--anime-id")
    episode_render.add_argument("--episode-number", type=int)
    episode_render.add_argument("--season", type=int, default=1)
    episode_render.add_argument("--output", type=Path)
    episode_render.add_argument(
        "--no-subtitles",
        action="store_true",
        help="do not burn narration subtitles into the video",
    )

    episode_run = episode_sub.add_parser(
        "run",
        help="run/resume the complete episode production pipeline",
    )
    episode_run.add_argument("input_path", type=Path)
    episode_run.add_argument("--anime-id")
    episode_run.add_argument("--episode-number", type=int)
    episode_run.add_argument("--season", type=int, default=1)

    providers = sub.add_parser("provider", help="inspect configured episode providers")
    provider_sub = providers.add_subparsers(dest="provider_command", required=True)
    provider_sub.add_parser("status", help="check health of every configured provider")
    provider_check = provider_sub.add_parser("check", help="probe one episode across configured providers")
    provider_check.add_argument("anime_id", help="provider-independent anime id, e.g. anilist:21")
    provider_check.add_argument("--episode-number", type=int, required=True)
    provider_check.add_argument("--language", choices=("sub", "dub"), default="sub")
    provider_check.add_argument("--output", type=Path, default=None)
    provider_check.add_argument("--require-catalog", action="store_true", help="fail when no provider confirms the episode")

    sub.add_parser("plan", help="show the scheduler's next job plan")

    metadata = sub.add_parser("metadata", help="query normalized anime metadata")
    metadata_sub = metadata.add_subparsers(dest="metadata_command", required=True)

    metadata_search = metadata_sub.add_parser("search", help="search anime metadata")
    metadata_search.add_argument("query")
    metadata_search.add_argument("--limit", type=int, default=None)

    metadata_get = metadata_sub.add_parser("get", help="fetch one anime by metadata provider id")
    metadata_get.add_argument("provider", choices=("anilist", "jikan"))
    metadata_get.add_argument("id")

    metadata_sync = metadata_sub.add_parser("sync", help="fetch metadata and upsert it into the anime library")
    metadata_sync.add_argument("provider", choices=("anilist", "jikan"))
    metadata_sync.add_argument("id")

    return parser


def _print_json(value: object) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    configure_logging(args.log_level)

    paths = _project_paths()
    store = StateStore(paths.data)

    if args.command == "init":
        store.ensure()
        print(f"Initialized AniMeXe at {paths.root}")
        return

    if args.command == "status":
        anime = store.list_anime()
        episodes = store.list_episodes()
        scheduler = store.load_scheduler()
        _print_json(
            {
                "root": str(paths.root),
                "anime": len(anime),
                "episodes": len(episodes),
                "active_anime": sum(item.active for item in anime),
                "successful_outputs_today": scheduler.successful_outputs_today,
                "daily_output_limit": scheduler.daily_output_limit,
                "strategy": scheduler.strategy,
            }
        )
        return

    if args.command == "anime":
        if args.anime_command == "list":
            _print_json([item.__dict__ for item in store.list_anime()])
            return

        if args.anime_command == "add":
            record = AnimeRecord(
                id=args.id,
                title=args.title,
                season=args.season,
                priority=args.priority,
                status="DISCOVERED",
                release_state="NOT_YET_RELEASED",
            )
            store.save_anime(record)
            print(f"Added anime: {record.title} (S{record.season})")
            return

    if args.command == "episode":
        if args.episode_command == "acquire-animeparadise":
            if not args.authorized_use:
                parser.error("Confirm you have permission to download and process this media by passing --authorized-use.")
            if args.anilist_id < 1:
                parser.error("--anilist-id must be a positive integer")
            if args.episode_number < 1:
                parser.error("--episode-number must be >= 1")
            if args.season < 1:
                parser.error("--season must be >= 1")
            if args.timeout < 1 or args.max_size_mb < 1:
                parser.error("--timeout and --max-size-mb must be positive")

            config_path = paths.config / "config.yml"
            if not config_path.exists():
                config_path = paths.config / "config.example.yml"
            try:
                app_config = load_config(config_path)
                metadata_service = MetadataService.create(
                    anilist_endpoint=app_config.metadata.anilist_endpoint,
                    jikan_base_url=app_config.metadata.jikan_base_url,
                )
                metadata = metadata_service.get_anime("anilist", args.anilist_id)
                source = AnimeParadiseProvider().resolve_anilist_episode(
                    metadata,
                    args.episode_number,
                )
                output_path = args.output or (
                    paths.workspace
                    / "input"
                    / f"anilist-{args.anilist_id}-s{args.season}-e{args.episode_number}.mkv"
                )
                result = download_media_source(
                    source.reference,
                    output_path,
                    source_provider="animeparadise",
                    headers=dict(source.headers),
                    timeout_seconds=args.timeout,
                    max_bytes=args.max_size_mb * 1024 * 1024,
                )
                if args.run_pipeline:
                    pipeline_result = EpisodePipeline(paths, app_config).run(
                        Path(str(result["output_path"])),
                        anime_id=f"anilist:{args.anilist_id}",
                        episode_number=args.episode_number,
                        season=args.season,
                    )
                    result["pipeline_result"] = pipeline_result.to_dict()
                result["anime"] = {
                    "anilist_id": args.anilist_id,
                    "title": metadata.title,
                    "episode_number": args.episode_number,
                    "season": args.season,
                }
            except (
                AnimeParadiseError,
                SourceDownloadError,
                PipelineError,
                OSError,
                ValueError,
                TypeError,
                KeyError,
                RuntimeError,
            ) as exc:
                parser.error(str(exc))
            _print_json(result)
            return

        if args.episode_command == "download-source":
            if not args.authorized_use:
                parser.error("Confirm you have permission to download and process this media by passing --authorized-use.")
            headers = {}
            if args.referer:
                headers["Referer"] = args.referer
            if args.user_agent:
                headers["User-Agent"] = args.user_agent
            output_path = args.output or (paths.workspace / "input" / "source-episode.mkv")
            try:
                result = download_media_source(
                    args.media_url,
                    output_path,
                    source_provider=args.source_provider,
                    headers=headers,
                    timeout_seconds=args.timeout,
                    max_bytes=args.max_size_mb * 1024 * 1024,
                )
            except (SourceDownloadError, ValueError) as exc:
                parser.error(str(exc))
            _print_json(result)
            return

        if args.episode_command == "list":
            _print_json(
                [item.__dict__ for item in store.list_episodes(args.anime_id)]
            )
            return

        if args.episode_command == "inspect":
            if (args.anime_id is None) != (args.episode_number is None):
                parser.error("--anime-id and --episode-number must be supplied together")
            if args.season < 1:
                parser.error("--season must be >= 1")
            if args.episode_number is not None and args.episode_number < 1:
                parser.error("--episode-number must be >= 1")

            episode_id = None
            if args.anime_id:
                assert args.episode_number is not None
                episode_id = (
                    f"{args.anime_id}-s{args.season}-e{args.episode_number}"
                )

            inspector = EpisodeInspector()
            try:
                manifest = inspector.inspect(
                    args.input_path,
                    episode_id=episode_id,
                    hash_input=not args.no_hash_input,
                )
            except InspectionError as exc:
                parser.error(str(exc))

            output_path = args.output or (
                paths.workspace
                / "analysis"
                / f"{args.input_path.stem}.analysis.json"
            )
            manifest.write(output_path)

            if args.anime_id:
                assert args.episode_number is not None
                existing = {
                    item.id: item
                    for item in store.list_episodes(args.anime_id)
                }.get(episode_id)
                record = existing or EpisodeRecord(
                    id=episode_id,
                    anime_id=args.anime_id,
                    episode_number=args.episode_number,
                )
                record.status = "PROCESSING"
                record.current_checkpoint = "inspected"
                record.failure_reason = None
                record.provider = "local"
                record.source_reference = str(
                    args.input_path.expanduser().resolve()
                )
                record.analysis_manifest = str(output_path)
                store.save_episode(record)

            _print_json(manifest.to_dict() | {"manifest_path": str(output_path)})
            return

    if args.command == "episode":
        if args.episode_command == "scenes":
            if (args.anime_id is None) != (args.episode_number is None):
                parser.error("--anime-id and --episode-number must be supplied together")
            if args.season < 1:
                parser.error("--season must be >= 1")
            if args.episode_number is not None and args.episode_number < 1:
                parser.error("--episode-number must be >= 1")

            config_path = paths.config / "config.yml"
            if not config_path.exists():
                config_path = paths.config / "config.example.yml"
            app_config = load_config(config_path)
            if not app_config.episode.scene_detection:
                parser.error("episode.scene_detection is disabled in configuration")

            episode_manifest_path = args.analysis_manifest
            if episode_manifest_path is None:
                episode_manifest_path = (
                    paths.workspace
                    / "analysis"
                    / f"{args.input_path.stem}.analysis.json"
                )

            if episode_manifest_path.exists():
                try:
                    episode_manifest = EpisodeAnalysisManifest.read(episode_manifest_path)
                except (OSError, ValueError, TypeError) as exc:
                    parser.error(f"could not read analysis manifest: {exc}")
            else:
                inspector = EpisodeInspector()
                try:
                    episode_id = None
                    if args.anime_id:
                        assert args.episode_number is not None
                        episode_id = f"{args.anime_id}-s{args.season}-e{args.episode_number}"
                    episode_manifest = inspector.inspect(
                        args.input_path,
                        episode_id=episode_id,
                    )
                    episode_manifest.write(episode_manifest_path)
                except InspectionError as exc:
                    parser.error(str(exc))

            output_dir = (
                args.output.parent
                if args.output
                else paths.workspace / "analysis" / args.input_path.stem
            )
            scene_manifest_path = args.output or (output_dir / "scenes.json")

            indexer = SceneIndexer(
                threshold=app_config.episode.scene_threshold,
                min_scene_duration_seconds=app_config.episode.scene_min_duration,
                frame_width=app_config.episode.scene_frame_width,
            )
            try:
                scene_manifest = indexer.index(
                    args.input_path,
                    output_dir=output_dir,
                    episode_manifest=episode_manifest,
                    episode_id=episode_manifest.episode_id,
                    extract_frames=not args.no_frames,
                )
            except SceneDetectionError as exc:
                parser.error(str(exc))

            scene_manifest.write(scene_manifest_path)

            if args.anime_id:
                assert args.episode_number is not None
                episode_id = f"{args.anime_id}-s{args.season}-e{args.episode_number}"
                existing = {
                    item.id: item
                    for item in store.list_episodes(args.anime_id)
                }.get(episode_id)
                record = existing or EpisodeRecord(
                    id=episode_id,
                    anime_id=args.anime_id,
                    episode_number=args.episode_number,
                )
                record.status = "PROCESSING"
                record.current_checkpoint = "scenes"
                record.failure_reason = None
                record.provider = "local"
                record.source_reference = str(
                    args.input_path.expanduser().resolve()
                )
                record.analysis_manifest = str(episode_manifest_path)
                record.scene_manifest = str(scene_manifest_path)
                store.save_episode(record)

            _print_json(
                scene_manifest.to_dict()
                | {
                    "analysis_manifest_path": str(episode_manifest_path),
                    "scene_manifest_path": str(scene_manifest_path),
                }
            )
            return

    if args.command == "episode":
        if args.episode_command == "transcript":
            if (args.anime_id is None) != (args.episode_number is None):
                parser.error("--anime-id and --episode-number must be supplied together")
            if args.season < 1:
                parser.error("--season must be >= 1")
            if args.episode_number is not None and args.episode_number < 1:
                parser.error("--episode-number must be >= 1")

            episode_manifest_path = args.analysis_manifest or (
                paths.workspace
                / "analysis"
                / f"{args.input_path.stem}.analysis.json"
            )
            scene_manifest_path = args.scene_manifest or (
                paths.workspace
                / "analysis"
                / args.input_path.stem
                / "scenes.json"
            )

            try:
                episode_manifest = EpisodeAnalysisManifest.read(episode_manifest_path)
            except (OSError, ValueError, TypeError) as exc:
                parser.error(f"could not read analysis manifest: {exc}")

            try:
                scene_manifest = SceneAnalysisManifest.read(scene_manifest_path)
            except (OSError, ValueError, TypeError) as exc:
                parser.error(f"could not read scene manifest: {exc}")

            output_dir = (
                args.output.parent
                if args.output
                else paths.workspace / "analysis" / args.input_path.stem
            )
            transcript_manifest_path = args.output or (output_dir / "transcript.json")

            extractor = SubtitleTranscriptExtractor(
                allow_missing_subtitles=args.allow_missing_subtitles,
            )
            try:
                transcript_manifest = extractor.extract(
                    args.input_path,
                    output_dir=output_dir,
                    episode_manifest=episode_manifest,
                    scene_manifest=scene_manifest,
                    episode_id=episode_manifest.episode_id,
                )
            except TranscriptError as exc:
                parser.error(str(exc))

            transcript_manifest.write(transcript_manifest_path)

            if args.anime_id:
                assert args.episode_number is not None
                episode_id = f"{args.anime_id}-s{args.season}-e{args.episode_number}"
                existing = {
                    item.id: item
                    for item in store.list_episodes(args.anime_id)
                }.get(episode_id)
                record = existing or EpisodeRecord(
                    id=episode_id,
                    anime_id=args.anime_id,
                    episode_number=args.episode_number,
                )
                record.status = "PROCESSING"
                record.current_checkpoint = "transcript"
                record.failure_reason = None
                record.provider = "local"
                record.source_reference = str(
                    args.input_path.expanduser().resolve()
                )
                record.analysis_manifest = str(episode_manifest_path)
                record.scene_manifest = str(scene_manifest_path)
                record.transcript_manifest = str(transcript_manifest_path)
                store.save_episode(record)

            _print_json(
                transcript_manifest.to_dict()
                | {
                    "analysis_manifest_path": str(episode_manifest_path),
                    "scene_manifest_path": str(scene_manifest_path),
                    "transcript_manifest_path": str(transcript_manifest_path),
                }
            )
            return

    if args.command == "episode":
        if args.episode_command == "story":
            if (args.anime_id is None) != (args.episode_number is None):
                parser.error("--anime-id and --episode-number must be supplied together")
            if args.season < 1:
                parser.error("--season must be >= 1")
            if args.episode_number is not None and args.episode_number < 1:
                parser.error("--episode-number must be >= 1")

            transcript_path = args.transcript_manifest or (
                paths.workspace
                / "analysis"
                / args.input_path.stem
                / "transcript.json"
            )
            scene_path = args.scene_manifest or (
                paths.workspace
                / "analysis"
                / args.input_path.stem
                / "scenes.json"
            )
            analysis_path = args.analysis_manifest or (
                paths.workspace
                / "analysis"
                / f"{args.input_path.stem}.analysis.json"
            )

            try:
                transcript_manifest = TranscriptAnalysisManifest.read(transcript_path)
                scene_manifest = SceneAnalysisManifest.read(scene_path)
                EpisodeAnalysisManifest.read(analysis_path)
            except (OSError, ValueError, TypeError) as exc:
                parser.error(f"could not read analysis manifests: {exc}")

            output_path = args.output or (
                paths.workspace
                / "analysis"
                / args.input_path.stem
                / "story.json"
            )

            config_path = paths.config / "config.yml"
            if not config_path.exists():
                config_path = paths.config / "config.example.yml"
            app_config = load_config(config_path)

            try:
                if args.mode == "gemini":
                    if app_config.llm.provider.lower() != "gemini":
                        parser.error(
                            f"llm.provider is configured as {app_config.llm.provider!r}; "
                            "set it to gemini before using --mode gemini"
                        )
                    story_manifest = GeminiStoryAnalyzer(
                        model=app_config.llm.model,
                        api_key_env=app_config.llm.api_key_env,
                        temperature=app_config.llm.temperature,
                        thinking_level=app_config.llm.thinking_level,
                        max_output_tokens=app_config.llm.max_output_tokens,
                        max_frames=app_config.llm.max_frames,
                    ).analyze(
                        transcript_manifest,
                        scene_manifest,
                        scene_manifest_dir=scene_path.parent,
                        source_transcript=str(transcript_path),
                        source_scenes=str(scene_path),
                    )
                else:
                    story_manifest = ExtractiveStoryAnalyzer().analyze(
                        transcript_manifest,
                        scene_manifest,
                        source_transcript=str(transcript_path),
                        source_scenes=str(scene_path),
                    )
            except (StoryAnalysisError, GeminiStoryError) as exc:
                parser.error(str(exc))

            story_manifest.write(output_path)

            if args.anime_id:
                assert args.episode_number is not None
                episode_id = f"{args.anime_id}-s{args.season}-e{args.episode_number}"
                existing = {
                    item.id: item
                    for item in store.list_episodes(args.anime_id)
                }.get(episode_id)
                record = existing or EpisodeRecord(
                    id=episode_id,
                    anime_id=args.anime_id,
                    episode_number=args.episode_number,
                )
                record.status = "PROCESSING"
                record.current_checkpoint = "story"
                record.failure_reason = None
                record.provider = "local"
                record.source_reference = str(
                    args.input_path.expanduser().resolve()
                )
                record.analysis_manifest = str(analysis_path)
                record.scene_manifest = str(scene_path)
                record.transcript_manifest = str(transcript_path)
                record.story_manifest = str(output_path)
                store.save_episode(record)

            _print_json(
                story_manifest.to_dict()
                | {
                    "analysis_manifest_path": str(analysis_path),
                    "scene_manifest_path": str(scene_path),
                    "transcript_manifest_path": str(transcript_path),
                    "story_manifest_path": str(output_path),
                }
            )
            return

    if args.command == "episode":
        if args.episode_command == "visual-cut":
            story_path = args.story_manifest or (
                paths.workspace
                / "analysis"
                / args.input_path.stem
                / "story.json"
            )
            scene_path = args.scene_manifest or (
                paths.workspace
                / "analysis"
                / args.input_path.stem
                / "scenes.json"
            )
            plan_path = args.edit_plan or (
                paths.workspace
                / "analysis"
                / args.input_path.stem
                / "edit_plan.json"
            )
            output_path = args.output or (
                paths.workspace
                / "output"
                / f"{args.input_path.stem}-visual-cut.mp4"
            )

            try:
                scene_manifest = SceneAnalysisManifest.read(scene_path)
                story_manifest = (
                    EpisodeStoryManifest.read(story_path)
                    if not args.visual_only
                    else None
                )
            except (OSError, ValueError, TypeError, KeyError) as exc:
                parser.error(
                    f"could not read {'scene' if args.visual_only else 'story/scene'} manifests: {exc}"
                )

            config_path = paths.config / "config.yml"
            if not config_path.exists():
                config_path = paths.config / "config.example.yml"
            app_config = load_config(config_path)

            target = (
                args.target_duration_seconds
                if args.target_duration_seconds is not None
                else app_config.narration.target_duration_seconds
            )
            minimum = (
                args.min_duration_seconds
                if args.min_duration_seconds is not None
                else app_config.narration.min_duration_seconds
            )
            maximum = (
                args.max_duration_seconds
                if args.max_duration_seconds is not None
                else app_config.narration.max_duration_seconds
            )
            max_clip = (
                args.max_clip_duration
                if args.max_clip_duration is not None
                else app_config.video.max_clip_duration
            )

            try:
                if plan_path.exists():
                    plan = EditPlanManifest.read(plan_path)
                    if plan.input_path != str(args.input_path.expanduser().resolve()):
                        parser.error("existing edit plan belongs to a different input")
                    expected_sha = scene_manifest.input_sha256
                    if expected_sha and plan.input_sha256 and expected_sha != plan.input_sha256:
                        parser.error("existing edit plan fingerprint does not match the scenes")
                else:
                    planner = EditPlanner(
                        target_duration_seconds=target,
                        min_duration_seconds=minimum,
                        max_duration_seconds=maximum,
                        max_clip_duration_seconds=max_clip,
                    )
                    if args.visual_only:
                        plan = planner.plan_visual_only(
                            scene_manifest,
                            source_story="visual-only",
                            source_scenes=str(scene_path),
                        )
                    else:
                        assert story_manifest is not None
                        plan = planner.plan(
                            story_manifest,
                            scene_manifest,
                            source_story=str(story_path),
                            source_scenes=str(scene_path),
                        )
                    plan.write(plan_path)
                VisualCutRenderer(
                    width=app_config.video.width,
                    height=app_config.video.height,
                    fps=app_config.video.fps,
                ).render(
                    args.input_path,
                    plan,
                    output_path=output_path,
                )
            except (EditPlanError, VisualCutError) as exc:
                parser.error(str(exc))

            _print_json(
                {
                    "input_path": str(args.input_path.expanduser().resolve()),
                    "story_manifest_path": str(story_path),
                    "scene_manifest_path": str(scene_path),
                    "edit_plan_path": str(plan_path),
                    "visual_cut_path": str(output_path),
                    "total_duration_seconds": plan.total_duration_seconds,
                    "selected_scene_ids": list(plan.scene_ids),
                }
            )
            return

    if args.command == "episode":
        if args.episode_command == "script":
            if (args.anime_id is None) != (args.episode_number is None):
                parser.error("--anime-id and --episode-number must be supplied together")
            if args.season < 1:
                parser.error("--season must be >= 1")
            if args.episode_number is not None and args.episode_number < 1:
                parser.error("--episode-number must be >= 1")

            story_path = args.story_manifest or (
                paths.workspace
                / "analysis"
                / args.input_path.stem
                / "story.json"
            )
            transcript_path = args.transcript_manifest or (
                paths.workspace
                / "analysis"
                / args.input_path.stem
                / "transcript.json"
            )

            try:
                story_manifest = EpisodeStoryManifest.read(story_path)
                transcript_manifest = TranscriptAnalysisManifest.read(transcript_path)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                parser.error(f"could not read story/transcript manifests: {exc}")

            config_path = paths.config / "config.yml"
            if not config_path.exists():
                config_path = paths.config / "config.example.yml"
            app_config = load_config(config_path)

            provider = (args.provider or app_config.llm.provider).strip().lower()
            if provider != "gemini":
                parser.error(
                    f"narration script provider {provider!r} is not implemented; "
                    "set llm.provider to gemini"
                )

            language = args.language or app_config.narration.language
            script_format = args.script or app_config.narration.script
            output_path = args.output or (
                paths.workspace
                / "narration"
                / args.input_path.stem
                / "script.json"
            )

            try:
                generator = GeminiNarrationScriptGenerator(
                    model=app_config.llm.model,
                    api_key_env=app_config.llm.api_key_env,
                    temperature=app_config.llm.temperature,
                    thinking_level=app_config.llm.thinking_level,
                    max_output_tokens=app_config.llm.max_output_tokens,
                    target_duration_seconds=app_config.narration.target_duration_seconds,
                    min_duration_seconds=app_config.narration.min_duration_seconds,
                    max_duration_seconds=app_config.narration.max_duration_seconds,
                    words_per_minute=app_config.narration.words_per_minute,
                )
                script_manifest = generator.generate(
                    story_manifest,
                    transcript=transcript_manifest,
                    language=language,
                    script=script_format,
                    style=app_config.narration.style,
                    source_story=str(story_path),
                )
            except NarrationScriptError as exc:
                parser.error(str(exc))

            script_manifest.write(output_path)

            if args.anime_id:
                assert args.episode_number is not None
                episode_id = f"{args.anime_id}-s{args.season}-e{args.episode_number}"
                existing = {
                    item.id: item
                    for item in store.list_episodes(args.anime_id)
                }.get(episode_id)
                record = existing or EpisodeRecord(
                    id=episode_id,
                    anime_id=args.anime_id,
                    episode_number=args.episode_number,
                )
                record.status = "PROCESSING"
                record.current_checkpoint = "script"
                record.failure_reason = None
                record.provider = "local"
                record.source_reference = str(
                    args.input_path.expanduser().resolve()
                )
                record.analysis_manifest = str(
                    paths.workspace
                    / "analysis"
                    / f"{args.input_path.stem}.analysis.json"
                )
                record.scene_manifest = str(
                    paths.workspace
                    / "analysis"
                    / args.input_path.stem
                    / "scenes.json"
                )
                record.transcript_manifest = str(transcript_path)
                record.story_manifest = str(story_path)
                record.script_manifest = str(output_path)
                store.save_episode(record)

            _print_json(
                script_manifest.to_dict()
                | {
                    "story_manifest_path": str(story_path),
                    "transcript_manifest_path": str(transcript_path),
                    "script_manifest_path": str(output_path),
                }
            )
            return

    if args.command == "episode":
        if args.episode_command == "tts":
            if (args.anime_id is None) != (args.episode_number is None):
                parser.error("--anime-id and --episode-number must be supplied together")
            if args.season < 1:
                parser.error("--season must be >= 1")
            if args.episode_number is not None and args.episode_number < 1:
                parser.error("--episode-number must be >= 1")

            script_path = args.script_manifest or (
                paths.workspace
                / "narration"
                / args.input_path.stem
                / "script.json"
            )
            try:
                script_manifest = NarrationScriptManifest.read(script_path)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                parser.error(f"could not read narration script manifest: {exc}")

            config_path = paths.config / "config.yml"
            if not config_path.exists():
                config_path = paths.config / "config.example.yml"
            app_config = load_config(config_path)

            provider = (args.provider or app_config.tts.provider).strip().lower()
            output_dir = (
                args.output.parent
                if args.output
                else paths.workspace / "narration" / args.input_path.stem / "audio"
            )
            output_manifest = args.output or (
                paths.workspace
                / "narration"
                / args.input_path.stem
                / "tts.json"
            )

            try:
                if provider == "synthetic":
                    synthesizer = SyntheticTTSSynthesizer(
                        words_per_minute=app_config.narration.words_per_minute,
                    )
                elif provider == "gemini":
                    synthesizer = GeminiTTSSynthesizer(
                        model=app_config.tts.model,
                        api_key_env=app_config.tts.api_key_env,
                        voice=app_config.tts.voice or "Kore",
                        style=app_config.tts.style,
                    )
                else:
                    synthesizer = CommandTTSSynthesizer(
                        tuple(app_config.tts.command),
                        voice=app_config.tts.voice,
                        timeout_seconds=app_config.tts.timeout_seconds,
                    )
                tts_manifest = synthesizer.synthesize(
                    script_manifest,
                    output_dir=output_dir,
                    source_script=str(script_path),
                )
            except TTSError as exc:
                parser.error(str(exc))

            tts_manifest.write(output_manifest)

            if args.anime_id:
                assert args.episode_number is not None
                episode_id = f"{args.anime_id}-s{args.season}-e{args.episode_number}"
                existing = {
                    item.id: item
                    for item in store.list_episodes(args.anime_id)
                }.get(episode_id)
                record = existing or EpisodeRecord(
                    id=episode_id,
                    anime_id=args.anime_id,
                    episode_number=args.episode_number,
                )
                record.status = "PROCESSING"
                record.current_checkpoint = "TTS"
                record.failure_reason = None
                record.provider = "local"
                record.source_reference = str(
                    args.input_path.expanduser().resolve()
                )
                record.script_manifest = str(script_path)
                record.tts_manifest = str(output_manifest)
                store.save_episode(record)

            _print_json(
                tts_manifest.to_dict()
                | {
                    "script_manifest_path": str(script_path),
                    "tts_manifest_path": str(output_manifest),
                }
            )
            return

    if args.command == "episode":
        if args.episode_command == "match":
            if (args.anime_id is None) != (args.episode_number is None):
                parser.error("--anime-id and --episode-number must be supplied together")
            if args.season < 1:
                parser.error("--season must be >= 1")
            if args.episode_number is not None and args.episode_number < 1:
                parser.error("--episode-number must be >= 1")

            scene_path = args.scene_manifest or (
                paths.workspace
                / "analysis"
                / args.input_path.stem
                / "scenes.json"
            )
            tts_path = args.tts_manifest or (
                paths.workspace
                / "narration"
                / args.input_path.stem
                / "tts.json"
            )

            try:
                scene_manifest = SceneAnalysisManifest.read(scene_path)
                tts_manifest = TTSManifest.read(tts_path)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                parser.error(f"could not read scene/TTS manifests: {exc}")

            config_path = paths.config / "config.yml"
            if not config_path.exists():
                config_path = paths.config / "config.example.yml"
            app_config = load_config(config_path)

            max_clip_duration = (
                args.max_clip_duration
                if args.max_clip_duration is not None
                else app_config.video.max_clip_duration
            )
            if max_clip_duration <= 0:
                parser.error("--max-clip-duration must be positive")

            output_path = args.output or (
                paths.workspace
                / "narration"
                / args.input_path.stem
                / "matching.json"
            )

            try:
                match_manifest = SceneMatcher(
                    max_clip_duration=max_clip_duration
                ).match(
                    scene_manifest,
                    tts_manifest,
                    source_scenes=str(scene_path),
                    source_tts=str(tts_path),
                )
            except MatchError as exc:
                parser.error(str(exc))

            match_manifest.write(output_path)

            if args.anime_id:
                assert args.episode_number is not None
                episode_id = f"{args.anime_id}-s{args.season}-e{args.episode_number}"
                existing = {
                    item.id: item
                    for item in store.list_episodes(args.anime_id)
                }.get(episode_id)
                record = existing or EpisodeRecord(
                    id=episode_id,
                    anime_id=args.anime_id,
                    episode_number=args.episode_number,
                )
                record.status = "PROCESSING"
                record.current_checkpoint = "matching"
                record.failure_reason = None
                record.provider = "local"
                record.source_reference = str(
                    args.input_path.expanduser().resolve()
                )
                record.tts_manifest = str(tts_path)
                record.matching_manifest = str(output_path)
                store.save_episode(record)

            _print_json(
                match_manifest.to_dict()
                | {
                    "scene_manifest_path": str(scene_path),
                    "tts_manifest_path": str(tts_path),
                    "matching_manifest_path": str(output_path),
                }
            )
            return

    if args.command == "episode":
        if args.episode_command == "timeline":
            if (args.anime_id is None) != (args.episode_number is None):
                parser.error("--anime-id and --episode-number must be supplied together")
            if args.season < 1:
                parser.error("--season must be >= 1")
            if args.episode_number is not None and args.episode_number < 1:
                parser.error("--episode-number must be >= 1")

            matching_path = args.matching_manifest or (
                paths.workspace
                / "narration"
                / args.input_path.stem
                / "matching.json"
            )
            tts_path = args.tts_manifest or (
                paths.workspace
                / "narration"
                / args.input_path.stem
                / "tts.json"
            )
            output_path = args.output or (
                paths.workspace
                / "narration"
                / args.input_path.stem
                / "timeline.json"
            )
            try:
                matching_manifest = SceneMatchManifest.read(matching_path)
                tts_manifest = TTSManifest.read(tts_path)
                timeline_manifest = TimelineBuilder().build(
                    matching_manifest,
                    tts_manifest,
                    source_matching=str(matching_path),
                    source_tts=str(tts_path),
                )
            except (OSError, ValueError, TypeError, KeyError, RenderError) as exc:
                parser.error(f"could not build render timeline: {exc}")

            timeline_manifest.write(output_path)

            if args.anime_id:
                assert args.episode_number is not None
                episode_id = f"{args.anime_id}-s{args.season}-e{args.episode_number}"
                existing = {
                    item.id: item
                    for item in store.list_episodes(args.anime_id)
                }.get(episode_id)
                record = existing or EpisodeRecord(
                    id=episode_id,
                    anime_id=args.anime_id,
                    episode_number=args.episode_number,
                )
                record.status = "PROCESSING"
                record.current_checkpoint = "timeline"
                record.failure_reason = None
                record.provider = "local"
                record.source_reference = str(
                    args.input_path.expanduser().resolve()
                )
                record.matching_manifest = str(matching_path)
                record.tts_manifest = str(tts_path)
                record.timeline_manifest = str(output_path)
                store.save_episode(record)

            _print_json(
                timeline_manifest.to_dict()
                | {
                    "matching_manifest_path": str(matching_path),
                    "tts_manifest_path": str(tts_path),
                    "timeline_manifest_path": str(output_path),
                }
            )
            return

        if args.episode_command == "render":
            if (args.anime_id is None) != (args.episode_number is None):
                parser.error("--anime-id and --episode-number must be supplied together")
            if args.season < 1:
                parser.error("--season must be >= 1")
            if args.episode_number is not None and args.episode_number < 1:
                parser.error("--episode-number must be >= 1")

            timeline_path = args.timeline_manifest or (
                paths.workspace
                / "narration"
                / args.input_path.stem
                / "timeline.json"
            )
            timeline_dir = args.tts_dir or (
                paths.workspace
                / "narration"
                / args.input_path.stem
                / "audio"
            )
            output_path = args.output or (
                paths.workspace
                / "output"
                / f"{args.input_path.stem}.mp4"
            )

            try:
                timeline_manifest = TimelineManifest.read(timeline_path)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                parser.error(f"could not read timeline manifest: {exc}")

            config_path = paths.config / "config.yml"
            if not config_path.exists():
                config_path = paths.config / "config.example.yml"
            app_config = load_config(config_path)

            try:
                rendered = FFmpegRenderer(
                    width=app_config.video.width,
                    height=app_config.video.height,
                    fps=app_config.video.fps,
                ).render(
                    timeline_manifest,
                    source_video=args.input_path,
                    narration_dir=timeline_dir,
                    output_path=output_path,
                    subtitles=app_config.subtitles.enabled
                    and app_config.subtitles.burn_in
                    and not args.no_subtitles,
                    background_music=(
                        _find_background_music(paths, app_config.audio.music_dir)
                        if app_config.audio.bgm
                        else None
                    ),
                    bgm_volume=app_config.audio.bgm_volume,
                    bgm_ducking_ratio=app_config.audio.bgm_ducking_ratio,
                )
            except RenderError as exc:
                parser.error(str(exc))

            if args.anime_id:
                assert args.episode_number is not None
                episode_id = f"{args.anime_id}-s{args.season}-e{args.episode_number}"
                existing = {
                    item.id: item
                    for item in store.list_episodes(args.anime_id)
                }.get(episode_id)
                record = existing or EpisodeRecord(
                    id=episode_id,
                    anime_id=args.anime_id,
                    episode_number=args.episode_number,
                )
                record.status = "RENDERED"
                record.current_checkpoint = "render"
                record.failure_reason = None
                record.provider = "local"
                record.source_reference = str(
                    args.input_path.expanduser().resolve()
                )
                record.timeline_manifest = str(timeline_path)
                record.render_output = str(rendered)
                store.save_episode(record)

            _print_json(
                {
                    "render_output": str(rendered),
                    "timeline_manifest_path": str(timeline_path),
                }
            )
            return

    if args.command == "episode" and args.episode_command == "run":
        config_path = paths.config / "config.yml"
        if not config_path.exists():
            config_path = paths.config / "config.example.yml"
        try:
            app_config = load_config(config_path)
            result = EpisodePipeline(paths, app_config).run(
                args.input_path,
                anime_id=args.anime_id,
                episode_number=args.episode_number,
                season=args.season,
            )
        except (PipelineError, OSError, ValueError, TypeError, KeyError) as exc:
            parser.error(str(exc))
        _print_json(result.to_dict())
        return

    if args.command == "provider":
        config_path = paths.config / "config.yml"
        if not config_path.exists():
            config_path = paths.config / "config.example.yml"
        app_config = load_config(config_path)
        registry = build_registry(app_config, paths.root)

        if args.provider_command == "status":
            result = {"providers": []}
            for name in registry.names():
                provider = registry.get(name)
                health = provider.check_health()
                result["providers"].append({
                    "provider": health.provider,
                    "status": health.status,
                    "checked_at": health.checked_at,
                    "detail": health.detail,
                })
            rendered = json.dumps(result, indent=2, ensure_ascii=False)
            output = getattr(args, "output", None)
            if output:
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(rendered + "\n", encoding="utf-8")
            print(rendered)
            return

        if args.provider_command == "check":
            if args.episode_number < 1:
                parser.error("--episode-number must be >= 1")
            broker = ProviderBroker(registry)
            probes = broker.probe_episode(
                args.anime_id,
                args.episode_number,
                language=args.language,
            )
            selected = broker.best_catalog_provider(probes)
            report = {
                "anime_id": args.anime_id,
                "episode_number": args.episode_number,
                "language": args.language,
                "probes": [
                    {
                        "provider": item.provider,
                        "score": round(item.score, 3),
                        "elapsed_ms": round(item.elapsed_ms, 1),
                        "catalog_available": item.catalog_available,
                        "availability": (
                            None if item.availability is None else item.availability.__dict__
                        ),
                        "error": item.error,
                    }
                    for item in probes
                ],
                "selected_catalog_provider": None if selected is None else selected.provider,
            }
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(
                    json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
            _print_json(report)
            if not probes:
                parser.error("no external providers are configured")
            if args.require_catalog and selected is None:
                parser.error("no configured provider confirmed the requested episode")
            return

    if args.command == "plan":
        scheduler_state = store.load_scheduler()
        planner = Scheduler(scheduler_state)
        plans = planner.plan(store.list_anime(), store.list_episodes())
        _print_json([plan.__dict__ for plan in plans])
        return

    if args.command == "metadata":
        config_path = paths.config / "config.yml"
        if not config_path.exists():
            config_path = paths.config / "config.example.yml"
        app_config = load_config(config_path)
        service = MetadataService.create(
            anilist_endpoint=app_config.metadata.anilist_endpoint,
            jikan_base_url=app_config.metadata.jikan_base_url,
        )

        if args.metadata_command == "search":
            limit = args.limit or app_config.metadata.search_limit
            results = service.search(args.query, limit=limit)
            _print_json([
                {
                    "provider": result.provider,
                    "error": result.error,
                    "metadata": (
                        None
                        if result.metadata is None
                        else {
                            key: value
                            for key, value in result.metadata.__dict__.items()
                            if key != "raw"
                        }
                    ),
                }
                for result in results
            ])
            return

        if args.metadata_command == "get":
            metadata = service.get_anime(args.provider, args.id)
            _print_json({
                key: value
                for key, value in metadata.__dict__.items()
                if key != "raw"
            })
            return

        if args.metadata_command == "sync":
            metadata = service.get_anime(args.provider, args.id)
            record = MetadataLibrary(store).upsert(metadata)
            _print_json(record.__dict__)
            return

    parser.error("unsupported command")
