# Threat Model

## Assets

- Raw meeting transcripts.
- Entity Vault mappings.
- Meeting summaries, decisions, and tasks.
- Audit events.
- API keys and provider credentials.
- Local enterprise memory.

## Trust Boundary

The Jetson device is the privacy boundary. Enterprise data remains local by default. External providers are outside the trust boundary and receive only safe payloads that passed local validation.

## Initial Threats

- Accidental exfiltration of raw transcripts.
- Secrets included in pasted meeting text.
- Pseudonym vault leakage.
- Logs containing secrets or full restricted payloads.
- Frontend exposure of provider API keys.
- Direct provider calls bypassing the Cloud Gateway.
- Internet unavailability during Vault Mode.

## MVP Controls

- Vault Mode blocks all provider calls.
- `EXTERNAL_AI_ENABLED=false` by default.
- Provider API keys are read only from environment variables.
- Secret-like values are classified as `RESTRICTED` and blocked.
- Confidential values are replaced with local vault placeholders.
- Audit logs store fingerprints and metadata, not raw secret values.
- The frontend only talks to the local API.

## Production Hardening

- Encrypt Entity Vault mappings at rest.
- Bind encryption keys to hardware-backed storage where available.
- Add authenticated local operator sessions.
- Add signed, append-only audit logs.
- Add policy versioning and approval workflows.
- Add model cards and provider-specific data retention checks.
- Add outbound network controls at the OS level.
