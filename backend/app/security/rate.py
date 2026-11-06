import hashlib
import hmac
from typing import cast

from fastapi import HTTPException

from backend.app.services.resources import Resources


def account_rate(resources: Resources, email: str, action: str) -> None:
    identifier = hmac.new(
        resources.settings.jwt_secret.get_secret_value().encode(),
        email.casefold().encode(),
        hashlib.sha256,
    ).hexdigest()
    try:
        count = resources.redis.eval(
            "local n=redis.call('INCR',KEYS[1]); "
            "if n==1 then redis.call('EXPIRE',KEYS[1],60) end; return n",
            1,
            f"account-rate:{action}:{identifier}",
        )
        if int(cast(str, count)) > 10:
            raise HTTPException(429, "Rate limit exceeded", headers={"Retry-After": "60"})
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "Rate limit service unavailable") from None
