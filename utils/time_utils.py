"""
utils/time_utils.py
-------------------
Utility for calculating VPN expiration dates based on a number of days
(typically read from the database for each plan).

Returns ISO8601 datetime string with Iran timezone (+03:30),
rounded to 00:00 of the next day after the added duration.
"""

from datetime import datetime, time, timedelta
from dateutil.relativedelta import relativedelta
from zoneinfo import ZoneInfo


def make_expire_date(days: int) -> str:
    """
    Generate an expiration datetime string for a VPN user.

    Args:
        days (int): Number of days to add to the current time.
                    (Fetched from the database for the selected plan.)

    Returns:
        str: ISO 8601 formatted datetime string with Iran timezone.
             Example: "2025-01-15T00:00:00+03:30"
    """
    if not isinstance(days, int) or days <= 0:
        raise ValueError("days must be a positive integer")

    iran_tz = ZoneInfo("Asia/Tehran")
    now_iran = datetime.now(tz=iran_tz)

    # Add duration to current time
    expire_time = now_iran + relativedelta(days=days)

    # Move to start of *next* day at 00:00
    next_day = (expire_time + timedelta(days=1)).date()
    expire_at_midnight = datetime.combine(next_day, time(0, 0), tzinfo=iran_tz)

    return expire_at_midnight.replace(microsecond=0).isoformat()
