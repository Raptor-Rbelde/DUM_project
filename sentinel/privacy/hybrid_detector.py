from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from sentinel.domain.privacy import SensitiveEntity
from sentinel.privacy.detectors import RegexSensitiveDataDetector, resolve_overlaps
from sentinel.privacy.local_ml import MODEL_VERSION as SPAN_MODEL_VERSION
from sentinel.privacy.local_ml import LocalMLSensitiveDataDetector
from sentinel.privacy.sequence_tagger import (
    DEFAULT_SEQUENCE_MODEL_PATH,
    SEQUENCE_MODEL_VERSION,
    LocalSequenceTaggerSensitiveDataDetector,
)


class LocalDetector(Protocol):
    @property
    def available(self) -> bool:
        ...

    def detect(self, text: str) -> list[SensitiveEntity]:
        ...


class HybridSensitiveDataDetector:
    def __init__(
        self,
        *,
        regex_detector: RegexSensitiveDataDetector | None = None,
        ml_detector: LocalDetector | None = None,
    ) -> None:
        self.regex_detector = regex_detector or RegexSensitiveDataDetector()
        self.ml_detector = ml_detector

    def detect(self, text: str) -> list[SensitiveEntity]:
        candidates = self.regex_detector.detect(text)
        if self.ml_detector is not None and self.ml_detector.available:
            candidates.extend(self.ml_detector.detect(text))
        return resolve_overlaps(candidates)


def build_privacy_detector(
    *,
    local_ml_enabled: bool = True,
    local_ml_model_path: str | Path = DEFAULT_SEQUENCE_MODEL_PATH,
) -> HybridSensitiveDataDetector:
    ml_detector = None
    if local_ml_enabled:
        ml_detector = load_local_ml_detector(local_ml_model_path)
    return HybridSensitiveDataDetector(ml_detector=ml_detector)


def load_local_ml_detector(model_path: str | Path) -> LocalDetector | None:
    path = Path(model_path)
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    model_version = payload.get("model_version")
    if model_version == SEQUENCE_MODEL_VERSION:
        return LocalSequenceTaggerSensitiveDataDetector(path)
    if model_version == SPAN_MODEL_VERSION:
        return LocalMLSensitiveDataDetector(path)
    raise ValueError(f"Unsupported local ML model version: {model_version}")
