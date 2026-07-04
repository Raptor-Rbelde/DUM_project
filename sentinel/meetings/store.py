from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from sentinel.db.schema import connect_database, initialize_database
from sentinel.domain.meetings import Meeting, MeetingDecision, MeetingSummary, MeetingTask, utc_now


class MeetingStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        return connect_database(self.db_path)

    def _init_db(self) -> None:
        initialize_database(self.db_path)

    def create(self, title: str, transcript: str) -> Meeting:
        now = utc_now()
        meeting = Meeting(id=str(uuid4()), title=title, transcript=transcript, created_at=now, updated_at=now)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO meetings (id, title, transcript, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (meeting.id, meeting.title, meeting.transcript, meeting.created_at, meeting.updated_at),
            )
        return meeting

    def get(self, meeting_id: str) -> Meeting | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
        return Meeting(**dict(row)) if row else None

    def save_privacy_report(self, meeting_id: str, report: dict, safe_content: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO privacy_reports (meeting_id, report_json, safe_content, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(meeting_id) DO UPDATE SET
                    report_json = excluded.report_json,
                    safe_content = excluded.safe_content,
                    created_at = excluded.created_at
                """,
                (meeting_id, json.dumps(report, sort_keys=True), safe_content, utc_now()),
            )

    def get_privacy_report(self, meeting_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT report_json, safe_content, created_at FROM privacy_reports WHERE meeting_id = ?", (meeting_id,)).fetchone()
        if not row:
            return None
        report = json.loads(str(row["report_json"]))
        report["safe_content"] = row["safe_content"]
        report["created_at"] = row["created_at"]
        return report

    def replace_outputs(
        self,
        meeting_id: str,
        *,
        summary: str,
        tasks: list[tuple[str, str | None]],
        decisions: list[str],
    ) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM meeting_tasks WHERE meeting_id = ?", (meeting_id,))
            conn.execute("DELETE FROM meeting_decisions WHERE meeting_id = ?", (meeting_id,))
            conn.execute("DELETE FROM meeting_summaries WHERE meeting_id = ?", (meeting_id,))
            now = utc_now()
            conn.execute(
                "INSERT INTO meeting_summaries (meeting_id, summary, created_at) VALUES (?, ?, ?)",
                (meeting_id, summary, now),
            )
            for description, owner in tasks:
                conn.execute(
                    "INSERT INTO meeting_tasks (id, meeting_id, description, owner, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (str(uuid4()), meeting_id, description, owner, "open", now),
                )
            for description in decisions:
                conn.execute(
                    "INSERT INTO meeting_decisions (id, meeting_id, description, created_at) VALUES (?, ?, ?, ?)",
                    (str(uuid4()), meeting_id, description, now),
                )

    def list_tasks(self, meeting_id: str) -> list[MeetingTask]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM meeting_tasks WHERE meeting_id = ? ORDER BY created_at", (meeting_id,)).fetchall()
        return [MeetingTask(**dict(row)) for row in rows]

    def list_decisions(self, meeting_id: str) -> list[MeetingDecision]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM meeting_decisions WHERE meeting_id = ? ORDER BY created_at", (meeting_id,)).fetchall()
        return [MeetingDecision(**dict(row)) for row in rows]

    def get_summary(self, meeting_id: str) -> MeetingSummary | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM meeting_summaries WHERE meeting_id = ?", (meeting_id,)).fetchone()
        return MeetingSummary(**dict(row)) if row else None
