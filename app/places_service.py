from typing import Optional

import httpx

from . import config
from .cache import TTLCache

_photo_reference_cache = TTLCache()


def _cache_key(title: str, context: str) -> str:
    return f"{title.strip().lower()}|{context.strip().lower()}"


async def find_photo_reference(title: str, context: str) -> Optional[str]:
    key = _cache_key(title, context)
    cached = _photo_reference_cache.get(key)
    if cached is not None:
        return cached or None  # cached empty string means "looked up, no photo"

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            "https://maps.googleapis.com/maps/api/place/textsearch/json",
            params={"query": f"{title} {context}", "key": config.GOOGLE_PLACES_API_KEY},
        )

    reference = ""
    if response.status_code == 200:
        results = response.json().get("results") or []
        if results:
            photos = results[0].get("photos") or []
            if photos:
                reference = photos[0].get("photo_reference", "")

    _photo_reference_cache.set(key, reference, config.PHOTO_REFERENCE_CACHE_TTL_SECONDS)
    return reference or None


async def fetch_photo_bytes(reference: str, max_width: int) -> tuple[bytes, str]:
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        response = await client.get(
            "https://maps.googleapis.com/maps/api/place/photo",
            params={
                "maxwidth": max_width,
                "photo_reference": reference,
                "key": config.GOOGLE_PLACES_API_KEY,
            },
        )
    response.raise_for_status()
    content_type = response.headers.get("content-type", "image/jpeg")
    return response.content, content_type
