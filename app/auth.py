import logging

from fastapi import Header, HTTPException

from . import attestation, config

logger = logging.getLogger("lesschoice.attest")


async def require_app_secret(x_app_secret: str = Header(default="")) -> None:
    if x_app_secret != config.APP_SHARED_SECRET:
        raise HTTPException(status_code=401, detail="invalid or missing x-app-secret header")


async def require_attested_device(
    x_key_id: str = Header(default=""),
    x_assertion: str = Header(default=""),
    x_challenge: str = Header(default=""),
) -> None:
    if not config.REQUIRE_APP_ATTEST:
        return

    if not (x_key_id and x_assertion and x_challenge):
        raise HTTPException(status_code=401, detail="missing App Attest headers")

    try:
        await attestation.verify_assertion(x_key_id, x_assertion, x_challenge)
    except attestation.AttestationError as exc:
        logger.warning("assertion rejected for keyId=%s: %s", x_key_id, exc)
        raise HTTPException(status_code=401, detail=str(exc)) from exc
