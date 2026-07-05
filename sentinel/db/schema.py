from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


CORE_TABLES = (
    "schema_migrations",
    "audit_events",
    "entity_vault",
    "meetings",
    "privacy_reports",
    "meeting_summaries",
    "meeting_tasks",
    "meeting_decisions",
    "memory_items",
    "memory_chunks",
    "memory_entities",
    "memory_artifacts",
    "memory_questions",
    "memory_question_sources",
    "memory_tags",
    "memory_links",
    "memory_embeddings",
)


def connect_database(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_database(db_path: str | Path) -> None:
    with connect_database(db_path) as conn:
        _configure_database(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        _apply_migration(conn, 1, "core_vector_memory_schema", _create_core_schema)
        _ensure_memory_columns(conn)
        _ensure_enterprise_memory_tables(conn)
        _ensure_embedding_columns(conn)
        _ensure_indexes(conn)


def database_status(db_path: str | Path) -> dict[str, Any]:
    initialize_database(db_path)
    with connect_database(db_path) as conn:
        current_version = conn.execute("SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations").fetchone()
        tables = [
            str(row["name"])
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            ).fetchall()
        ]
        counts: dict[str, int] = {}
        for table in CORE_TABLES:
            if table in tables:
                counts[table] = int(conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])
    return {
        "engine": "sqlite-vector",
        "schema_version": int(current_version["version"] if current_version else 0),
        "tables": tables,
        "counts": counts,
    }


def _configure_database(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")


def _apply_migration(conn: sqlite3.Connection, version: int, name: str, migration) -> None:
    existing = conn.execute("SELECT 1 FROM schema_migrations WHERE version = ?", (version,)).fetchone()
    if existing:
        return
    migration(conn)
    conn.execute("INSERT INTO schema_migrations (version, name) VALUES (?, ?)", (version, name))


def _create_core_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            event_type TEXT NOT NULL,
            session_id TEXT,
            policy_decision TEXT,
            number_of_entities INTEGER,
            number_blocked INTEGER,
            number_pseudonymized INTEGER,
            provider TEXT,
            payload_fingerprint TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS entity_vault (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            original_value TEXT NOT NULL,
            placeholder TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(session_id, entity_type, original_value)
        );

        CREATE TABLE IF NOT EXISTS meetings (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            transcript TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS privacy_reports (
            meeting_id TEXT PRIMARY KEY,
            report_json TEXT NOT NULL,
            safe_content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS meeting_tasks (
            id TEXT PRIMARY KEY,
            meeting_id TEXT NOT NULL,
            description TEXT NOT NULL,
            owner TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS meeting_decisions (
            id TEXT PRIMARY KEY,
            meeting_id TEXT NOT NULL,
            description TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS meeting_summaries (
            meeting_id TEXT PRIMARY KEY,
            summary TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
        );

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
            record_type TEXT NOT NULL DEFAULT 'transcript',
            content_hash TEXT,
            retention_state TEXT NOT NULL DEFAULT 'active',
            deleted_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS memory_chunks (
            id TEXT PRIMARY KEY,
            memory_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            text TEXT NOT NULL,
            safe_text TEXT NOT NULL,
            token_count INTEGER NOT NULL DEFAULT 0,
            content_hash TEXT,
            start_char INTEGER,
            end_char INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY(memory_id) REFERENCES memory_items(id) ON DELETE CASCADE,
            UNIQUE(memory_id, chunk_index)
        );

        CREATE TABLE IF NOT EXISTS memory_entities (
            id TEXT PRIMARY KEY,
            memory_id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            action TEXT NOT NULL,
            sensitivity TEXT NOT NULL,
            placeholder TEXT,
            confidence REAL NOT NULL,
            start_char INTEGER NOT NULL,
            end_char INTEGER NOT NULL,
            original_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(memory_id) REFERENCES memory_items(id) ON DELETE CASCADE,
            UNIQUE(memory_id, entity_type, original_hash, start_char, end_char)
        );

        CREATE TABLE IF NOT EXISTS memory_artifacts (
            id TEXT PRIMARY KEY,
            memory_id TEXT NOT NULL,
            artifact_type TEXT NOT NULL,
            content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            owner TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            source TEXT NOT NULL DEFAULT 'local_extractor',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(memory_id) REFERENCES memory_items(id) ON DELETE CASCADE,
            UNIQUE(memory_id, artifact_type, content_hash)
        );

        CREATE TABLE IF NOT EXISTS memory_questions (
            id TEXT PRIMARY KEY,
            question TEXT NOT NULL,
            safe_question TEXT NOT NULL,
            answer TEXT NOT NULL,
            mode TEXT NOT NULL,
            source_count INTEGER NOT NULL,
            external_sent INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS memory_question_sources (
            question_id TEXT NOT NULL,
            memory_id TEXT NOT NULL,
            chunk_id TEXT NOT NULL,
            rank INTEGER NOT NULL,
            score REAL NOT NULL,
            PRIMARY KEY(question_id, rank),
            FOREIGN KEY(question_id) REFERENCES memory_questions(id) ON DELETE CASCADE,
            FOREIGN KEY(memory_id) REFERENCES memory_items(id) ON DELETE CASCADE,
            FOREIGN KEY(chunk_id) REFERENCES memory_chunks(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS memory_tags (
            memory_id TEXT NOT NULL,
            tag TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(memory_id, tag),
            FOREIGN KEY(memory_id) REFERENCES memory_items(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS memory_links (
            id TEXT PRIMARY KEY,
            source_memory_id TEXT NOT NULL,
            target_memory_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            evidence TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY(source_memory_id) REFERENCES memory_items(id) ON DELETE CASCADE,
            FOREIGN KEY(target_memory_id) REFERENCES memory_items(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS memory_embeddings (
            chunk_id TEXT NOT NULL,
            model TEXT NOT NULL,
            vector_json TEXT NOT NULL,
            dimensions INTEGER NOT NULL,
            source_text_hash TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY(chunk_id, model),
            FOREIGN KEY(chunk_id) REFERENCES memory_chunks(id) ON DELETE CASCADE
        );
        """
    )


def _ensure_memory_columns(conn: sqlite3.Connection) -> None:
    item_columns = {row["name"] for row in conn.execute("PRAGMA table_info(memory_items)").fetchall()}
    item_migrations = {
        "summary": "ALTER TABLE memory_items ADD COLUMN summary TEXT NOT NULL DEFAULT ''",
        "tasks_json": "ALTER TABLE memory_items ADD COLUMN tasks_json TEXT NOT NULL DEFAULT '[]'",
        "decisions_json": "ALTER TABLE memory_items ADD COLUMN decisions_json TEXT NOT NULL DEFAULT '[]'",
        "risks_json": "ALTER TABLE memory_items ADD COLUMN risks_json TEXT NOT NULL DEFAULT '[]'",
        "record_type": "ALTER TABLE memory_items ADD COLUMN record_type TEXT NOT NULL DEFAULT 'transcript'",
        "content_hash": "ALTER TABLE memory_items ADD COLUMN content_hash TEXT",
        "retention_state": "ALTER TABLE memory_items ADD COLUMN retention_state TEXT NOT NULL DEFAULT 'active'",
        "deleted_at": "ALTER TABLE memory_items ADD COLUMN deleted_at TEXT",
    }
    for column, statement in item_migrations.items():
        if column not in item_columns:
            conn.execute(statement)

    chunk_columns = {row["name"] for row in conn.execute("PRAGMA table_info(memory_chunks)").fetchall()}
    chunk_migrations = {
        "token_count": "ALTER TABLE memory_chunks ADD COLUMN token_count INTEGER NOT NULL DEFAULT 0",
        "content_hash": "ALTER TABLE memory_chunks ADD COLUMN content_hash TEXT",
        "start_char": "ALTER TABLE memory_chunks ADD COLUMN start_char INTEGER",
        "end_char": "ALTER TABLE memory_chunks ADD COLUMN end_char INTEGER",
    }
    for column, statement in chunk_migrations.items():
        if column not in chunk_columns:
            conn.execute(statement)


def _ensure_embedding_columns(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_embeddings (
            chunk_id TEXT NOT NULL,
            model TEXT NOT NULL,
            vector_json TEXT NOT NULL,
            dimensions INTEGER NOT NULL,
            source_text_hash TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY(chunk_id, model),
            FOREIGN KEY(chunk_id) REFERENCES memory_chunks(id) ON DELETE CASCADE
        )
        """
    )
    embedding_columns = {row["name"] for row in conn.execute("PRAGMA table_info(memory_embeddings)").fetchall()}
    embedding_migrations = {
        "source_text_hash": "ALTER TABLE memory_embeddings ADD COLUMN source_text_hash TEXT",
    }
    for column, statement in embedding_migrations.items():
        if column not in embedding_columns:
            conn.execute(statement)


def _ensure_enterprise_memory_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS memory_entities (
            id TEXT PRIMARY KEY,
            memory_id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            action TEXT NOT NULL,
            sensitivity TEXT NOT NULL,
            placeholder TEXT,
            confidence REAL NOT NULL,
            start_char INTEGER NOT NULL,
            end_char INTEGER NOT NULL,
            original_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(memory_id) REFERENCES memory_items(id) ON DELETE CASCADE,
            UNIQUE(memory_id, entity_type, original_hash, start_char, end_char)
        );

        CREATE TABLE IF NOT EXISTS memory_artifacts (
            id TEXT PRIMARY KEY,
            memory_id TEXT NOT NULL,
            artifact_type TEXT NOT NULL,
            content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            owner TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            source TEXT NOT NULL DEFAULT 'local_extractor',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(memory_id) REFERENCES memory_items(id) ON DELETE CASCADE,
            UNIQUE(memory_id, artifact_type, content_hash)
        );

        CREATE TABLE IF NOT EXISTS memory_questions (
            id TEXT PRIMARY KEY,
            question TEXT NOT NULL,
            safe_question TEXT NOT NULL,
            answer TEXT NOT NULL,
            mode TEXT NOT NULL,
            source_count INTEGER NOT NULL,
            external_sent INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS memory_question_sources (
            question_id TEXT NOT NULL,
            memory_id TEXT NOT NULL,
            chunk_id TEXT NOT NULL,
            rank INTEGER NOT NULL,
            score REAL NOT NULL,
            PRIMARY KEY(question_id, rank),
            FOREIGN KEY(question_id) REFERENCES memory_questions(id) ON DELETE CASCADE,
            FOREIGN KEY(memory_id) REFERENCES memory_items(id) ON DELETE CASCADE,
            FOREIGN KEY(chunk_id) REFERENCES memory_chunks(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS memory_tags (
            memory_id TEXT NOT NULL,
            tag TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(memory_id, tag),
            FOREIGN KEY(memory_id) REFERENCES memory_items(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS memory_links (
            id TEXT PRIMARY KEY,
            source_memory_id TEXT NOT NULL,
            target_memory_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            evidence TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY(source_memory_id) REFERENCES memory_items(id) ON DELETE CASCADE,
            FOREIGN KEY(target_memory_id) REFERENCES memory_items(id) ON DELETE CASCADE
        );
        """
    )


def _ensure_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_audit_events_timestamp ON audit_events(timestamp);
        CREATE INDEX IF NOT EXISTS idx_audit_events_session_id ON audit_events(session_id);
        CREATE INDEX IF NOT EXISTS idx_audit_events_type ON audit_events(event_type);
        CREATE INDEX IF NOT EXISTS idx_entity_vault_session_id ON entity_vault(session_id);
        CREATE INDEX IF NOT EXISTS idx_entity_vault_type ON entity_vault(entity_type);
        CREATE INDEX IF NOT EXISTS idx_meetings_created_at ON meetings(created_at);
        CREATE INDEX IF NOT EXISTS idx_meeting_tasks_meeting_id ON meeting_tasks(meeting_id);
        CREATE INDEX IF NOT EXISTS idx_meeting_decisions_meeting_id ON meeting_decisions(meeting_id);
        CREATE INDEX IF NOT EXISTS idx_memory_items_created_at ON memory_items(created_at);
        CREATE INDEX IF NOT EXISTS idx_memory_items_source ON memory_items(source);
        CREATE INDEX IF NOT EXISTS idx_memory_items_retention_state ON memory_items(retention_state);
        CREATE INDEX IF NOT EXISTS idx_memory_chunks_memory_id ON memory_chunks(memory_id);
        CREATE INDEX IF NOT EXISTS idx_memory_chunks_index ON memory_chunks(memory_id, chunk_index);
        CREATE INDEX IF NOT EXISTS idx_memory_entities_memory_id ON memory_entities(memory_id);
        CREATE INDEX IF NOT EXISTS idx_memory_entities_type ON memory_entities(entity_type);
        CREATE INDEX IF NOT EXISTS idx_memory_entities_placeholder ON memory_entities(placeholder);
        CREATE INDEX IF NOT EXISTS idx_memory_artifacts_memory_id ON memory_artifacts(memory_id);
        CREATE INDEX IF NOT EXISTS idx_memory_artifacts_type ON memory_artifacts(artifact_type);
        CREATE INDEX IF NOT EXISTS idx_memory_artifacts_status ON memory_artifacts(status);
        CREATE INDEX IF NOT EXISTS idx_memory_questions_created_at ON memory_questions(created_at);
        CREATE INDEX IF NOT EXISTS idx_memory_questions_mode ON memory_questions(mode);
        CREATE INDEX IF NOT EXISTS idx_memory_question_sources_memory_id ON memory_question_sources(memory_id);
        CREATE INDEX IF NOT EXISTS idx_memory_question_sources_chunk_id ON memory_question_sources(chunk_id);
        CREATE INDEX IF NOT EXISTS idx_memory_tags_tag ON memory_tags(tag);
        CREATE INDEX IF NOT EXISTS idx_memory_links_source ON memory_links(source_memory_id);
        CREATE INDEX IF NOT EXISTS idx_memory_links_target ON memory_links(target_memory_id);
        CREATE INDEX IF NOT EXISTS idx_memory_links_relation ON memory_links(relation_type);
        CREATE INDEX IF NOT EXISTS idx_memory_embeddings_model ON memory_embeddings(model);
        """
    )
