from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from sentinel.audit.store import AuditStore
from sentinel.config.settings import Settings, load_settings
from sentinel.db.schema import database_status
from sentinel.domain.privacy import SystemMode
from sentinel.memory.service import MemoryService
from sentinel.memory.store import PersistentMemoryStore
from sentinel.meetings.service import MeetingAnalysisService
from sentinel.meetings.store import MeetingStore
from sentinel.privacy.engine import PrivacyEngine
from sentinel.privacy.hybrid_detector import build_privacy_detector
from sentinel.privacy.vault import EntityVault
from sentinel.providers.cloud_gateway import CloudGateway, SafePayloadValidator
from sentinel.providers.openai_provider import OpenAIProvider


class AnalyzePrivacyRequest(BaseModel):
    text: str = Field(min_length=1)
    session_id: str | None = None


class CreateMeetingRequest(BaseModel):
    title: str = "Untitled meeting"
    transcript: str = Field(min_length=1)


class AnalyzeMeetingRequest(BaseModel):
    mode: SystemMode = SystemMode.INTELLIGENCE
    purpose: str = "Generate local meeting intelligence from a safe payload."


class AnalyzeSafeContentRequest(BaseModel):
    safe_content: str = Field(min_length=1)
    session_id: str
    purpose: str
    mode: SystemMode = SystemMode.INTELLIGENCE


class RememberTranscriptRequest(BaseModel):
    transcript: str = Field(min_length=1)
    title: str | None = None
    source: str = "manual"


class AskMemoryRequest(BaseModel):
    question: str = Field(min_length=1)
    mode: SystemMode = SystemMode.INTELLIGENCE
    limit: int = Field(default=6, ge=1, le=12)


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or load_settings()
    audit_store = AuditStore(app_settings.db_path)
    vault = EntityVault(app_settings.db_path)
    privacy_detector = build_privacy_detector(
        local_ml_enabled=app_settings.local_ml_enabled,
        local_ml_model_path=app_settings.local_ml_model_path,
    )
    privacy_engine = PrivacyEngine(vault=vault, audit_store=audit_store, detector=privacy_detector)
    meeting_store = MeetingStore(app_settings.db_path)
    meeting_service = MeetingAnalysisService(meeting_store, privacy_engine, audit_store)
    memory_store = PersistentMemoryStore(app_settings.db_path)
    memory_service = MemoryService(memory_store, privacy_engine, audit_store)
    provider = OpenAIProvider(api_key=app_settings.openai_api_key, model=app_settings.openai_model)
    cloud_gateway = CloudGateway(app_settings, audit_store, provider, validator=SafePayloadValidator(detector=privacy_detector))

    app = FastAPI(
        title="Sentinel API",
        version="0.1.0",
        description="Local-first privacy gateway MVP for meeting intelligence.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/system/status")
    def system_status() -> dict[str, object]:
        return {
            "system": "sentinel",
            "default_mode": SystemMode.INTELLIGENCE.value,
            "external_ai_enabled": app_settings.external_ai_enabled,
            "local_ml_enabled": app_settings.local_ml_enabled,
            "local_ml_model_path": str(Path(app_settings.local_ml_model_path)),
            "local_ml_model_loaded": bool(
                getattr(getattr(privacy_detector, "ml_detector", None), "available", False)
            ),
            "openai_key_configured": bool(app_settings.openai_api_key),
            "db_path": str(Path(app_settings.db_path)),
            "memory": memory_service.counts(),
        }

    @app.get("/api/database/status")
    def get_database_status() -> dict[str, object]:
        return database_status(app_settings.db_path)

    @app.post("/api/privacy/analyze")
    def analyze_privacy(request: AnalyzePrivacyRequest):
        return privacy_engine.analyze(request.text, session_id=request.session_id)

    @app.post("/api/privacy/sanitize")
    def sanitize_privacy(request: AnalyzePrivacyRequest) -> dict[str, object]:
        analysis = privacy_engine.analyze(request.text, session_id=request.session_id)
        return {
            "session_id": analysis.session_id,
            "safe_content": analysis.safe_content,
            "report": analysis.report(),
        }

    @app.post("/api/meetings")
    def create_meeting(request: CreateMeetingRequest):
        meeting = meeting_store.create(title=request.title, transcript=request.transcript)
        audit_store.record("meeting_created", session_id=meeting.id)
        return meeting

    @app.post("/api/meetings/{meeting_id}/analyze")
    def analyze_meeting(meeting_id: str, request: AnalyzeMeetingRequest | None = None):
        payload = request or AnalyzeMeetingRequest()
        try:
            result = meeting_service.analyze(meeting_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Meeting not found") from None

        safe_purpose = privacy_engine.sanitize_purpose(payload.purpose, meeting_id)
        external = cloud_gateway.analyze_safe_content(
            result.privacy.safe_content,
            purpose=safe_purpose,
            session_id=meeting_id,
            mode=payload.mode,
        )
        reconstructed = privacy_engine.reconstruct(external.response, session_id=meeting_id) if external.sent else external.response
        return {
            "meeting_id": meeting_id,
            "mode": payload.mode.value,
            "privacy": result.privacy,
            "summary": result.summary,
            "tasks": result.tasks,
            "decisions": result.decisions,
            "safe_purpose": safe_purpose,
            "external_ai": external,
            "reconstructed_response": reconstructed,
        }

    @app.get("/api/meetings/{meeting_id}")
    def get_meeting(meeting_id: str):
        meeting = meeting_store.get(meeting_id)
        if meeting is None:
            raise HTTPException(status_code=404, detail="Meeting not found")
        summary = meeting_store.get_summary(meeting_id)
        return {
            "meeting": meeting,
            "summary": summary,
            "tasks": meeting_store.list_tasks(meeting_id),
            "decisions": meeting_store.list_decisions(meeting_id),
        }

    @app.get("/api/meetings/{meeting_id}/privacy-report")
    def get_privacy_report(meeting_id: str):
        report = meeting_store.get_privacy_report(meeting_id)
        if report is None:
            raise HTTPException(status_code=404, detail="Privacy report not found")
        return report

    @app.get("/api/meetings/{meeting_id}/tasks")
    def get_tasks(meeting_id: str):
        if meeting_store.get(meeting_id) is None:
            raise HTTPException(status_code=404, detail="Meeting not found")
        return {"tasks": meeting_store.list_tasks(meeting_id)}

    @app.get("/api/audit/events")
    def list_audit_events(limit: int = Query(default=100, ge=1, le=500)):
        return {"events": audit_store.list_events(limit=limit)}

    @app.post("/api/memory/remember")
    def remember_transcript(request: RememberTranscriptRequest):
        return memory_service.remember_transcript(
            transcript=request.transcript,
            title=request.title,
            source=request.source,
        )

    @app.get("/api/memory/search")
    def search_memory(q: str = Query(min_length=1), limit: int = Query(default=6, ge=1, le=12)):
        return {"sources": memory_service.search(q, limit=limit)}

    @app.post("/api/memory/ask")
    def ask_memory(request: AskMemoryRequest):
        return memory_service.ask(
            question=request.question,
            mode=request.mode,
            limit=request.limit,
            cloud_gateway=cloud_gateway,
        )

    @app.get("/api/memory/status")
    def memory_status() -> dict[str, int]:
        return memory_service.counts()

    @app.get("/api/memory/items")
    def list_memory_items(limit: int = Query(default=50, ge=1, le=200)):
        return {"items": memory_service.list_items(limit=limit), "counts": memory_service.counts()}

    @app.get("/api/memory/items/{memory_id}")
    def get_memory_item(memory_id: str):
        item = memory_service.get_item(memory_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Memory item not found")
        return item

    @app.delete("/api/memory/items/{memory_id}")
    def delete_memory_item(memory_id: str):
        deleted = memory_service.delete_item(memory_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Memory item not found")
        return {"deleted": True, "memory_id": memory_id}

    @app.post("/api/ai/analyze-safe-content")
    def analyze_safe_content(request: AnalyzeSafeContentRequest):
        safe_purpose = privacy_engine.sanitize_purpose(request.purpose, request.session_id)
        result = cloud_gateway.analyze_safe_content(
            request.safe_content,
            purpose=safe_purpose,
            session_id=request.session_id,
            mode=request.mode,
        )
        reconstructed = privacy_engine.reconstruct(result.response, session_id=request.session_id) if result.sent else result.response
        return {"external_ai": result, "safe_purpose": safe_purpose, "reconstructed_response": reconstructed}

    return app


app = create_app()
