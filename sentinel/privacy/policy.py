from __future__ import annotations

from sentinel.domain.privacy import (
    PrivacyAction,
    SensitiveEntity,
    SensitiveEntityType,
    SensitivityLevel,
)


SECRET_TYPES = {
    SensitiveEntityType.API_KEY,
    SensitiveEntityType.PASSWORD,
    SensitiveEntityType.TOKEN,
    SensitiveEntityType.PRIVATE_KEY,
    SensitiveEntityType.OTHER_SECRET,
}


class PrivacyPolicy:
    def classify(self, entity: SensitiveEntity) -> SensitivityLevel:
        if entity.type in SECRET_TYPES or entity.type == SensitiveEntityType.ID_DOCUMENT:
            return SensitivityLevel.RESTRICTED
        return entity.sensitivity

    def decide(self, sensitivity: SensitivityLevel) -> PrivacyAction:
        if sensitivity == SensitivityLevel.PUBLIC:
            return PrivacyAction.ALLOW
        if sensitivity == SensitivityLevel.INTERNAL:
            return PrivacyAction.MINIMIZE
        if sensitivity == SensitivityLevel.CONFIDENTIAL:
            return PrivacyAction.PSEUDONYMIZE
        return PrivacyAction.BLOCK

    def apply(self, entity: SensitiveEntity) -> SensitiveEntity:
        sensitivity = self.classify(entity)
        return entity.model_copy(update={"sensitivity": sensitivity, "action": self.decide(sensitivity)})
