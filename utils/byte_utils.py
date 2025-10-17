"""
utils/bytes_utils.py
--------------------
Production-grade utilities for converting data sizes between bytes and gigabytes (GiB).

Features:
- Accurate binary conversion (1 GiB = 1024³ bytes)
- Accepts both int and float inputs
- Returns:
    - int for gb_to_bytes (backend-safe)
    - float for bytes_to_gb (user display, 1 decimal precision)
- Strict validation and safe error handling
"""

from typing import Union


# ---------- Constants ----------
BYTES_IN_GB: float = float(1024 ** 3)  # 1 GiB = 1,073,741,824 bytes


# ---------- Conversions ----------
def gb_to_bytes(gb_value: Union[int, float, None]) -> int:
    """
    Convert gigabytes (GiB) to bytes, suitable for backend operations.

    Args:
        gb_value (int | float | None): Size in gigabytes.

    Returns:
        int: Equivalent size in bytes (accurate integer).

    Raises:
        ValueError: If input is invalid or negative.
    """
    if gb_value is None:
        return 0

    try:
        value = float(gb_value)
        if value < 0:
            raise ValueError("Negative values are not allowed for data sizes.")
        return int(value * BYTES_IN_GB)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Invalid value for gb_to_bytes: {gb_value!r}") from e


def bytes_to_gb(byte_value: Union[int, float, None]) -> float:
    """
    Convert bytes to gigabytes (GiB), rounded to 1 decimal place for user display.

    Args:
        byte_value (int | float | None): Size in bytes.

    Returns:
        float: Equivalent size in gigabytes (rounded to 1 decimal).

    Raises:
        ValueError: If input is invalid or negative.
    """
    if byte_value is None:
        return 0.0

    try:
        value = float(byte_value)
        if value < 0:
            raise ValueError("Negative values are not allowed for data sizes.")
        return round(value / BYTES_IN_GB, 1)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Invalid value for bytes_to_gb: {byte_value!r}") from e
