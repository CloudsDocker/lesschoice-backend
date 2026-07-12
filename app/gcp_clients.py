from functools import lru_cache

from google.cloud import storage
from google.cloud.firestore import AsyncClient

from . import config


@lru_cache
def firestore_client() -> AsyncClient:
    return AsyncClient(project=config.GCP_PROJECT_ID, database=config.FIRESTORE_DATABASE)


@lru_cache
def storage_bucket() -> storage.Bucket:
    client = storage.Client(project=config.GCP_PROJECT_ID)
    return client.bucket(config.PHOTO_BUCKET_NAME)
