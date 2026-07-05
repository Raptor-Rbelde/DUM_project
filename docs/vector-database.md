# Local Vector Database

Sentinel stores enterprise memory in a local SQLite-backed vector database.

## Design

```text
transcript
-> privacy engine
-> safe chunks
-> local embedding per chunk
-> memory_embeddings table
-> cosine-similarity retrieval
-> safe context for local or external analysis
```

The vector index is local. No transcript, safe chunk, or embedding is sent to an external provider to build the index.

## Tables

- `memory_items`: remembered transcripts/documents.
- `memory_chunks`: searchable text units.
- `memory_embeddings`: vector per chunk and model.

Each embedding row stores:

- `chunk_id`
- `model`
- `vector_json`
- `dimensions`
- `source_text_hash`
- `created_at`

## Embedding Model

Current model:

```text
sentinel-local-hashing-v1
```

It is a deterministic local hashing vectorizer with 384 dimensions. It uses normalized tokens, stems, character n-grams, and domain synonym groups for business/security terms such as payroll, treasury, credentials, incidents, decisions, and tasks.

This is intentionally dependency-free so it can run on a MacBook and later on Sentinel hardware. It can later be replaced with a heavier local embedding model while preserving the same `memory_embeddings` storage contract.

## Retrieval

`PersistentMemoryStore.search()` now performs hybrid ranking:

- lexical overlap for exact terms;
- vector cosine similarity for semantic recall.

This lets questions find relevant memory even when wording differs from the transcript, for example `pago de empleados` matching transcript content about `nomina`.
