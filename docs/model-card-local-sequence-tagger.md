# Sentinel Local Sequence Tagger Model Card

## Model

- Name: `sentinel-local-sensitive-sequence-tagger-v1`
- Artifact: `data/models/sensitive_sequence_tagger.json`
- Family: averaged perceptron sequence tagger
- Runtime dependencies: Python standard library only
- Training command:

```bash
.venv/bin/python scripts/train_local_ml_detector.py --output data/models/sensitive_sequence_tagger.json
```

## Purpose

The model detects sensitive operational spans in meeting transcripts before any optional external AI call. It is designed to preserve reasoning context with placeholders while keeping raw sensitive values inside Sentinel.

## Labels

- `O`
- `CLASSIFICATION`
- `CODE_NAME`
- `FACILITY`
- `INTERNAL_PROJECT`
- `ORGANIZATION`
- `ROLE`
- `SECRET_REFERENCE`
- `SECURITY_CONTROL`

## Architecture

The detector uses a hybrid design:

```text
regex restricted-secret detector
-> local sequence tagger
-> overlap resolver
-> policy engine
-> local entity vault
```

The sequence tagger predicts a label per token, groups contiguous token labels into spans, and returns `SensitiveEntity` objects.

## Safety Rule

Deterministic restricted-secret rules remain authoritative. API keys, passwords, tokens, private keys, and ID documents are blocked by regex and are not downgraded by the ML model.

## Training Data

The current training set is local and synthetic, built from Spanish/English operational-security meeting templates. It covers sensitive references such as:

- secret references and credentials;
- communication channels and vaults;
- infrastructure controls;
- roles;
- facilities;
- code names and internal projects;
- classification labels;
- organizations.

## Known Limits

This is not a general-purpose LLM and not a transformer. It is a compact local NER-style model optimized for Sentinel's current domain. Accuracy should improve as real, approved, locally labeled examples are added.
