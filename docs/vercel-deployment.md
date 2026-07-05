# Vercel Deployment

TEO can be deployed to Vercel with `Dockerfile.vercel`, but this target is best treated as a demo/preview deploy.

## Important Difference

Vercel Container Images run as Vercel Functions. That means:

- The app can run from an OCI/Docker image.
- The container should listen on `$PORT`.
- Instances can scale down when idle.
- Vercel Function limits still apply.
- Local SQLite memory is ephemeral unless replaced with external storage.

For persistent enterprise memory, prefer the Render deployment in `render.yaml`, or move the memory/vault database to a managed external database before using Vercel as the primary production host.

## Files

- `Dockerfile.vercel`: Vercel-specific container image.
- `Dockerfile`: Render/general container with `/var/data` persistent disk support.

## Required Environment Variables

Set these in Vercel Project Settings:

```text
EXTERNAL_AI_ENABLED=true
PORT=8000
OPENAI_API_KEY=...
ELEVENLABS_API_KEY=...
SENTINEL_LOCAL_ML_ENABLED=true
SENTINEL_LOCAL_ML_MODEL_PATH=/app/data/models/sensitive_sequence_tagger.json
SENTINEL_WEB_DIST=/app/apps/web/dist
SENTINEL_DATA_DIR=/tmp/sentinel-data
SENTINEL_DB_PATH=/tmp/sentinel-data/sentinel.sqlite
OPENAI_MODEL=gpt-4o-mini
ELEVENLABS_STT_MODEL=scribe_v2
ELEVENLABS_TTS_MODEL=eleven_multilingual_v2
ELEVENLABS_ENABLE_LOGGING=true
```

Optional:

```text
ELEVENLABS_TTS_VOICE_ID=...
```

## Deploy Steps

1. Push the repo to GitHub.
2. Import the project in Vercel.
3. Ensure Vercel detects `Dockerfile.vercel`.
4. Add the environment variables above.
5. Deploy.
6. Test:
   - `/`
   - `/health`
   - `/api/security/checks`

## Local Vercel-Container Smoke Test

```bash
docker build -f Dockerfile.vercel -t teo-sentinel:vercel-smoke .
docker run --rm -p 8002:8000 \
  -e EXTERNAL_AI_ENABLED=false \
  teo-sentinel:vercel-smoke
```

Open `http://127.0.0.1:8002`.

## Caveats

- Audio uploads to Vercel Functions are subject to Vercel request/response body limits.
- Meeting memory written to `/tmp` can disappear when the function instance is recycled.
- Long-running background behavior is not guaranteed because Vercel scales idle function containers down.
