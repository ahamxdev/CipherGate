"""
get_user.py
------------
Async helper to retrieve a user's information from the Marzban panel.

Features:
- Automatically builds username (CipherGate_{tier}_{user_id})
- Uses tier-based token from marzban.get_token.get_token()
- Handles token refresh (401) and retry with backoff
- Returns parsed MarzbanUserInfo (status, expire, remaining_gb, etc.)

Usage Example:
--------------
from marzban.get_user import get_user

user = await get_user(user_id=123456, tier="vip")
print(user.username, user.expire, user.remaining_gb)
"""

import asyncio
import logging
from typing import Optional

import aiohttp
from pydantic import BaseModel, Field

from marzban.get_token import get_token
from utils.config import settings

logger = logging.getLogger(__name__)


# ---------- Models ----------
class MarzbanUserInfo(BaseModel):
    """Response model for GET /api/user/{username} (simplified, without lifetime fields)."""

    id: Optional[int]
    username: str
    status: str
    data_limit: Optional[int] = Field(0, description="Maximum data in bytes")
    expire: Optional[str]
    used_traffic: Optional[int] = Field(0, description="Used traffic in bytes")
    created_at: Optional[str]
    edit_at: Optional[str]
    online_at: Optional[str]
    subscription_url: Optional[str] = None

    # --- Derived properties for bot display ---
    @property
    def remaining_gb(self) -> float:
        """Return remaining traffic in GB (rounded to 2 decimals)."""
        if not self.data_limit:
            return 0
        remaining = self.data_limit - (self.used_traffic or 0)
        return round(max(remaining, 0) / (1024**3), 2)

    @property
    def used_gb(self) -> float:
        """Return used traffic in GB (rounded to 2 decimals)."""
        return round((self.used_traffic or 0) / (1024**3), 2)

    class Config:
        extra = "allow"


# ---------- Core Function ----------
async def get_user(
    user_id: int,
    tier: str,
    max_retries: int = 3,
) -> MarzbanUserInfo:
    """
    Fetch detailed user information from Marzban.

    Args:
        user_id (int): Telegram user ID used to build the Marzban username.
        tier (str): Account tier ("free", "test", or "vip").
        max_retries (int): Number of retry attempts on network failure.

    Returns:
        MarzbanUserInfo: Parsed Marzban user information.

    Raises:
        RuntimeError: On unrecoverable network or API errors.
    """
    tier = tier.lower().strip()
    if tier not in {"free", "test", "vip"}:
        raise ValueError("tier must be one of: free, test, vip")

    # Build username using the same naming pattern as in create_user
    username = f"CipherGate_{tier}_{user_id}"

    host = settings.MARZBAN_HOST.rstrip("/")
    if not host:
        raise RuntimeError("MARZBAN_HOST not defined in .env")

    url = f"{host}/api/user/{username}"
    timeout = aiohttp.ClientTimeout(total=10)
    backoff = 1.5

    async with aiohttp.ClientSession(timeout=timeout) as session:
        force_refresh = False
        last_error: Optional[Exception] = None

        for attempt in range(1, max_retries + 1):
            try:
                token = await get_token(tier=tier, force=force_refresh, session=session)
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                }

                async with session.get(url, headers=headers) as resp:
                    data = await resp.json(content_type=None)

                    if 200 <= resp.status < 300:
                        logger.info("✅ Retrieved info for %s (tier=%s)", username, tier)
                        return MarzbanUserInfo(**data)

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
                logger.warning(
                    "Network issue (attempt %d/%d): %s", attempt, max_retries, e
                )
                await asyncio.sleep(backoff * attempt)

        raise RuntimeError(
            f"Failed to retrieve user '{username}' after {max_retries} attempts"
        ) from last_error


# ---------- Example ----------
# async def main():
#     user = await get_user(user_id=123456, tier="vip")
#     print(f"👤 Username: {user.username}")
#     print(f"📅 Expire: {user.expire}")
#     print(f"📦 Remaining: {user.remaining_gb} GB")
#     print(f"🟢 Status: {user.status}")
#     print(f"🔗 {user.subscription_url}")
#
# if __name__ == "__main__":
#     asyncio.run(main())
