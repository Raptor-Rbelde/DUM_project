from __future__ import annotations

from sentinel.audit.store import AuditStore
from sentinel.domain.privacy import PrivacyAction, SensitiveEntityType
from sentinel.privacy.engine import PrivacyEngine
from sentinel.privacy.hybrid_detector import build_privacy_detector
from sentinel.privacy.sequence_tagger import LocalSequenceTaggerSensitiveDataDetector, train_default_sequence_model
from sentinel.privacy.vault import EntityVault


def test_final_local_sequence_model_loads_and_detects_control(tmp_path) -> None:
    model_path = tmp_path / "sensitive_sequence_tagger.json"
    train_default_sequence_model(model_path)
    detector = LocalSequenceTaggerSensitiveDataDetector(model_path)

    entities = detector.detect("El canal privado de Signal queda autorizado para verificacion.")

    assert detector.available is True
    assert any(entity.type == SensitiveEntityType.SECURITY_CONTROL for entity in entities)


def test_hybrid_detector_pseudonymizes_ml_only_sensitive_context(tmp_path) -> None:
    model_path = tmp_path / "sensitive_sequence_tagger.json"
    train_default_sequence_model(model_path)
    audit_store = AuditStore(tmp_path / "sentinel.sqlite")
    vault = EntityVault(tmp_path / "sentinel.sqlite")
    detector = build_privacy_detector(local_ml_enabled=True, local_ml_model_path=model_path)
    engine = PrivacyEngine(vault=vault, audit_store=audit_store, detector=detector)

    analysis = engine.analyze("Usen el canal privado de Signal para verificar el despliegue.", session_id="ml1")

    assert "Signal" not in analysis.safe_content
    assert "[CONTROL_" in analysis.safe_content


def test_hybrid_detector_keeps_regex_secret_blocking_authoritative(tmp_path) -> None:
    model_path = tmp_path / "sensitive_sequence_tagger.json"
    train_default_sequence_model(model_path)
    audit_store = AuditStore(tmp_path / "sentinel.sqlite")
    vault = EntityVault(tmp_path / "sentinel.sqlite")
    detector = build_privacy_detector(local_ml_enabled=True, local_ml_model_path=model_path)
    engine = PrivacyEngine(vault=vault, audit_store=audit_store, detector=detector)
    secret = "OPENAI_API_KEY=sk-example-not-real-123456789"

    analysis = engine.analyze(f"Rota este secreto urgente: {secret}", session_id="ml2")

    assert secret not in analysis.safe_content
    assert "[BLOCKED_API_KEY]" in analysis.safe_content
    assert any(
        entity.type == SensitiveEntityType.API_KEY and entity.action == PrivacyAction.BLOCK
        for entity in analysis.entities
    )
