# AniMeXe Providers

## 1. Provider architecture

Providers are adapters. They translate external metadata/episode/media systems into normalized AniMeXe objects. The scheduler, story engine, scene matcher, media inspector, and renderer must not depend on provider-specific response formats.

Provider integrations are divided into three roles:

1. **Metadata providers** — anime identity, season, episode metadata, airing/release information.
2. **Media providers** — episode catalogs, source references, stream/media capabilities, subtitle metadata, and source-resolution status.
3. **Local/manual input** — deterministic development input and the fallback path for supplied media.

The provider layer must preserve a strict distinction between:

```text
metadata exists
    !=
episode catalog exists
    !=
source resolves
    !=
media is usable
    !=
episode is processable
```

A metadata provider may say that Episode 12 exists without proving that any usable media source exists for Episode 12.

---

## 2. Provider priority

### Primary — Kuhi / anime-api

**Repository:** `aryaniiil/anime-api`

**Role:** Primary external provider integration target. The first implementation slice covers Kuhi's catalog/health boundary; source extraction remains a separate authorized-media boundary.

Kuhi became the strongest current candidate during the September 2026 research pass because it has a recent native-provider architecture rather than relying entirely on one old upstream API. Its recent commits added a native provider foundation, multiple independent provider adapters, provider status reporting, provider selection, and a race-based extractor.

Observed native providers include:

- AniNeko
- AniZone
- AniKoto
- ReAnime
- AniWaves
- AnimeOnsen
- MKissa
- AnimeGG
- AniBD
- KAA

Kuhi also has a legacy Miruro-compatible fallback path. AniMeXe should treat that fallback as secondary implementation context rather than coupling the entire architecture to Miruro.

### Why Kuhi is primary

Kuhi is the best current fit for AniMeXe because it demonstrates:

- native provider adapters;
- independent search/episode/source resolution;
- shared matching and metadata context;
- provider health/status reporting;
- provider selection;
- race-based fastest-success extraction;
- normalized stream/subtitle handling;
- recent maintenance in 2026;
- a Python implementation that aligns naturally with AniMeXe's Python-first orchestration.

**Important:** Kuhi is an integration target, not a permanent dependency. AniMeXe currently integrates its search/info/episode-catalog/provider-health contract while intentionally leaving stream extraction outside the core adapter until an authorized media source is selected. The provider interface must remain independent of Kuhi's endpoint or internal module names.

---

## 3. Secondary providers and references

### Anivexa API

**Repository:** `walterwhite-69/Anivexa-API`

**Role:** Secondary multi-provider integration/reference.

Anivexa is another actively maintained multi-provider API with a modular provider architecture. Recent September 2026 work includes provider maintenance, rejection of mismatched Anikoto episode catalogs, ReAnime fixes, removal of dead providers, and playback/source handling improvements.

It is valuable for AniMeXe because it demonstrates:

- provider modularity;
- provider-specific episode matching;
- explicit rejection of bad title/catalog matches;
- fallback and stream-resolution patterns;
- source/proxy separation.

Anivexa should be considered a **secondary provider/fallback candidate** and an implementation reference, not the primary AniMeXe abstraction.

---

### Anivault Scraper

**Repository:** `SH0MIK/Anivault-Scraper`

**Role:** Secondary provider/reference with very recent maintenance.

This repository was actively updated in late September and October 2026. It contains provider-specific scraping and source-resolution work, including AnimeHeaven and AniKoto-related handling, source fixes, referer preservation, and Megaplay source handling.

It is useful for:

- examining fresh provider break/fix work;
- understanding source-resolution failure modes;
- comparing episode/catalog matching approaches;
- identifying useful secondary providers.

Because it has a narrower provider scope than Kuhi/Anivexa, AniMeXe should not make it the central provider abstraction.

---

### StreamPlay

**Repository:** `F-e-n-y-x/streamplay`

**Role:** Provider research and extractor reference.

StreamPlay contains a useful provider research/feasibility layer and active extractor work. It documents provider status such as working, build-ready, anti-bot-hard, or dead instead of assuming every provider is permanently usable.

Recent provider work includes:

- AnimeNoSub
- AniNeko
- AniZone
- AnimeWorld
- CastleTV

It is particularly valuable for:

- provider feasibility research;
- title/medium matching;
- Sub/Dub handling;
- provider health decisions;
- documenting dead or fragile providers;
- identifying new sources worth investigating.

StreamPlay is a reference source rather than an AniMeXe runtime dependency.

---

### Anime SDK

**Repository:** `hexxt-git/anime-sdk`

**Role:** Architecture reference.

The project demonstrates:

- unified provider-independent URN identifiers;
- metadata-provider abstraction;
- content-provider abstraction;
- mapping between metadata sources and content sources;
- AniList/MAL/Kitsu metadata;
- transport abstraction;
- per-host rate limiting;
- retry/backoff;
- abort/cancellation propagation.

AniMeXe should take architectural ideas from this project, especially provider-independent IDs and a separate mapping layer, without coupling the production pipeline to its implementation.

---

### CloudStream anime extensions

**Repository/ecosystem:** `yuzono/anime-extensions` and related CloudStream extension repositories.

**Role:** Discovery and provider research source.

CloudStream-style extensions can expose individual providers that do not exist as standalone REST APIs. They are valuable when AniMeXe needs to investigate additional provider candidates.

These extensions should not be treated as a drop-in AniMeXe API. If used later, an adapter must translate their provider-specific output into the normalized AniMeXe contract.

---

## 4. Legacy/reference only

### Kitsune

**Repository:** `Dovakiin0/Kitsune`

**Role:** Historical/reference architecture only.

Kitsune remains useful because its frontend demonstrates a Miruro-compatible episode/source contract, provider lists, Sub/Dub normalization, stream metadata, subtitles, intro/outro information, and HLS playback concepts.

However, research found that its older `api.kitsunee.me` Hianime-oriented backend is historical/unavailable, while the newer Kitsune frontend depends on an external API that is not bundled with the public frontend repository.

Therefore:

- do not hard-code the old Kitsune API;
- do not treat the Kitsune frontend as the backend;
- do not make AniMeXe depend on a single Kitsune deployment;
- use Kitsune primarily as a compatibility/reference contract.

---

## 5. Normalized AniMeXe provider contract

Every external media provider should map into a provider-independent model.

### Anime identity

```text
AnimeRecord
├── provider-independent ID
├── title
├── season
├── release status
├── latest known episode
└── next airing information
```

### Episode reference

```text
EpisodeRef
├── anime_id
├── season
├── episode_number
├── episode_title
├── provider
├── provider_reference
├── language/category
└── metadata snapshot
```

### Source state

```text
EpisodeAvailability
├── metadata_exists
├── catalog_exists
├── source_resolved
├── media_usable
├── processable
├── provider_status
├── checked_at
└── error
```

This prevents metadata-only fallback from falsely marking an episode as processable.

### Media source

```text
MediaSource
├── provider
├── protocol: file | hls | dash | other
├── url/reference
├── headers/referer when legitimately required
├── subtitles
├── intro/outro intervals
├── quality information
└── capabilities
```

Capabilities should eventually describe whether the source supports:

- streaming;
- range access;
- segmented retrieval;
- subtitles;
- duration probing;
- timestamp seeking;
- direct file access.

---

## 6. Required provider operations

Provider adapters should expose a small stable interface:

```text
search(query)
get_anime(anime_id)
get_episodes(anime_id, season)
resolve_episode(anime_id, episode_number, language)
get_source(episode_reference)
check_health()
```

Optional performance operation:

```text
probe_many(episode_references)
```

The scheduler should be able to ask for availability across several candidates without knowing provider-specific internals.

---

## 7. Provider selection policy

AniMeXe should not permanently bind an anime to one provider.

Selection should consider:

1. Provider health.
2. Episode availability.
3. Source resolution success.
4. Media usability.
5. Processing capabilities.
6. Recent latency/success history.
7. Required language/audio mode.
8. Subtitle availability.
9. Failure/backoff state.

A provider that fails temporarily should enter a retry/backoff state rather than causing the anime to disappear.

Example:

```text
Kuhi provider
  ↓ temporary failure
retry/backoff
  ↓
Anivexa candidate
  ↓ source resolves
MediaSource
  ↓
process episode
```

---

## 8. Race-based resolution

Kuhi demonstrates a useful pattern where several providers can be queried and the fastest successful provider can win.

AniMeXe may adopt this pattern, but with a processing-oriented scoring function.

A provider result should be scored on:

```text
usable source
+ seekability
+ subtitle availability
+ duration confidence
+ provider health
+ latency
- recent failure penalty
```

Fastest is not automatically best.

For example, a direct MP4 that cannot reliably seek may be worse for scene extraction than a slightly slower HLS source that supports stable timestamp access.

The selected provider should be recorded in generation state for reproducibility.

---

## 9. Matching and validation

Provider title matching is safety-critical for the scheduler.

A provider may return:

- several seasons;
- a movie with the same name;
- a live-action adaptation;
- a compilation;
- an OVA;
- another anime containing similar title tokens.

AniMeXe should validate candidates using multiple signals:

- normalized title similarity;
- alternate titles;
- AniList/MAL mappings;
- format/type;
- year where available;
- expected episode count;
- season identity;
- relation/continuity;
- provider episode coverage.

A fuzzy title match alone must never silently select a source.

---

## 10. Metadata fallback rules

Metadata providers may be used to recover:

- titles;
- season information;
- expected episode counts;
- airing times;
- descriptions;
- episode titles;
- identity mappings.

Metadata fallback must **never** manufacture source availability.

For example:

```text
AniList says 12 episodes
        ↓
valid metadata

It must NOT become:

Episode 12 = PROCESSABLE
```

Instead:

```text
AniList says 12 episodes
        ↓
episode 12 expected/known
        ↓
media provider check required
        ↓
source resolution
        ↓
media usability
```

This is a critical scheduler invariant.

---

## 11. Provider health states

Every provider adapter must distinguish:

```text
AVAILABLE
TEMPORARILY_UNAVAILABLE
EPISODE_UNAVAILABLE
INVALID_RESPONSE
RATE_LIMITED
CONFIG_ERROR
AUTH_ERROR
MEDIA_UNUSABLE
```

Temporary failures must not overwrite previously confirmed episode availability.

Provider errors should be retained with:

- timestamp;
- provider;
- endpoint/operation;
- error class;
- retry-after/backoff information;
- attempt count.

---

## 12. Caching

Cache independently by information type.

Suggested categories:

```text
metadata
airing schedule
episode catalog
provider identity mapping
source resolution
provider health
failure/backoff
```

Different TTLs should be used for each class.

Source URLs and provider availability are generally more volatile than anime identity metadata.

Cache entries must include enough provider/version context to avoid mixing incompatible results.

---

## 13. Media and temporary storage

Provider media is processing input, not permanent project storage.

Preferred lifecycle:

```text
Provider source/reference
        ↓
stream/range/segments when supported
        ↓
temporary worker workspace
        ↓
analysis
        ↓
selected clips
        ↓
narration/timeline
        ↓
final render
        ↓
validation
        ↓
cleanup
```

Providers should expose capabilities so AniMeXe can prefer targeted retrieval where practical.

A full episode may be materialized temporarily if FFmpeg or analysis requires random access. It must not enter Git-backed state or permanent repository storage.

---

## 14. Provider fallback order

Default strategy:

```text
1. Kuhi/native provider candidate
2. Anivexa secondary provider candidate
3. Anivault or another configured provider
4. Other vetted provider adapters
5. Local/manual input
6. Pending / retry
```

This order is conceptual, not a hard-coded provider name sequence.

The scheduler should choose based on real-time health and source usability rather than blindly trying every provider in a fixed order.

---

## 15. Provider registry

Current registry:

| Provider/reference | Role | Status | Primary use |
|---|---|---|---|
| Kuhi / anime-api | Primary external media layer | Preferred | Native multi-provider extraction |
| Anivexa API | Secondary | Preferred fallback | Multi-provider extraction/reference |
| Anivault Scraper | Secondary | Experimental | Fresh provider/source work |
| StreamPlay | Research/reference | Experimental | Provider discovery and feasibility |
| anime-sdk | Architecture reference | Reference | IDs, mappings, transport patterns |
| CloudStream extensions | Provider discovery | Reference | Additional adapters |
| Kitsune | Legacy/reference | Legacy | Miruro-style contract compatibility |
| Local/manual | Deterministic input | Required | Development and controlled testing |

"Preferred" does not mean permanently guaranteed. Every external provider must pass current health and media-usability checks.

---

## 16. Real integration verification

A provider is not considered workflow-tested merely because:

- its GitHub repository exists;
- its README claims support;
- its code contains an extractor;
- its API returns metadata.

Minimum verification for a provider integration:

1. Resolve a known anime identity.
2. Resolve the required episode number.
3. Confirm source resolution.
4. Confirm source protocol/URL is usable.
5. Probe media with ffprobe or equivalent.
6. Confirm duration is sane.
7. Confirm timestamp seeking or equivalent extraction is practical.
8. Confirm subtitles when required.
9. Record provider name/version and verification time.

Provider verification status should be stored separately from generic provider availability.

---

## 17. Security and reliability

Provider adapters must:

- avoid hard-coded secrets;
- validate remote URLs;
- restrict proxy targets when a proxy is introduced;
- avoid writing arbitrary remote content into persistent paths;
- enforce request timeouts;
- use bounded retries;
- honor rate limits;
- classify upstream failures;
- prevent malformed provider responses from corrupting scheduler state.

Browser automation, anti-bot systems, or challenge pages must be treated as provider capability constraints rather than hidden assumptions inside the renderer.

AniMeXe should not build features intended to bypass access controls or platform protections.

---

## 17.1 Current runtime configuration

The canonical config supports one primary provider plus optional fallbacks:

```yaml
provider:
  name: kuhi
  api_base_url: ${KUHI_API_BASE_URL}
  language: sub

provider_fallbacks:
  - name: anivexa
    api_base_url: ${ANIVEXA_API_BASE_URL}
    language: sub
  - name: anivault
    api_base_url: ${ANIVAULT_API_BASE_URL}
    language: sub
```

Useful commands:

```bash
python -m animexe provider status
python -m animexe provider check anilist:21 --episode-number 1 --language sub
```

GitHub Actions provider smoke testing is manual-only via `.github/workflows/provider-smoke.yml`. Configure the provider endpoint URLs as repository Variables named `KUHI_API_BASE_URL`, `ANIVEXA_API_BASE_URL`, and `ANIVAULT_API_BASE_URL`.

## 18. Implementation plan

### Provider foundation

Create:

```text
src/providers/
├── interface.py
├── models.py
├── registry.py
├── health.py
├── cache.py
├── local/
├── kuhi/
├── anivexa/
├── anivault/
└── fixtures/
```

### Stage 1

Implement the normalized interface and LocalProvider first.

### Stage 2

Implement the Kuhi catalog/health adapter around the verified public contract.

Current implementation:
- normalized search;
- normalized anime details;
- Sub/Dub episode catalogs;
- provider health;
- explicit episode availability state.

Source extraction is intentionally not coupled into the processing pipeline yet.

### Stage 3

Add Anivexa as the first secondary fallback. **Implemented:** catalog/episode availability adapter with provider-normalized episode references.

### Stage 4

Add Anivault/other adapters only after the core provider tests are stable. **Implemented:** AniVault catalog/availability adapter using its documented API catalog endpoints.

### Stage 5

Add provider fan-out and selection. **Implemented:** `ProviderBroker` probes configured external providers concurrently, scores current catalog/availability results, and exposes the strongest catalog candidate without coupling the scheduler to provider-specific response formats.

Source extraction remains an explicit authorized-media boundary. The external projects reviewed during research include routes that perform stream extraction, proxying, decryption, or access-control work; AniMeXe does not copy those mechanisms into its runtime.

### Stage 5

Add provider race/probing and historical success/latency scoring.

---

## 19. Required provider tests

For every provider adapter:

- search normalization;
- identity mapping;
- detail normalization;
- season selection;
- episode normalization;
- sub/dub mapping;
- title matching;
- episode-count validation;
- source resolution;
- source normalization;
- subtitle normalization;
- intro/outro normalization when present;
- malformed response handling;
- timeout handling;
- rate-limit handling;
- temporary outage handling;
- media usability check;
- retry/backoff behavior;
- one manually verified real integration run.

For the scheduler, also test:

- metadata says episode exists but provider has none;
- provider temporarily unavailable;
- source resolves but media is unusable;
- primary provider fails and secondary succeeds;
- provider selection is persisted;
- cached stale data does not incorrectly clear known state.

---

## 20. Research notes

### Kuhi / anime-api

Recent 2026 development added a native-provider foundation, shared HTTP helpers, caching, title matching, AniList/ARM/AniZip identity support, a fastest-success race engine, provider status, provider preference, and several native provider adapters.

The project also retains a Miruro-compatible fallback path. AniMeXe should prefer the native provider abstraction and keep Miruro-style compatibility behind a separate adapter if it is used.

### Anivexa API

Recent 2026 work shows active provider maintenance, title/catalog validation, ReAnime changes, provider removal when dead, and stream/playback improvements.

The most useful idea for AniMeXe is strict rejection of mismatched episode catalogs.

### Anivault Scraper

Recent September/October 2026 commits demonstrate active source-resolution maintenance and fixes. It is a useful experimental source for fresh provider behavior, especially where another aggregator may lag.

### StreamPlay

Useful as a living provider feasibility/research notebook and extractor reference. Its documentation explicitly separates working, build-ready, anti-bot-hard, and dead providers.

### Kitsune

Useful mainly as a historical contract/reference. Do not use the old `api.kitsunee.me` backend as an AniMeXe dependency.

---

## 21. Design rule

The AniMeXe provider layer must remain **replaceable**.

No scheduler, story, scene, TTS, audio, subtitle, or rendering module may import a concrete provider implementation directly.

The only dependency allowed across the boundary is:

```text
provider → normalized AniMeXe models
```

not:

```text
provider → scheduler internals
provider → renderer internals
provider → story engine
```

---

## 22. Source-of-truth rule

The AniMeXe repository is the source of truth for provider decisions.

When provider research changes:

- update this document;
- update the provider registry;
- record why a provider was promoted, demoted, or retired;
- keep exact verification dates for volatile integrations;
- do not rely on chat history alone.

The purpose of this document is to let future implementation sessions start from the latest verified provider architecture instead of re-discovering old assumptions.

---

## 16. Saving a source from 7xAnime

AniMeXe can now save a **direct video URL** or a **clearly unencrypted HLS playlist** to a local workspace file before analysis. It does not treat an iframe URL as a media file.

The 7xAnime provider map currently divides into:

| 7xAnime provider | Current route type | AniMeXe behavior |
|---|---|---|
| AniXo | Embed | Requires a direct media URL; the iframe is rejected |
| Megavid | Embed | Requires a direct media URL; the iframe is rejected |
| AnimeParadise | HLS candidate | A direct `stream.animeparadise.moe/m3u8` playlist can be checked and remuxed when it is accessible and unencrypted; actual playback/source availability is not guaranteed |
| MegaFlix | Embed | Requires a direct media URL; the iframe is rejected |
| TryEmbed | Embed | Requires a direct media URL; the iframe is rejected |
| CinexStream | Embed | Requires a direct media URL; the iframe is rejected |
| NontonGo | Embed | Requires a direct media URL; the iframe is rejected |

This is a **source-saving hand-off**, not an iframe scraper or automatic provider resolver. Provider labels are metadata only: for example, `--source-provider anixo` does not make an AniXo iframe downloadable, and it does not scrape the iframe's internal requests. If the provider only supplies an embedded player page, select another source that explicitly exposes a direct, permitted media URL.

### CLI

```bash
python -m animexe episode download-source \
  "https://media.example/episode.m3u8" \
  --source-provider animeparadise \
  --referer "https://animeparadise.moe/" \
  --output workspace/input/source-episode.mkv \
  --authorized-use
```

For a direct MP4/MKV/WebM URL, the same command streams the file to disk. HLS uses FFmpeg to remux the stream locally. Requests have a timeout and configurable maximum file size; temporary files are replaced atomically after success.

AniMeXe rejects:
- iframe/catalog/player pages that are not direct media;
- DASH manifests;
- HLS playlists declaring encryption or with ambiguous key signaling;
- non-HTTP(S) URLs and literal localhost/private IP addresses.

The source's audio is retained in the downloaded file so analysis can still inspect the original media tracks. The existing visual-cut/final-render stages are responsible for producing an explanation video without the episode's original audio; Sub/Dub selection is not required by this saving step.

Only download and process media you have permission to use. The downloader does not bypass DRM, extract hidden player URLs, or defeat provider access controls. A direct URL can still expire or fail, and an HLS URL passing playlist checks is not proof that every segment will be available.


## Experimental direct-media acquisition: AnimeParadise

AnimeParadise is the first native-media adapter in AniMeXe. It is opt-in and independent of Kuhi; it uses the site's JSON catalogue flow rather than treating an embed/player URL as media:

1. Search the public JSON catalogue using AniList title variants.
2. Require a confident, unambiguous series match.
3. Select the requested integer episode from that series catalogue.
4. Resolve the selected episode UID through the documented episode endpoint and convert its `streamLink` to the AnimeParadise HLS URL.
5. Pass that URL and its minimal Referer header to the shared media saver, which rejects encrypted/ambiguous HLS and applies acquisition time and size limits.

The adapter currently exposes **subbed episodes only**. AniMeXe's explanation renderer continues to mute original episode audio. This does not imply that a requested provider episode is available: only a successful, permitted acquisition followed by media inspection establishes that.

Example:

```bash
animexe episode acquire-animeparadise \
  --anilist-id 21 \
  --episode-number 1 \
  --authorized-use \
  --output workspace/input/episode-1.mkv
```

Add `--run-pipeline` to pass the acquired local file to the existing explanation pipeline. The command requires `--authorized-use` and does not print the expiring stream URL in its JSON result. Provider configuration is optional for direct acquisition; set `provider.name: animeparadise` if it should also appear in the configured provider registry/status report.

**Verification status:** resolver behaviour is covered by mocked API contract tests. A successful test run does not prove present-day provider uptime or prove a real episode plays end-to-end; keep the adapter manual/opt-in until a permitted sample is checked with `ffprobe` and a decoded frame.
