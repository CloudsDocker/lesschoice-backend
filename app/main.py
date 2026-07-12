import hashlib
import json

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from . import config
from .auth import require_app_secret
from .cache import FirestoreCache
from .gemini_service import GeminiError, fetch_places
from .places_service import fetch_photo_bytes, find_photo_reference

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="lesschoice-backend")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

_suggestions_cache = FirestoreCache("suggestions_cache")


class SuggestionsRequest(BaseModel):
    prompt: str
    constraints: str
    likedTitles: list[str] = []
    blacklistedTitles: list[str] = []
    alreadySuggestedTitles: list[str] = []
    count: int = 5


@app.get("/status")
async def status():
    return {"status": "ok"}


@app.post("/v1/suggestions", dependencies=[Depends(require_app_secret)])
@limiter.limit(config.RATE_LIMIT)
async def suggestions(request: Request, body: SuggestionsRequest):
    # Only cache the "cold start" case: no personalization signal yet, so many
    # users hitting the same popular destination/constraints get a shared cache hit.
    cache_key = None
    if not body.likedTitles and not body.blacklistedTitles and not body.alreadySuggestedTitles:
        raw_key = f"{body.prompt.strip().lower()}|{body.constraints.strip().lower()}|{body.count}"
        cache_key = hashlib.sha256(raw_key.encode()).hexdigest()
        cached = await _suggestions_cache.get(cache_key)
        if cached is not None:
            return json.loads(cached)

    try:
        places = await fetch_places(
            prompt=body.prompt,
            constraints=body.constraints,
            liked_titles=body.likedTitles,
            blacklisted_titles=body.blacklistedTitles,
            already_suggested_titles=body.alreadySuggestedTitles,
            count=body.count,
        )
    except GeminiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if cache_key is not None:
        await _suggestions_cache.set(cache_key, json.dumps(places), config.SUGGESTIONS_CACHE_TTL_SECONDS)

    return places


@app.get("/v1/place-photo", dependencies=[Depends(require_app_secret)])
@limiter.limit(config.RATE_LIMIT)
async def place_photo(request: Request, title: str = Query(...), context: str = Query(...)):
    reference = await find_photo_reference(title, context)
    if reference is None:
        return {"photoUrl": None}
    photo_url = f"/v1/photo-image/{reference}?maxwidth=800&secret={config.APP_SHARED_SECRET}"
    return {"photoUrl": photo_url}


@app.get("/v1/photo-image/{reference}")
@limiter.limit(config.RATE_LIMIT)
async def photo_image(request: Request, reference: str, maxwidth: int = 800, secret: str = Query(default="")):
    # AsyncImage on iOS can't attach custom headers, so this one endpoint is
    # authorized via a query-string secret instead of the x-app-secret header.
    if secret != config.APP_SHARED_SECRET:
        raise HTTPException(status_code=401, detail="invalid or missing secret")

    image_bytes, content_type = await fetch_photo_bytes(reference, maxwidth)
    return Response(
        content=image_bytes,
        media_type=content_type,
        headers={"Cache-Control": f"public, max-age={config.PHOTO_IMAGE_CACHE_TTL_SECONDS}"},
    )
