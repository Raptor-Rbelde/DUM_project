from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from sentinel.db.schema import connect_database, initialize_database
from sentinel.domain.meetings import utc_now
from sentinel.memory.vectorizer import (
    LOCAL_VECTOR_DIMENSIONS,
    LOCAL_VECTOR_MODEL,
    cosine_similarity,
    embed_text,
    vector_from_json,
    vector_to_json,
)


TOKEN_PATTERN = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9_/-]{3,}")
VECTOR_MATCH_THRESHOLD = 0.13


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
    areas: list[dict[str, Any]]
    task_segments: list[dict[str, Any]]
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

    def _connect(self):
        return connect_database(self.db_path)

    def _init_db(self) -> None:
        initialize_database(self.db_path)

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
        areas: list[dict[str, Any]] | None = None,
        task_segments: list[dict[str, Any]] | None = None,
    ) -> MemoryItem:
        now = utc_now()
        safe_areas = areas or []
        safe_task_segments = task_segments or []
        with self._connect() as conn:
            existing = conn.execute("SELECT created_at FROM memory_items WHERE id = ?", (memory_id,)).fetchone()
            created_at = str(existing["created_at"]) if existing else now
            conn.execute(
                """
                INSERT INTO memory_items (
                    id, title, transcript, safe_content, privacy_report_json,
                    summary, tasks_json, decisions_json, risks_json, areas_json,
                    task_segments_json,
                    source, content_hash, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    transcript = excluded.transcript,
                    safe_content = excluded.safe_content,
                    privacy_report_json = excluded.privacy_report_json,
                    summary = excluded.summary,
                    tasks_json = excluded.tasks_json,
                    decisions_json = excluded.decisions_json,
                    risks_json = excluded.risks_json,
                    areas_json = excluded.areas_json,
                    task_segments_json = excluded.task_segments_json,
                    source = excluded.source,
                    content_hash = excluded.content_hash,
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
                    json.dumps(safe_areas, sort_keys=True),
                    json.dumps(safe_task_segments, sort_keys=True),
                    source,
                    _hash_text(transcript),
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
            safe_areas,
            safe_task_segments,
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
                    INSERT INTO memory_chunks (
                        id, memory_id, chunk_index, text, safe_text,
                        token_count, content_hash, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk.id,
                        chunk.memory_id,
                        chunk.chunk_index,
                        chunk.text,
                        chunk.safe_text,
                        len(_tokens(chunk.safe_text or chunk.text)),
                        _hash_text(chunk.text),
                        chunk.created_at,
                    ),
                )
                self._upsert_embedding(conn, chunk.id, chunk.safe_text or chunk.text, now)
                saved.append(chunk)
        return saved

    def backfill_missing_embeddings(self) -> int:
        now = utc_now()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT memory_chunks.id, memory_chunks.safe_text, memory_chunks.text, memory_embeddings.source_text_hash
                FROM memory_chunks
                LEFT JOIN memory_embeddings
                    ON memory_embeddings.chunk_id = memory_chunks.id
                    AND memory_embeddings.model = ?
                WHERE memory_embeddings.chunk_id IS NULL
                    OR memory_embeddings.source_text_hash IS NULL
                """,
                (LOCAL_VECTOR_MODEL,),
            ).fetchall()
            for row in rows:
                self._upsert_embedding(conn, str(row["id"]), str(row["safe_text"] or row["text"]), now)
        return len(rows)

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
            conn.execute(
                """
                DELETE FROM memory_embeddings
                WHERE chunk_id IN (SELECT id FROM memory_chunks WHERE memory_id = ?)
                """,
                (memory_id,),
            )
            conn.execute("DELETE FROM memory_chunks WHERE memory_id = ?", (memory_id,))
            cursor = conn.execute("DELETE FROM memory_items WHERE id = ?", (memory_id,))
        return cursor.rowcount > 0

    def search(self, query: str, limit: int = 6) -> list[MemorySearchResult]:
        query_tokens = _tokens(query)
        query_vector = embed_text(query)
        if not query_tokens and not any(query_vector):
            return []

        self.backfill_missing_embeddings()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    memory_chunks.*,
                    memory_embeddings.vector_json,
                    memory_items.title,
                    memory_items.transcript,
                    memory_items.safe_content,
                    memory_items.privacy_report_json,
                    memory_items.summary,
                    memory_items.tasks_json,
                    memory_items.decisions_json,
                    memory_items.risks_json,
                    memory_items.areas_json,
                    memory_items.task_segments_json,
                    memory_items.source,
                    memory_items.created_at AS item_created_at,
                    memory_items.updated_at
                FROM memory_chunks
                JOIN memory_items ON memory_items.id = memory_chunks.memory_id
                LEFT JOIN memory_embeddings
                    ON memory_embeddings.chunk_id = memory_chunks.id
                    AND memory_embeddings.model = ?
                ORDER BY memory_items.created_at DESC, memory_chunks.chunk_index ASC
                """,
                (LOCAL_VECTOR_MODEL,),
            ).fetchall()

        scored: list[MemorySearchResult] = []
        for row in rows:
            tasks = list(json.loads(str(row["tasks_json"])))
            decisions = list(json.loads(str(row["decisions_json"])))
            risks = list(json.loads(str(row["risks_json"])))
            areas = _json_list(str(row["areas_json"]))
            task_segments = _json_list(str(row["task_segments_json"]))
            haystack = _search_haystack(
                row,
                tasks=tasks,
                decisions=decisions,
                risks=risks,
                areas=areas,
                task_segments=task_segments,
            )
            lexical_score = _lexical_score(query, query_tokens, haystack)
            vector_score = cosine_similarity(query_vector, vector_from_json(str(row["vector_json"] or "[]")))
            score = (0.45 * lexical_score) + (0.55 * max(vector_score, 0.0))
            if lexical_score <= 0 and vector_score < VECTOR_MATCH_THRESHOLD:
                continue
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
                areas=areas,
                task_segments=task_segments,
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
            scored.append(MemorySearchResult(item=item, chunk=chunk, score=round(score, 4)))
        return sorted(scored, key=lambda result: result.score, reverse=True)[:limit]

    def counts(self) -> dict[str, int]:
        self.backfill_missing_embeddings()
        with self._connect() as conn:
            item_count = conn.execute("SELECT COUNT(*) AS count FROM memory_items").fetchone()["count"]
            chunk_count = conn.execute("SELECT COUNT(*) AS count FROM memory_chunks").fetchone()["count"]
            embedding_count = conn.execute(
                "SELECT COUNT(*) AS count FROM memory_embeddings WHERE model = ?",
                (LOCAL_VECTOR_MODEL,),
            ).fetchone()["count"]
        return {
            "items": int(item_count),
            "chunks": int(chunk_count),
            "embeddings": int(embedding_count),
            "vector_dimensions": LOCAL_VECTOR_DIMENSIONS,
        }

    def _upsert_embedding(self, conn, chunk_id: str, text: str, created_at: str) -> None:
        source_hash = _hash_text(text)
        vector = embed_text(text)
        conn.execute(
            """
            INSERT INTO memory_embeddings (
                chunk_id, model, vector_json, dimensions, source_text_hash, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(chunk_id, model) DO UPDATE SET
                vector_json = excluded.vector_json,
                dimensions = excluded.dimensions,
                source_text_hash = excluded.source_text_hash,
                created_at = excluded.created_at
            """,
            (chunk_id, LOCAL_VECTOR_MODEL, vector_to_json(vector), LOCAL_VECTOR_DIMENSIONS, source_hash, created_at),
        )

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
            areas=_json_list(str(row["areas_json"])),
            task_segments=_json_list(str(row["task_segments_json"])),
            source=str(row["source"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )


def _search_haystack(
    row,
    *,
    tasks: list[str],
    decisions: list[str],
    risks: list[str],
    areas: list[dict[str, Any]],
    task_segments: list[dict[str, Any]],
) -> str:
    artifact_terms: list[str] = []
    if tasks:
        artifact_terms.extend(["tarea", "tareas", "accion", "acciones", "pendiente", "responsable"])
    if decisions:
        artifact_terms.extend(["decision", "decisiones", "acuerdo", "acuerdos", "aprobado"])
    if risks:
        artifact_terms.extend(["riesgo", "riesgos", "bloqueo", "incidente", "critico", "crítico"])
    return " ".join(
        [
            str(row["title"]),
            str(row["text"]),
            str(row["safe_text"]),
            str(row["summary"]),
            " ".join(tasks),
            " ".join(decisions),
            " ".join(risks),
            " ".join(str(area.get("area", "")) for area in areas if isinstance(area, dict)),
            " ".join(
                " ".join([str(segment.get("area", "")), str(segment.get("role", "")), str(segment.get("description", ""))])
                for segment in task_segments
                if isinstance(segment, dict)
            ),
            " ".join(artifact_terms),
        ]
    )


def _json_list(raw: str) -> list[dict[str, Any]]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _lexical_score(query: str, query_tokens: set[str], haystack: str) -> float:
    haystack_tokens = _tokens(haystack)
    if not query_tokens:
        return 0.0
    overlap = query_tokens & haystack_tokens
    base = len(overlap) / max(len(query_tokens), 1)
    phrase_bonus = 0.2 if _normalize(query).lower() in _normalize(haystack).lower() else 0.0
    return min(base + phrase_bonus, 1.0)


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


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
