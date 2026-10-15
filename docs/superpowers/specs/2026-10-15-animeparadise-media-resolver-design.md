# AnimeParadise Media Resolver Design

**Date:** 2026-10-15  
**Status:** Draft for review

## Goal

Add a provider-specific AnimeParadise resolver to AniMeXe that maps a requested AniList anime and episode to an accessible, direct HLS source, safely saves the episode into the existing workspace, and hands the resulting local file to AniMeXe's existing processing pipeline. This is the first native-media provider; it must not depend on Kuhi or treat embed URLs as downloadable media.

## Current context

- AniMeXe exposes a normalized `Provider` contract through `src/animexe/providers/base.py` and `MediaSource` / `EpisodeRef` models in `src/animexe/models.py`.
- The direct media saver is `src/animexe/media/source_download.py`, invoked by `animexe episode download-source`. It supports direct files and preflights HLS before FFmpeg remuxing.
- The current saver accepts a manually supplied media URL, not an AniList ID + episode number. The missing feature is provider resolution and integration, not another generic iframe scraper.
- 7xAnime's AnimeParadise adapter and the referenced independent SDK describe a flow of search → episode catalogue → episode endpoint → `streamLink` → `https://stream.animeparadise.moe/m3u8?url=…`. The repository documentation calls it a candidate; the flow still needs current verification.
- AniMeXe's existing final rendering policy mutes source episode audio. The acquisition stage should preserve source audio and subtitle tracks when present because they may help content analysis; the explanation output must not retain the episode's original audio.

## Scope

### In scope

1. Add a first-party `AnimeParadiseProvider` implementation using its documented JSON search, episode catalogue, and episode stream routes.
2. Resolve an AniList identity to exactly one provider catalogue entry using available AniList title variants and conservative matching. Fail closed on ambiguous matches rather than risk downloading the wrong series/episode.
3. Resolve only the requested episode and return a normalized `MediaSource` whose protocol is `hls`, with the required legitimate `Referer` hint and provider identity.
4. Add a CLI flow that accepts an AniList ID and episode number, acquires the selected episode to the workspace, reports a useful manifest/result, and optionally passes that file to the existing pipeline without duplicating pipeline logic.
5. Harden HLS acquisition for this path: inspect master and media playlists, reject encrypted or ambiguous key signaling, pass required request headers to FFmpeg, enforce size/output limits during as well as after the FFmpeg run, use temporary files and atomic replacement, and fail with actionable errors.
6. Register the provider without making Kuhi a required dependency. Keep source resolution, acquisition, and processing as explicit distinct stages so failures are diagnosable.
7. Add deterministic tests with mocked HTTP/API responses and FFmpeg. Live provider availability must remain an explicitly separate integration check.

### Out of scope

- Extracting hidden media URLs from AniXo, Megavid, MegaPlay, MegaFlix, TryEmbed, CinexStream, or NontonGo if they only expose embed/player routes.
- Bypassing DRM, authentication, origin restrictions, anti-bot controls, paywalls, or other access controls. Do not emulate a browser to defeat provider protections.
- Implementing DASH decryption or adding a DASH playback engine.
- Copying third-party scraper source code or assuming permission to reuse unlicensed code.
- Shipping episode media in Git or persisting expiring signed URLs as durable catalog data.
- Automatically enabling this provider in a multi-provider race before it passes source and real-media verification.

## Proposed architecture

### Components

- **`AnimeParadiseProvider`** (`src/animexe/providers/animeparadise.py`): implements the existing provider contract. It owns provider API calls, series matching, episode UID lookup, and normalization into `AnimeMetadata`, `EpisodeRef`, `EpisodeAvailability`, and `MediaSource`.
- **Provider factory/registry** (`src/animexe/providers/factory.py` and package exports): register AnimeParadise as an opt-in native-media provider. Configuration must not silently turn arbitrary embed providers into download providers.
- **Media saver** (`src/animexe/media/source_download.py`): remains the single place responsible for saving a resolved direct file/HLS URL. Its interface should accept normalized `MediaSource` protocol/reference/headers rather than duplicate provider lookup logic.
- **CLI** (`src/animexe/cli.py`): provide an explicit AnimeParadise acquisition command (or an explicit provider mode on the existing command) that accepts `--anilist-id`, `--episode-number`, `--season` and an output path, requires the existing authorized-use confirmation, and can optionally run the existing `EpisodePipeline` after acquisition.
- **Tests and documentation**: provider contract tests, API-shape tests, HLS-safety tests, CLI argument tests, and updated provider documentation.

### Data flow

1. Validate AniList ID, positive episode number, output path, and authorized-use confirmation.
2. Fetch AniList metadata through AniMeXe's existing `MetadataService`; gather primary and alternate titles plus year and known episode count.
3. Query AnimeParadise search using a bounded set of title variants. Normalize titles and score candidates using title similarity plus available year/episode-count evidence.
4. Select a candidate only when its score meets a defined confidence threshold and it is unambiguous against the next candidate. Otherwise return a typed, actionable “series match ambiguous/not found” error.
5. Fetch the provider episode catalogue once for that selected series, validate episode numbers/UIDs, and select the requested episode exactly. Do not resolve an entire season's stream URLs.
6. Request the documented episode endpoint using the selected UID and series ID as origin. Require a non-empty `streamLink`; build the documented HLS resolver URL, and normalize the response into `MediaSource(protocol="hls", headers=(("Referer", "https://animeparadise.moe/"), ...))`.
7. Validate and preflight the returned media URL with the shared saver. Refuse HTML, unsupported protocols, encrypted or ambiguous HLS, invalid/private targets, and oversized output. Use FFmpeg only to fetch/remux media already exposed by the documented API; do not extract or decrypt hidden sources.
8. Atomically save the acquired media to `workspace/input` (or an explicit output path). If pipeline execution was requested, call `EpisodePipeline.run` with the local file and the supplied anime/episode metadata. Keep acquisition and analysis failures distinct in output.
9. Do not retain signed source URLs longer than necessary. Clean temporary files after success or failure.

## Failure and fallback rules

- **Provider outage / HTTP or JSON error:** fail the requested acquisition with provider, stage, and safe diagnostic context; do not present a fabricated availability result.
- **No match / ambiguous match:** stop before the episode endpoint; require a more specific title or a corrected mapping rather than guessing.
- **Episode absent / special numbering mismatch:** report that specific episode as unavailable; do not silently shift to another episode.
- **Missing streamLink or invalid URL:** stop with a source-resolution error.
- **Encrypted / ambiguous HLS, DASH, HTML, redirect to blocked target, size cap, FFmpeg missing/failure/timeout:** reject the acquisition, remove temporary output, and preserve any pre-existing final file.
- **No automatic alternate-provider fallback in this first slice:** do not silently switch to an iframe provider or another show's media. A future fallback may only try independently configured, supported direct-media adapters and must report the chosen provider.

## Security and media handling

- Only use documented, accessible API interfaces and direct media URLs that the caller is entitled to process.
- URL validation must run on the initial URL, redirects observed by the HTTP client, and nested playlist URIs that are inspected. Reject non-global literal IPs and localhost names; resolve hostnames and reject them when all resolved addresses are not public. Document that preflight DNS checks alone cannot completely prevent DNS rebinding or protect FFmpeg from every malicious redirect; never describe this as complete SSRF protection.
- Do not give FFmpeg arbitrary hidden browser state, cookies, or credentials. Pass only the minimal, explicitly configured non-secret headers needed by the provider's documented media path.
- For HLS, inspect nested variant and referenced media playlists where identifiable. Refuse any `EXT-X-KEY` or `EXT-X-SESSION-KEY` declaration unless it explicitly and unambiguously specifies `METHOD=NONE`; the first phase must not support encrypted segments.
- Configure FFmpeg's output-size limit and timeout and check the final size; use a temporary sibling file and atomic replacement. Never put episode binaries into the repository.
- Source audio may be acquired for analysis; final explanation render remains muted for the original episode audio.

## Verification and acceptance criteria

1. Unit tests prove the provider parses valid API responses, maps alternate titles conservatively, rejects ambiguous/no-match results, selects exactly the requested episode, and does not call the stream endpoint for unrelated episodes.
2. API failures, malformed JSON, missing episode UID, missing/blank `streamLink`, unexpected URL schemes, redirects, and expired/unavailable stream responses produce useful errors without leaving partial final output.
3. Tests prove clear HLS media playlists and supported master playlists are remuxed with the required headers; nested encrypted/ambiguous key signaling is rejected before FFmpeg starts.
4. Tests prove direct-file and HLS output size limits, FFmpeg timeouts/non-zero exits, and cleanup/atomic replacement semantics.
5. CLI tests prove the command requires authorization confirmation, validates IDs/numbers, reports the acquired path, and only invokes `EpisodePipeline` when explicitly requested.
6. Existing tests remain compatible and the registered provider is opt-in; Kuhi is not needed for the AnimeParadise path.
7. A separate manual integration check on a permitted test episode records (a) API resolution succeeded, (b) output is a real playable media file according to `ffprobe`, and (c) a representative frame decodes. Code-level tests alone must not be described as current provider uptime or Android playback proof.

## Rollout

Keep AnimeParadise manual/opt-in until the manual integration check succeeds. Do not add it to any automatic provider race on the strength of a module import, constructed URL, or successful JSON response alone. Preserve the provider classification table in documentation so all non-supported embed-only sources remain explicitly excluded from direct download.
