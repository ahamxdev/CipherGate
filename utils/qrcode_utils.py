"""
utils/qrcode_utils.py
---------------------
Utility for generating QR codes from Marzban subscription URLs.

Features:
- Generates QR code in-memory (no file saving)
- Returns PNG bytes ready for Telegram send_photo or HTTP response
- Lightweight and production-ready
"""

import qrcode
from io import BytesIO


async def generate_qr_code(url: str) -> bytes:
    """
    Generate a QR code image (PNG bytes) from a given URL.

    Args:
        url (str): Subscription link or any string to encode.

    Returns:
        bytes: QR code image as PNG bytes (no file saved).

    Raises:
        ValueError: If the URL is missing or invalid.
    """
    if not url or not isinstance(url, str):
        raise ValueError("Invalid URL provided for QR code generation")

    # Configure QR generation
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)

    # Create image and store it in memory
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    return buffer.getvalue()  # ✅ return bytes directly, not a file


# ---------- Example ----------
# import asyncio
#
# async def main():
#     url = "https://example.com/subscription/abc123"
#     qr_bytes = await generate_qr_code(url)
#     print(f"Generated QR code ({len(qr_bytes)} bytes). Ready to send!")
#
# if __name__ == "__main__":
#     asyncio.run(main())
