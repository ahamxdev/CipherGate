"""
revoke_user_sub.py
------------------
Async helper to revoke (invalidate and regenerate) an existing user's
subscription and proxy configuration on the Marzban panel.

Features:
- Uses cached JWT tokens from marzban.get_token.get_token()
- Automatically builds username (CipherGate_{tier}_{user_id})
- Calls POST /api/user/{username}/revoke_sub
- Returns full MarzbanUserResponse (including traffic info and QR image)
- Handles token refresh (401) and retry with backoff
"""

import asyncio
import logging
from typing import Optional, Dict, Any

import aiohttp
from pydantic import BaseModel, Field

from marzban.get_token import get_token
from utils.config import settings
from utils.qrcode_utils import generate_qr_code  # ✅ to generate QR images

logger = logging.getLogger(__name__)


# ---------- Models ----------
class MarzbanUserResponse(BaseModel):
    """Full Marzban API response model for revoke_sub (with QR generation)."""

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
    proxy_settings: Optional[Dict[str, Any]] = None

    # --- Derived properties for bot display ---
    @property
    def data_limit_gb(self) -> float:
        """Return total data limit in GB (rounded to 2 decimals)."""
        return round((self.data_limit or 0) / (1024**3), 2)

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

    # ---------- Derived Field ----------
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

        return None


# ---------- Core Function ----------
async def revoke_user_sub(
    user_id: int,
    tier: str,
    idempotency_key: Optional[str] = None,
    max_retries: int = 3,
) -> MarzbanUserResponse:
    """
    Revoke (reset) a user's subscription and proxies on Marzban.

    Args:
        user_id (int): Telegram user ID used to build Marzban username.
        tier (str): Account tier ("free", "test", "vip").
        idempotency_key (str, optional): Unique key for duplicate prevention.
        max_retries (int): Number of retry attempts on network failure.

    Returns:
        MarzbanUserResponse: User info with new subscription link, data, and QR code.
    """

    tier = tier.lower().strip()
    if tier not in {"free", "test", "vip"}:
        raise ValueError("tier must be one of: free, test, vip")

    username = f"CipherGate_{tier}_{user_id}"

    host = settings.MARZBAN_HOST.rstrip("/")
    if not host:
        raise RuntimeError("MARZBAN_HOST not defined in .env")

    url = f"{host}/api/user/{username}/revoke_sub"
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
                if idempotency_key:
                    headers["Idempotency-Key"] = str(idempotency_key)

                async with session.post(url, headers=headers) as resp:
                    data = await resp.json(content_type=None)

                    if 200 <= resp.status < 300:
                        logger.info("🔄 Revoked subscription for %s (tier=%s)", username, tier)
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

        raise RuntimeError(f"Failed to revoke subscription after {max_retries} attempts") from last_error


# ---------- Example ----------
# async def main():
#     user = await revoke_user_sub(user_id=123456, tier="vip")
#     qr_bytes = await user.qr_image()
#     print(f"✅ New subscription: {user.subscription_url}")
#     print(f"📦 Remaining: {user.remaining_gb} GB")
#
# if __name__ == "__main__":
#     asyncio.run(main())
