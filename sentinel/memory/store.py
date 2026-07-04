from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from sentinel.domain.meetings import utc_now


TOKEN_PATTERN = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9_/-]{3,}")


@dataclass(frozen=True)
class MemoryItem:
    id: str
    title: str
    transcript: str
    safe_content: str
    privacy_report: dict
    summary: str
    tasks: list[str]
    decisions: list[str]
    risks: list[str]
    source: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class MemoryChunk:
    id: str
    memory_id: str
    chunk_index: int
    text: str
    safe_text: str
    created_at: str


@dataclass(frozen=True)
class MemorySearchResult:
    item: MemoryItem
    chunk: MemoryChunk
    score: float


class PersistentMemoryStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_items (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    transcript TEXT NOT NULL,
                    safe_content TEXT NOT NULL,
                    privacy_report_json TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    tasks_json TEXT NOT NULL DEFAULT '[]',
                    decisions_json TEXT NOT NULL DEFAULT '[]',
                    risks_json TEXT NOT NULL DEFAULT '[]',
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory_chunks (
                    id TEXT PRIMARY KEY,
                    memory_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    safe_text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(memory_id) REFERENCES memory_items(id)
                );
                CREATE INDEX IF NOT EXISTS idx_memory_chunks_memory_id ON memory_chunks(memory_id);
                """
            )
            self._ensure_columns(conn)

    @staticmethod
    def _ensure_columns(conn: sqlite3.Connection) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(memory_items)").fetchall()}
        migrations = {
            "summary": "ALTER TABLE memory_items ADD COLUMN summary TEXT NOT NULL DEFAULT ''",
            "tasks_json": "ALTER TABLE memory_items ADD COLUMN tasks_json TEXT NOT NULL DEFAULT '[]'",
            "decisions_json": "ALTER TABLE memory_items ADD COLUMN decisions_json TEXT NOT NULL DEFAULT '[]'",
            "risks_json": "ALTER TABLE memory_items ADD COLUMN risks_json TEXT NOT NULL DEFAULT '[]'",
        }
        for column, statement in migrations.items():
            if column not in columns:
                conn.execute(statement)

    def save_item(
        self,
        *,
        memory_id: str,
        title: str,
        transcript: str,
        safe_content: str,
        privacy_report: dict,
        summary: str,
        tasks: list[str],
        decisions: list[str],
        risks: list[str],
        source: str,
    ) -> MemoryItem:
        now = utc_now()
        with self._connect() as conn:
            existing = conn.execute("SELECT created_at FROM memory_items WHERE id = ?", (memory_id,)).fetchone()
            created_at = str(existing["created_at"]) if existing else now
            conn.execute(
                """
                INSERT INTO memory_items (
                    id, title, transcript, safe_content, privacy_report_json,
                    summary, tasks_json, decisions_json, risks_json,
                    source, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    transcript = excluded.transcript,
                    safe_content = excluded.safe_content,
                    privacy_report_json = excluded.privacy_report_json,
                    summary = excluded.summary,
                    tasks_json = excluded.tasks_json,
                    decisions_json = excluded.decisions_json,
                    risks_json = excluded.risks_json,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                (
                    memory_id,
                    title,
                    transcript,
                    safe_content,
                    json.dumps(privacy_report, sort_keys=True),
                    summary,
                    json.dumps(tasks, sort_keys=True),
                    json.dumps(decisions, sort_keys=True),
                    json.dumps(risks, sort_keys=True),
                    source,
                    created_at,
                    now,
                ),
            )
        return MemoryItem(
            memory_id,
            title,
            transcript,
            safe_content,
            privacy_report,
            summary,
            tasks,
            decisions,
            risks,
            source,
            created_at,
            now,
        )

    def replace_chunks(self, memory_id: str, chunks: list[tuple[str, str]]) -> list[MemoryChunk]:
        now = utc_now()
        saved: list[MemoryChunk] = []
        with self._connect() as conn:
            conn.execute("DELETE FROM memory_chunks WHERE memory_id = ?", (memory_id,))
            for index, (text, safe_text) in enumerate(chunks):
                chunk = MemoryChunk(str(uuid4()), memory_id, index, text, safe_text, now)
                conn.execute(
                    """
                    INSERT INTO memory_chunks (id, memory_id, chunk_index, text, safe_text, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (chunk.id, chunk.memory_id, chunk.chunk_index, chunk.text, chunk.safe_text, chunk.created_at),
                )
                saved.append(chunk)
        return saved

    def get_item(self, memory_id: str) -> MemoryItem | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM memory_items WHERE id = ?", (memory_id,)).fetchone()
        return self._item_from_row(row) if row else None

    def list_items(self, limit: int = 50) -> list[MemoryItem]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memory_items ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._item_from_row(row) for row in rows]

    def delete_item(self, memory_id: str) -> bool:
        with self._connect() as conn:
            conn.execute("DELETE FROM memory_chunks WHERE memory_id = ?", (memory_id,))
            cursor = conn.execute("DELETE FROM memory_items WHERE id = ?", (memory_id,))
        return cursor.rowcount > 0

    def search(self, query: str, limit: int = 6) -> list[MemorySearchResult]:
        query_tokens = _tokens(query)
        if not query_tokens:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    memory_chunks.*,
                    memory_items.title,
                    memory_items.transcript,
                    memory_items.safe_content,
                    memory_items.privacy_report_json,
                    memory_items.summary,
                    memory_items.tasks_json,
                    memory_items.decisions_json,
                    memory_items.risks_json,
                    memory_items.source,
                    memory_items.created_at AS item_created_at,
                    memory_items.updated_at
                FROM memory_chunks
                JOIN memory_items ON memory_items.id = memory_chunks.memory_id
                ORDER BY memory_items.created_at DESC, memory_chunks.chunk_index ASC
                """
            ).fetchall()

        scored: list[MemorySearchResult] = []
        for row in rows:
            haystack = " ".join([str(row["title"]), str(row["text"]), str(row["safe_text"])])
            tasks = list(json.loads(str(row["tasks_json"])))
            decisions = list(json.loads(str(row["decisions_json"])))
            risks = list(json.loads(str(row["risks_json"])))
            artifact_terms: list[str] = []
            if tasks:
                artifact_terms.extend(["tarea", "tareas", "accion", "acciones", "pendiente", "responsable"])
            if decisions:
                artifact_terms.extend(["decision", "decisiones", "acuerdo", "acuerdos", "aprobado"])
            if risks:
                artifact_terms.extend(["riesgo", "riesgos", "bloqueo", "incidente", "critico", "critico"])
            haystack = " ".join(
                [
                    haystack,
                    str(row["summary"]),
                    " ".join(tasks),
                    " ".join(decisions),
                    " ".join(risks),
                    " ".join(artifact_terms),
                ]
            )
            haystack_tokens = _tokens(haystack)
            overlap = query_tokens & haystack_tokens
            phrase_bonus = 2.0 if query.lower() in haystack.lower() else 0.0
            score = len(overlap) + phrase_bonus
            if score <= 0:
                continue
            item = MemoryItem(
                id=str(row["memory_id"]),
                title=str(row["title"]),
                transcript=str(row["transcript"]),
                safe_content=str(row["safe_content"]),
                privacy_report=json.loads(str(row["privacy_report_json"])),
                summary=str(row["summary"]),
                tasks=tasks,
                decisions=decisions,
                risks=risks,
                source=str(row["source"]),
                created_at=str(row["item_created_at"]),
                updated_at=str(row["updated_at"]),
            )
            chunk = MemoryChunk(
                id=str(row["id"]),
                memory_id=str(row["memory_id"]),
                chunk_index=int(row["chunk_index"]),
                text=str(row["text"]),
                safe_text=str(row["safe_text"]),
                created_at=str(row["created_at"]),
            )
            scored.append(MemorySearchResult(item=item, chunk=chunk, score=score))
        return sorted(scored, key=lambda result: result.score, reverse=True)[:limit]

    def counts(self) -> dict[str, int]:
        with self._connect() as conn:
            item_count = conn.execute("SELECT COUNT(*) AS count FROM memory_items").fetchone()["count"]
            chunk_count = conn.execute("SELECT COUNT(*) AS count FROM memory_chunks").fetchone()["count"]
        return {"items": int(item_count), "chunks": int(chunk_count)}

    @staticmethod
    def _item_from_row(row: sqlite3.Row) -> MemoryItem:
        return MemoryItem(
            id=str(row["id"]),
            title=str(row["title"]),
            transcript=str(row["transcript"]),
            safe_content=str(row["safe_content"]),
            privacy_report=json.loads(str(row["privacy_report_json"])),
            summary=str(row["summary"]),
            tasks=list(json.loads(str(row["tasks_json"]))),
            decisions=list(json.loads(str(row["decisions_json"]))),
            risks=list(json.loads(str(row["risks_json"]))),
            source=str(row["source"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )


def _tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for raw_token in TOKEN_PATTERN.findall(_normalize(text)):
        token = raw_token.lower()
        tokens.add(token)
        for suffix in ("es", "s"):
            if len(token) > 5 and token.endswith(suffix):
                tokens.add(token[: -len(suffix)])
    return tokens


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(char for char in normalized if not unicodedata.combining(char))
