from __future__ import annotations

from typing import Protocol


class SpeechToTextProvider(Protocol):
    def transcribe(self, audio_path: str) -> str:
        ...


class DiarizationProvider(Protocol):
    def diarize(self, audio_path: str) -> list[dict[str, str]]:
        ...


class LocalLLMProvider(Protocol):
    def analyze(self, prompt: str) -> str:
        ...


class ExternalLLMProvider(Protocol):
    name: str

    def analyze(self, prompt: str, *, purpose: str) -> str:
        ...


class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> list[float]:
        ...
