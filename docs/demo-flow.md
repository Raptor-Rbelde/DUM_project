# Demo Flow

## Goal

Show Sentinel as a local privacy gateway that sends only safe payloads to the configured external AI API.

## Steps

1. Start the API with `make api`.
2. Start the UI with `make web`.
3. Open `http://127.0.0.1:5173`.
4. Select `Confidential`.
5. Run `Analyze with API`.
7. Show:
   - identities detected;
   - client detected;
   - money detected;
   - pseudonymized values;
   - minimized dates;
   - original text versus safe payload.
8. Select `Dangerous`.
9. Run `Analyze with API`.
10. Show the fake API key and password blocked.
11. Run again with `EXTERNAL_AI_ENABLED=false`.
12. Show that external AI is blocked when the API switch is disabled.

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
