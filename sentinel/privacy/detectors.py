from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Protocol

from sentinel.domain.privacy import SensitiveEntity, SensitiveEntityType, SensitivityLevel


class SensitiveDataDetector(Protocol):
    def detect(self, text: str) -> list[SensitiveEntity]:
        ...


@dataclass(frozen=True)
class DetectorRule:
    entity_type: SensitiveEntityType
    sensitivity: SensitivityLevel
    pattern: re.Pattern[str]
    confidence: float
    value_group: int = 0


def _compile(pattern: str, flags: int = re.IGNORECASE) -> re.Pattern[str]:
    return re.compile(pattern, flags | re.MULTILINE)


def _compile_case_sensitive(pattern: str, flags: int = re.MULTILINE) -> re.Pattern[str]:
    return re.compile(pattern, flags)


MONTHS = (
    "enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|"
    "noviembre|diciembre|january|february|march|april|may|june|july|august|"
    "september|october|november|december"
)

ENTITY_PRIORITY = {
    SensitiveEntityType.PRIVATE_KEY: 100,
    SensitiveEntityType.API_KEY: 98,
    SensitiveEntityType.PASSWORD: 96,
    SensitiveEntityType.TOKEN: 94,
    SensitiveEntityType.ID_DOCUMENT: 92,
    SensitiveEntityType.OTHER_SECRET: 90,
    SensitiveEntityType.EMAIL: 88,
    SensitiveEntityType.CONNECTION_STRING: 87,
    SensitiveEntityType.CLASSIFICATION: 86,
    SensitiveEntityType.CODE_NAME: 85,
    SensitiveEntityType.MONEY: 84,
    SensitiveEntityType.DATE: 82,
    SensitiveEntityType.TIME: 80,
    SensitiveEntityType.PHONE: 78,
    SensitiveEntityType.SECRET_REFERENCE: 77,
    SensitiveEntityType.SECURITY_CONTROL: 76,
    SensitiveEntityType.FACILITY: 75,
    SensitiveEntityType.CLIENT: 74,
    SensitiveEntityType.INTERNAL_PROJECT: 72,
    SensitiveEntityType.ORGANIZATION: 68,
    SensitiveEntityType.ROLE: 79,
    SensitiveEntityType.PERSON: 64,
}

DATE_LIKE = re.compile(
    rf"^(?:\d{{1,2}}[/-]\d{{1,2}}[/-]\d{{2,4}}|\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}\s+(?:de\s+)?(?:{MONTHS})(?:\s+(?:de\s+)?\d{{4}})?)$",
    re.IGNORECASE,
)

PERSON_STOP_VALUES = {
    "Alto",
    "Bien",
    "Buenas",
    "Cero",
    "Desactivación",
    "Distribución",
    "Entendido",
    "Excelente",
    "Fase",
    "Finalmente",
    "Finalizando",
    "Luego",
    "Migración",
    "Ninguna",
    "Operación",
    "Perfecto",
    "Procedo",
    "Secreto",
    "Tomo",
    "Todo",
    "Solo",
    "Personal",
    "Autorizado",
    "Arquitecto",
    "Principal",
    "Sistemas",
    "Líder",
    "Desarrollo",
    "Backend",
    "Crítico",
    "Critico",
    "Supabase",
    "Claude",
    "OpenAI",
    "GitHub",
    "Actions",
    "Docker",
    "Postgres",
    "SQL",
    "SecOps",
    "Slack",
}


class RegexSensitiveDataDetector:
    def __init__(self) -> None:
        self.rules: list[DetectorRule] = [
            DetectorRule(
                SensitiveEntityType.PRIVATE_KEY,
                SensitivityLevel.RESTRICTED,
                _compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
                0.99,
            ),
            DetectorRule(
                SensitiveEntityType.API_KEY,
                SensitivityLevel.RESTRICTED,
                _compile(r"\b(?:OPENAI_API_KEY|ANTHROPIC_API_KEY|API_KEY|SECRET_KEY)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{8,}['\"]?"),
                0.98,
            ),
            DetectorRule(
                SensitiveEntityType.API_KEY,
                SensitivityLevel.RESTRICTED,
                _compile(r"`?\bsk-(?:[A-Za-z0-9_-]+-)*[A-Za-z0-9_.-]{6,}(?:\.\.\.)?`?"),
                0.97,
            ),
            DetectorRule(
                SensitiveEntityType.API_KEY,
                SensitivityLevel.RESTRICTED,
                _compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_\-]{10,}\b"),
                0.96,
            ),
            DetectorRule(
                SensitiveEntityType.PASSWORD,
                SensitivityLevel.RESTRICTED,
                _compile(r"\b(?:password|passwd|contrasena|contraseña)\s*[:=]\s*['\"]?[^'\"\s,;]+['\"]?"),
                0.96,
            ),
            DetectorRule(
                SensitiveEntityType.TOKEN,
                SensitivityLevel.RESTRICTED,
                _compile(r"\b(?:access_token|refresh_token|token|bearer)\s*[:= ]\s*['\"]?[A-Za-z0-9._\-]{10,}['\"]?"),
                0.94,
            ),
            DetectorRule(
                SensitiveEntityType.ID_DOCUMENT,
                SensitivityLevel.RESTRICTED,
                _compile(r"\b(?:DUI|SSN|NIT|passport|pasaporte)\s*[:#]?\s*[A-Z0-9\-]{6,}\b"),
                0.93,
            ),
            DetectorRule(
                SensitiveEntityType.EMAIL,
                SensitivityLevel.CONFIDENTIAL,
                _compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b"),
                0.97,
            ),
            DetectorRule(
                SensitiveEntityType.CONNECTION_STRING,
                SensitivityLevel.CONFIDENTIAL,
                _compile(r"`(?:postgres(?:ql)?|mysql|mongodb|redis)://[^`]+`"),
                0.96,
            ),
            DetectorRule(
                SensitiveEntityType.CLASSIFICATION,
                SensitivityLevel.CONFIDENTIAL,
                _compile_case_sensitive(r"\b(?:Alto Secreto|Distribución Restringida|Distribucion Restringida|Solo Personal Autorizado|Crítico|Critico|Confidencial|Secreto)\b"),
                0.96,
            ),
            DetectorRule(
                SensitiveEntityType.CODE_NAME,
                SensitivityLevel.CONFIDENTIAL,
                _compile_case_sensitive(r"\b(?:contacto|contactar\s+a|comunícate\s+con|comunicate\s+con|te\s+comuniques\s+con)\s+\"?([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ0-9_-]+)\"?"),
                0.94,
                value_group=1,
            ),
            DetectorRule(
                SensitiveEntityType.CODE_NAME,
                SensitivityLevel.CONFIDENTIAL,
                _compile_case_sensitive(r"Cito:\s+\*?\"([^\"]{8,160})\"\*?"),
                0.92,
                value_group=1,
            ),
            DetectorRule(
                SensitiveEntityType.PHONE,
                SensitivityLevel.CONFIDENTIAL,
                _compile(r"(?<![\w-])(?:\+?\d{1,3}[\s().-])?(?:\(?\d{3,4}\)?[\s.-]){1,3}\d{3,4}(?![\w-])"),
                0.85,
            ),
            DetectorRule(
                SensitiveEntityType.MONEY,
                SensitivityLevel.CONFIDENTIAL,
                _compile(r"(?:USD|US\$|\$)\s?\d{1,3}(?:,\d{3})*(?:\.\d+)?|\b\d+(?:\.\d+)?\s?(?:USD|dollars|dolares|colones)\b"),
                0.9,
            ),
            DetectorRule(
                SensitiveEntityType.DATE,
                SensitivityLevel.CONFIDENTIAL,
                _compile(rf"\b(?:hoy|mañana|manana|pasado mañana|pasado manana|\d{{1,2}}[/-]\d{{1,2}}[/-]\d{{2,4}}|\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}\s+(?:de\s+)?(?:{MONTHS})(?:\s+(?:de\s+)?\d{{4}})?)\b"),
                0.82,
            ),
            DetectorRule(
                SensitiveEntityType.TIME,
                SensitivityLevel.CONFIDENTIAL,
                _compile(r"\b(?:\d{1,2}:\d{2}|próximos\s+\w+\s+minutos|proximos\s+\w+\s+minutos|madrugada)\b"),
                0.82,
            ),
            DetectorRule(
                SensitiveEntityType.SECRET_REFERENCE,
                SensitivityLevel.CONFIDENTIAL,
                _compile_case_sensitive(r"`?[A-Z][A-Z0-9_]{4,}`?"),
                0.9,
            ),
            DetectorRule(
                SensitiveEntityType.SECRET_REFERENCE,
                SensitivityLevel.CONFIDENTIAL,
                _compile(r"\b(?:API\s*keys?|llaves?|gestor de secretos|vault de secretos|variables de entorno|secretos?|password de (?:la )?base de datos|contraseña de conexión|contrasena de conexion|string de conexión|string de conexion)\b"),
                0.86,
            ),
            DetectorRule(
                SensitiveEntityType.ROLE,
                SensitivityLevel.CONFIDENTIAL,
                _compile_case_sensitive(r"\((Arquitecto Principal de Sistemas|Directora de SecOps|Líder de Desarrollo Backend|Lider de Desarrollo Backend|Jefe de Infraestructura Técnica|Jefe de Infraestructura Tecnica|Directora de Operaciones Especiales|Coordinadora de Logística|Coordinadora de Logistica)\)"),
                0.88,
                value_group=1,
            ),
            DetectorRule(
                SensitiveEntityType.INTERNAL_PROJECT,
                SensitivityLevel.CONFIDENTIAL,
                _compile_case_sensitive(r"\b(?:Proyecto|Project)\s+([A-Z][A-Za-z0-9_\-]*(?:\s+[A-Z][A-Za-z0-9_\-]*){0,4})\b"),
                0.88,
                value_group=1,
            ),
            DetectorRule(
                SensitiveEntityType.INTERNAL_PROJECT,
                SensitivityLevel.CONFIDENTIAL,
                _compile_case_sensitive(r"\b(?:Operación|Operacion|Fase)\s+[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ0-9_\-]*(?:\s+[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ0-9_\-]*){0,3}\b"),
                0.89,
            ),
            DetectorRule(
                SensitiveEntityType.CLIENT,
                SensitivityLevel.CONFIDENTIAL,
                _compile_case_sensitive(r"\b(?:cliente|Cliente|client|Client)\s+([A-Z][A-Za-z&]*(?:\s+[A-Z][A-Za-z&]*){0,4})\b"),
                0.82,
                value_group=1,
            ),
            DetectorRule(
                SensitiveEntityType.FACILITY,
                SensitivityLevel.CONFIDENTIAL,
                _compile(r"\b(?:servidor aislado|red principal|zona de servidores\s+[A-Z]|zona\s+[A-Z]|puertas magnéticas|puertas magneticas)\b"),
                0.86,
            ),
            DetectorRule(
                SensitiveEntityType.SECURITY_CONTROL,
                SensitivityLevel.CONFIDENTIAL,
                _compile(r"(?:`?\.env`?|\b(?:archivo `.env`|archivo \.env|entorno de staging|panel de administración|panel de administracion|consola de administración|consola de administracion|acceso temporal al vault|registro de auditoría externo|registro de auditoria externo|auditoría externa|auditoria externa|credenciales|caché de GitHub Actions|cache de GitHub Actions|GitHub Actions|runner viejo|runners viejos|contenedores Docker|imágenes de Docker|imagenes de Docker|runtime|build|códigos de acceso|codigos de acceso|canal encriptado de contingencia|canal de contingencia|canal encriptado|correos|correo|Slack|llamadas regulares|sistemas de monitoreo automáticos|sistemas de monitoreo automaticos|cifrado[^.\n]{0,80}grado militar)\b)"),
                0.86,
            ),
            DetectorRule(
                SensitiveEntityType.ORGANIZATION,
                SensitivityLevel.CONFIDENTIAL,
                _compile_case_sensitive(r"\b(?:Banco|Grupo|Corporacion|Corporation|Acme|Globex|Initech)\s+[A-Z][A-Za-z&]*(?:\s+[A-Z][A-Za-z&]*){0,3}\b|\b[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ&]+(?:\s+[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ&]+){0,3}\s+(?:S\.A\.|Inc\.|LLC|Ltd\.|Corp\.|Bank)\b|\b(?:Operaciones Especiales|Infraestructura Técnica|Infraestructura Tecnica|SecOps|Supabase|Claude|OpenAI|GitHub Actions|Docker|Postgres)\b"),
                0.78,
            ),
            DetectorRule(
                SensitiveEntityType.PERSON,
                SensitivityLevel.CONFIDENTIAL,
                _compile_case_sensitive(r"\b[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ]\.)(?=\W|$)"),
                0.78,
            ),
            DetectorRule(
                SensitiveEntityType.PERSON,
                SensitivityLevel.CONFIDENTIAL,
                _compile_case_sensitive(r"\b([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,})(?=,\s)"),
                0.74,
                value_group=1,
            ),
            DetectorRule(
                SensitiveEntityType.PERSON,
                SensitivityLevel.CONFIDENTIAL,
                _compile_case_sensitive(r"(?<=,\s)([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,})(?=[.?!])"),
                0.74,
                value_group=1,
            ),
            DetectorRule(
                SensitiveEntityType.PERSON,
                SensitivityLevel.CONFIDENTIAL,
                _compile_case_sensitive(r"\b([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,})(?=\s+me\s+confirme\b)"),
                0.74,
                value_group=1,
            ),
            DetectorRule(
                SensitiveEntityType.PERSON,
                SensitivityLevel.CONFIDENTIAL,
                _compile_case_sensitive(r"\b[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}){1,2}\b"),
                0.7,
            ),
        ]

    def detect(self, text: str) -> list[SensitiveEntity]:
        candidates: list[SensitiveEntity] = []
        for rule in self.rules:
            candidates.extend(self._find_rule(text, rule))
        return self._resolve_overlaps(candidates)

    def _find_rule(self, text: str, rule: DetectorRule) -> Iterable[SensitiveEntity]:
        for match in rule.pattern.finditer(text):
            value = match.group(rule.value_group)
            start, end = match.span(rule.value_group)
            if not value.strip():
                continue
            value = value.strip()
            if rule.entity_type == SensitiveEntityType.PHONE and DATE_LIKE.fullmatch(value.strip()):
                continue
            if rule.entity_type == SensitiveEntityType.PERSON and value in PERSON_STOP_VALUES:
                continue
            yield SensitiveEntity(
                type=rule.entity_type,
                original_value=value,
                sensitivity=rule.sensitivity,
                start=start,
                end=end,
                confidence=rule.confidence,
            )

    def _resolve_overlaps(self, candidates: list[SensitiveEntity]) -> list[SensitiveEntity]:
        return resolve_overlaps(candidates)


def resolve_overlaps(candidates: list[SensitiveEntity]) -> list[SensitiveEntity]:
    priority = {
        SensitivityLevel.RESTRICTED: 4,
        SensitivityLevel.CONFIDENTIAL: 3,
        SensitivityLevel.INTERNAL: 2,
        SensitivityLevel.PUBLIC: 1,
    }
    sorted_candidates = sorted(
        candidates,
        key=lambda item: (ENTITY_PRIORITY.get(item.type, 0), priority[item.sensitivity], item.length, item.confidence),
        reverse=True,
    )
    accepted: list[SensitiveEntity] = []
    occupied: list[tuple[int, int]] = []
    for entity in sorted_candidates:
        if any(entity.start < end and entity.end > start for start, end in occupied):
            continue
        accepted.append(entity)
        occupied.append((entity.start, entity.end))
    return sorted(accepted, key=lambda item: item.start)
