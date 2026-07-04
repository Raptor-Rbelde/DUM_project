from __future__ import annotations

from sentinel.providers.openai_provider import OpenAIProvider


def test_openai_provider_marks_negative_channel_options_as_forbidden() -> None:
    provider = OpenAIProvider(api_key="test")
    safe_payload = (
        "Por ningun motivo las compartas por [CONTROL_AAAA] ni por [CONTROL_BBBB]. "
        "Si [PERSON_CCCC] necesita verificar, lo haran mediante [CONTROL_DDDD]."
    )

    messages = provider._build_messages(
        safe_payload,
        purpose=(
            "Por que canal de comunicacion ([CONTROL_AAAA], [CONTROL_BBBB], etc.) "
            "acordaron enviarse las nuevas [SECRET_EEEE]?"
        ),
    )

    system_prompt = messages[0]["content"]
    user_prompt = messages[1]["content"]

    assert "Respect negation" in system_prompt
    assert "Do not answer with placeholders that appear only inside forbidden" in system_prompt
    assert "explicit contradiction" in system_prompt
    assert "Forbidden or excluded placeholders" in user_prompt
    assert "[CONTROL_AAAA]" in user_prompt
    assert "[CONTROL_BBBB]" in user_prompt
    assert "Positive handling, channel, or verification placeholders" in user_prompt
    assert "[CONTROL_DDDD]" in user_prompt


def test_openai_provider_uses_deterministic_temperature() -> None:
    provider = OpenAIProvider(api_key="test")

    body = provider._build_body("Safe payload.", purpose="Summarize.")

    assert body["temperature"] == 0


def test_local_hints_mark_secret_injection_destination_not_the_secret() -> None:
    provider = OpenAIProvider(api_key="test")
    safe_payload = (
        "La nueva [SECRET_AAAA] de [ORG_BBBB] se debe inyectar directamente "
        "en el [SECRET_CCCC] de la nube."
    )

    hints = provider._build_local_reading_hints(safe_payload)

    assert "[SECRET_CCCC]" in hints
    assert "[SECRET_AAAA]" not in hints
