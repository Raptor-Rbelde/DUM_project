from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from sentinel.memory.vectorizer import cosine_similarity, embed_text


@dataclass(frozen=True)
class AreaInsight:
    area: str
    score: float
    evidence: list[str]


@dataclass(frozen=True)
class TaskSegment:
    description: str
    area: str
    role: str
    confidence: float


AREA_PROFILES: dict[str, tuple[str, ...]] = {
    "Direccion Ejecutiva": (
        "direccion ejecutiva ceo junta directiva estrategia aprobacion decision liderazgo objetivo corporativo",
        "comite ejecutivo direccion general priorizacion presupuesto organizacion gobierno corporativo",
    ),
    "Recursos Humanos": (
        "recursos humanos rrhh hr people talento contratacion entrevistas onboarding nomina empleados salarios beneficios",
        "desempeno capacitacion cultura vacantes personal colaboradores vacaciones compensacion comp payroll",
    ),
    "Seguridad": (
        "seguridad secops incidente brecha amenaza vulnerabilidad credenciales revocar api key token password",
        "auditoria acceso permisos vault cifrado secreto monitoreo alerta respuesta forense phishing",
    ),
    "Tecnologia / TI": (
        "tecnologia ti infraestructura sistemas servidor red endpoint base datos cloud supabase postgres docker",
        "desarrollo backend frontend despliegue integraciones api repositorio github actions migracion ambiente",
    ),
    "Finanzas": (
        "finanzas tesoreria pagos presupuesto facturacion stripe banco cuenta swift transferencias fondos",
        "cfo contabilidad impuestos auditoria financiera ingresos egresos cobranza pci dss",
    ),
    "Legal y Cumplimiento": (
        "legal cumplimiento compliance regulatorio contrato licencia politica confidencialidad privacidad auditoria",
        "riesgo fiscal pci dss gdpr hipaa evidencia retencion investigacion autorizacion",
    ),
    "Ventas y Clientes": (
        "ventas cliente clientes cuenta comercial propuesta contrato crm oportunidad renovacion pipeline",
        "customer success relacion cliente banco agricola acme negociacion cotizacion",
    ),
    "Marketing": (
        "marketing campana marca lanzamiento contenido comunicacion prensa redes posicionamiento audiencia",
        "crecimiento demanda anuncio evento web publicacion copy",
    ),
    "Operaciones y Logistica": (
        "operaciones logistica proceso entrega inventario proveedores coordinacion planificacion zona fisica",
        "cadena suministro almacen rutas ejecucion turnos contingencia",
    ),
    "Producto e Ingenieria": (
        "producto ingenieria roadmap feature bug sprint backlog arquitectura release version qa calidad",
        "requerimientos usuario diseno tecnico implementacion pruebas codigo",
    ),
    "Datos y Analitica": (
        "datos analitica dashboard metricas reporte modelo machine learning ml entrenamiento embeddings",
        "pipeline dataset calidad datos inteligencia bi consulta sql",
    ),
    "Atencion al Cliente": (
        "soporte atencion cliente ticket queja reclamo caso sla mesa ayuda contacto satisfaccion",
        "servicio cliente respuesta seguimiento escalamiento",
    ),
    "Instalaciones": (
        "instalaciones facility oficina edificio puertas magneticas acceso fisico zona servidores seguridad fisica",
        "mantenimiento infraestructura fisica credenciales puertas sala servidores",
    ),
    "Salud": (
        "salud medico paciente historia clinica diagnostico tratamiento hospital laboratorio datos medicos",
        "hipaa privacidad sanitaria cita receta consentimiento",
    ),
}

ROLE_BY_AREA = {
    "Direccion Ejecutiva": "Direccion / Liderazgo",
    "Recursos Humanos": "People / RRHH",
    "Seguridad": "Seguridad / SecOps",
    "Tecnologia / TI": "TI / Infraestructura",
    "Finanzas": "Finanzas / Tesoreria",
    "Legal y Cumplimiento": "Legal / Compliance",
    "Ventas y Clientes": "Ventas / Customer Success",
    "Marketing": "Marketing / Comunicaciones",
    "Operaciones y Logistica": "Operaciones / Logistica",
    "Producto e Ingenieria": "Producto / Ingenieria",
    "Datos y Analitica": "Datos / Analitica",
    "Atencion al Cliente": "Soporte / Atencion al Cliente",
    "Instalaciones": "Facilities / Seguridad Fisica",
    "Salud": "Salud / Clinico",
}

TICKET_AREA_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?:#|\b)(?:HR|RRHH|PEOPLE)[-_][A-Z0-9_-]+", re.IGNORECASE), "Recursos Humanos"),
    (re.compile(r"(?:#|\b)(?:SEC|SECOps|SECURITY)[-_][A-Z0-9_-]+", re.IGNORECASE), "Seguridad"),
    (re.compile(r"(?:#|\b)(?:IT|TI|INFRA)[-_][A-Z0-9_-]+", re.IGNORECASE), "Tecnologia / TI"),
    (re.compile(r"(?:#|\b)(?:FIN|FINOPS|TREASURY)[-_][A-Z0-9_-]+", re.IGNORECASE), "Finanzas"),
    (re.compile(r"(?:#|\b)(?:LEGAL|CMP|COMP|COMPLIANCE)[-_][A-Z0-9_-]+", re.IGNORECASE), "Legal y Cumplimiento"),
    (re.compile(r"(?:#|\b)(?:OPS|LOG)[-_][A-Z0-9_-]+", re.IGNORECASE), "Operaciones y Logistica"),
    (re.compile(r"(?:#|\b)(?:FAC|FACILITY|BLDG)[-_][A-Z0-9_-]+", re.IGNORECASE), "Instalaciones"),
    (re.compile(r"(?:#|\b)(?:CS|SUPPORT|SOPORTE)[-_][A-Z0-9_-]+", re.IGNORECASE), "Atencion al Cliente"),
    (re.compile(r"(?:#|\b)(?:MKT|MARKETING)[-_][A-Z0-9_-]+", re.IGNORECASE), "Marketing"),
    (re.compile(r"(?:#|\b)(?:DATA|BI|ANALYTICS)[-_][A-Z0-9_-]+", re.IGNORECASE), "Datos y Analitica"),
    (re.compile(r"(?:#|\b)(?:PROD|ENG|QA)[-_][A-Z0-9_-]+", re.IGNORECASE), "Producto e Ingenieria"),
)

WEAK_AREA_EVIDENCE = {
    "Atencion al Cliente": {"ticket", "caso", "contacto"},
}


class EnterpriseAreaClassifier:
    def __init__(self) -> None:
        self._profiles = {
            area: [embed_text(profile) for profile in profiles]
            for area, profiles in AREA_PROFILES.items()
        }

    def classify_areas(self, text: str, *, limit: int = 4, threshold: float = 0.12) -> list[AreaInsight]:
        query_vector = embed_text(text)
        normalized = _normalize(text)
        insights: list[AreaInsight] = []
        for area, profile_vectors in self._profiles.items():
            vector_score = max((cosine_similarity(query_vector, profile) for profile in profile_vectors), default=0.0)
            evidence = _matching_terms(normalized, AREA_PROFILES[area])
            if _is_only_weak_evidence(area, evidence) and vector_score < 0.2:
                evidence = []
            keyword_score = min(len(evidence) / 8, 1.0)
            score = (0.68 * max(vector_score, 0.0)) + (0.32 * keyword_score)
            if score >= threshold or evidence:
                insights.append(AreaInsight(area=area, score=round(score, 3), evidence=evidence[:8]))

        ranked = sorted(insights, key=lambda item: item.score, reverse=True)
        return ranked[:limit] or [AreaInsight(area="General", score=0.0, evidence=[])]

    def segment_task(self, description: str) -> TaskSegment:
        ticket_area = _area_from_ticket_code(description)
        if ticket_area:
            return TaskSegment(
                description=description,
                area=ticket_area,
                role=ROLE_BY_AREA.get(ticket_area, "General / Sin asignar"),
                confidence=0.92,
            )
        areas = self.classify_areas(description, limit=1, threshold=0.0)
        area = areas[0].area if areas else "General"
        confidence = areas[0].score if areas else 0.0
        return TaskSegment(
            description=description,
            area=area,
            role=ROLE_BY_AREA.get(area, "General / Sin asignar"),
            confidence=confidence,
        )

    def segment_tasks(self, descriptions: list[str]) -> list[TaskSegment]:
        return [self.segment_task(description) for description in descriptions if description.strip()]


def _matching_terms(normalized_text: str, profiles: tuple[str, ...]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for profile in profiles:
        for term in re.findall(r"[a-z0-9_/-]{3,}", _normalize(profile)):
            if term in seen:
                continue
            if re.search(rf"\b{re.escape(term)}\b", normalized_text):
                seen.add(term)
                terms.append(term)
    return terms


def _area_from_ticket_code(text: str) -> str | None:
    for pattern, area in TICKET_AREA_HINTS:
        if pattern.search(text):
            return area
    return None


def _is_only_weak_evidence(area: str, evidence: list[str]) -> bool:
    weak_terms = WEAK_AREA_EVIDENCE.get(area)
    if not weak_terms or not evidence:
        return False
    return set(evidence).issubset(weak_terms)


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    return without_accents.lower()
