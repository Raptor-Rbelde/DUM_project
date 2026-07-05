from __future__ import annotations

import json
import mimetypes
import secrets
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TranscriptionResult:
    provider: str
    model_id: str
    text: str
    language_code: str | None
    language_probability: float | None
    words: list[dict[str, Any]]
    raw: dict[str, Any]


class ElevenLabsSpeechToTextProvider:
    name = "elevenlabs"
    endpoint = "https://api.elevenlabs.io/v1/speech-to-text"

    def __init__(
        self,
        api_key: str | None,
        *,
        model_id: str = "scribe_v2",
        enable_logging: bool = True,
        timeout_seconds: int = 90,
    ) -> None:
        self.api_key = api_key
        self.model_id = model_id
        self.enable_logging = enable_logging
        self.timeout_seconds = timeout_seconds

    def transcribe_bytes(
        self,
        audio: bytes,
        *,
        filename: str = "sentinel-audio.webm",
        content_type: str | None = None,
        language_code: str | None = "es",
        diarize: bool = True,
        num_speakers: int | None = None,
    ) -> TranscriptionResult:
        if not self.api_key:
            raise RuntimeError("ELEVENLABS_API_KEY is not configured")
        if not audio:
            raise ValueError("Audio payload is empty")

        fields: dict[str, str] = {
            "model_id": self.model_id,
            "diarize": _bool_form(diarize),
            "tag_audio_events": "false",
            "timestamps_granularity": "word",
            "no_verbatim": "true",
        }
        if language_code:
            fields["language_code"] = language_code
        if num_speakers is not None:
            fields["num_speakers"] = str(num_speakers)

        body, boundary = _build_multipart_body(
            fields=fields,
            file_field="file",
            filename=filename,
            content_type=content_type or _guess_content_type(filename),
            file_bytes=audio,
        )
        url = f"{self.endpoint}?{urllib.parse.urlencode({'enable_logging': _bool_form(self.enable_logging)})}"
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "xi-api-key": self.api_key,
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if _is_zero_retention_forbidden(detail):
                raise RuntimeError(
                    "ElevenLabs rejected zero retention mode. Set ELEVENLABS_ENABLE_LOGGING=true, "
                    "or use an ElevenLabs account that supports zero retention."
                ) from exc
            raise RuntimeError(f"ElevenLabs transcription failed: {exc.code} {detail}") from exc

        return TranscriptionResult(
            provider=self.name,
            model_id=self.model_id,
            text=str(payload.get("text", "")),
            language_code=_optional_str(payload.get("language_code")),
            language_probability=_optional_float(payload.get("language_probability")),
            words=list(payload.get("words") or []),
            raw=payload,
        )


def _build_multipart_body(
    *,
    fields: dict[str, str],
    file_field: str,
    filename: str,
    content_type: str,
    file_bytes: bytes,
) -> tuple[bytes, str]:
    boundary = f"----sentinel-{secrets.token_hex(16)}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    chunks.extend(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            (
                f'Content-Disposition: form-data; name="{file_field}"; filename="{_safe_filename(filename)}"\r\n'
            ).encode("utf-8"),
            f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"),
            file_bytes,
            b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    return b"".join(chunks), boundary


def _guess_content_type(filename: str) -> str:
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


def _safe_filename(filename: str) -> str:
    cleaned = filename.rsplit("/", maxsplit=1)[-1].rsplit("\\", maxsplit=1)[-1].strip()
    return cleaned or "sentinel-audio.webm"


def _bool_form(value: bool) -> str:
    return "true" if value else "false"


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_zero_retention_forbidden(detail: str) -> bool:
    normalized = detail.lower()
    return (
        "zrm" in normalized
        or "zero retention" in normalized
        or ("enterprise" in normalized and "trial" in normalized and "not_allowed" in normalized)
    )
