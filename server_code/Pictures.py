"""Image helpers that need no imaging library (Anvil's server image has none by default).

    sniff(data)            -> "image/png" | "image/jpeg" | "image/webp" | None  (from the bytes, never the file name)
    size(data, ctype)      -> (width, height) or (None, None)
    decode_base64(text)    -> bytes from plain base64 or a data URL ("data:image/png;base64,...")
    png(w, h, pixel)       -> a small PNG made in pure Python (demo pictures)
"""
import base64
import binascii
import re
import struct
import zlib

TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
MAX_BYTES = 15 * 1024 * 1024
MAX_SIDE = 8000


def sniff(data):
    if not data or len(data) < 12:
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def looks_like_svg(data):
    head = (data or b"")[:600].lstrip().lower()
    return head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in head)


def size(data, ctype):
    try:
        if ctype == "image/png":
            w, h = struct.unpack(">II", data[16:24])
            return w, h
        if ctype == "image/jpeg":
            i = 2
            while i < len(data) - 9:
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h, w = struct.unpack(">HH", data[i + 5:i + 9])
                    return w, h
                if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                    i += 2
                    continue
                seg = struct.unpack(">H", data[i + 2:i + 4])[0]
                i += 2 + seg
            return None, None
        if ctype == "image/webp":
            kind = data[12:16]
            if kind == b"VP8 ":
                w, h = struct.unpack("<HH", data[26:30])
                return w & 0x3FFF, h & 0x3FFF
            if kind == b"VP8L":
                b = data[21:25]
                w = 1 + (((b[1] & 0x3F) << 8) | b[0])
                h = 1 + (((b[3] & 0x0F) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6))
                return w, h
            if kind == b"VP8X":
                w = 1 + int.from_bytes(data[24:27], "little")
                h = 1 + int.from_bytes(data[27:30], "little")
                return w, h
    except Exception:
        pass
    return None, None


def decode_base64(text):
    """Plain base64 or a data URL. Returns bytes, or None if it isn't base64."""
    if not isinstance(text, str):
        return None
    t = text.strip()
    m = re.match(r"^data:[\w/+.-]+;base64,", t)
    if m:
        t = t[m.end():]
    t = re.sub(r"\s+", "", t)
    try:
        return base64.b64decode(t + "=" * (-len(t) % 4), validate=True)
    except (binascii.Error, ValueError):
        return None


def png(w, h, pixel):
    """pixel(x, y) -> (r, g, b). Small pictures only (demo data)."""
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        for x in range(w):
            raw.extend(bytes(pixel(x, y)))

    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))
