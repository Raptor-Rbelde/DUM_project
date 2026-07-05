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


def test_memory_intelligence_sends_structured_artifacts_to_provider(tmp_path) -> None:
    service, _, audit_store = make_memory_service(tmp_path)
    provider = SpyProvider()
    settings = Settings(data_dir=tmp_path, db_path=tmp_path / "sentinel.sqlite", external_ai_enabled=True, openai_api_key="demo")
    gateway = CloudGateway(settings=settings, audit_store=audit_store, provider=provider)

    service.remember_transcript(
        title="Security tasks",
        transcript="SecOps debe revocar credenciales comprometidas. Riesgo critico: token expuesto.",
    )
    answer = service.ask(
        question="Que tareas y riesgos aparecen en la memoria?",
        mode=SystemMode.INTELLIGENCE,
        cloud_gateway=gateway,
    )

    assert answer.external_ai is not None
    assert answer.external_ai.sent is True
    assert provider.last_prompt is not None
    assert provider.last_purpose is not None
    assert "Tasks in snippet:" in provider.last_prompt
    assert "Risks in snippet:" in provider.last_prompt
    assert "credenciales comprometidas" not in provider.last_prompt
    assert answer.answer == "Answer from safe enterprise memory."


def test_memory_safe_context_aggregates_tasks_before_source_details(tmp_path) -> None:
    service, _, audit_store = make_memory_service(tmp_path)
    provider = SpyProvider()
    settings = Settings(data_dir=tmp_path, db_path=tmp_path / "sentinel.sqlite", external_ai_enabled=True, openai_api_key="demo")
    gateway = CloudGateway(settings=settings, audit_store=audit_store, provider=provider)

    service.remember_transcript(
        title="Debt remediation",
        transcript=(
            "Ismael C.: Bajo ningun motivo ejecutaremos un borrado masivo de comentarios TODO en produccion. "
            "Necesitamos una lista de tareas operativa segmentada por areas. "
            "TODO para el Departamento de Seguridad (Ticket #SEC-8801): Natalia debe revocar el acceso filtrado en IAM. "
            "TODO para el Departamento de Ingenieria (Ticket #ENG-5504): El equipo debe reactivar SSL."
        ),
    )
    answer = service.ask(
        question="Que decisiones, tareas o riesgos aparecen en la memoria?",
        mode=SystemMode.INTELLIGENCE,
        cloud_gateway=gateway,
    )

    assert answer.external_ai is not None
    assert answer.external_ai.sent is True
    assert provider.last_prompt is not None
    aggregate_index = provider.last_prompt.index("Aggregate structured memory facts")
    sources_index = provider.last_prompt.index("Relevant safe memory records")
    assert aggregate_index < sources_index
    assert "Consistency rule" in provider.last_prompt
    assert "Task Segments: Seguridad / SecOps" in provider.last_prompt
    assert "Task Segments: None" not in provider.last_prompt[aggregate_index:sources_index]


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
    assert items[0].areas
    assert items[0].task_segments
    assert "Decisiones:" in answer.answer
    assert "Tareas:" in answer.answer
    assert "Riesgos:" in answer.answer
    assert "sk-example" not in answer.answer


def test_memory_segments_tasks_by_enterprise_area_and_role(tmp_path) -> None:
    service, _, _ = make_memory_service(tmp_path)

    remembered = service.remember_transcript(
        title="Cross-functional incident",
        transcript=(
            "Recursos Humanos debe preparar la comunicacion a empleados sobre nomina. "
            "SecOps debe revocar credenciales comprometidas y rotar tokens. "
            "TI debe migrar el servidor y actualizar Docker."
        ),
    )
    item = service.list_items()[0]
    answer = service.ask(question="Segmenta las tareas por area y rol", mode=SystemMode.VAULT)

    area_names = {area.area for area in remembered.areas}
    task_roles = {segment.role for segment in item.task_segments}

    assert "Recursos Humanos" in area_names
    assert "Seguridad" in area_names
    assert "Tecnologia / TI" in area_names
    assert "People / RRHH" in task_roles
    assert "Seguridad / SecOps" in task_roles
    assert "TI / Infraestructura" in task_roles
    assert "Tareas por rol:" in answer.answer


def test_memory_ignores_meta_ticket_assignment_as_operational_task(tmp_path) -> None:
    service, _, _ = make_memory_service(tmp_path)

    remembered = service.remember_transcript(
        title="Debt review",
        transcript=(
            "Hay un comentario que dice: // TODO: Eliminar antes de prod - "
            "Password maestro de contingencia: T3mp_Adm1n_99!. "
            "Asigna esta tarea al ticket #HR-COMP-012."
        ),
    )
    answer = service.ask(question="Que decisiones, tareas o riesgos aparecen en la memoria?", mode=SystemMode.VAULT)

    assert remembered.tasks == []
    assert remembered.task_segments == []
    assert "Tareas:" not in answer.answer
    assert "Asigna esta tarea" not in answer.answer
    assert all(not source.task_segments for source in answer.sources)


def test_memory_extracts_operational_todo_assignments(tmp_path) -> None:
    service, _, _ = make_memory_service(tmp_path)

    remembered = service.remember_transcript(
        title="TODO plan",
        transcript=(
            "TODO para el Departamento de Seguridad (Ticket #SEC-8801): "
            "Natalia debe revocar inmediatamente el acceso filtrado en IAM."
        ),
    )

    assert any("revocar" in task.lower() for task in remembered.tasks)
    assert any(segment.area == "Seguridad" for segment in remembered.task_segments)


def test_memory_segments_safe_todos_with_reconstructed_ticket_context(tmp_path) -> None:
    service, _, _ = make_memory_service(tmp_path)

    remembered = service.remember_transcript(
        title="Multi area TODO plan",
        transcript=(
            "TODO para el Departamento de Ingenieria (Ticket #ENG-5504): "
            "Mi equipo debe reactivar SSL y eliminar credenciales estaticas. "
            "TODO para el Departamento de Cumplimiento (Ticket #CMP-1109): "
            "Tu TODO asignado es redactar el reporte para los auditores."
        ),
    )

    areas = {segment.area for segment in remembered.task_segments}

    assert "Producto e Ingenieria" in areas
    assert "Legal y Cumplimiento" in areas


def test_memory_ignores_cancelled_todos_when_new_todo_replaces_them(tmp_path) -> None:
    service, _, _ = make_memory_service(tmp_path)

    remembered = service.remember_transcript(
        title="VPN correction",
        transcript=(
            "Marcos T., en tu TO DO list inicial tenias programado forzar un reseteo masivo de las contrasenas. "
            "Tacha eso de tu TO DO list. "
            "Tu nuevo TO DO es habilitar MFA obligatorio sin desconectar sesiones activas."
        ),
    )

    assert all("reseteo masivo" not in task.lower() for task in remembered.tasks)
    assert all("tacha eso" not in task.lower() for task in remembered.tasks)
    assert any("habilitar mfa" in task.lower() for task in remembered.tasks)


def test_memory_ignores_todo_inventory_and_negative_task_description(tmp_path) -> None:
    service, _, _ = make_memory_service(tmp_path)

    remembered = service.remember_transcript(
        title="TODO cleanup",
        transcript=(
            "Tengo identificados tres TODO criticos. "
            "TODO para el Departamento de Cumplimiento (Ticket #CMP-1109): Raul, tu tarea no es tecnica. "
            "Tu TODO asignado es redactar el reporte para los auditores."
        ),
    )

    assert all("tengo identificados" not in task.lower() for task in remembered.tasks)
    assert all("no es tecnica" not in task.lower() for task in remembered.tasks)
    assert any("redactar el reporte" in task.lower() for task in remembered.tasks)
    assert len(remembered.task_segments) == 1


def test_memory_source_artifacts_are_scoped_to_retrieved_snippet(tmp_path) -> None:
    service, _, _ = make_memory_service(tmp_path)

    service.remember_transcript(
        title="Security follow up",
        transcript=(
            f"Riesgo critico: hay un password hardcodeado en el archivo de autenticacion. {'Contexto tecnico. ' * 75}\n\n"
            "SecOps debe rotar credenciales comprometidas y abrir evidencia forense."
        ),
    )
    source = service.search("password hardcodeado riesgo", limit=1)[0]

    assert "password hardcodeado" in source.snippet.lower()
    assert source.risks
    assert source.tasks == []
    assert source.task_segments == []


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
