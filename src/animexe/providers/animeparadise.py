"""AnimeParadise's documented JSON-catalogue to HLS adapter.

This provider resolves only a caller-selected episode. It does not inspect
iframes, scrape player pages, or attempt to bypass access controls.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import quote, urlencode

import requests

from ..metadata.models import AnimeMetadata
from ..models import EpisodeAvailability, EpisodeRef, MediaSource, utc_now
from .base import Provider, ProviderHealth


class AnimeParadiseError(RuntimeError):
    """Raised when AnimeParadise cannot safely resolve a requested episode."""


class AnimeParadiseProvider(Provider):
    """Resolve AniList metadata to AnimeParadise's direct HLS endpoint."""

    name = "animeparadise"
    API_BASE = "https://api.animeparadise.moe"
    STREAM_BASE = "https://stream.animeparadise.moe"
    WEB_BASE = "https://animeparadise.moe"
    USER_AGENT = "AniMeXe/0.1 (permitted media acquisition)"

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        api_base_url: str | None = None,
        timeout_seconds: int = 18,
        min_match_score: float = 0.86,
        match_margin: float = 0.08,
    ) -> None:
        if timeout_seconds < 1:
            raise ValueError("timeout_seconds must be positive")
        if not 0 < min_match_score <= 1:
            raise ValueError("min_match_score must be in (0, 1]")
        if not 0 <= match_margin <= 1:
            raise ValueError("match_margin must be in [0, 1]")
        self.session = session or requests.Session()
        self.api_base_url = (api_base_url or self.API_BASE).rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.min_match_score = min_match_score
        self.match_margin = match_margin
        self._known_titles: dict[str, str] = {}

    @staticmethod
    def _normalize_title(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value).casefold()
        decomposed = unicodedata.normalize("NFKD", normalized)
        return "".join(char for char in decomposed if char.isalnum())

    @classmethod
    def _title_values(cls, item: dict[str, Any]) -> tuple[str, ...]:
        values: list[str] = []
        for key in ("title", "name", "english", "romaji", "native"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                values.append(value.strip())
            elif isinstance(value, dict):
                for nested in value.values():
                    if isinstance(nested, str) and nested.strip():
                        values.append(nested.strip())
        alternatives = item.get("alternativeTitle")
        if isinstance(alternatives, dict):
            for value in alternatives.values():
                if isinstance(value, str) and value.strip():
                    values.append(value.strip())
        elif isinstance(alternatives, list):
            values.extend(value.strip() for value in alternatives if isinstance(value, str) and value.strip())
        return tuple(dict.fromkeys(values))

    @staticmethod
    def _provider_id(item: dict[str, Any]) -> str | None:
        value = item.get("_id", item.get("id", item.get("mediaId")))
        if value is None or not str(value).strip():
            return None
        return str(value).strip()

    def _request_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.api_base_url}/{path.lstrip('/')}"
        headers = {
            "Accept": "application/json",
            "User-Agent": self.USER_AGENT,
            "Origin": self.WEB_BASE,
            "Referer": self.WEB_BASE + "/",
        }
        try:
            response = self.session.get(
                url,
                params=params,
                headers=headers,
                timeout=self.timeout_seconds,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise AnimeParadiseError(
                f"AnimeParadise API request failed ({type(exc).__name__})."
            ) from exc
        try:
            if 300 <= response.status_code < 400:
                raise AnimeParadiseError("AnimeParadise API returned an unexpected redirect.")
            if response.status_code >= 400:
                raise AnimeParadiseError(
                    f"AnimeParadise API returned HTTP {response.status_code}."
                )
            try:
                payload = response.json()
            except (ValueError, requests.RequestException) as exc:
                raise AnimeParadiseError("AnimeParadise returned invalid JSON.") from exc
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        if not isinstance(payload, dict):
            raise AnimeParadiseError("AnimeParadise returned a non-object JSON response.")
        return payload

    @staticmethod
    def _data_list(payload: dict[str, Any], stage: str) -> list[dict[str, Any]]:
        data = payload.get("data")
        if not isinstance(data, list):
            raise AnimeParadiseError(f"AnimeParadise returned an invalid {stage} catalogue.")
        return [item for item in data if isinstance(item, dict)]

    def search(self, query: str) -> list[AnimeMetadata]:
        query = query.strip()
        if not query:
            return []
        payload = self._request_json("/search", {"q": query, "limit": 20})
        results: list[AnimeMetadata] = []
        for item in self._data_list(payload, "search"):
            provider_id = self._provider_id(item)
            titles = self._title_values(item)
            if not provider_id or not titles:
                continue
            title = titles[0]
            self._known_titles[provider_id] = title
            results.append(
                AnimeMetadata(
                    id=provider_id,
                    title=title,
                    titles=titles,
                    episodes=item.get("episodes") if isinstance(item.get("episodes"), int) else None,
                    season_year=item.get("year") if isinstance(item.get("year"), int) else None,
                    source_provider=self.name,
                    raw=item,
                )
            )
        return results

    def get_anime(self, anime_id: str) -> AnimeMetadata:
        provider_id = str(anime_id).strip()
        if not provider_id:
            raise ValueError("anime_id cannot be empty")
        episodes = self._catalogue(provider_id)
        return AnimeMetadata(
            id=provider_id,
            title=self._known_titles.get(provider_id, provider_id),
            titles=(self._known_titles[provider_id],) if provider_id in self._known_titles else (),
            episodes=len(episodes),
            source_provider=self.name,
        )

    def _catalogue(self, media_id: str) -> list[dict[str, Any]]:
        payload = self._request_json(f"/anime/{quote(media_id, safe='')}/episode")
        catalogue: list[dict[str, Any]] = []
        for item in self._data_list(payload, "episode"):
            uid = item.get("uid")
            try:
                number = float(item.get("number"))
            except (TypeError, ValueError):
                continue
            if not isinstance(uid, (str, int)) or not str(uid).strip():
                continue
            # Specials/decimal episode numbers need an explicit mapping; do not
            # silently treat them as an ordinary numbered episode.
            if number < 1 or not number.is_integer():
                continue
            catalogue.append({
                "number": int(number),
                "title": str(item.get("title") or f"Episode {int(number)}"),
                "uid": str(uid).strip(),
            })
        catalogue.sort(key=lambda item: item["number"])
        return catalogue

    def get_episodes(self, anime_id: str, season: int = 1) -> list[EpisodeRef]:
        if season < 1:
            raise ValueError("season must be >= 1")
        return [
            EpisodeRef(
                anime_id=str(anime_id),
                season=season,
                episode=item["number"],
                language="sub",
                external_id=f"{anime_id}|{item['uid']}",
            )
            for item in self._catalogue(str(anime_id))
        ]

    def _match_series(self, metadata: AnimeMetadata) -> tuple[str, str]:
        title_queries = tuple(dict.fromkeys(
            value.strip()
            for value in (metadata.title, *metadata.titles)
            if isinstance(value, str) and value.strip()
        ))[:5]
        if not title_queries:
            raise AnimeParadiseError("AniList metadata did not contain a usable title.")

        candidates: dict[str, dict[str, Any]] = {}
        for query in title_queries:
            for result in self.search(query):
                titles = result.titles or (result.title,)
                score = max(
                    (
                        SequenceMatcher(
                            None,
                            self._normalize_title(query_title),
                            self._normalize_title(candidate_title),
                        ).ratio()
                        for query_title in title_queries
                        for candidate_title in titles
                    ),
                    default=0.0,
                )
                item = candidates.get(result.id)
                if item is None or score > item["score"]:
                    candidates[result.id] = {
                        "id": result.id,
                        "title": result.title,
                        "score": score,
                        "metadata": result,
                    }

        ranked = sorted(candidates.values(), key=lambda item: item["score"], reverse=True)
        if not ranked or ranked[0]["score"] < self.min_match_score:
            raise AnimeParadiseError(
                f"No confident AnimeParadise title match for AniList {metadata.anilist_id or metadata.id}."
            )
        if len(ranked) > 1 and ranked[0]["score"] - ranked[1]["score"] < self.match_margin:
            raise AnimeParadiseError(
                "AnimeParadise title match is ambiguous; refusing to guess the series."
            )
        selected = ranked[0]
        return str(selected["id"]), str(selected["title"])

    def resolve_anilist_episode(self, metadata: AnimeMetadata, episode_number: int) -> MediaSource:
        if episode_number < 1:
            raise ValueError("episode_number must be >= 1")
        if metadata.episodes is not None and episode_number > metadata.episodes:
            raise AnimeParadiseError(
                f"AniList lists only {metadata.episodes} episodes; episode {episode_number} is out of range."
            )

        media_id, _title = self._match_series(metadata)
        episode = next(
            (item for item in self._catalogue(media_id) if item["number"] == episode_number),
            None,
        )
        if episode is None:
            raise AnimeParadiseError(
                f"AnimeParadise does not list episode {episode_number} for the matched series."
            )
        return self._resolve_uid(media_id, episode["uid"])

    def _resolve_uid(self, media_id: str, uid: str) -> MediaSource:
        payload = self._request_json(
            f"/ep/{quote(uid, safe='')}",
            {"origin": media_id},
        )
        data = payload.get("data")
        data = data if isinstance(data, dict) else {}
        episode_data = data.get("episode")
        episode_data = episode_data if isinstance(episode_data, dict) else {}
        stream_link = episode_data.get("streamLink")
        if not isinstance(stream_link, str) or not stream_link.strip():
            raise AnimeParadiseError("AnimeParadise did not return a streamLink for this episode.")

        stream_url = (
            f"{self.STREAM_BASE}/m3u8?"
            f"{urlencode({'url': stream_link.strip()})}"
        )
        subtitles: list[dict[str, Any]] = []
        raw_subtitles = episode_data.get("subData")
        if isinstance(raw_subtitles, list):
            for item in raw_subtitles:
                if not isinstance(item, dict):
                    continue
                url = item.get("url") or item.get("src") or item.get("file")
                if not isinstance(url, str) or not url.startswith(("https://", "http://")):
                    continue
                label = item.get("label") or item.get("name") or item.get("language") or "Subtitle"
                subtitles.append({"url": url, "label": str(label), "lang": str(label)})

        source = MediaSource(
            provider=self.name,
            protocol="hls",
            reference=stream_url,
            language="sub",
            subtitles=tuple(subtitles),
            headers=(("Referer", self.WEB_BASE + "/"),),
            capabilities=("un-encrypted-hls-candidate",),
        )
        source.validate()
        return source

    def resolve_episode(
        self,
        anime_id: str,
        episode_number: int,
        season: int = 1,
        language: str = "sub",
    ) -> EpisodeAvailability:
        if episode_number < 1 or season < 1:
            raise ValueError("season and episode number must be >= 1")
        if language.lower() != "sub":
            return EpisodeAvailability(
                metadata_exists=True,
                catalog_exists=False,
                provider_status="UNAVAILABLE",
                checked_at=utc_now(),
                error="AnimeParadise currently exposes subbed episodes only.",
            )
        try:
            episode = next(
                (item for item in self.get_episodes(anime_id, season) if item.episode == episode_number),
                None,
            )
            if episode is None:
                return EpisodeAvailability(
                    metadata_exists=True,
                    catalog_exists=False,
                    provider_status="UNAVAILABLE",
                    checked_at=utc_now(),
                    error=f"Episode {episode_number} is not in the AnimeParadise catalogue.",
                )
            self.get_source(episode)
        except (AnimeParadiseError, requests.RequestException, ValueError) as exc:
            return EpisodeAvailability(
                metadata_exists=True,
                catalog_exists=episode is not None if "episode" in locals() else False,
                source_resolved=False,
                media_usable=False,
                processable=False,
                provider_status="ERROR",
                checked_at=utc_now(),
                error=str(exc),
            )
        return EpisodeAvailability(
            metadata_exists=True,
            catalog_exists=True,
            source_resolved=True,
            media_usable=True,
            processable=True,
            provider_status="AVAILABLE",
            checked_at=utc_now(),
        )

    def get_source(self, episode: EpisodeRef) -> MediaSource:
        if not episode.external_id or "|" not in episode.external_id:
            raise ValueError("EpisodeRef.external_id must contain the provider series ID and episode UID.")
        media_id, uid = episode.external_id.split("|", 1)
        if not media_id or not uid:
            raise ValueError("EpisodeRef.external_id is malformed.")
        return self._resolve_uid(media_id, uid)

    def check_health(self) -> ProviderHealth:
        try:
            self._request_json("/search", {"q": "anime", "limit": 1})
        except AnimeParadiseError as exc:
            return ProviderHealth(
                status="UNAVAILABLE",
                provider=self.name,
                checked_at=utc_now(),
                detail=str(exc),
            )
        return ProviderHealth(
            status="AVAILABLE",
            provider=self.name,
            checked_at=utc_now(),
            detail="AnimeParadise JSON search API responded; media availability is episode-specific.",
        )


__all__ = ["AnimeParadiseError", "AnimeParadiseProvider"]
