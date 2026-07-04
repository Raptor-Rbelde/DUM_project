from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Meeting(BaseModel):
    id: str
    title: str
    transcript: str = Field(repr=False)
    created_at: str
    updated_at: str


class MeetingTask(BaseModel):
    id: str
    meeting_id: str
    description: str
    owner: str | None = None
    status: str = "open"
    created_at: str


class MeetingDecision(BaseModel):
    id: str
    meeting_id: str
    description: str
    created_at: str


class MeetingSummary(BaseModel):
    meeting_id: str
    summary: str
    created_at: str
