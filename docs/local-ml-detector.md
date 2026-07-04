# Local ML Detector

Sentinel should use a hybrid privacy detector:

```text
deterministic secret rules
-> local ML named-entity recognition
-> context-preserving placeholder assignment
-> policy engine
-> entity vault
-> safe payload
```

## Why Hybrid

Secrets should not depend only on an ML model. API keys, passwords, tokens, private keys, ID documents, and blocked markers are best handled with deterministic high-recall rules.

Names, organizations, clients, dates, internal projects, and domain-specific terms benefit from local ML because they vary by language, writing style, and company vocabulary.

## Context-Preserving Placeholders

Sentinel should not destroy useful context before optional external analysis. If the external model needs to answer a question such as "what date was mentioned?", the safe payload must contain a unique local placeholder:

```text
Original: launch target is 2026-08-15
Safe:     launch target is [DATE_A12F]
External answer: The date was [DATE_A12F].
Local answer:    The date was 2026-08-15.
```

This gives the external model enough structure to reason over the full meeting while keeping real values inside the local Entity Vault.

## Current Final Local Model

The project now includes a dependency-free sequence-tagging model:

```text
scripts/train_local_ml_detector.py
-> data/models/sensitive_sequence_tagger.json
-> HybridSensitiveDataDetector
-> PrivacyEngine
```

It is an averaged-perceptron sequence tagger. It tokenizes the transcript, predicts a sensitive label for each token, groups contiguous labels back into spans, and returns `SensitiveEntity` objects to the existing Privacy Engine.

The runtime has no third-party ML dependencies. The model artifact is plain JSON, so the same file can run on the MacBook during development and later be copied to the Sentinel runtime without downloading model weights.

Train or refresh it locally:

```bash
.venv/bin/python scripts/train_local_ml_detector.py --output data/models/sensitive_sequence_tagger.json
```

Runtime settings:

```env
SENTINEL_LOCAL_ML_ENABLED=true
SENTINEL_LOCAL_ML_MODEL_PATH=data/models/sensitive_sequence_tagger.json
```

The current labels are:

- `O`
- `CLASSIFICATION`
- `CODE_NAME`
- `FACILITY`
- `INTERNAL_PROJECT`
- `ORGANIZATION`
- `ROLE`
- `SECRET_REFERENCE`
- `SECURITY_CONTROL`

The previous span-level Naive Bayes model remains loadable for compatibility as `data/models/sensitive_span_nb.json`, but the default local model is now `data/models/sensitive_sequence_tagger.json`.

The model augments regex detection. It does not classify raw API keys, passwords, tokens, or private keys as safe; deterministic rules remain authoritative for restricted secrets.

See `docs/model-card-local-sequence-tagger.md` for the model card.

## Jetson-Friendly Path

For the next implementation phase, run the ML detector locally on the Jetson:

- start with a compact NER model;
- export to ONNX where possible;
- quantize to INT8 if accuracy remains acceptable;
- run inference with ONNX Runtime or TensorRT;
- keep raw transcripts local;
- return only `SensitiveEntity` objects to the existing Privacy Engine.

## Adapter Boundary

The detector should expose the same shape as the current detector:

```python
class SensitiveDataDetector:
    def detect(self, text: str) -> list[SensitiveEntity]:
        ...
```

This lets Sentinel swap:

- regex-only detector;
- local ML detector;
- hybrid regex + local ML detector;
- future domain-tuned detector.

## Recommended Production Rule

Never let ML downgrade deterministic secret matches. If a regex finds an API key, token, password, or private key, the final action must remain `BLOCK`.

ML can add entities or improve classification, but it should not override restricted-data blocking.
