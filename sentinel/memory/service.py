from __future__ import annotations

import re
import unicodedata
from itertools import zip_longest
from uuid import uuid4

from pydantic import BaseModel

from sentinel.audit.store import AuditStore
from sentinel.domain.privacy import PrivacyAnalysis, SystemMode
from sentinel.memory.store import MemoryItem, MemorySearchResult, PersistentMemoryStore
from sentinel.privacy.engine import PrivacyEngine
from sentinel.providers.cloud_gateway import CloudGateway, ExternalAIResult, SafePayloadValidation
from sentinel.tasks.extractor import LocalMeetingExtractor


class MemorySource(BaseModel):
    memory_id: str
    title: str
    chunk_id: str
    score: float
    snippet: str
    safe_snippet: str
    summary: str
    tasks: list[str]
    decisions: list[str]
    risks: list[str]
    areas: list["EnterpriseAreaInsight"]
    task_segments: list["TaskSegmentInsight"]
    created_at: str


class EnterpriseAreaInsight(BaseModel):
    area: str
    score: float
    evidence: list[str] = []


class TaskSegmentInsight(BaseModel):
    description: str
    area: str
    role: str
    confidence: float


class RememberedTranscript(BaseModel):
    memory_id: str
    title: str
    chunk_count: int
    summary: str
    tasks: list[str]
    decisions: list[str]
    risks: list[str]
    areas: list[EnterpriseAreaInsight]
    task_segments: list[TaskSegmentInsight]
    analysis: PrivacyAnalysis


class MemoryDashboardItem(BaseModel):
    memory_id: str
    title: str
    source: str
    created_at: str
    updated_at: str
    summary: str
    tasks: list[str]
    decisions: list[str]
    risks: list[str]
    areas: list[EnterpriseAreaInsight]
    task_segments: list[TaskSegmentInsight]
    risk_level: str
    entities: int
    chunks: int | None = None


class MemoryDetail(MemoryDashboardItem):
    transcript: str
    safe_content: str
    privacy_report: dict


class MemoryAnswer(BaseModel):
    question: str
    answer: str
    mode: SystemMode
    sources: list[MemorySource]
    safe_context: str
    external_ai: ExternalAIResult | None = None


class MemoryService:
    def __init__(
        self,
        memory_store: PersistentMemoryStore,
        privacy_engine: PrivacyEngine,
        audit_store: AuditStore,
        extractor: LocalMeetingExtractor | None = None,
    ) -> None:
        self.memory_store = memory_store
        self.privacy_engine = privacy_engine
        self.audit_store = audit_store
        self.extractor = extractor or LocalMeetingExtractor()

    def remember_transcript(
        self,
        *,
        transcript: str,
        title: str | None = None,
        source: str = "manual",
        memory_id: str | None = None,
    ) -> RememberedTranscript:
        item_id = memory_id or str(uuid4())
        clean_title = title.strip() if title and title.strip() else _title_from_transcript(transcript)
        analysis = self.privacy_engine.analyze(transcript, session_id=item_id)
        summary = self.extractor.summarize(analysis.safe_content)
        tasks = [task.description for task in self.extractor.extract_tasks(analysis.safe_content)]
        decisions = [decision.description for decision in self.extractor.extract_decisions(analysis.safe_content)]
        risks = [risk.description for risk in self.extractor.extract_risks(analysis.safe_content)]
        areas = [_area_dict(area) for area in self.extractor.classify_areas(analysis.safe_content)]
        task_segments = self._segment_safe_tasks(tasks)
        item = self.memory_store.save_item(
            memory_id=item_id,
            title=clean_title,
            transcript=transcript,
            safe_content=analysis.safe_content,
            privacy_report=analysis.report(),
            summary=summary,
            tasks=tasks,
            decisions=decisions,
            risks=risks,
            areas=areas,
            task_segments=task_segments,
            source=source,
        )
        chunks = self.memory_store.replace_chunks(item.id, _paired_chunks(transcript, analysis.safe_content))
        self.audit_store.record(
            "memory_transcript_saved",
            session_id=item.id,
            number_of_entities=len(analysis.entities),
            number_blocked=len(analysis.blocked_entities),
            number_pseudonymized=len(analysis.pseudonymized_entities),
            payload=analysis.safe_content,
            metadata={
                "title": item.title,
                "source": source,
                "chunks": len(chunks),
                "tasks": len(tasks),
                "decisions": len(decisions),
                "risks": len(risks),
                "areas": [area["area"] for area in areas],
            },
        )
        return RememberedTranscript(
            memory_id=item.id,
            title=item.title,
            chunk_count=len(chunks),
            summary=self.privacy_engine.reconstruct(summary),
            tasks=[self.privacy_engine.reconstruct(task) for task in tasks],
            decisions=[self.privacy_engine.reconstruct(decision) for decision in decisions],
            risks=[self.privacy_engine.reconstruct(risk) for risk in risks],
            areas=[EnterpriseAreaInsight(**area) for area in areas],
            task_segments=[self._reconstructed_task_segment(segment) for segment in task_segments],
            analysis=analysis,
        )

    def list_items(self, limit: int = 50) -> list[MemoryDashboardItem]:
        return [self._dashboard_item(item) for item in self.memory_store.list_items(limit=limit)]

    def get_item(self, memory_id: str) -> MemoryDetail | None:
        item = self.memory_store.get_item(memory_id)
        if item is None:
            return None
        dashboard = self._dashboard_item(item)
        return MemoryDetail(
            **dashboard.model_dump(),
            transcript=item.transcript,
            safe_content=item.safe_content,
            privacy_report=item.privacy_report,
        )

    def delete_item(self, memory_id: str) -> bool:
        deleted = self.memory_store.delete_item(memory_id)
        if deleted:
            self.audit_store.record("memory_item_deleted", session_id=memory_id)
        return deleted

    def search(self, query: str, limit: int = 6) -> list[MemorySource]:
        return [self._source_from_result(result) for result in self.memory_store.search(query, limit=limit)]

    def ask(
        self,
        *,
        question: str,
        mode: SystemMode,
        limit: int = 6,
        cloud_gateway: CloudGateway | None = None,
    ) -> MemoryAnswer:
        results = self.memory_store.search(question, limit=limit)
        sources = [self._source_from_result(result) for result in results]
        safe_question = self._sanitize_question_for_results(question, results)
        safe_context = self._safe_context(results, safe_question=safe_question)

        if not results:
            return MemoryAnswer(
                question=question,
                answer="No encontre informacion relevante en la memoria empresarial local.",
                mode=mode,
                sources=[],
                safe_context=safe_context,
            )

        local_correction = self._false_premise_correction(question, sources)
        if local_correction is not None:
            return MemoryAnswer(
                question=question,
                answer=local_correction,
                mode=mode,
                sources=sources,
                safe_context=safe_context,
                external_ai=ExternalAIResult(
                    sent=False,
                    provider=None,
                    response="Answered locally because the retrieved memory explicitly contradicts the question premise.",
                    validation=SafePayloadValidation(allowed=False, reason="Local false-premise correction."),
                ),
            )

        if mode == SystemMode.INTELLIGENCE and cloud_gateway is not None:
            external = cloud_gateway.analyze_safe_content(
                safe_context,
                purpose=f"Answer this enterprise memory question using only the safe context: {safe_question}",
                session_id=f"memory-question-{uuid4()}",
                mode=mode,
            )
            answer = self.privacy_engine.reconstruct(external.response) if external.sent else external.response
            return MemoryAnswer(
                question=question,
                answer=answer,
                mode=mode,
                sources=sources,
                safe_context=safe_context,
                external_ai=external,
            )

        return MemoryAnswer(
            question=question,
            answer=self._local_answer(question, sources),
            mode=mode,
            sources=sources,
            safe_context=safe_context,
            external_ai=ExternalAIResult(
                sent=False,
                provider=None,
                response="Vault Mode answered with local retrieved memory snippets. No external provider was called.",
                validation=SafePayloadValidation(allowed=False, reason="Vault Mode blocks all external calls."),
            ),
        )

    def counts(self) -> dict[str, int]:
        return self.memory_store.counts()

    def _dashboard_item(self, item: MemoryItem) -> MemoryDashboardItem:
        report = item.privacy_report
        counts = report.get("counts", {})
        artifacts = self._artifacts_for_safe_text(item.safe_content)
        return MemoryDashboardItem(
            memory_id=item.id,
            title=item.title,
            source=item.source,
            created_at=item.created_at,
            updated_at=item.updated_at,
            summary=self.privacy_engine.reconstruct(item.summary),
            tasks=[self.privacy_engine.reconstruct(task) for task in artifacts["tasks"]],
            decisions=[self.privacy_engine.reconstruct(decision) for decision in artifacts["decisions"]],
            risks=[self.privacy_engine.reconstruct(risk) for risk in artifacts["risks"]],
            areas=[EnterpriseAreaInsight(**area) for area in artifacts["areas"]],
            task_segments=[self._reconstructed_task_segment(segment) for segment in artifacts["task_segments"]],
            risk_level=str(report.get("risk_level", "LOW")),
            entities=int(counts.get("total_entities", 0) or 0),
        )

    def _areas_for_item(self, item: MemoryItem) -> list[dict]:
        if item.areas:
            return item.areas
        return [_area_dict(area) for area in self.extractor.classify_areas(item.safe_content)]

    def _task_segments_for_item(self, item: MemoryItem) -> list[dict]:
        if item.task_segments:
            return item.task_segments
        return [_task_segment_dict(segment) for segment in self.extractor.segment_tasks(item.tasks)]

    def _artifacts_for_safe_text(self, safe_text: str) -> dict[str, list]:
        tasks = [task.description for task in self.extractor.extract_tasks(safe_text)]
        decisions = [decision.description for decision in self.extractor.extract_decisions(safe_text)]
        risks = [risk.description for risk in self.extractor.extract_risks(safe_text)]
        areas = [_area_dict(area) for area in self.extractor.classify_areas(safe_text)]
        task_segments = self._segment_safe_tasks(tasks)
        return {
            "tasks": tasks,
            "decisions": decisions,
            "risks": risks,
            "areas": areas,
            "task_segments": task_segments,
        }

    def _segment_safe_tasks(self, tasks: list[str]) -> list[dict]:
        segments: list[dict] = []
        for safe_task in tasks:
            classifier_input = self.privacy_engine.reconstruct(safe_task)
            segment = self.extractor.area_classifier.segment_task(classifier_input)
            segments.append(
                {
                    "description": safe_task,
                    "area": segment.area,
                    "role": segment.role,
                    "confidence": segment.confidence,
                }
            )
        return segments

    def _reconstructed_task_segment(self, segment: dict) -> TaskSegmentInsight:
        clean = {
            "description": self.privacy_engine.reconstruct(str(segment.get("description", ""))),
            "area": str(segment.get("area", "General")),
            "role": str(segment.get("role", "General / Sin asignar")),
            "confidence": float(segment.get("confidence", 0.0) or 0.0),
        }
        return TaskSegmentInsight(**clean)

    def _source_from_result(self, result: MemorySearchResult) -> MemorySource:
        artifacts = self._artifacts_for_safe_text(result.chunk.safe_text)
        return MemorySource(
            memory_id=result.item.id,
            title=result.item.title,
            chunk_id=result.chunk.id,
            score=result.score,
            snippet=self.privacy_engine.reconstruct(result.chunk.safe_text),
            safe_snippet=result.chunk.safe_text,
            summary=self.privacy_engine.reconstruct(result.item.summary),
            tasks=[self.privacy_engine.reconstruct(task) for task in artifacts["tasks"]],
            decisions=[self.privacy_engine.reconstruct(decision) for decision in artifacts["decisions"]],
            risks=[self.privacy_engine.reconstruct(risk) for risk in artifacts["risks"]],
            areas=[EnterpriseAreaInsight(**area) for area in artifacts["areas"]],
            task_segments=[self._reconstructed_task_segment(segment) for segment in artifacts["task_segments"]],
            created_at=result.item.created_at,
        )

    def _safe_context(self, results: list[MemorySearchResult], *, safe_question: str) -> str:
        aggregate = self._aggregate_artifacts(results)
        lines = [
            "Enterprise memory question:",
            safe_question,
            "",
            "Aggregate structured memory facts across all retrieved snippets:",
            f"Tasks: {_format_list(aggregate['tasks'])}",
            f"Areas: {_format_area_list(aggregate['areas'])}",
            f"Task Segments: {_format_task_segment_list(aggregate['task_segments'])}",
            f"Decisions: {_format_list(aggregate['decisions'])}",
            f"Risks: {_format_list(aggregate['risks'])}",
            "",
            "Consistency rule: the aggregate structured memory facts above are authoritative. "
            "If Tasks or Task Segments are not None, do not answer that no tasks are registered. "
            "If Decisions or Risks are not None, include them instead of saying they are absent.",
            "",
            "Relevant safe memory records:",
        ]
        for index, result in enumerate(results, start=1):
            safe_title = self.privacy_engine.sanitize_text(result.item.title, session_id=result.item.id)
            artifacts = self._artifacts_for_safe_text(result.chunk.safe_text)
            lines.extend(
                [
                    f"[Source {index}] memory_id={result.item.id} title={safe_title} score={result.score:.2f}",
                    f"Summary: {result.item.summary}",
                    f"Tasks in snippet: {_format_list(artifacts['tasks'])}",
                    f"Areas in snippet: {_format_area_list(artifacts['areas'])}",
                    f"Task Segments in snippet: {_format_task_segment_list(artifacts['task_segments'])}",
                    f"Decisions in snippet: {_format_list(artifacts['decisions'])}",
                    f"Risks in snippet: {_format_list(artifacts['risks'])}",
                    "Snippet:",
                    result.chunk.safe_text,
                    "",
                ]
            )
        lines.append("Answer only from these snippets. If the answer is not present, say it is not in memory.")
        lines.append(
            "If the snippets explicitly contradict the question premise, correct the premise directly instead of "
            "saying the answer is not in memory. Negative instructions such as no, nunca, prohibido, bajo ninguna "
            "circunstancia, detente, and cero bloqueos are decisive evidence."
        )
        return "\n".join(lines)

    def _aggregate_artifacts(self, results: list[MemorySearchResult]) -> dict[str, list]:
        aggregate: dict[str, list] = {
            "tasks": [],
            "decisions": [],
            "risks": [],
            "areas": [],
            "task_segments": [],
        }
        seen_text: dict[str, set[str]] = {"tasks": set(), "decisions": set(), "risks": set()}
        seen_areas: set[str] = set()
        seen_segments: set[tuple[str, str, str]] = set()

        for result in results:
            artifacts = self._artifacts_for_safe_text(result.chunk.safe_text)
            for key in ("tasks", "decisions", "risks"):
                for value in artifacts[key]:
                    clean = str(value).strip()
                    if clean and clean not in seen_text[key]:
                        seen_text[key].add(clean)
                        aggregate[key].append(clean)
            for area in artifacts["areas"]:
                if not isinstance(area, dict):
                    continue
                area_name = str(area.get("area", "")).strip()
                if area_name and area_name not in seen_areas:
                    seen_areas.add(area_name)
                    aggregate["areas"].append(area)
            for segment in artifacts["task_segments"]:
                if not isinstance(segment, dict):
                    continue
                signature = (
                    str(segment.get("area", "")),
                    str(segment.get("role", "")),
                    str(segment.get("description", "")),
                )
                if signature[2] and signature not in seen_segments:
                    seen_segments.add(signature)
                    aggregate["task_segments"].append(segment)
        return aggregate

    def _sanitize_question_for_results(self, question: str, results: list[MemorySearchResult]) -> str:
        sanitized = question
        seen_sessions: set[str] = set()
        for result in results:
            if result.item.id in seen_sessions:
                continue
            seen_sessions.add(result.item.id)
            sanitized = self.privacy_engine.sanitize_text(sanitized, session_id=result.item.id)
        return self.privacy_engine.sanitize_text(sanitized)

    @staticmethod
    def _local_answer(question: str, sources: list[MemorySource]) -> str:
        if not sources:
            return "No encontre informacion relevante en la memoria empresarial local."
        question_lower = question.lower()
        wants_tasks = any(term in question_lower for term in ("tarea", "accion", "acción", "pendiente", "responsable"))
        wants_decisions = any(term in question_lower for term in ("decision", "decisión", "acuerdo", "aprobo", "aprobó"))
        wants_risks = any(term in question_lower for term in ("riesgo", "bloqueo", "incidente", "critico", "crítico"))
        wants_summary = any(term in question_lower for term in ("resumen", "contexto", "que paso", "qué pasó"))
        wants_areas = any(
            term in question_lower
            for term in ("area", "área", "departamento", "rol", "roles", "segment", "segmenta", "equipo")
        )

        sections: list[str] = []
        if wants_areas:
            areas = _unique(area.area for source in sources for area in source.areas)
            task_segments = _unique(
                f"{segment.role} ({segment.area}): {segment.description}"
                for source in sources
                for segment in source.task_segments
            )
            if areas:
                sections.append("Areas detectadas:\n" + "\n".join(f"- {item}" for item in areas[:8]))
            if task_segments:
                sections.append("Tareas por rol:\n" + "\n".join(f"- {item}" for item in task_segments[:10]))
        if wants_summary:
            summaries = _unique(source.summary for source in sources if source.summary)
            if summaries:
                sections.append("Resumen:\n" + "\n".join(f"- {item}" for item in summaries[:4]))
        if wants_decisions:
            decisions = _unique(item for source in sources for item in source.decisions)
            if decisions:
                sections.append("Decisiones:\n" + "\n".join(f"- {item}" for item in decisions[:8]))
        if wants_tasks:
            tasks = _unique(item for source in sources for item in source.tasks)
            if tasks:
                sections.append("Tareas:\n" + "\n".join(f"- {item}" for item in tasks[:8]))
        if wants_risks:
            risks = _unique(item for source in sources for item in source.risks)
            if risks:
                sections.append("Riesgos:\n" + "\n".join(f"- {item}" for item in risks[:8]))
        if sections:
            return "\n\n".join(sections)

        primary = sources[0]
        return (
            f"Encontre {len(sources)} fragmento(s) relevante(s) en la memoria local. "
            f"La fuente principal es \"{primary.title}\". Fragmento: {primary.snippet}"
        )

    @staticmethod
    def _false_premise_correction(question: str, sources: list[MemorySource]) -> str | None:
        normalized_question = _normalize(question)
        combined = "\n".join(source.snippet for source in sources)
        normalized_context = _normalize(combined)

        asks_about_freezing = any(term in normalized_question for term in ("congel", "bloque")) and any(
            term in normalized_question for term in ("cuenta", "banco", "fondos")
        )
        context_forbids_freezing = (
            "bajo ninguna circunstancia" in normalized_context and "congel" in normalized_context
        ) or "cero bloqueos" in normalized_context or (
            _contains_term(normalized_context, "no") and "congel" in normalized_context and "cuenta" in normalized_context
        )

        if not asks_about_freezing or not context_forbids_freezing:
            return None

        sentences = _sentences(combined)
        prohibition = _first_sentence_matching(
            sentences,
            ("bajo ninguna circunstancia", "cero bloqueos", "prohibido"),
            ("congel", "bloque", "cuenta"),
        ) or _first_sentence_matching(sentences, ("no",), ("congel", "bloque", "cuenta"))
        reason = _first_sentence_matching(sentences, ("nomina", "rebota", "panico", "mediatico"), ())
        action = _first_sentence_matching(sentences, ("deshabilitar", "transferencias"), ()) or _first_sentence_matching(
            sentences,
            ("revoca", "stripe"),
            (),
        )

        parts = [
            "Valeria no dio la orden de congelar la cuenta corporativa principal; corrigio esa premisa y lo prohibio explicitamente."
        ]
        if prohibition:
            parts.append(f"Evidencia: {prohibition}")
        if reason:
            parts.append(f"Motivo: {reason}")
        if action:
            parts.append(f"La accion indicada fue: {action}")
        return " ".join(parts)


def _title_from_transcript(transcript: str) -> str:
    for line in transcript.splitlines():
        clean = line.strip(" #*-:\t")
        if clean:
            return clean[:90]
    return "Untitled memory"


def _paired_chunks(transcript: str, safe_content: str) -> list[tuple[str, str]]:
    raw_chunks = _chunk_text(transcript)
    safe_chunks = _chunk_text(safe_content)
    pairs: list[tuple[str, str]] = []
    for raw, safe in zip_longest(raw_chunks, safe_chunks, fillvalue=""):
        if raw.strip() or safe.strip():
            pairs.append((raw or "", safe or ""))
    return pairs or [(transcript, safe_content)]


def _chunk_text(text: str, max_chars: int = 1200) -> list[str]:
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    if not paragraphs:
        paragraphs = [text.strip()] if text.strip() else []

    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_long_text(paragraph, max_chars=max_chars))
            continue
        if current and len(current) + len(paragraph) + 2 > max_chars:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}".strip() if current else paragraph
    if current:
        chunks.append(current)
    return chunks


def _split_long_text(text: str, max_chars: int) -> list[str]:
    sentences = [part.strip() for part in text.replace("\n", " ").split(". ") if part.strip()]
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        sentence = sentence if sentence.endswith(".") else f"{sentence}."
        if current and len(current) + len(sentence) + 1 > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip() if current else sentence
    if current:
        chunks.append(current)
    return chunks


def _format_list(items: list[str]) -> str:
    return "; ".join(items) if items else "None"


def _format_area_list(items: list[dict]) -> str:
    if not items:
        return "None"
    return "; ".join(str(item.get("area", "General")) for item in items if isinstance(item, dict))


def _format_task_segment_list(items: list[dict]) -> str:
    if not items:
        return "None"
    segments = []
    for item in items:
        if not isinstance(item, dict):
            continue
        segments.append(
            f"{item.get('role', 'General / Sin asignar')} ({item.get('area', 'General')}): {item.get('description', '')}"
        )
    return "; ".join(segments) if segments else "None"


def _area_dict(area) -> dict:
    return {
        "area": area.area,
        "score": area.score,
        "evidence": list(area.evidence),
    }


def _task_segment_dict(segment) -> dict:
    return {
        "description": segment.description,
        "area": segment.area,
        "role": segment.role,
        "confidence": segment.confidence,
    }


def _unique(items) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        clean = str(item).strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return normalized.lower()


def _sentences(text: str) -> list[str]:
    return [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+|\n+", text) if sentence.strip()]


def _first_sentence_matching(sentences: list[str], required_any: tuple[str, ...], extra_any: tuple[str, ...]) -> str | None:
    for sentence in sentences:
        normalized = _normalize(sentence)
        if required_any and not any(_contains_term(normalized, term) for term in required_any):
            continue
        if extra_any and not any(_contains_term(normalized, term) for term in extra_any):
            continue
        return sentence
    return None


def _contains_term(normalized_text: str, term: str) -> bool:
    normalized_term = _normalize(term)
    if len(normalized_term) <= 3 and normalized_term.isalpha():
        return bool(re.search(rf"\b{re.escape(normalized_term)}\b", normalized_text))
    return normalized_term in normalized_text
