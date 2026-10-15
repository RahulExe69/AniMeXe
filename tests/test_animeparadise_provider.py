from __future__ import annotations

from urllib.parse import urlsplit

import pytest

from animexe.metadata.models import AnimeMetadata
from animexe.providers.animeparadise import AnimeParadiseError, AnimeParadiseProvider


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.closed = False

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        parsed = urlsplit(url)
        route = (parsed.path, kwargs.get("params") or {})
        for (path, expected_params), response in self.routes.items():
            if path == parsed.path and all(route[1].get(k) == v for k, v in expected_params.items()):
                return response
        raise AssertionError(f"Unexpected API request: {parsed.path} params={route[1]}")


def _metadata(episodes=2):
    return AnimeMetadata(
        id="anilist:123",
        title="Exact Anime",
        titles=("Exact Anime", "Exact Anime Native"),
        anilist_id=123,
        episodes=episodes,
        source_provider="anilist",
    )


def _search_result(*items):
    return FakeResponse({"data": list(items)})


def _catalogue(*items):
    return FakeResponse({"data": list(items)})


def _episode_response(stream_link="opaque-token"):
    episode = {}
    if stream_link is not None:
        episode["streamLink"] = stream_link
    episode["subData"] = [{"url": "https://subtitles.example/episode.vtt", "label": "English"}]
    return FakeResponse({"data": {"episode": episode}})


def test_resolves_selected_episode_to_normalized_hls_source():
    session = FakeSession({
        ("/search", {"q": "Exact Anime", "limit": 20}): _search_result({
            "_id": "series-1",
            "title": "Exact Anime",
            "alternativeTitle": {"english": "Exact Anime", "native": "Exact Anime Native"},
        }),
        ("/search", {"q": "Exact Anime Native", "limit": 20}): _search_result({
            "_id": "series-1",
            "title": "Exact Anime",
            "alternativeTitle": {"english": "Exact Anime", "native": "Exact Anime Native"},
        }),
        ("/anime/series-1/episode", {}): _catalogue(
            {"uid": "episode-1", "number": 1},
            {"uid": "episode-2", "number": 2},
        ),
        ("/ep/episode-2", {"origin": "series-1"}): _episode_response(),
    })
    provider = AnimeParadiseProvider(session=session)

    source = provider.resolve_anilist_episode(_metadata(), 2)

    assert source.provider == "animeparadise"
    assert source.protocol == "hls"
    assert source.reference == "https://stream.animeparadise.moe/m3u8?url=opaque-token"
    assert dict(source.headers)["Referer"] == "https://animeparadise.moe/"
    assert source.subtitles[0]["lang"] == "English"
    assert [urlsplit(call[0]).path for call in session.calls].count("/ep/episode-2") == 1
    assert not any(urlsplit(call[0]).path == "/ep/episode-1" for call in session.calls)


def test_refuses_ambiguous_title_matches_before_catalogue_lookup():
    duplicate_response = _search_result(
        {"_id": "series-1", "title": "Exact Anime"},
        {"_id": "series-2", "title": "Exact Anime"},
    )
    session = FakeSession({
        ("/search", {"q": "Exact Anime", "limit": 20}): duplicate_response,
        ("/search", {"q": "Exact Anime Native", "limit": 20}): duplicate_response,
    })
    provider = AnimeParadiseProvider(session=session)

    with pytest.raises(AnimeParadiseError, match="ambiguous"):
        provider.resolve_anilist_episode(_metadata(), 1)

    assert not any("/anime/" in urlsplit(call[0]).path for call in session.calls)


def test_missing_episode_stops_before_stream_endpoint():
    session = FakeSession({
        ("/search", {"q": "Exact Anime", "limit": 20}): _search_result({
            "_id": "series-1", "title": "Exact Anime"
        }),
        ("/search", {"q": "Exact Anime Native", "limit": 20}): _search_result({
            "_id": "series-1", "title": "Exact Anime"
        }),
        ("/anime/series-1/episode", {}): _catalogue({"uid": "episode-1", "number": 1}),
    })
    provider = AnimeParadiseProvider(session=session)

    with pytest.raises(AnimeParadiseError, match="does not list episode 2"):
        provider.resolve_anilist_episode(_metadata(), 2)

    assert not any(urlsplit(call[0]).path.startswith("/ep/") for call in session.calls)


def test_missing_stream_link_is_a_resolution_error():
    session = FakeSession({
        ("/search", {"q": "Exact Anime", "limit": 20}): _search_result({
            "_id": "series-1", "title": "Exact Anime"
        }),
        ("/search", {"q": "Exact Anime Native", "limit": 20}): _search_result({
            "_id": "series-1", "title": "Exact Anime"
        }),
        ("/anime/series-1/episode", {}): _catalogue({"uid": "episode-1", "number": 1}),
        ("/ep/episode-1", {"origin": "series-1"}): _episode_response(stream_link=None),
    })
    provider = AnimeParadiseProvider(session=session)

    with pytest.raises(AnimeParadiseError, match="did not return a streamLink"):
        provider.resolve_anilist_episode(_metadata(), 1)


def test_dub_is_reported_unavailable_not_silently_substituted():
    provider = AnimeParadiseProvider(session=FakeSession({}))

    result = provider.resolve_episode("series-1", 1, language="dub")

    assert result.provider_status == "UNAVAILABLE"
    assert result.source_resolved is False
    assert "subbed" in (result.error or "")
