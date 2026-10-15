# 7xAnime-compatible media ingestion

AniMeXe's current 7xAnime provider research separates **embed pages** from **direct media**. Most 7xAnime integrations currently construct iframe URLs (MegaPlay, AniXo, Megavid, MegaFlix, TryEmbed, CinexStream, NontonGo); those URLs are not media files and are not treated as downloadable sources. AnimeParadise has been identified as an HLS candidate, but it still requires real source and playback verification.

The new media downloader accepts only a direct HTTP(S) media URL that the caller is authorized to process:

- direct MP4/M4V/MKV/MOV responses are streamed to a temporary output file;
- unencrypted HLS manifests can be remuxed with FFmpeg when FFmpeg is installed;
- encrypted HLS, HLS session keys, HTML/player pages, empty responses, non-routable IP URLs, and over-limit downloads are rejected;
- source language is not required by the downloader. AniMeXe's render stage already mutes source audio for the explanation output;
- download output belongs in the temporary workspace and must be removed after the job succeeds or fails. Do not commit episode media to Git.

This is an ingestion boundary, not a provider extractor. It does not automate browser playback, scrape iframe internals, bypass anti-bot/access controls, or handle DRM. If a provider returns only an embed page, it must be marked `EMBED_ONLY` and skipped; a provider needs to expose an authorized direct MP4 or clear HLS source before AniMeXe can ingest it.

## Usage

```bash
python -m animexe.media_download 'https://media.example/episode.mp4' \
  --output workspace/incoming/example-s1e1.mp4 \
  --provider direct
```

For a clear HLS manifest:

```bash
python -m animexe.media_download 'https://media.example/episode/index.m3u8' \
  --output workspace/incoming/example-s1e1.mp4 \
  --provider animeparadise
```

The HLS command is a capability path only; it does not imply that any particular provider URL is currently working. The resulting file can then enter the existing checkpointed pipeline:

```bash
python -m animexe episode run workspace/incoming/example-s1e1.mp4 \
  --anime-id anilist:21 --episode-number 1 --season 1
```

The direct URL should be obtained from a provider's documented/authorized media interface. Do not paste a provider's iframe URL and expect it to download.
