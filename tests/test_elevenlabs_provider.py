from __future__ import annotations

import json
from typing import Any
import urllib.error

import pytest

from sentinel.providers.elevenlabs_provider import ElevenLabsSpeechToTextProvider


class FakeResponse:
    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(
            {
                "language_code": "es",
                "language_probability": 0.99,
                "text": "Hola mundo",
                "words": [{"text": "Hola", "speaker_id": "speaker_1", "start": 0, "end": 0.2}],
            }
        ).encode("utf-8")


def test_elevenlabs_provider_posts_audio_as_multipart(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: int) -> FakeResponse:
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = request.data
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = ElevenLabsSpeechToTextProvider(api_key="test-key", timeout_seconds=12)

    result = provider.transcribe_bytes(
        b"audio-bytes",
        filename="meeting.webm",
        content_type="audio/webm",
        language_code="es",
        diarize=True,
        num_speakers=2,
    )

    body = captured["body"]
    assert captured["url"].startswith("https://api.elevenlabs.io/v1/speech-to-text?enable_logging=true")
    assert captured["headers"]["Xi-api-key"] == "test-key"
    assert "multipart/form-data" in captured["headers"]["Content-type"]
    assert b'name="model_id"\r\n\r\nscribe_v2' in body
    assert b'name="diarize"\r\n\r\ntrue' in body
    assert b'name="num_speakers"\r\n\r\n2' in body
    assert b'name="file"; filename="meeting.webm"' in body
    assert b"audio-bytes" in body
    assert captured["timeout"] == 12
    assert result.text == "Hola mundo"
    assert result.language_code == "es"
    assert result.language_probability == 0.99


def test_elevenlabs_provider_requires_api_key() -> None:
    provider = ElevenLabsSpeechToTextProvider(api_key=None)

    with pytest.raises(RuntimeError, match="ELEVENLABS_API_KEY"):
        provider.transcribe_bytes(b"audio")


def test_elevenlabs_provider_explains_zero_retention_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(_request: Any, timeout: int) -> FakeResponse:
        assert timeout == 90
        raise urllib.error.HTTPError(
            url="https://api.elevenlabs.io/v1/speech-to-text",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=ErrorBody(),
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = ElevenLabsSpeechToTextProvider(api_key="test-key", enable_logging=False)

    with pytest.raises(RuntimeError, match="ELEVENLABS_ENABLE_LOGGING=true"):
        provider.transcribe_bytes(b"audio")


class ErrorBody:
    def read(self) -> bytes:
        return json.dumps(
            {
                "detail": {
                    "type": "authorization_error",
                    "code": "forbidden",
                    "message": "Only users from the enterprise or trial tier can use ZRM mode.",
                    "status": "not_allowed",
                }
            }
        ).encode("utf-8")

    def close(self) -> None:
        return None
