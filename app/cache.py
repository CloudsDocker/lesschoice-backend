from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .gcp_clients import firestore_client


class FirestoreCache:
    """TTL cache backed by Firestore so entries survive instance restarts and are
    shared across Cloud Run instances, instead of the old in-process dict which
    was lost on every cold start and not shared between concurrent instances.

    `expires_at` is stored as a real Firestore Timestamp so Firestore's native TTL
    policy (see infra/setup) purges expired docs automatically; the explicit check
    here is a fallback since native TTL deletion can lag up to ~24h."""

    def __init__(self, collection: str):
        self._collection = collection

    async def get(self, key: str) -> Optional[Any]:
        doc = await firestore_client().collection(self._collection).document(key).get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        if data["expires_at"] < datetime.now(timezone.utc):
            return None
        return data["value"]

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        await firestore_client().collection(self._collection).document(key).set({
            "value": value,
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
        })
