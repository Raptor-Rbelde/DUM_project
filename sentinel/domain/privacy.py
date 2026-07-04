from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SensitiveEntityType(str, Enum):
    PERSON = "PERSON"
    ORGANIZATION = "ORGANIZATION"
    CLIENT = "CLIENT"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    ID_DOCUMENT = "ID_DOCUMENT"
    MONEY = "MONEY"
    DATE = "DATE"
    API_KEY = "API_KEY"
    PASSWORD = "PASSWORD"
    TOKEN = "TOKEN"
    PRIVATE_KEY = "PRIVATE_KEY"
    INTERNAL_PROJECT = "INTERNAL_PROJECT"
    CLASSIFICATION = "CLASSIFICATION"
    CODE_NAME = "CODE_NAME"
    TIME = "TIME"
    ROLE = "ROLE"
    FACILITY = "FACILITY"
    SECURITY_CONTROL = "SECURITY_CONTROL"
    SECRET_REFERENCE = "SECRET_REFERENCE"
    CONNECTION_STRING = "CONNECTION_STRING"
    OTHER_SECRET = "OTHER_SECRET"


class SensitivityLevel(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"


class PrivacyAction(str, Enum):
    ALLOW = "ALLOW"
    MINIMIZE = "MINIMIZE"
    PSEUDONYMIZE = "PSEUDONYMIZE"
    BLOCK = "BLOCK"


class SystemMode(str, Enum):
    VAULT = "VAULT"
    INTELLIGENCE = "INTELLIGENCE"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SensitiveEntity(BaseModel):
    type: SensitiveEntityType
    original_value: str = Field(repr=False)
    sensitivity: SensitivityLevel
    start: int
    end: int
    action: PrivacyAction = PrivacyAction.ALLOW
    placeholder: str | None = None
    confidence: float = Field(default=0.85, ge=0.0, le=1.0)

    @property
    def length(self) -> int:
        return self.end - self.start


class PrivacyCounts(BaseModel):
    total_entities: int = 0
    identities_detected: int = 0
    clients_detected: int = 0
    financial_items_detected: int = 0
    secrets_detected: int = 0
    blocked: int = 0
    pseudonymized: int = 0
    minimized: int = 0


class PrivacyAnalysis(BaseModel):
    session_id: str
    original_text: str
    safe_content: str
    entities: list[SensitiveEntity]
    blocked_entities: list[SensitiveEntity]
    pseudonymized_entities: list[SensitiveEntity]
    minimized_entities: list[SensitiveEntity]
    counts: PrivacyCounts
    risk_level: RiskLevel
    external_payload_allowed: bool

    def report(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "counts": self.counts.model_dump(),
            "risk_level": self.risk_level.value,
            "external_payload_allowed": self.external_payload_allowed,
            "entities": [entity.model_dump(mode="json") for entity in self.entities],
            "blocked_entities": [entity.model_dump(mode="json") for entity in self.blocked_entities],
            "pseudonymized_entities": [entity.model_dump(mode="json") for entity in self.pseudonymized_entities],
            "minimized_entities": [entity.model_dump(mode="json") for entity in self.minimized_entities],
        }
