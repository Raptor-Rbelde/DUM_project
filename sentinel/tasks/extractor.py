from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ExtractedTask:
    description: str
    owner: str | None = None


@dataclass(frozen=True)
class ExtractedDecision:
    description: str


@dataclass(frozen=True)
class ExtractedRisk:
    description: str


class LocalMeetingExtractor:
    task_patterns = (
        re.compile(r"\b(?:tarea|accion|action item|follow up|responsable|debe|will)\b", re.IGNORECASE),
    )
    decision_patterns = (
        re.compile(r"\b(?:decision|decidimos|acordamos|approved|aprobado|se aprueba)\b", re.IGNORECASE),
    )
    risk_patterns = (
        re.compile(
            r"\b(?:riesgo|risk|bloqueo|blocked|bloqueado|incidente|comprometido|compromiso|"
            r"urgente|critico|crítico|secreto|secret|password|token|api key|auditoria|auditoría)\b",
            re.IGNORECASE,
        ),
    )

    def summarize(self, safe_content: str) -> str:
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", safe_content.strip()) if part.strip()]
        if not sentences:
            return "No meeting content was provided."
        return " ".join(sentences[:2])

    def extract_tasks(self, safe_content: str) -> list[ExtractedTask]:
        tasks: list[ExtractedTask] = []
        for line in self._lines(safe_content):
            if any(pattern.search(line) for pattern in self.task_patterns):
                tasks.append(ExtractedTask(description=line[:280]))
        return tasks

    def extract_decisions(self, safe_content: str) -> list[ExtractedDecision]:
        decisions: list[ExtractedDecision] = []
        for line in self._lines(safe_content):
            if any(pattern.search(line) for pattern in self.decision_patterns):
                decisions.append(ExtractedDecision(description=line[:280]))
        return decisions

    def extract_risks(self, safe_content: str) -> list[ExtractedRisk]:
        risks: list[ExtractedRisk] = []
        for line in self._lines(safe_content):
            if any(pattern.search(line) for pattern in self.risk_patterns):
                risks.append(ExtractedRisk(description=line[:280]))
        return risks

    @staticmethod
    def _lines(text: str) -> list[str]:
        chunks = re.split(r"[\n\r]+|(?<=[.!?])\s+", text)
        return [chunk.strip(" -") for chunk in chunks if chunk.strip(" -")]
