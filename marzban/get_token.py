"""
Marzban token helper (multi-tier, async-safe).
Use get_token(tier="free"|"test"|"vip") to obtain an access token for the requested Marzban account.
Credentials and host are loaded from utils.config (via dotenv).
"""

import time
import base64
import json
import asyncio
import logging
from typing import Optional, Dict

import aiohttp
from utils.config import settings

# Setup logger
logger = logging.getLogger(__name__)

# Cache tokens per tier to avoid repeated authentication requests
_token_cache: Dict[str, Dict[str, object]] = {
    "free": {"token": None, "expires_at": 0},
    "test": {"token": None, "expires_at": 0},
    "vip": {"token": None, "expires_at": 0},
}

# Lock to prevent concurrent token refresh collisions
_token_lock = asyncio.Lock()


def _creds_for(tier: str) -> Dict[str, str]:
    """
    Get Marzban username/password for a given tier.
    """
    t = tier.lower()
    if t == "free":
        return {"username": settings.MARZBAN_USER_FREE, "password": settings.MARZBAN_PASS_FREE}
    if t == "test":
        return {"username": settings.MARZBAN_USER_TEST, "password": settings.MARZBAN_PASS_TEST}
    if t == "vip":
        return {"username": settings.MARZBAN_USER_VIP, "password": settings.MARZBAN_PASS_VIP}
    raise ValueError("tier must be one of: 'free', 'test', 'vip'")


def _extract_exp_from_jwt(token: str) -> Optional[int]:
    """
    Extract 'exp' (expiry timestamp) from a JWT token payload.
    """
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload_b64 = parts[1]
        rem = len(payload_b64) % 4
        if rem:
            payload_b64 += "=" * (4 - rem)
        payload_bytes = base64.urlsafe_b64decode(payload_b64.encode("utf-8"))
        payload = json.loads(payload_bytes.decode("utf-8"))
        exp = payload.get("exp")
        if isinstance(exp, str) and exp.isdigit():
            exp = int(exp)
        if isinstance(exp, int):
            # handle ms timestamps
            if exp > 1e12:
                exp //= 1000
            return exp
    except Exception:
        return None
    return None


async def _request_token(session: aiohttp.ClientSession, host: str, username: str, password: str) -> Dict:
    """
    Send HTTP POST request to Marzban's /api/admin/token endpoint.
    """
    base = host.rstrip("/")
    url = f"{base}/api/admin/token"
    data = {"username": username, "password": password}

    try:
        async with session.post(url, json=data, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            body = await resp.json(content_type=None)
            return {"status": resp.status, "body": body}
    except asyncio.TimeoutError:
        raise RuntimeError("Timeout while connecting to Marzban host.")
    except aiohttp.ClientError as e:
        raise RuntimeError(f"Connection error: {e}") from e


async def get_token(tier: str = "free", force: bool = False, session: Optional[aiohttp.ClientSession] = None) -> str:
    """
    Retrieve an access token for a given Marzban tier (free/test/vip).
    Uses caching and JWT expiry extraction for reuse until expiration.
    """
    t = tier.lower()
    if t not in _token_cache:
        raise ValueError("tier must be one of: 'free', 'test', 'vip'")

    now = time.time()
    cached = _token_cache[t]
    if not force and cached.get("token") and cached.get("expires_at", 0) > now + 5:
        logger.debug(f"Using cached Marzban token for tier '{t}'")
        return cached["token"]

    async with _token_lock:
        # Double-check inside lock
        cached = _token_cache[t]
        if not force and cached.get("token") and cached.get("expires_at", 0) > time.time() + 5:
            return cached["token"]

        creds = _creds_for(t)
        username, password = creds["username"], creds["password"]
        if not username or not password:
            raise RuntimeError(f"Missing credentials for '{t}' in .env file")

        host = settings.MARZBAN_HOST
        if not host:
            raise RuntimeError("MARZBAN_HOST is not defined in .env")

        close_session = False
        if session is None:
            timeout = aiohttp.ClientTimeout(total=10)
            session = aiohttp.ClientSession(timeout=timeout)
            close_session = True

        try:
            res = await _request_token(session, host, username, password)
            status, body = res.get("status"), res.get("body")

            if not (200 <= status < 300):
                raise RuntimeError(f"Token request failed: status={status}, body={body}")

            token = body.get("access_token")
            if not token:
                raise RuntimeError(f"No 'access_token' in response: {body}")

            exp_ts = _extract_exp_from_jwt(token)
            ttl = max(60, int(exp_ts - time.time() - 5)) if exp_ts else 3600

            _token_cache[t]["token"] = token
            _token_cache[t]["expires_at"] = now + ttl

            logger.info(f"New Marzban token cached for '{t}' (valid {ttl:.0f}s)")
            return token

        finally:
            if close_session:
                await session.close()
