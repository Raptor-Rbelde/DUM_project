from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from sentinel.db.schema import connect_database, initialize_database


def payload_fingerprint(payload: str | None) -> str | None:
    if payload is None:
        return None
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class AuditStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        return connect_database(self.db_path)

    def _init_db(self) -> None:
        initialize_database(self.db_path)

    def record(
        self,
        event_type: str,
        *,
        session_id: str | None = None,
        policy_decision: str | None = None,
        number_of_entities: int | None = None,
        number_blocked: int | None = None,
        number_pseudonymized: int | None = None,
        provider: str | None = None,
        payload: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        safe_metadata = metadata or {}
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_events (
                    event_type, session_id, policy_decision, number_of_entities,
                    number_blocked, number_pseudonymized, provider,
                    payload_fingerprint, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_type,
                    session_id,
                    policy_decision,
                    number_of_entities,
                    number_blocked,
                    number_pseudonymized,
                    provider,
                    payload_fingerprint(payload),
                    json.dumps(safe_metadata, sort_keys=True),
                ),
            )

    def list_events(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM audit_events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            event = dict(row)
            event["metadata"] = json.loads(event.pop("metadata_json") or "{}")
            events.append(event)
        return events
