from pathlib import Path
from types import SimpleNamespace

import pytest

from animexe.analysis.gemini_story import GeminiStoryAnalyzer, GeminiStoryError
from animexe.analysis.scenes import SceneAnalysisManifest, SceneRecord
from animexe.analysis.transcript import TranscriptAnalysisManifest, TranscriptSegment


class _FakeModels:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        import json
        return SimpleNamespace(text=json.dumps(self.payload))


class _FakeClient:
    def __init__(self, payload: dict) -> None:
        self.models = _FakeModels(payload)


def _inputs() -> tuple[TranscriptAnalysisManifest, SceneAnalysisManifest]:
    scenes = SceneAnalysisManifest(
        schema_version=1,
        episode_id="demo-s1-e1",
        input_path="/tmp/episode.mkv",
        input_sha256="a" * 64,
        detection_method="test",
        threshold=27.0,
        min_scene_duration_seconds=0.5,
        detected_scenes=2,
        frames_extracted=0,
        scenes=(
            SceneRecord("scene_0001", 1, 0.0, 4.0, 4.0, 2.0),
            SceneRecord("scene_0002", 2, 4.0, 10.0, 6.0, 7.0),
        ),
    )
    transcript = TranscriptAnalysisManifest(
        schema_version=1,
        episode_id="demo-s1-e1",
        input_path="/tmp/episode.mkv",
        input_sha256="a" * 64,
        source="embedded_subtitle",
        language="eng",
        subtitle_stream_index=2,
        transcript_status="READY",
        segments=(
            TranscriptSegment("segment_0001", 1.0, 2.5, "Gon is here!", ("scene_0001",)),
            TranscriptSegment("segment_0002", 3.5, 5.5, "We need to move now.", ("scene_0001", "scene_0002")),
        ),
    )
    return transcript, scenes


def _payload() -> dict:
    return {
        "episode_summary": "Gon arrives and the group decides to move.",
        "characters": ["Gon"],
        "locations": ["Forest"],
        "keywords": ["Gon", "move"],
        "relationships": ["Gon is traveling with the group."],
        "events": [
            {
                "event_id": "event_0001",
                "scene_ids": ["scene_0001"],
                "start_seconds": 1.0,
                "end_seconds": 2.5,
                "description": "Gon arrives.",
                "importance": 0.8,
                "kind": "arrival",
            },
            {
                "event_id": "event_0002",
                "scene_ids": ["scene_0001", "scene_0002"],
                "start_seconds": 3.5,
                "end_seconds": 5.5,
                "description": "The group decides to move.",
                "importance": 0.9,
                "kind": "decision",
            },
        ],
        "ending": "The group begins moving.",
        "continuity_notes": ["Continue with the group's journey."],
        "narration_points": ["Gon arrives.", "The group decides to move."],
        "confidence": 0.93,
    }


def test_gemini_story_analyzer_builds_valid_manifest() -> None:
    client = _FakeClient(_payload())
    manifest = GeminiStoryAnalyzer(client=client).analyze(*_inputs())

    assert manifest.method == "gemini"
    assert manifest.schema_version == 2
    assert manifest.summary.startswith("Gon arrives")
    assert manifest.evidence.characters == ("Gon",)
    assert manifest.relationships
    assert manifest.ending_event_id == "event_0002"
    assert manifest.confidence == 0.93
    assert manifest.model == "gemini-3.8-flash"

    call = client.models.calls[0]
    assert call["model"] == "gemini-3.8-flash"
    assert call["config"].response_mime_type == "application/json"


def test_gemini_story_rejects_unknown_scene() -> None:
    payload = _payload()
    payload["events"][0]["scene_ids"] = ["scene_9999"]

    with pytest.raises(GeminiStoryError, match="unknown scene_id"):
        GeminiStoryAnalyzer(client=_FakeClient(payload)).analyze(*_inputs())


def test_gemini_story_requires_api_key_without_injected_client(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    analyzer = GeminiStoryAnalyzer()
    with pytest.raises(GeminiStoryError, match="GEMINI_API_KEY"):
        analyzer.analyze(*_inputs())


def test_gemini_story_uses_existing_frame_when_present(tmp_path: Path) -> None:
    frame = tmp_path / "frames" / "scene_0001.jpg"
    frame.parent.mkdir(parents=True)
    frame.write_bytes(b"jpeg")

    scenes = _inputs()[1]
    scenes = SceneAnalysisManifest(
        schema_version=scenes.schema_version,
        episode_id=scenes.episode_id,
        input_path=scenes.input_path,
        input_sha256=scenes.input_sha256,
        detection_method=scenes.detection_method,
        threshold=scenes.threshold,
        min_scene_duration_seconds=scenes.min_scene_duration_seconds,
        detected_scenes=scenes.detected_scenes,
        frames_extracted=1,
        scenes=(
            SceneRecord(
                "scene_0001",
                1,
                0.0,
                4.0,
                4.0,
                2.0,
                "frames/scene_0001.jpg",
            ),
            scenes.scenes[1],
        ),
    )

    client = _FakeClient(_payload())
    GeminiStoryAnalyzer(client=client).analyze(
        _inputs()[0],
        scenes,
        scene_manifest_dir=tmp_path,
    )
    assert len(client.models.calls[0]["contents"]) == 3
