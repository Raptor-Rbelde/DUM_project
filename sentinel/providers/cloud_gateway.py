from __future__ import annotations

from pydantic import BaseModel

from sentinel.audit.store import AuditStore
from sentinel.config.settings import Settings
from sentinel.domain.privacy import PrivacyAction, SensitiveEntityType, SystemMode
from sentinel.privacy.detectors import RegexSensitiveDataDetector, SensitiveDataDetector
from sentinel.privacy.policy import PrivacyPolicy
from sentinel.providers.base import ExternalLLMProvider


class SafePayloadValidation(BaseModel):
    allowed: bool
    reason: str
    restricted_types: list[str] = []


class ExternalAIResult(BaseModel):
    sent: bool
    provider: str | None = None
    response: str
    validation: SafePayloadValidation


class SafePayloadValidator:
    def __init__(self, detector: SensitiveDataDetector | None = None, policy: PrivacyPolicy | None = None) -> None:
        self.detector = detector or RegexSensitiveDataDetector()
        self.policy = policy or PrivacyPolicy()

    def validate(self, payload: str, *, purpose: str) -> SafePayloadValidation:
        if not purpose.strip():
            return SafePayloadValidation(allowed=False, reason="External requests require an explicit purpose.")
        purpose_entities = [self.policy.apply(entity) for entity in self.detector.detect(purpose)]
        unsafe_purpose_entities = [
            entity
            for entity in purpose_entities
            if entity.action == PrivacyAction.BLOCK or entity.type in self._restricted_types()
        ]
        if unsafe_purpose_entities:
            return SafePayloadValidation(
                allowed=False,
                reason="External request purpose contains restricted data and must be rewritten locally.",
                restricted_types=sorted({entity.type.value for entity in unsafe_purpose_entities}),
            )
        entities = [self.policy.apply(entity) for entity in self.detector.detect(payload)]
        restricted = [entity for entity in entities if entity.type in self._restricted_types()]
        if restricted:
            return SafePayloadValidation(
                allowed=False,
                reason="Payload still contains restricted data.",
                restricted_types=sorted({entity.type.value for entity in restricted}),
            )
        return SafePayloadValidation(allowed=True, reason="Payload passed local privacy validation.")

    @staticmethod
    def _restricted_types() -> set[SensitiveEntityType]:
        return {
            SensitiveEntityType.API_KEY,
            SensitiveEntityType.PASSWORD,
            SensitiveEntityType.TOKEN,
            SensitiveEntityType.PRIVATE_KEY,
            SensitiveEntityType.ID_DOCUMENT,
            SensitiveEntityType.OTHER_SECRET,
        }


class CloudGateway:
    def __init__(
        self,
        settings: Settings,
        audit_store: AuditStore,
        provider: ExternalLLMProvider,
        validator: SafePayloadValidator | None = None,
    ) -> None:
        self.settings = settings
        self.audit_store = audit_store
        self.provider = provider
        self.validator = validator or SafePayloadValidator()

    def analyze_safe_content(
        self,
        safe_content: str,
        *,
        purpose: str,
        session_id: str,
        mode: SystemMode = SystemMode.INTELLIGENCE,
    ) -> ExternalAIResult:
        provider_name = getattr(self.provider, "name", "unknown")
        self.audit_store.record(
            "external_request_attempted",
            session_id=session_id,
            provider=provider_name,
            payload=safe_content,
            metadata={"mode": mode.value, "purpose": purpose},
        )

        if mode == SystemMode.VAULT:
            self.audit_store.record(
                "external_request_blocked",
                session_id=session_id,
                provider=provider_name,
                policy_decision="VAULT_MODE_BLOCK",
            )
            return ExternalAIResult(
                sent=False,
                provider=provider_name,
                response="Vault Mode is local only. No external provider was called.",
                validation=SafePayloadValidation(allowed=False, reason="Vault Mode blocks all external calls."),
            )

        validation = self.validator.validate(safe_content, purpose=purpose)
        if not validation.allowed:
            self.audit_store.record(
                "external_request_blocked",
                session_id=session_id,
                provider=provider_name,
                policy_decision="SAFE_PAYLOAD_VALIDATION_FAILED",
                payload=safe_content,
                metadata=validation.model_dump(),
            )
            return ExternalAIResult(sent=False, provider=provider_name, response=validation.reason, validation=validation)

        if not self.settings.external_ai_enabled:
            self.audit_store.record(
                "external_request_blocked",
                session_id=session_id,
                provider=provider_name,
                policy_decision="EXTERNAL_AI_DISABLED",
            )
            return ExternalAIResult(
                sent=False,
                provider=provider_name,
                response="External AI is disabled by default. Set EXTERNAL_AI_ENABLED=true to allow Intelligence Mode.",
                validation=validation,
            )

        response = self.provider.analyze(safe_content, purpose=purpose)
        self.audit_store.record(
            "external_request_sent",
            session_id=session_id,
            provider=provider_name,
            policy_decision="SENT_SAFE_PAYLOAD",
            payload=safe_content,
        )
        self.audit_store.record(
            "external_response_received",
            session_id=session_id,
            provider=provider_name,
            payload=response,
        )
        return ExternalAIResult(sent=True, provider=provider_name, response=response, validation=validation)
