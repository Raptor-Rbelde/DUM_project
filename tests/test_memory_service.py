from __future__ import annotations

from sentinel.audit.store import AuditStore
from sentinel.config.settings import Settings
from sentinel.domain.privacy import SystemMode
from sentinel.memory.service import MemoryService
from sentinel.memory.store import PersistentMemoryStore
from sentinel.privacy.engine import PrivacyEngine
from sentinel.privacy.vault import EntityVault
from sentinel.providers.cloud_gateway import CloudGateway


class SpyProvider:
    name = "spy"

    def __init__(self) -> None:
        self.last_prompt: str | None = None
        self.last_purpose: str | None = None

    def analyze(self, prompt: str, *, purpose: str) -> str:
        self.last_prompt = prompt
        self.last_purpose = purpose
        return "Answer from safe enterprise memory."


def make_memory_service(tmp_path):
    db_path = tmp_path / "sentinel.sqlite"
    audit_store = AuditStore(db_path)
    vault = EntityVault(db_path)
    engine = PrivacyEngine(vault=vault, audit_store=audit_store)
    memory_store = PersistentMemoryStore(db_path)
    return MemoryService(memory_store, engine, audit_store), engine, audit_store


def test_memory_remembers_transcript_and_returns_local_reconstructed_sources(tmp_path) -> None:
    service, _, _ = make_memory_service(tmp_path)

    remembered = service.remember_transcript(
        title="Launch review",
        transcript="Carlos Hernandez approved the launch plan. Email finance@example.com after the call.",
    )
    sources = service.search("Carlos launch", limit=3)

    assert remembered.chunk_count >= 1
    assert "[PERSON_" in remembered.analysis.safe_content
    assert remembered.analysis.safe_content.count("Carlos Hernandez") == 0
    assert service.counts()["items"] == 1
    assert sources
    assert "Carlos Hernandez" in sources[0].snippet
    assert "Carlos Hernandez" not in sources[0].safe_snippet


def test_memory_intelligence_sends_only_safe_context_to_provider(tmp_path) -> None:
    service, _, audit_store = make_memory_service(tmp_path)
    provider = SpyProvider()
    settings = Settings(data_dir=tmp_path, db_path=tmp_path / "sentinel.sqlite", external_ai_enabled=True, openai_api_key="demo")
    gateway = CloudGateway(settings=settings, audit_store=audit_store, provider=provider)

    service.remember_transcript(
        title="Launch review",
        transcript="Carlos Hernandez approved the launch plan. Email finance@example.com after the call.",
    )
    answer = service.ask(
        question="Que aprobo Carlos?",
        mode=SystemMode.INTELLIGENCE,
        cloud_gateway=gateway,
    )

    assert answer.external_ai is not None
    assert answer.external_ai.sent is True
    assert provider.last_prompt is not None
    assert provider.last_purpose is not None
    assert "Carlos Hernandez" not in provider.last_prompt
    assert "Carlos" not in provider.last_purpose
    assert "finance@example.com" not in provider.last_prompt
    assert "[PERSON_" in provider.last_prompt
    assert "[PERSON_" in provider.last_purpose


def test_memory_question_uses_placeholder_from_retrieved_source(tmp_path) -> None:
    service, _, _ = make_memory_service(tmp_path)

    service.remember_transcript(
        title="Launch review",
        transcript="Carlos Hernandez approved the launch plan.",
    )
    answer = service.ask(question="Que aprobo Carlos?", mode=SystemMode.VAULT)
    source_placeholder = answer.sources[0].safe_snippet.split("]")[0] + "]"

    assert source_placeholder in answer.safe_context
    assert f"Que aprobo {source_placeholder}" in answer.safe_context


def test_memory_dashboard_items_include_business_artifacts(tmp_path) -> None:
    service, _, _ = make_memory_service(tmp_path)

    remembered = service.remember_transcript(
        title="Incident review",
        transcript=(
            "Decision: rotate demo credentials today. "
            "Carlos Hernandez debe revisar el despliegue. "
            "Riesgo critico: OPENAI_API_KEY=sk-example-not-real-123456789 fue expuesta."
        ),
    )
    items = service.list_items()
    answer = service.ask(question="Cuales son las decisiones tareas y riesgos?", mode=SystemMode.VAULT)

    assert items
    assert items[0].memory_id == remembered.memory_id
    assert items[0].summary
    assert items[0].tasks
    assert items[0].decisions
    assert items[0].risks
    assert "Decisiones:" in answer.answer
    assert "Tareas:" in answer.answer
    assert "Riesgos:" in answer.answer
    assert "sk-example" not in answer.answer


def test_memory_item_can_be_deleted(tmp_path) -> None:
    service, _, _ = make_memory_service(tmp_path)
    remembered = service.remember_transcript(title="Delete me", transcript="A plain memory entry.")

    assert service.delete_item(remembered.memory_id) is True
    assert service.get_item(remembered.memory_id) is None
    assert service.counts()["items"] == 0


def test_memory_corrects_false_premise_about_freezing_treasury_account(tmp_path) -> None:
    service, _, _ = make_memory_service(tmp_path)
    transcript = (
        "Valeria Gomez: Tenemos una brecha financiera de nivel 1. "
        "Una actualizacion anoche expuso datos de enrutamiento de la cuenta maestra de tesoreria. "
        "Tomas R.: Voy a llamar al banco inmediatamente para que congelen la cuenta corporativa principal "
        "y asi evitar que drenen los fondos. "
        "Valeria Gomez: Detente ahi, Tomas. Bajo ninguna circunstancia congeles la cuenta corporativa principal. "
        "Si bloqueas esa cuenta, la nomina de toda la empresa que esta programada para salir al mediodia va a rebotar. "
        "Lo que vas a hacer es entrar al portal del banco y deshabilitar exclusivamente las transferencias salientes internacionales. "
        "Luego, entra al dashboard de Stripe y revoca la llave que empieza con sk_live_51Mxyz."
    )

    service.remember_transcript(title="Fuga de Datos de Tesoreria", transcript=transcript)
    answer = service.ask(
        question=(
            "Para proteger los fondos de la empresa de manera inmediata, "
            "por que Valeria dio la orden de congelar la cuenta corporativa principal en el banco?"
        ),
        mode=SystemMode.VAULT,
    )

    assert "no dio la orden" in answer.answer.lower()
    assert "evidencia: bajo ninguna circunstancia" in answer.answer.lower()
    assert "deshabilitar" in answer.answer.lower()
    assert "transferencias" in answer.answer.lower()
    assert "not in memory" not in answer.answer.lower()
    assert "no encontre" not in answer.answer.lower()
    assert "contradict" in answer.safe_context.lower() or "contradice" in answer.safe_context.lower()
