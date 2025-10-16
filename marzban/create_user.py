"""
create_user.py
---------------
Async helper to create a new user on Marzban panel.

Features:
- Uses cached JWT tokens from marzban.get_token.get_token()
- Auto-assigns group_id based on tier (free/test/vip)
- Calculates expiration date and data limit dynamically
- Validates payload using Pydantic (v2+)
- Handles token refresh (401) and retry with backoff
- Returns parsed MarzbanUserResponse (including data_limit_gb and subscription_url)
"""

import asyncio
import logging
from typing import Optional, Dict, Any, Literal

import aiohttp
from pydantic import BaseModel, Field

from marzban.get_token import get_token
from utils.config import settings
from utils.time_utils import make_expire_date

logger = logging.getLogger(__name__)


# ---------- Models ----------
class ProxySettings(BaseModel):
    vless: Optional[Dict[str, Any]] = None
    shadowsocks: Optional[Dict[str, Any]] = None


class CreateUserPayload(BaseModel):
    """Validates Marzban /api/user request body."""

    username: str = Field(..., min_length=3, max_length=32)
    status: Literal["active"] = "active"  # always active (bot-controlled)
    data_limit: Optional[int] = Field(default=0, ge=0)
    expire: Optional[str] = None  # ISO 8601 datetime string
    note: Optional[str] = ""
    group_ids: Optional[list[int]] = Field(default_factory=list)
    proxy_settings: Optional[ProxySettings] = None

    class Config:
        extra = "allow"


class MarzbanUserResponse(BaseModel):
    """Simplified Marzban API response model."""

    id: Optional[int]
    username: Optional[str]
    status: Optional[str]
    data_limit_gb: Optional[int]
    expire: Optional[str]
    subscription_url: Optional[str]

    class Config:
        extra = "allow"


# ---------- Core Function ----------
async def create_user(
    user_id: int,
    tier: str,
    data_limit_gb: int,
    plan_days: int,
    note: str,
    idempotency_key: Optional[str] = None,
    max_retries: int = 3,
) -> MarzbanUserResponse:
    """
    Create a user on Marzban based on provided info.

    Args:
        user_id (int): Telegram user ID (used in username generation).
        tier (str): Account tier ("free", "test", "vip").
        data_limit_gb (int): Data limit in GB (e.g., 40 for 40GB).
        expire_days (int): Duration in days (e.g., 30 for 1 month).
        note (str): Optional description or product note.
        idempotency_key (str, optional): Prevent duplicate creation.
        max_retries (int): Retry attempts on failure.

    Returns:
        MarzbanUserResponse: Parsed user response (with data_limit_gb and subscription_url).
    """

    # Normalize tier & map to group
    tier = tier.lower().strip()
    group_map = {"vip": [4], "test": [5], "free": [6]}
    if tier not in group_map:
        raise ValueError(f"Invalid tier '{tier}'. Must be one of {list(group_map.keys())}")

    # Compute dynamic fields
    username = f"CipherGate_{tier}_{user_id}"
    data_limit_bytes = data_limit_gb * 1024**3
    expire_date = make_expire_date(plan_days)

    # Build payload
    payload = {
        "username": username,
        "status": "active",
        "data_limit": data_limit_bytes,
        "expire": expire_date,
        "note": note,
        "group_ids": group_map[tier],
        "proxy_settings": {
            "vless": {"flow": "xtls-rprx-vision"},
            "shadowsocks": {"method": "chacha20-ietf-poly1305"},
        },
    }

    # Validate before sending
    body = CreateUserPayload(**payload).model_dump(exclude_none=True)

    host = settings.MARZBAN_HOST.rstrip("/")
    if not host:
        raise RuntimeError("MARZBAN_HOST not defined in .env")

    url = f"{host}/api/user"
    timeout = aiohttp.ClientTimeout(total=15)
    backoff = 1.5

    async with aiohttp.ClientSession(timeout=timeout) as session:
        force_refresh = False
        last_error: Optional[Exception] = None

        for attempt in range(1, max_retries + 1):
            try:
                # Token per tier
                token = await get_token(tier=tier, force=force_refresh, session=session)
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                }
                if idempotency_key:
                    headers["Idempotency-Key"] = str(idempotency_key)

                async with session.post(url, json=body, headers=headers) as resp:
                    data = await resp.json(content_type=None)

                    # Always inject data_limit_gb for bot display
                    data["data_limit_gb"] = data_limit_gb

                    if 200 <= resp.status < 300:
                        logger.info(
                            "✅ Created user %s (tier=%s, group=%s, data=%s, expire=%dGB)",
                            username,
                            tier,
                            group_map[tier],
                            data_limit_gb,
                            expire_date,
                        )
                        return MarzbanUserResponse(**data)

                    elif resp.status == 401 and not force_refresh:
                        logger.warning("⚠️ Token expired, refreshing and retrying...")
                        force_refresh = True
                        continue

                    else:
                        msg = f"Marzban error {resp.status}: {data}"
                        logger.error(msg)
                        # return a typed response including data_limit_gb for bot handling
                        return MarzbanUserResponse(**data)

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_error = e
                logger.warning("Network issue (attempt %d/%d): %s", attempt, max_retries, e)
                await asyncio.sleep(backoff * atte"""
create_user.py
---------------
Async helper to create a new user on Marzban panel.

Features:
- Uses cached JWT tokens from marzban.get_token.get_token()
- Auto-assigns group_id based on tier (free/test/vip)
- Calculates expiration date and data limit dynamically
- Validates payload using Pydantic (v2+)
- Handles token refresh (401) and retry with backoff
- Returns parsed MarzbanUserResponse (including data_limit_gb and subscription_url)
"""

import asyncio
import logging
from typing import Optional, Dict, Any, Literal

import aiohttp
from pydantic import BaseModel, Field

from marzban.get_token import get_token
from utils.config import settings
from utils.time_utils import make_expire_date

logger = logging.getLogger(__name__)


# ---------- Models ----------
class ProxySettings(BaseModel):
    vless: Optional[Dict[str, Any]] = None
    shadowsocks: Optional[Dict[str, Any]] = None


class CreateUserPayload(BaseModel):
    """Validates Marzban /api/user request body."""

    username: str = Field(..., min_length=3, max_length=32)
    status: Literal["active"] = "active"  # always active (bot-controlled)
    data_limit: Optional[int] = Field(default=0, ge=0)
    expire: Optional[str] = None  # ISO 8601 datetime string
    note: Optional[str] = ""
    group_ids: Optional[list[int]] = Field(default_factory=list)
    proxy_settings: Optional[ProxySettings] = None

    class Config:
        extra = "allow"


class MarzbanUserResponse(BaseModel):
    """Simplified Marzban API response model."""

    id: Optional[int]
    username: Optional[str]
    status: Optional[str]
    data_limit_gb: Optional[int]
    expire: Optional[str]
    subscription_url: Optional[str]

    class Config:
        extra = "allow"


# ---------- Core Function ----------
async def create_user(
    user_id: int,
    tier: str,
    data_limit_gb: int,
    expire_days: int,
    note: str,
    idempotency_key: Optional[str] = None,
    max_retries: int = 3,
) -> MarzbanUserResponse:
    """
    Create a user on Marzban based on provided info.

    Args:
        user_id (int): Telegram user ID (used in username generation).
        tier (str): Account tier ("free", "test", "vip").
        data_limit_gb (int): Data limit in GB (e.g., 40 for 40GB).
        expire_days (int): Duration in days (e.g., 30 for 1 month).
        note (str): Optional description or product note.
        idempotency_key (str, optional): Prevent duplicate creation.
        max_retries (int): Retry attempts on failure.

    Returns:
        MarzbanUserResponse: Parsed user response (with data_limit_gb and subscription_url).
    """

    # Normalize tier & map to group
    tier = tier.lower().strip()
    group_map = {"vip": [4], "test": [5], "free": [6]}
    if tier not in group_map:
        raise ValueError(f"Invalid tier '{tier}'. Must be one of {list(group_map.keys())}")

    # Compute dynamic fields
    username = f"CipherGate_{tier}_{user_id}"
    data_limit_bytes = data_limit_gb * 1024**3
    expire_date = make_expire_date(expire_days)

    # Build payload
    payload = {
        "username": username,
        "status": "active",
        "data_limit": data_limit_bytes,
        "expire": expire_date,
        "note": note,
        "group_ids": group_map[tier],
        "proxy_settings": {
            "vless": {"flow": "xtls-rprx-vision"},
            "shadowsocks": {"method": "chacha20-ietf-poly1305"},
        },
    }

    # Validate before sending
    body = CreateUserPayload(**payload).model_dump(exclude_none=True)

    host = settings.MARZBAN_HOST.rstrip("/")
    if not host:
        raise RuntimeError("MARZBAN_HOST not defined in .env")

    url = f"{host}/api/user"
    timeout = aiohttp.ClientTimeout(total=15)
    backoff = 1.5

    async with aiohttp.ClientSession(timeout=timeout) as session:
        force_refresh = False
        last_error: Optional[Exception] = None

        for attempt in range(1, max_retries + 1):
            try:
                # Token per tier
                token = await get_token(tier=tier, force=force_refresh, session=session)
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                }
                if idempotency_key:
                    headers["Idempotency-Key"] = str(idempotency_key)

                async with session.post(url, json=body, headers=headers) as resp:
                    data = await resp.json(content_type=None)

                    # Always inject data_limit_gb for bot display
                    data["data_limit_gb"] = data_limit_gb

                    if 200 <= resp.status < 300:
                        logger.info(
                            "✅ Created user %s (tier=%s, group=%s, data=%s, expire=%dGB)",
                            username,
                            tier,
                            group_map[tier],
                            data_limit_gb,
                            expire_date,
                        )
                        return MarzbanUserResponse(**data)

                    elif resp.status == 401 and not force_refresh:
                        logger.warning("⚠️ Token expired, refreshing and retrying...")
                        force_refresh = True
                        continue

                    else:
                        msg = f"Marzban error {resp.status}: {data}"
                        logger.error(msg)
                        # return a typed response including data_limit_gb for bot handling
                        return MarzbanUserResponse(**data)

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_error = e
                logger.warning("Network issue (attempt %d/%d): %s", attempt, max_retries, e)
                await asyncio.sleep(backoff * attempt)

        raise RuntimeError(f"Failed to create user after {max_retries} attempts") from last_error
mpt)

        raise RuntimeError(f"Failed to create user after {max_retries} attempts") from last_error
