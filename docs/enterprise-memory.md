# Enterprise Memory

Sentinel now includes a local enterprise-memory layer for transcripts.

## Flow

```text
raw transcript
-> local privacy analysis
-> safe transcript with placeholders
-> local SQLite memory item
-> searchable memory chunks
-> summary, tasks, decisions, risks
-> future questions over retrieved safe context
```

Raw transcripts stay local in SQLite. Optional external AI receives only safe memory snippets with placeholders.

## API

Remember a transcript:

```http
POST /api/memory/remember
```

Ask the accumulated memory:

```http
POST /api/memory/ask
```

Search relevant snippets:

```http
GET /api/memory/search?q=...
```

List dashboard entries:

```http
GET /api/memory/items
```

Open a memory item:

```http
GET /api/memory/items/{memory_id}
```

Delete a memory item:

```http
DELETE /api/memory/items/{memory_id}
```

Read memory counts:

```http
GET /api/memory/status
```

## Modes

- `VAULT`: retrieves and reconstructs local memory snippets without calling an external provider.
- `INTELLIGENCE`: sends only safe retrieved snippets to the configured external provider, then reconstructs authorized placeholders locally.

This makes Sentinel behave like a growing enterprise assistant: the more meetings it remembers, the more context it can retrieve for future questions.

## Dashboard

The web app includes an Enterprise Memory dashboard:

- saved meeting list;
- local search over title, summary, tasks, decisions, and risks;
- meeting detail view;
- original transcript;
- safe transcript;
- reconstructed summary, tasks, decisions, and risks;
- delete action for local memory entries.
