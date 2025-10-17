"""
modify_user.py
---------------
Async helper to modify (update or extend) an existing user on the Marzban panel.

Features:
- Uses cached JWT tokens from marzban.get_token.get_token()
- Automatically builds username (CipherGate_{tier}_{user_id})
- Updates user fields: data limit, expire, group, note, and proxy settings
- Always includes all required fields (so nothing resets unintentionally)
- Handles token refresh (401) and retry with backoff
- Returns parsed MarzbanUserResponse (with updated data)
"""

import asyncio
import logging
from typing import Optional, Dict, Any, Literal

import aiohttp
from pydantic import BaseModel, Field

from marzban.get_token import get_token
from utils.config import settings
from utils.time_utils import make_expire_date
from marzban.get_user import get_user
from utils.qrcode_utils import generate_qr_code
from utils.byte_utils import bytes_to_gb, gb_to_bytes

logger = logging.getLogger(__name__)


# ---------- Models ----------

class ProxySettings(BaseModel):
    """Nested VPN protocol settings model (optional)."""

    vmess: Optional[Dict[str, Any]] = None
    vless: Optional[Dict[str, Any]] = None
    trojan: Optional[Dict[str, Any]] = None
    shadowsocks: Optional[Dict[str, Any]] = None

    class Config:
        extra = "allow"


class ModifyUserPayload(BaseModel):
    """Validates Marzban /api/user/{username} PUT request body."""

    username: str = Field(..., min_length=3, max_length=32)
    status: Literal["active"] = "active"
    data_limit: Optional[int] = Field(default=0, ge=0)
    expire: Optional[str] = None
    note: Optional[str] = ""
    data_limit_reset_strategy: Literal["no_reset"] = "no_reset"
    group_ids: Optional[list[int]] = Field(default_factory=list)
    proxy_settings: Optional[ProxySettings] = None

    class Config:
        extra = "allow"


class MarzbanUserResponse(BaseModel):
    """Response model for GET /api/user/{username} (simplified, without lifetime fields)."""

    id: Optional[int]
    username: str
    status: str
    data_limit: Optional[int] = Field(0, description="Maximum data in bytes")
    used_traffic: Optional[int] = Field(0, description="Used traffic in bytes")
    expire: Optional[str]
    created_at: Optional[str]
    edit_at: Optional[str]
    online_at: Optional[str]
    subscription_url: Optional[str] = None

    # --- Derived properties for bot display ---
    @property
    def data_limit_gb(self) -> float:
        """Return total data limit in GB (rounded to 1 decimal)."""
        return bytes_to_gb(self.data_limit or 0)

    @property
    def remaining_gb(self) -> float:
        """Return remaining traffic in GB (rounded to 1 decimal)."""
        if not self.data_limit:
            return 0.0
        remaining = self.data_limit - (self.used_traffic or 0)
        return bytes_to_gb(max(remaining, 0))

    @property
    def used_gb(self) -> float:
        """Return used traffic in GB (rounded to 1 decimal)."""
        return bytes_to_gb(self.used_traffic or 0)

    # ---------- Derived Field ----------
    @property
    async def qr_image(self) -> Optional[bytes]:
        """
        Generate and return a QR code (PNG bytes) for the user's subscription URL.

        Returns:
            bytes | None: PNG bytes if subscription_url exists, otherwise None.
        """
        if not self.subscription_url:
            return None

        try:
            return await generate_qr_code(self.subscription_url)
        except aiohttp.ClientError as e:
            logger.warning("⚠️ Network error while generating QR for %s: %s", self.username, e)
        except asyncio.TimeoutError:
            logger.warning("⚠️ Timeout while generating QR for %s", self.username)
        except ValueError as e:
            logger.warning("⚠️ Invalid subscription URL for %s: %s", self.username, e)
        except OSError as e:
            logger.warning("⚠️ File or I/O error while generating QR for %s: %s", self.username, e)

    class Config:
        extra = "allow"


# ---------- Core Function ----------
async def modify_user(
    user_id: int,
    tier: str,
    data_limit_gb: int,
    plan_days: int,
    idempotency_key: Optional[str] = None,
    max_retries: int = 3,
) -> MarzbanUserResponse:
    """
    Modify an existing user on Marzban.

    Args:
        user_id (int): Telegram user ID (used in username generation).
        tier (str): Account tier ("free", "test", "vip").
        data_limit_gb (int): Data limit in GB.
        plan_days (int): Duration in days.
        note (str): Optional note or product name.
        idempotency_key (str, optional): Prevent duplicate modifications.
        max_retries (int): Number of retry attempts on failure.

    Returns:
        MarzbanUserResponse: Updated user information.
    """

    # Normalize tier & map to correct Marzban group
    tier = tier.lower().strip()
    group_map = {"vip": [4], "test": [5], "free": [6]}
    if tier not in group_map:
        raise ValueError(f"Invalid tier '{tier}'. Must be one of {list(group_map.keys())}")

    username = f"CipherGate_{tier}_{user_id}"
    data_limit_bytes = gb_to_bytes(data_limit_gb)
    expire_date = make_expire_date(plan_days)

    # --- Get current user info first ---
    try:
        current_user = await get_user(user_id=user_id, tier=tier)
        current_proxy_settings = current_user.proxy_settings or {}
    except aiohttp.ClientError as e:
        logger.warning("⚠️ Network error while fetching user data: %s", e)
        current_proxy_settings = {}
    except asyncio.TimeoutError:
        logger.warning("⚠️ Request timed out while fetching user data")
        current_proxy_settings = {}
    except ValueError as e:
        logger.warning("⚠️ Invalid response parsing user data: %s", e)
        current_proxy_settings = {}

    if hasattr(current_proxy_settings, "model_dump"):
        current_proxy_settings = current_proxy_settings.model_dump()

    # Prepare payload exactly like Marzban expects
    payload = {
        "username": username,
        "status": "active",
        "data_limit": data_limit_bytes,
        "expire": expire_date,
        "note": "",
        "data_limit_reset_strategy": "no_reset",
        "group_ids": group_map[tier],
        "proxy_settings": current_proxy_settings,  # ✅ use existing proxy settings
    }

    body = ModifyUserPayload(**payload).model_dump(exclude_none=True)

    host = settings.MARZBAN_HOST.rstrip("/")
    if not host:
        raise RuntimeError("MARZBAN_HOST not defined in .env")

    url = f"{host}/api/user/{username}"
    timeout = aiohttp.ClientTimeout(total=15)
    backoff = 1.5

    async with aiohttp.ClientSession(timeout=timeout) as session:
        force_refresh = False
        last_error: Optional[Exception] = None

        for attempt in range(1, max_retries + 1):
            try:
                # Get valid JWT token per tier
                token = await get_token(tier=tier, force=force_refresh, session=session)
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                }
                if idempotency_key:
                    headers["Idempotency-Key"] = str(idempotency_key)

                async with session.put(url, json=body, headers=headers) as resp:
                    data = await resp.json(content_type=None)


                    if 200 <= resp.status < 300:
                        data["data_limit_gb"] = data_limit_gb
                        logger.info("✅ Modified user %s | Tier=%s | Data=%sGB | Expire=%s)", username, tier, data_limit_gb, expire_date)
                        return MarzbanUserResponse(**data)

                    elif resp.status == 401 and not force_refresh:
                        logger.warning("⚠️ Token expired, refreshing and retrying...")
                        force_refresh = True
                        continue

                    else:
                        msg = f"Marzban error {resp.status}: {data}"
                        logger.error(msg)
                        raise RuntimeError(msg)

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_error = e
                logger.warning("Network issue (attempt %d/%d): %s", attempt, max_retries, e)
                await asyncio.sleep(backoff * attempt)

        raise RuntimeError(f"Failed to modify user after {max_retries} attempts") from last_error
