# Deployment

TEO ships as one Docker web service:

- FastAPI serves the API at `/api/*`.
- FastAPI also serves the compiled React app from `apps/web/dist`.
- SQLite memory, vault, vectors, and audit data are written to `/var/data/sentinel.sqlite`.

## Recommended Buildathon Deploy

Use Render with the included `render.yaml`.

Why this target:

- It provides HTTPS, which the browser needs for reliable microphone permissions outside localhost.
- It can run the API and frontend from one Docker service.
- It supports a persistent disk for the local SQLite memory.

## Required Secrets

Set these in the Render dashboard when prompted by the Blueprint:

```text
OPENAI_API_KEY
ELEVENLABS_API_KEY
```

Optional: add `ELEVENLABS_TTS_VOICE_ID` only if you want to override the default multilingual voice configured by the backend.

## Render Steps

1. Push this repository to GitHub.
2. In Render, create a new Blueprint from the repo.
3. Confirm the `teo-sentinel` web service.
4. Enter the secret values requested by `render.yaml`.
5. Deploy.
6. Open the generated HTTPS URL and test:
   - `/health`
   - `/api/security/checks`
   - the root web app `/`

## Local Production Smoke Test

After a frontend build, the API can serve the production app locally:

```bash
cd apps/web
npm run build
cd ../..
.venv/bin/python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

## Docker Smoke Test

```bash
docker build -t teo-sentinel .
docker run --rm -p 8000:8000 \
  -e EXTERNAL_AI_ENABLED=true \
  -e OPENAI_API_KEY=your_openai_key \
  -e ELEVENLABS_API_KEY=your_elevenlabs_key \
  -v teo-sentinel-data:/var/data \
  teo-sentinel
```

Open `http://127.0.0.1:8000`.

## Notes

- Do not commit `.env`; the Docker context ignores it.
- Persistent memory requires a mounted volume or platform disk.
- On Render, only data written below `/var/data` is expected to survive restarts and deploys.
