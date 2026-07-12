import asyncio
from typing import Optional

import httpx

from . import config
from .cache import FirestoreCache
from .gcp_clients import storage_bucket

_photo_reference_cache = FirestoreCache("photo_references")


def _cache_key(title: str, context: str) -> str:
    # Firestore document IDs can't contain "/", and keep this readable for debugging.
    key = f"{title.strip().lower()}|{context.strip().lower()}"
    return key.replace("/", "_")


async def find_photo_reference(title: str, context: str) -> Optional[str]:
    key = _cache_key(title, context)
    cached = await _photo_reference_cache.get(key)
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

    await _photo_reference_cache.set(key, reference, config.PHOTO_REFERENCE_CACHE_TTL_SECONDS)
    return reference or None


def _blob_name(reference: str, max_width: int) -> str:
    return f"photos/{reference}_{max_width}.jpg"


async def fetch_photo_bytes(reference: str, max_width: int) -> tuple[bytes, str]:
    blob = storage_bucket().blob(_blob_name(reference, max_width))

    cached_bytes = await asyncio.to_thread(_download_if_exists, blob)
    if cached_bytes is not None:
        return cached_bytes, "image/jpeg"

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

    await asyncio.to_thread(_upload, blob, response.content, content_type)
    return response.content, content_type


def _download_if_exists(blob) -> Optional[bytes]:
    if not blob.exists():
        return None
    return blob.download_as_bytes()


def _upload(blob, data: bytes, content_type: str) -> None:
    blob.upload_from_string(data, content_type=content_type)
