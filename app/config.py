import os

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GOOGLE_PLACES_API_KEY = os.environ["GOOGLE_PLACES_API_KEY"]
APP_SHARED_SECRET = os.environ["APP_SHARED_SECRET"]

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")

# Suggestions depend on the user's liked/blacklisted history, but the very first
# load for a given prompt+constraints (no history yet) repeats a lot across users
# hitting the same popular destinations, so it's worth caching briefly.
SUGGESTIONS_CACHE_TTL_SECONDS = int(os.environ.get("SUGGESTIONS_CACHE_TTL_SECONDS", 60 * 30))

# Photo lookups for a given place rarely change, so cache them much longer.
PHOTO_REFERENCE_CACHE_TTL_SECONDS = int(os.environ.get("PHOTO_REFERENCE_CACHE_TTL_SECONDS", 60 * 60 * 24 * 7))
PHOTO_IMAGE_CACHE_TTL_SECONDS = int(os.environ.get("PHOTO_IMAGE_CACHE_TTL_SECONDS", 60 * 60 * 24 * 7))

RATE_LIMIT = os.environ.get("RATE_LIMIT", "30/minute")

GCP_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "todzhangphray")
FIRESTORE_DATABASE = os.environ.get("FIRESTORE_DATABASE", "lesschoice-cache")
PHOTO_BUCKET_NAME = os.environ.get("PHOTO_BUCKET_NAME", "lesschoice-photo-cache")

APPLE_TEAM_ID = os.environ.get("APPLE_TEAM_ID", "ZLQUC8CBXW")
APPLE_BUNDLE_ID = os.environ.get("APPLE_BUNDLE_ID", "com.hdeazy.selectless")
# Rollout switch: keep False until a client build that actually sends attestation
# headers is confirmed live, otherwise every existing installed build starts 401ing.
REQUIRE_APP_ATTEST = os.environ.get("REQUIRE_APP_ATTEST", "false").lower() == "true"
