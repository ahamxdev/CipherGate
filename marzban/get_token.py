"""
Marzban token helper (multi-tier).
Use get_token(tier="free"|"test"|"vip") to obtain an access token for the requested Marzban account.
Credentials are read directly from utils.config (loaded via dotenv).
"""

import time
import base64
import json
from typing import Optional, Dict
import aiohttp

import utils.config as config  # Environment-based settings loader

# Cache tokens per tier to avoid repeated authentication requests
_token_cache: Dict[str, Dict[str, object]] = {
    "free": {"token": None, "expires_at": 0},
    "test": {"token": None, "expires_at": 0},
    "vip": {"token": None, "expires_at": 0},
}


def _creds_for(tier: str) -> Dict[str, str]:
    """
    Get Marzban username/password for a given tier.

    Args:
        tier (str): One of "free", "test", "vip".

    Returns:
        dict: A dictionary containing {"username": str, "password": str}.
    """
    t = tier.lower()
    if t == "free":
        return {"username": config.MARZBAN_USER_FREE, "password": config.MARZBAN_PASS_FREE}
    if t == "test":
        return {"username": config.MARZBAN_USER_TEST, "password": config.MARZBAN_PASS_TEST}
    if t == "vip":
        return {"username": config.MARZBAN_USER_VIP, "password": config.MARZBAN_PASS_VIP}
    raise ValueError("tier must be one of: 'free', 'test', 'vip'")


def _extract_exp_from_jwt(token: str) -> Optional[int]:
    """
    Extract 'exp' (expiry timestamp) from a JWT token payload.

    Args:
        token (str): JWT access token string.

    Returns:
        Optional[int]: Expiration timestamp if found, otherwise None.
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
        if isinstance(exp, int):
            return exp
        if isinstance(exp, str) and exp.isdigit():
            return int(exp)
    except Exception:
        return None
    return None


async def _request_token(session: aiohttp.ClientSession, host: str, username: str, password: str) -> Dict:
    """
    Send HTTP POST request to Marzban's /api/admin/token endpoint.

    Args:
        session (aiohttp.ClientSession): Active HTTP session.
        host (str): Base Marzban URL.
        username (str): Admin username.
        password (str): Admin password.

    Returns:
        dict: Response status and parsed JSON body.
    """
    base = host.rstrip("/")
    url = f"{base}/api/admin/token"
    data = {"username": username, "password": password}
    async with session.post(url, data=data, timeout=10) as resp:
        body = await resp.json()
        return {"status": resp.status, "body": body}


async def get_token(tier: str = "free", force: bool = False, session: Optional[aiohttp.ClientSession] = None) -> str:
    """
    Retrieve an access token for a given Marzban user tier.

    Args:
        tier (str, optional): User tier ("free", "test", "vip"). Defaults to "free".
        force (bool, optional): If True, ignores cache and fetches new token. Defaults to False.
        session (aiohttp.ClientSession, optional): Reusable session for async requests.

    Returns:
        str: The access token.

    Raises:
        ValueError: If invalid tier specified.
        RuntimeError: If credentials are missing or request fails.
    """
    t = tier.lower()
    if t not in _token_cache:
        raise ValueError("tier must be one of: 'free', 'test', 'vip'")

    now = time.time()
    cached = _token_cache[t]
    if not force and cached.get("token") and cached.get("expires_at", 0) > now + 5:
        return cached["token"]

    creds = _creds_for(t)
    username, password = creds["username"], creds["password"]
    if not username or not password:
        raise RuntimeError(f"Missing credentials for '{t}' in .env file")

    host = config.MARZBAN_HOST
    if not host:
        raise RuntimeError("MARZBAN_HOST is not defined in .env")

    close_session = False
    if session is None:
        session = aiohttp.ClientSession()
        close_session = True

    try:
        res = await _request_token(session, host, username, password)
        status, body = res.get("status"), res.get("body")
        if not (200 <= status < 300):
            raise RuntimeError(f"Token request failed: status={status} body={body}")

        token = body.get("access_token")
        if not token:
            raise RuntimeError(f"No access_token in response: {body}")

        exp_ts = _extract_exp_from_jwt(token)
        ttl = max(30, int(exp_ts - int(now))) if exp_ts else 3600

        _token_cache[t]["token"] = token
        _token_cache[t]["expires_at"] = now + ttl
        return token

    finally:
        if close_session:
            await session.close()
