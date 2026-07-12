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

## Live service

Deployed at `https://lesschoice-backend-798630052741.australia-southeast1.run.app`
in the `todzhangphray` GCP project, region `australia-southeast1` (Sydney).

## Deploying to Google Cloud Run (manual)

```bash
gcloud run deploy lesschoice-backend \
  --project todzhangphray \
  --source . \
  --region australia-southeast1 \
  --allow-unauthenticated \
  --set-secrets="GEMINI_API_KEY=gemini-api-key:latest,GOOGLE_PLACES_API_KEY=google-places-api-key:latest,APP_SHARED_SECRET=app-shared-secret:latest"
```

`--allow-unauthenticated` is required since the iOS app calls this over plain
HTTPS with the app-level shared secret, not Google IAM auth. The shared
secret plus per-IP rate limiting (`RATE_LIMIT` env var, default `30/minute`)
is what stands between this endpoint and abuse — see the cost-control
discussion in the iOS repo's `APP_STORE_PUBLISHING.md` for context.

The actual API keys and app secret live in Google Secret Manager
(`gemini-api-key`, `google-places-api-key`, `app-shared-secret` in project
`todzhangphray`), not as plain Cloud Run env vars — this keeps them out of
revision metadata, `gcloud run services describe` output, and any CI logs.

## Automated deploys (GitHub Actions)

`.github/workflows/deploy.yml` deploys to Cloud Run on every push to `main`.
It authenticates to Google Cloud via Workload Identity Federation (no
long-lived JSON key stored in GitHub) — the trust is scoped to this exact
repo (`CloudsDocker/lesschoice-backend`) via a workload identity pool
provider already configured in the `todzhangphray` project
(`github-pool` / `github-provider`), bound to the
`github-actions-deployer@todzhangphray.iam.gserviceaccount.com` service
account. No GitHub Secrets are needed for the deploy — the API keys are
pulled straight from Secret Manager at deploy time via `--set-secrets`.

If this repo is ever renamed or moved to a different org, the workload
identity pool provider's `--attribute-condition` needs updating to match, or
the Action will fail to authenticate.

After deploying, also set on the Google Cloud side:
- Restrict the Places API key to this Cloud Run service's IP range if
  possible, or at minimum to the "Places API" only (no bundle ID restriction
  needed anymore since the key never reaches the client).
- Set a daily quota cap on Places Text Search and a spend cap/budget alert on
  the Gemini key, same as before — the backend reduces call volume via
  caching but doesn't eliminate the need for a hard ceiling.

## Caching

Both caches are persistent and shared across Cloud Run instances/restarts —
no more losing the cache on every cold start:

- **Suggestions + photo references** — Firestore, database `lesschoice-cache`
  (Native mode, `australia-southeast1`), collections `suggestions_cache` and
  `photo_references`. Each doc has an `expires_at` Timestamp field with a
  native Firestore TTL policy enabled on it, so expired docs are purged
  automatically (can lag up to ~24h; `FirestoreCache.get` also checks
  expiry itself so stale-but-not-yet-purged docs are never served).
- **Photo image bytes** — Cloud Storage bucket `lesschoice-photo-cache`
  (`australia-southeast1`), objects at `photos/<reference>_<maxwidth>.jpg`.
  A bucket lifecycle rule deletes objects after 7 days
  (`gsutil lifecycle get gs://lesschoice-photo-cache` to inspect/change it).

The Cloud Run runtime service account
(`798630052741-compute@developer.gserviceaccount.com`) has `roles/datastore.user`
on the project and `roles/storage.objectAdmin` on the bucket — both already
granted. Local dev needs `gcloud auth application-default login` for these
clients to authenticate.
