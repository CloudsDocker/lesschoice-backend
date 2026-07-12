from fastapi import Header, HTTPException

from . import config


async def require_app_secret(x_app_secret: str = Header(default="")) -> None:
    if x_app_secret != config.APP_SHARED_SECRET:
        raise HTTPException(status_code=401, detail="invalid or missing x-app-secret header")
