from __future__ import annotations

from sentinel.tasks.enterprise_classifier import EnterpriseAreaClassifier


def test_classifier_detects_enterprise_areas_from_meeting_context() -> None:
    classifier = EnterpriseAreaClassifier()

    areas = classifier.classify_areas(
        "Recursos Humanos debe preparar onboarding y nomina. "
        "SecOps revocara credenciales comprometidas. "
        "TI migrara el servidor y actualizara Docker."
    )
    names = {area.area for area in areas}

    assert "Recursos Humanos" in names
    assert "Seguridad" in names
    assert "Tecnologia / TI" in names


def test_classifier_segments_task_by_role() -> None:
    classifier = EnterpriseAreaClassifier()

    segment = classifier.segment_task("SecOps debe revocar la API key y rotar el password en el vault.")

    assert segment.area == "Seguridad"
    assert segment.role == "Seguridad / SecOps"
    assert segment.confidence > 0


def test_classifier_uses_ticket_prefix_as_area_hint() -> None:
    classifier = EnterpriseAreaClassifier()

    segment = classifier.segment_task("Revisar compensacion y beneficios bajo el ticket #HR-COMP-012.")

    assert segment.area == "Recursos Humanos"
    assert segment.role == "People / RRHH"
