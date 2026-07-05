from __future__ import annotations

import re
from dataclasses import dataclass

from sentinel.tasks.enterprise_classifier import AreaInsight, EnterpriseAreaClassifier, TaskSegment


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
        re.compile(r"\b(?:tarea|accion|action item|follow up|responsable|debe|will|to\s*do|todo)\b", re.IGNORECASE),
    )
    negative_task_patterns = (
        re.compile(r"\b(?:no se registran|no hay|sin|ninguna|ningun|ningún)\b.{0,80}\btareas?\b", re.IGNORECASE),
        re.compile(r"\btareas?\s+especificas?\b|\btareas?\s+específicas?\b", re.IGNORECASE),
        re.compile(r"\bcomentarios?\s+todo\b|\bcomentario\s+que\s+dice\b.{0,80}\btodo\b|//\s*todo\b", re.IGNORECASE),
        re.compile(r"\blista\s+de\s+(?:tareas?|to\s*dos?|todo)\b", re.IGNORECASE),
        re.compile(r"\b(?:tengo|tenemos|hay)\s+identificad\w*\b.{0,60}\b(?:todo|tareas?|riesgos?)\b", re.IGNORECASE),
        re.compile(r"\bto\s*do\s+list\s+inicial\b|\binicial\s+ten[ií]as\s+programado\b", re.IGNORECASE),
        re.compile(r"\btacha\s+eso\b|\bcancelad[oa]\b|\bdet[eé]n\s+eso\b", re.IGNORECASE),
        re.compile(
            r"\btu\s+tarea\s+no\s+es\b|\bno\s+es\s+t[eé]cnica\b|\[[A-Z]+(?:_[A-Z]+)*_[A-Z0-9]{4}\]\s+no\s+es\s+t[eé]cnica\b|"
            r"\bprocedo\s+con\s+el\s+todo\s+del\s+ticket\b",
            re.IGNORECASE,
        ),
        re.compile(r"\b(?:asigna|asignar|asigne)\s+(?:esta|esa)\s+tarea\s+al\s+ticket\b", re.IGNORECASE),
        re.compile(r"\b(?:documentare|documentaré|documentar)\s+esto\s+bajo\s+el\s+ticket\b", re.IGNORECASE),
        re.compile(r"\b(?:esta|esa)\s+tarea\s+al\s+ticket\b", re.IGNORECASE),
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

    def __init__(self, area_classifier: EnterpriseAreaClassifier | None = None) -> None:
        self.area_classifier = area_classifier or EnterpriseAreaClassifier()

    def summarize(self, safe_content: str) -> str:
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", safe_content.strip()) if part.strip()]
        if not sentences:
            return "No meeting content was provided."
        return " ".join(sentences[:2])

    def extract_tasks(self, safe_content: str) -> list[ExtractedTask]:
        tasks: list[ExtractedTask] = []
        for line in self._lines(safe_content):
            if self._is_task_line(line):
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

    def classify_areas(self, safe_content: str) -> list[AreaInsight]:
        return self.area_classifier.classify_areas(safe_content)

    def segment_tasks(self, tasks: list[str]) -> list[TaskSegment]:
        return self.area_classifier.segment_tasks(tasks)

    def _is_task_line(self, line: str) -> bool:
        if any(pattern.search(line) for pattern in self.negative_task_patterns):
            return False
        return any(pattern.search(line) for pattern in self.task_patterns)

    @staticmethod
    def _lines(text: str) -> list[str]:
        chunks = re.split(r"[\n\r]+|(?<=[.!?])\s+", text)
        return [chunk.strip(" -") for chunk in chunks if chunk.strip(" -")]
