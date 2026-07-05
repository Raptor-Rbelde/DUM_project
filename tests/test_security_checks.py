from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import create_app
from sentinel.config.settings import Settings


def test_security_checks_report_expected_policy_outcomes(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        db_path=tmp_path / "sentinel.sqlite",
        external_ai_enabled=True,
        openai_api_key="demo",
        elevenlabs_api_key="demo",
    )
    client = TestClient(create_app(settings))

    response = client.get("/api/security/checks")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 4
    assert payload["passed"] == payload["total"]

    checks = {check["id"]: check for check in payload["checks"]}
    assert checks["prompt-injection"]["blocked"] is True
    assert checks["sensitive-export"]["blocked"] is True
    assert checks["secret-exfiltration"]["blocked"] is True
    assert checks["safe-summary"]["blocked"] is False
