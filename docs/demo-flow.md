# Demo Flow

## Goal

Show Sentinel as a local-first privacy gateway before optional external AI.

## Steps

1. Start the API with `make api`.
2. Start the UI with `make web`.
3. Open `http://127.0.0.1:5173`.
4. Select `Confidential`.
5. Keep `Vault Mode` selected.
6. Run `Analyze locally`.
7. Show:
   - identities detected;
   - client detected;
   - money detected;
   - pseudonymized values;
   - minimized dates;
   - original text versus safe payload.
8. Select `Dangerous`.
9. Run `Analyze locally`.
10. Show the fake API key and password blocked.
11. Switch to `Intelligence Mode`.
12. Run again with `EXTERNAL_AI_ENABLED=false`.
13. Show that external AI remains blocked by default.

## Visual Story

```text
ORIGINAL DATA
-> SENTINEL PRIVACY ENGINE
-> SAFE PAYLOAD
-> OPTIONAL EXTERNAL AI
-> LOCAL RECONSTRUCTION
```

The dangerous transcript uses only fake demo credentials:

```text
OPENAI_API_KEY=sk-example-not-real-123456789
```
