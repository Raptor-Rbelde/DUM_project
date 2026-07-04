from __future__ import annotations

from pydantic import BaseModel

from sentinel.audit.store import AuditStore
from sentinel.domain.privacy import PrivacyAnalysis
from sentinel.meetings.store import MeetingStore
from sentinel.privacy.engine import PrivacyEngine
from sentinel.tasks.extractor import LocalMeetingExtractor


class MeetingAnalysisResult(BaseModel):
    meeting_id: str
    privacy: PrivacyAnalysis
    summary: str
    tasks: list[str]
    decisions: list[str]


class MeetingAnalysisService:
    def __init__(
        self,
        meeting_store: MeetingStore,
        privacy_engine: PrivacyEngine,
        audit_store: AuditStore,
        extractor: LocalMeetingExtractor | None = None,
    ) -> None:
        self.meeting_store = meeting_store
        self.privacy_engine = privacy_engine
        self.audit_store = audit_store
        self.extractor = extractor or LocalMeetingExtractor()

    def analyze(self, meeting_id: str) -> MeetingAnalysisResult:
        meeting = self.meeting_store.get(meeting_id)
        if meeting is None:
            raise KeyError(meeting_id)

        privacy = self.privacy_engine.analyze(meeting.transcript, session_id=meeting.id)
        summary = self.extractor.summarize(privacy.safe_content)
        tasks = self.extractor.extract_tasks(privacy.safe_content)
        decisions = self.extractor.extract_decisions(privacy.safe_content)
        self.meeting_store.save_privacy_report(meeting.id, privacy.report(), privacy.safe_content)
        self.meeting_store.replace_outputs(
            meeting.id,
            summary=summary,
            tasks=[(task.description, task.owner) for task in tasks],
            decisions=[decision.description for decision in decisions],
        )
        return MeetingAnalysisResult(
            meeting_id=meeting.id,
            privacy=privacy,
            summary=summary,
            tasks=[task.description for task in tasks],
            decisions=[decision.description for decision in decisions],
        )
