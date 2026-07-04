# Sentinel Architecture

Sentinel is a modular monolith designed to run locally on an NVIDIA Jetson Orin Nano. The Jetson is treated as a trust boundary and privacy gateway.

## Runtime Modules

- `sentinel.domain`: shared typed models.
- `sentinel.privacy`: detection, policy, pseudonymization, and reconstruction.
- `sentinel.audit`: local audit event store with payload fingerprints, never raw secrets.
- `sentinel.meetings`: meeting persistence and analysis orchestration.
- `sentinel.tasks`: local heuristic summary, task, and decision extraction.
- `sentinel.memory`: memory store abstraction for later local knowledge work.
- `sentinel.providers`: provider interfaces, OpenAI adapter, and Cloud Gateway.
- `apps.api`: FastAPI composition root.
- `apps.web`: touchscreen-friendly React UI.

## Privacy Pipeline

```text
INPUT
-> CLASSIFICATION
-> SENSITIVE DATA DETECTION
-> POLICY ENGINE
-> REDACTION / PSEUDONYMIZATION
-> DATA MINIMIZATION
-> EXPLICIT CLOUD POLICY
-> EXTERNAL PROVIDER
```

The domain never calls an external LLM directly. Optional provider calls must pass through:

```text
CloudGateway -> PrivacyPolicy -> SafePayloadValidator -> ProviderAdapter
```

## Detection Strategy

The current MVP uses deterministic local detectors with explicit priority rules. The next hardening step is a hybrid detector: deterministic rules for secrets and a local ML named-entity-recognition model for names, organizations, dates, clients, and internal projects. See `docs/local-ml-detector.md`.

## Persistence

SQLite stores:

- entity vault mappings;
- audit events;
- meetings;
- privacy reports;
- summaries;
- tasks;
- decisions.

The MVP uses one database at `data/local/sentinel.sqlite` by default. This keeps the buildathon workflow simple and still preserves clear module boundaries for later service extraction.
