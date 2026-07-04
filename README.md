# Sentinel

Sentinel is a local-first privacy gateway MVP for meeting intelligence on Jetson-class hardware. This bootstrap implements a runnable vertical slice:

1. Paste or load a meeting transcript.
2. Analyze it locally with the Sentinel Privacy Engine.
3. Detect sensitive entities, secrets, dates, money, clients, and identities.
4. Block restricted data, pseudonymize confidential data, and minimize internal data.
5. Produce a safe payload for optional Intelligence Mode.
6. Keep vault mappings and audit events local in SQLite.

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

## Modes

Vault Mode is the default. It never calls an external provider.

Intelligence Mode can call an external provider only when `EXTERNAL_AI_ENABLED=true`, a provider key is configured, the payload passes local validation, and the request has an explicit purpose.

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
