from __future__ import annotations

import sqlite3

from sentinel.audit.store import AuditStore
from sentinel.config.settings import Settings
from sentinel.db.schema import database_status, initialize_database
from sentinel.memory.service import MemoryService
from sentinel.memory.store import PersistentMemoryStore
from sentinel.memory.vectorizer import LOCAL_VECTOR_DIMENSIONS, LOCAL_VECTOR_MODEL
from sentinel.privacy.engine import PrivacyEngine
from sentinel.privacy.vault import EntityVault


def make_memory_service(tmp_path):
    db_path = tmp_path / "sentinel.sqlite"
    audit_store = AuditStore(db_path)
    vault = EntityVault(db_path)
    engine = PrivacyEngine(vault=vault, audit_store=audit_store)
    memory_store = PersistentMemoryStore(db_path)
    return MemoryService(memory_store, engine, audit_store), db_path


def test_database_status_reports_vector_engine(tmp_path) -> None:
    db_path = tmp_path / "sentinel.sqlite"

    initialize_database(db_path)
    status = database_status(db_path)

    assert status["engine"] == "sqlite-vector"
    assert "memory_embeddings" in status["tables"]
    assert "memory_entities" in status["tables"]
    assert "memory_questions" in status["tables"]


def test_memory_persists_vector_embeddings_for_chunks(tmp_path) -> None:
    service, db_path = make_memory_service(tmp_path)

    remembered = service.remember_transcript(
        title="Payroll incident",
        transcript="La nomina de toda la empresa estaba programada para salir al mediodia.",
    )
    counts = service.counts()

    assert counts["chunks"] == remembered.chunk_count
    assert counts["embeddings"] == remembered.chunk_count
    assert counts["vector_dimensions"] == LOCAL_VECTOR_DIMENSIONS

    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT model, dimensions FROM memory_embeddings LIMIT 1").fetchone()

    assert row[0] == LOCAL_VECTOR_MODEL
    assert row[1] == LOCAL_VECTOR_DIMENSIONS


def test_vector_search_finds_semantically_related_memory_without_exact_keyword_overlap(tmp_path) -> None:
    service, _ = make_memory_service(tmp_path)

    service.remember_transcript(
        title="Treasury controls",
        transcript=(
            "Valeria explico que la nomina de toda la empresa estaba programada para salir al mediodia. "
            "La accion correcta era deshabilitar transferencias internacionales salientes."
        ),
    )

    sources = service.search("pago de empleados", limit=3)

    assert sources
    assert "nomina" in sources[0].snippet.lower()
