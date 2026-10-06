from types import SimpleNamespace

import pytest

from animexe.analysis.scenes import SceneAnalysisManifest, SceneRecord
from animexe.analysis.story import EpisodeStoryManifest, StoryEvent, StoryEvidence
from animexe.analysis.transcript import TranscriptAnalysisManifest, TranscriptSegment
from animexe.narration.script import GeminiNarrationScriptGenerator, NarrationScriptError


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


def _story() -> EpisodeStoryManifest:
    return EpisodeStoryManifest(
        schema_version=2,
        episode_id="demo-s1-e1",
        input_path="/tmp/episode.mkv",
        input_sha256="a" * 64,
        source_transcript="transcript.json",
        source_scenes="scenes.json",
        method="gemini",
        evidence=StoryEvidence(
            characters=("Gon",),
            locations=("Forest",),
            keywords=("journey",),
        ),
        events=(
            StoryEvent("event_0001", ("scene_0001",), 0.0, 20.0, "Gon arrives.", 0.8, "arrival"),
            StoryEvent("event_0002", ("scene_0002",), 20.0, 60.0, "The group decides to move.", 0.9, "decision"),
            StoryEvent("event_0003", ("scene_0003",), 60.0, 100.0, "They begin the journey.", 0.85, "transition"),
        ),
        ending_event_id="event_0003",
        summary="Gon arrives, the group makes a decision, and the journey begins.",
        relationships=("Gon travels with the group.",),
        ending="The group begins moving into the forest.",
        narration_points=("Gon arrives.", "The group decides to move.", "The journey starts."),
        confidence=0.92,
        model="gemini-test",
    )


def _transcript() -> TranscriptAnalysisManifest:
    return TranscriptAnalysisManifest(
        schema_version=1,
        episode_id="demo-s1-e1",
        input_path="/tmp/episode.mkv",
        input_sha256="a" * 64,
        source="embedded_subtitle",
        language="eng",
        subtitle_stream_index=2,
        transcript_status="READY",
        segments=(
            TranscriptSegment(
                "segment_0001",
                1.0,
                2.5,
                "Hey, we need to move now before the storm reaches us.",
                ("scene_0001",),
            ),
        ),
    )


def _payload() -> dict:
    body_words = [f"word{i}" for i in range(255)]
    chunks = [body_words[:94], body_words[94:187], body_words[187:]]
    texts = [
        "The episode begins by showing why Gon matters to this journey. " + " ".join(chunks[0]),
        "That decision changes the direction of the group and gives the story a new goal. " + " ".join(chunks[1]),
        "From there the characters move forward together while the tension around the journey keeps building. "
        + " ".join(chunks[2]),
    ]
    hook = "Everything changes when Gon arrives."
    ending = "And that decision sets up the next part of their journey."
    full = " ".join([hook, *texts, ending])
    word_count = GeminiNarrationScriptGenerator._word_count(full)
    duration = word_count / 145.0 * 60.0
    return {
        "hook": hook,
        "hook_scene_ids": ["scene_0001"],
        "segments": [
            {
                "segment_id": "segment_0001",
                "text": texts[0],
                "scene_ids": ["scene_0001"],
                "story_event_ids": ["event_0001"],
                "purpose": "setup",
                "start_seconds": 0.0,
                "end_seconds": 35.0,
            },
            {
                "segment_id": "segment_0002",
                "text": texts[1],
                "scene_ids": ["scene_0002"],
                "story_event_ids": ["event_0002"],
                "purpose": "turning_point",
                "start_seconds": 35.0,
                "end_seconds": 80.0,
            },
            {
                "segment_id": "segment_0003",
                "text": texts[2],
                "scene_ids": ["scene_0003"],
                "story_event_ids": ["event_0003"],
                "purpose": "resolution",
                "start_seconds": 80.0,
                "end_seconds": 120.0,
            },
        ],
        "ending": ending,
        "ending_scene_ids": ["scene_0003"],
        "word_count": word_count,
        "estimated_duration_seconds": duration,
    }


def test_generates_hinglish_script() -> None:
    client = _FakeClient(_payload())
    generator = GeminiNarrationScriptGenerator(client=client)

    manifest = generator.generate(
        _story(),
        transcript=_transcript(),
        language="hinglish",
        script="roman",
    )

    assert manifest.language == "hinglish"
    assert manifest.script == "roman"
    assert manifest.checkpoint == "script"
    assert manifest.model == "gemini-3.8-flash"
    assert client.models.calls[0]["model"] == "gemini-3.8-flash"
    assert client.models.calls[0]["config"].response_mime_type == "application/json"


def test_generates_english_script_from_same_story() -> None:
    client = _FakeClient(_payload())
    manifest = GeminiNarrationScriptGenerator(client=client).generate(
        _story(),
        transcript=_transcript(),
        language="english",
        script="latin",
    )

    assert manifest.language == "english"
    assert manifest.script == "latin"


def test_rejects_unknown_scene() -> None:
    payload = _payload()
    payload["segments"][1]["scene_ids"] = ["scene_9999"]

    with pytest.raises(NarrationScriptError, match="unknown scene"):
        GeminiNarrationScriptGenerator(client=_FakeClient(payload)).generate(
            _story(), transcript=_transcript(), language="hinglish", script="roman"
        )


def test_rejects_exact_subtitle_copy() -> None:
    payload = _payload()
    payload["segments"][0]["text"] = (
        "Hey, we need to move now before the storm reaches us. "
        + " ".join(f"safe{i}" for i in range(90))
    )
    full = " ".join(
        [
            payload["hook"],
            *(segment["text"] for segment in payload["segments"]),
            payload["ending"],
        ]
    )
    payload["word_count"] = GeminiNarrationScriptGenerator._word_count(full)
    payload["estimated_duration_seconds"] = payload["word_count"] / 145.0 * 60.0

    with pytest.raises(NarrationScriptError, match="exact 9-word subtitle overlap"):
        GeminiNarrationScriptGenerator(client=_FakeClient(payload)).generate(
            _story(), transcript=_transcript(), language="hinglish", script="roman"
        )


def test_requires_matching_language_script_pair() -> None:
    with pytest.raises(NarrationScriptError, match="English narration"):
        GeminiNarrationScriptGenerator(client=_FakeClient(_payload())).generate(
            _story(), transcript=_transcript(), language="english", script="roman"
        )
