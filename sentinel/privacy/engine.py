from __future__ import annotations

import re
from uuid import uuid4

from sentinel.audit.store import AuditStore
from sentinel.domain.privacy import (
    PrivacyAction,
    PrivacyAnalysis,
    PrivacyCounts,
    RiskLevel,
    SensitiveEntity,
    SensitiveEntityType,
    SensitivityLevel,
)
from sentinel.privacy.detectors import RegexSensitiveDataDetector, SensitiveDataDetector
from sentinel.privacy.policy import PrivacyPolicy
from sentinel.privacy.vault import EntityVault


IDENTITY_TYPES = {
    SensitiveEntityType.PERSON,
    SensitiveEntityType.EMAIL,
    SensitiveEntityType.PHONE,
}

SECRET_TYPES = {
    SensitiveEntityType.API_KEY,
    SensitiveEntityType.PASSWORD,
    SensitiveEntityType.TOKEN,
    SensitiveEntityType.PRIVATE_KEY,
    SensitiveEntityType.ID_DOCUMENT,
    SensitiveEntityType.OTHER_SECRET,
    SensitiveEntityType.SECRET_REFERENCE,
    SensitiveEntityType.CONNECTION_STRING,
}


class PrivacyEngine:
    def __init__(
        self,
        vault: EntityVault,
        audit_store: AuditStore,
        detector: SensitiveDataDetector | None = None,
        policy: PrivacyPolicy | None = None,
    ) -> None:
        self.vault = vault
        self.audit_store = audit_store
        self.detector = detector or RegexSensitiveDataDetector()
        self.policy = policy or PrivacyPolicy()

    def analyze(self, text: str, session_id: str | None = None) -> PrivacyAnalysis:
        session = session_id or str(uuid4())
        raw_entities = self.detector.detect(text)
        entities = [self.policy.apply(entity) for entity in raw_entities]
        person_aliases = self._person_aliases(entities)
        safe_content = self._build_safe_content(text, session, entities, person_aliases)
        blocked = [entity for entity in entities if entity.action == PrivacyAction.BLOCK]
        pseudonymized = [entity for entity in entities if entity.action == PrivacyAction.PSEUDONYMIZE]
        minimized = [entity for entity in entities if entity.action == PrivacyAction.MINIMIZE]
        counts = self._counts(entities)
        risk_level = self._risk_level(entities)
        external_allowed = not blocked and "[BLOCKED_" not in safe_content

        self.audit_store.record(
            "privacy_scan_completed",
            session_id=session,
            policy_decision="ALLOW_LOCAL_ONLY" if blocked else "SAFE_PAYLOAD_READY",
            number_of_entities=len(entities),
            number_blocked=len(blocked),
            number_pseudonymized=len(pseudonymized),
            payload=safe_content,
            metadata={"risk_level": risk_level.value},
        )
        for entity in entities:
            self.audit_store.record(
                "sensitive_entity_detected",
                session_id=session,
                policy_decision=entity.action.value,
                metadata={
                    "type": entity.type.value,
                    "sensitivity": entity.sensitivity.value,
                    "start": entity.start,
                    "end": entity.end,
                    "confidence": entity.confidence,
                },
            )
            if entity.action == PrivacyAction.PSEUDONYMIZE:
                self.audit_store.record(
                    "entity_pseudonymized",
                    session_id=session,
                    policy_decision=entity.action.value,
                    metadata={"type": entity.type.value, "placeholder": entity.placeholder},
                )
            elif entity.action == PrivacyAction.BLOCK:
                self.audit_store.record(
                    "restricted_data_blocked",
                    session_id=session,
                    policy_decision=entity.action.value,
                    metadata={"type": entity.type.value},
                )

        return PrivacyAnalysis(
            session_id=session,
            original_text=text,
            safe_content=safe_content,
            entities=entities,
            blocked_entities=blocked,
            pseudonymized_entities=pseudonymized,
            minimized_entities=minimized,
            counts=counts,
            risk_level=risk_level,
            external_payload_allowed=external_allowed,
        )

    def reconstruct(self, text: str, placeholders: set[str] | None = None, session_id: str | None = None) -> str:
        reconstructed = self.vault.reconstruct(text, placeholders)
        self.audit_store.record("local_reconstruction_completed", session_id=session_id, payload=reconstructed)
        return reconstructed

    def sanitize_purpose(self, purpose: str, session_id: str) -> str:
        sanitized = self.vault.rewrite_text_for_session(session_id, purpose)
        self.audit_store.record(
            "external_request_purpose_sanitized",
            session_id=session_id,
            payload=sanitized,
            metadata={"changed": sanitized != purpose},
        )
        return sanitized

    def sanitize_text(self, text: str, session_id: str | None = None) -> str:
        sanitized = self.vault.rewrite_text_for_session(session_id, text) if session_id else self.vault.rewrite_text(text)
        self.audit_store.record(
            "text_sanitized",
            session_id=session_id,
            payload=sanitized,
            metadata={"changed": sanitized != text, "scope": "session" if session_id else "global"},
        )
        return sanitized

    def _build_safe_content(
        self,
        text: str,
        session_id: str,
        entities: list[SensitiveEntity],
        person_aliases: dict[str, str],
    ) -> str:
        safe_content = text
        for entity in sorted(entities, key=lambda item: item.start, reverse=True):
            replacement = self._replacement_for(session_id, entity, person_aliases)
            safe_content = safe_content[: entity.start] + replacement + safe_content[entity.end :]
        for alias, canonical in sorted(person_aliases.items(), key=lambda item: len(item[0]), reverse=True):
            placeholder = self.vault.get_or_create(session_id, SensitiveEntityType.PERSON, canonical)
            safe_content = re.sub(rf"(?<!\w){re.escape(alias)}(?!\w)", f"[{placeholder}]", safe_content)
        return safe_content

    def _replacement_for(self, session_id: str, entity: SensitiveEntity, person_aliases: dict[str, str]) -> str:
        if entity.action == PrivacyAction.ALLOW:
            return entity.original_value
        if entity.action == PrivacyAction.MINIMIZE:
            entity.placeholder = entity.type.value
            return f"[{entity.type.value}]"
        if entity.action == PrivacyAction.PSEUDONYMIZE:
            vault_value = person_aliases.get(entity.original_value, entity.original_value)
            placeholder = self.vault.get_or_create(session_id, entity.type, vault_value)
            entity.placeholder = placeholder
            return f"[{placeholder}]"
        entity.placeholder = f"BLOCKED_{entity.type.value}"
        return f"[BLOCKED_{entity.type.value}]"

    def _person_aliases(self, entities: list[SensitiveEntity]) -> dict[str, str]:
        canonical_by_first_name: dict[str, str] = {}
        for entity in entities:
            if entity.type != SensitiveEntityType.PERSON:
                continue
            value = entity.original_value.strip()
            parts = value.split()
            if len(parts) <= 1:
                continue
            first_name = parts[0]
            existing = canonical_by_first_name.get(first_name)
            if existing is None or len(value) > len(existing):
                canonical_by_first_name[first_name] = value

        aliases: dict[str, str] = {}
        for entity in entities:
            if entity.type != SensitiveEntityType.PERSON:
                continue
            value = entity.original_value.strip()
            if " " not in value and value in canonical_by_first_name:
                aliases[value] = canonical_by_first_name[value]
        return aliases

    def _counts(self, entities: list[SensitiveEntity]) -> PrivacyCounts:
        return PrivacyCounts(
            total_entities=len(entities),
            identities_detected=sum(1 for entity in entities if entity.type in IDENTITY_TYPES),
            clients_detected=sum(1 for entity in entities if entity.type == SensitiveEntityType.CLIENT),
            financial_items_detected=sum(1 for entity in entities if entity.type == SensitiveEntityType.MONEY),
            secrets_detected=sum(1 for entity in entities if entity.type in SECRET_TYPES),
            blocked=sum(1 for entity in entities if entity.action == PrivacyAction.BLOCK),
            pseudonymized=sum(1 for entity in entities if entity.action == PrivacyAction.PSEUDONYMIZE),
            minimized=sum(1 for entity in entities if entity.action == PrivacyAction.MINIMIZE),
        )

    def _risk_level(self, entities: list[SensitiveEntity]) -> RiskLevel:
        if any(entity.sensitivity == SensitivityLevel.RESTRICTED for entity in entities):
            return RiskLevel.CRITICAL
        confidential = sum(1 for entity in entities if entity.sensitivity == SensitivityLevel.CONFIDENTIAL)
        if confidential >= 5:
            return RiskLevel.HIGH
        if confidential > 0:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW
