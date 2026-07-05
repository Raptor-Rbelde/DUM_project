from __future__ import annotations

import json
import re
from typing import Any
import urllib.request

from sentinel.providers.base import ExternalLLMProvider


PLACEHOLDER_SOURCE = r"\[[A-Z]+(?:_[A-Z]+)*_[A-Z0-9]{4}\]"
PLACEHOLDER_PATTERN = re.compile(PLACEHOLDER_SOURCE)
NEGATION_PATTERN = re.compile(r"\b(?:no|nunca|ni|sin|sin usar|por ning[uú]n motivo|do not|never|without)\b", re.IGNORECASE)
POSITIVE_CHANNEL_PATTERN = re.compile(
    r"\b(?:mediante|usando|unicamente|únicamente|exclusivamente|a trav[eé]s de|inyectar|inyectarlas|"
    r"inyectarlos|inyecten|acceso temporal|vault|gestor de secretos|canal)\b",
    re.IGNORECASE,
)
FORBIDDEN_LINK_PATTERN = re.compile(
    rf"\b(?:por|via|v[ií]a|mediante)\b(?:\s+\w+){{0,4}}\s+({PLACEHOLDER_SOURCE})",
    re.IGNORECASE,
)
APPROVED_LINK_PATTERN = re.compile(
    rf"\b(?:mediante|usando|unicamente|únicamente|exclusivamente|a trav[eé]s de|en|al)\b"
    rf"(?:\s+\w+){{0,6}}\s+({PLACEHOLDER_SOURCE})",
    re.IGNORECASE,
)
INJECTION_TARGET_PATTERN = re.compile(
    rf"\binyect\w+\b[^.\n]{{0,120}}\b(?:en|al)\b(?:\s+\w+){{0,4}}\s+({PLACEHOLDER_SOURCE})",
    re.IGNORECASE,
)
CHANNEL_PREFIXES = ("[CONTROL_", "[SECRET_", "[CONN_", "[CODE_", "[FACILITY_")


class OpenAIProvider(ExternalLLMProvider):
    name = "openai"

    def __init__(self, api_key: str | None, model: str = "gpt-4o-mini") -> None:
        self.api_key = api_key
        self.model = model

    def analyze(self, prompt: str, *, purpose: str) -> str:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")

        body = self._build_body(prompt, purpose=purpose)
        request = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return str(payload["choices"][0]["message"]["content"])

    def _build_body(self, prompt: str, *, purpose: str) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": self._build_messages(prompt, purpose=purpose),
            "temperature": 0,
        }

    def _build_messages(self, prompt: str, *, purpose: str) -> list[dict[str, str]]:
        user_parts = [f"Purpose: {purpose}"]
        local_hints = self._build_local_reading_hints(prompt)
        if local_hints:
            user_parts.append(f"Local reading hints derived from the safe payload:\n{local_hints}")
        user_parts.append(f"Safe payload:\n{prompt}")
        return [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": "\n\n".join(user_parts)},
        ]

    def _system_prompt(self) -> str:
        return (
            "Analyze only the safe payload. The payload contains local privacy placeholders such as "
            "[PERSON_ABCD], [DATE_ABCD], [TIME_ABCD], [MONEY_ABCD], [CLIENT_ABCD], [EMAIL_ABCD], "
            "[PROJECT_ABCD], [CODE_ABCD], [FACILITY_ABCD], [CONTROL_ABCD], [CLASSIFICATION_ABCD], "
            "[ROLE_ABCD], [SECRET_ABCD], [CONN_ABCD], and [ORG_ABCD]. Treat every unique placeholder "
            "as an exact hidden value that exists locally. Markers like [BLOCKED_API_KEY] mean the real "
            "restricted value was removed before this request. If the user asks for a hidden value, answer "
            "with the placeholder exactly instead of saying the value is missing. Do not infer or invent "
            "hidden private data. Sentinel will reconstruct authorized placeholders locally after your response.\n\n"
            "Reasoning rules for Spanish and English meeting transcripts:\n"
            "- Respect negation and prohibition terms such as no, ni, sin usar, por ningun motivo, nunca, "
            "do not, never, and without as hard constraints.\n"
            "- If a question asks which channel, path, tool, or medium was agreed for sending, sharing, "
            "verifying, or handling secrets or keys, separate forbidden options from approved instructions.\n"
            "- Do not answer with placeholders that appear only inside forbidden or negative clauses.\n"
            "- Treat options mentioned only in the user's question as examples, not as facts from the transcript.\n"
            "- If the payload contains a section named 'Aggregate structured memory facts', treat that section as "
            "authoritative across all retrieved snippets. If its Tasks or Task Segments are not 'None', do not say "
            "that no tasks are registered. If its Decisions or Risks are not 'None', include them when asked.\n"
            "- If the question premise conflicts with the payload, correct it directly. Do not say the answer is "
            "missing when the payload contains an explicit contradiction.\n"
            "- If the question asks why someone ordered an action, but the payload says the action was forbidden "
            "or stopped, answer that they did not order it and explain the actual instruction.\n"
            "- Example: if the payload says 'Por ningun motivo las compartas por [CONTROL_AAAA] ni por "
            "[CONTROL_BBBB]. Si [PERSON_CCCC] necesita verificar, lo haran mediante [CONTROL_DDDD]', then "
            "answer that [CONTROL_AAAA] and [CONTROL_BBBB] were prohibited, and the verification path was "
            "[CONTROL_DDDD]."
        )

    def _build_local_reading_hints(self, prompt: str) -> str:
        sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", prompt) if sentence.strip()]
        forbidden: set[str] = set()
        approved: set[str] = set()

        for sentence in sentences:
            placeholders = self._channel_placeholders(sentence)
            if not placeholders:
                continue
            if NEGATION_PATTERN.search(sentence):
                forbidden.update(self._linked_channel_placeholders(FORBIDDEN_LINK_PATTERN, sentence) or placeholders)
            if POSITIVE_CHANNEL_PATTERN.search(sentence):
                sentence_approved = self._linked_channel_placeholders(APPROVED_LINK_PATTERN, sentence)
                sentence_approved.update(self._linked_channel_placeholders(INJECTION_TARGET_PATTERN, sentence))
                if sentence_approved:
                    approved.update(sentence_approved)
                else:
                    approved.update(placeholders)

        approved -= forbidden
        hints: list[str] = []
        if forbidden:
            hints.append(
                "Forbidden or excluded placeholders from negative clauses: "
                f"{', '.join(sorted(forbidden))}. Do not present them as agreed channels."
            )
        if approved:
            hints.append(
                "Positive handling, channel, or verification placeholders mentioned in the payload: "
                f"{', '.join(sorted(approved))}."
            )
        return "\n".join(hints)

    @staticmethod
    def _channel_placeholders(sentence: str) -> set[str]:
        return {
            placeholder
            for placeholder in PLACEHOLDER_PATTERN.findall(sentence)
            if placeholder.startswith(CHANNEL_PREFIXES)
        }

    @staticmethod
    def _linked_channel_placeholders(pattern: re.Pattern[str], sentence: str) -> set[str]:
        return {
            match.group(1)
            for match in pattern.finditer(sentence)
            if match.group(1).startswith(CHANNEL_PREFIXES)
        }
