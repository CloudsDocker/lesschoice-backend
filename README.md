# lesschoice-backend

Backend for the LessChoice / DecisionDeck app. Holds the Gemini and Google
Places API keys server-side (never shipped in the iOS binary), and caches
place suggestions and photos so popular destinations (Rome, London, New York,
etc.) don't re-trigger a Gemini or Places API call for every user.

## Endpoints

- `POST /v1/suggestions` — proxies Gemini place suggestions. Requires header
  `x-app-secret: <APP_SHARED_SECRET>`. Caches the response for 30 min when the
  request has no personalization signal yet (first load for a given
  prompt+constraints), since that's the case most likely to repeat across
  users hitting the same popular destination.
- `GET /v1/place-photo?title=...&context=...` — looks up a place's photo
  reference via Google Places Text Search (cached 7 days), returns a URL
  pointing at `/v1/photo-image/...` for the actual image bytes. Requires
  `x-app-secret` header.
- `GET /v1/photo-image/{reference}` — proxies the actual photo bytes from
  Google Places Photo API, with a long `Cache-Control` header. Since iOS
  `AsyncImage` can't attach custom headers, this endpoint is authorized via a
  `secret` query param instead (the `photoUrl` returned by `/v1/place-photo`
  already includes it) rather than the `x-app-secret` header.

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in GEMINI_API_KEY, GOOGLE_PLACES_API_KEY, APP_SHARED_SECRET
export $(cat .env | xargs)
uvicorn app.main:app --reload
```

## Deploying to Google Cloud Run

```bash
gcloud run deploy lesschoice-backend \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars GEMINI_API_KEY=...,GOOGLE_PLACES_API_KEY=...,APP_SHARED_SECRET=...
```

`--allow-unauthenticated` is required since the iOS app calls this over plain
HTTPS with the app-level shared secret, not Google IAM auth. The shared
secret plus per-IP rate limiting (`RATE_LIMIT` env var, default `30/minute`)
is what stands between this endpoint and abuse — see the cost-control
discussion in the iOS repo's `APP_STORE_PUBLISHING.md` for context.

After deploying, also set on the Google Cloud side:
- Restrict the Places API key to this Cloud Run service's IP range if
  possible, or at minimum to the "Places API" only (no bundle ID restriction
  needed anymore since the key never reaches the client).
- Set a daily quota cap on Places Text Search and a spend cap/budget alert on
  the Gemini key, same as before — the backend reduces call volume via
  caching but doesn't eliminate the need for a hard ceiling.

## Cache limitations

The cache is in-process (a plain dict with TTLs), not Redis/Firestore. Cloud
Run can run multiple instances and recycles them on scale-to-zero, so this is
best-effort: it cuts a lot of repeat calls within an instance's lifetime but
isn't a global cache. If usage grows enough that this matters, swap `TTLCache`
in `app/cache.py` for a Redis-backed one (e.g. via Memorystore) without
changing any calling code.
