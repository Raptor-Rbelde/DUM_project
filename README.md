# Sentinel

Sentinel is a local-first privacy gateway MVP for meeting intelligence on Jetson-class hardware. This bootstrap implements a runnable vertical slice:

1. Paste or load a meeting transcript.
2. Record or upload meeting audio and transcribe it through ElevenLabs Speech to Text.
3. Analyze the resulting transcript locally with the Sentinel Privacy Engine.
4. Detect sensitive entities, secrets, dates, money, clients, and identities.
5. Block restricted data, pseudonymize confidential data, and minimize internal data.
6. Send the safe payload to the configured external AI API for intelligence.
7. Keep vault mappings, vector memory, and audit events local in SQLite.

## Repository Layout

```text
apps/api        FastAPI app
apps/web        React, TypeScript, Vite UI
sentinel        Modular monolith domain code
data/samples    Demo transcripts
data/local      Local SQLite runtime data
tests           Privacy and gateway tests
docs            Architecture, threat model, demo flow
```

## API Intelligence

The web app runs in API-backed intelligence mode. Sentinel still performs privacy detection, redaction, pseudonymization, validation, vault mapping, and audit logging locally before any provider call.

External AI calls are sent only when `EXTERNAL_AI_ENABLED=true`, a provider key is configured, the safe payload passes local validation, and the request has an explicit purpose.

## Audio Transcription

Sentinel can receive browser microphone recordings or uploaded audio/video files and transcribe them server-side with ElevenLabs. The browser never receives the ElevenLabs key; it sends raw audio to Sentinel, and the API calls `POST https://api.elevenlabs.io/v1/speech-to-text` with `model_id=scribe_v2`.

Configure:

```bash
ELEVENLABS_API_KEY=your_key_here
ELEVENLABS_STT_MODEL=scribe_v2
ELEVENLABS_ENABLE_LOGGING=true
```

For enterprise ElevenLabs accounts, `ELEVENLABS_ENABLE_LOGGING=false` requests zero retention mode for transcription requests. Keep it `true` if your account does not support zero retention.

API endpoint:

- `POST /api/audio/transcribe`

After transcription, the text is placed into the same local privacy, memory, ticket routing, and safe external AI pipeline.

## Local Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
make install-dev
cp .env.example .env
make test
make api
```

In a second terminal:

```bash
make web
```

Open `http://127.0.0.1:5173`.

## API Highlights

- `GET /health`
- `GET /api/system/status`
- `POST /api/audio/transcribe`
- `POST /api/privacy/analyze`
- `POST /api/privacy/sanitize`
- `POST /api/meetings`
- `POST /api/meetings/{id}/analyze`
- `GET /api/meetings/{id}`
- `GET /api/meetings/{id}/privacy-report`
- `GET /api/meetings/{id}/tasks`
- `GET /api/audit/events`
- `POST /api/ai/analyze-safe-content`

## Security Boundary

The Entity Vault and audit log are local SQLite tables. The current vault is a demo implementation and stores plaintext mappings locally so reconstruction is visible during the buildathon. Production hardening should add encryption at rest, hardware-backed key management, access control, retention policies, and tamper-evident audit records.
