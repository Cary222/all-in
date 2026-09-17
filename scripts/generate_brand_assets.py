"""Regenerate the All In brand assets from a single definition.

The in-app sidebar logo is the source of truth: a green rounded square using the
theme's `--primary` (HSL 166 50% 28% -> #246B5A) with the white lucide `Route`
glyph. The browser favicon and the Windows icon are derived from that same shape
so the app, the browser tab and the desktop shortcut cannot drift apart again —
before this they were three different marks ("BH" from the original BOSS-only
project, an orange "AIN" icon, and the green sidebar logo).

Standard library only, on purpose: the virtualenv ships no imaging package, and
adding a heavy dependency just to rasterise a rounded square and a stroked glyph
would be a poor trade. PNG payloads are written by hand (zlib) and wrapped in an
ICO container, which is what Windows Vista and later expect.

Usage:
    .venv/Scripts/python.exe scripts/generate_brand_assets.py
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SVG_PATH = REPO_ROOT / "src" / "allin" / "web" / "frontend" / "public" / "favicon.svg"
ICO_PATH = REPO_ROOT / "assets" / "allin.ico"

# Theme `--primary`: hsl(166 50% 28%).
BRAND_RGB = (0x24, 0x6B, 0x5A)
GLYPH_RGB = (0xFF, 0xFF, 0xFF)

CANVAS = 32.0            # favicon canvas, in user units
# Proportions mirror the sidebar mark exactly rather than being eyeballed: the
# in-app logo is a 36px square (`h-9 w-9`) with an 8px radius (`rounded-lg`) holding
# an 18px lucide glyph (`h-[18px] w-[18px]`). Deriving the ratios here keeps the tab
# icon, the desktop icon and the sidebar showing the same silhouette — an earlier
# pass used 0.25/0.75, which drew the glyph ~12% larger than the sidebar does.
SIDEBAR_BOX_PX = 36.0
SIDEBAR_RADIUS_PX = 8.0
SIDEBAR_GLYPH_PX = 18.0
CORNER_RATIO = SIDEBAR_RADIUS_PX / SIDEBAR_BOX_PX              # 0.2222
GLYPH_UNITS = 24.0                                             # lucide authored box
GLYPH_SCALE = (SIDEBAR_GLYPH_PX / SIDEBAR_BOX_PX) * CANVAS / GLYPH_UNITS   # 2/3
STROKE_UNITS = 2.0                                             # lucide default
SUPERSAMPLE = 4        # render factor, then box-downsample for smooth edges

ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)

# lucide `Route` (ISC): two circles joined by an S-curve.
ROUTE_CIRCLES = ((6.0, 19.0, 3.0), (18.0, 5.0, 3.0))


def _arc_points(cx: float, cy: float, radius: float, start_deg: float, end_deg: float) -> list[tuple[float, float]]:
    """Sample an arc centreline, endpoints included."""
    steps = max(int(abs(end_deg - start_deg) / 4), 2)
    return [
        (
            cx + radius * math.cos(math.radians(start_deg + (end_deg - start_deg) * i / steps)),
            cy + radius * math.sin(math.radians(start_deg + (end_deg - start_deg) * i / steps)),
        )
        for i in range(steps + 1)
    ]


def _route_centreline() -> list[tuple[float, float]]:
    """Return the glyph centreline in lucide's 24-unit space.

    Mirrors `M9 19h8.5a3.5 3.5 0 0 0 0-7h-11a3.5 3.5 0 0 1 0-7H15`: the lower arc
    bulges to +x and the upper arc to -x, which is what makes the S shape.
    """
    points: list[tuple[float, float]] = [(9.0, 19.0), (17.5, 19.0)]
    points += _arc_points(17.5, 15.5, 3.5, 90.0, -90.0)   # bulge right
    points.append((6.5, 12.0))
    points += _arc_points(6.5, 8.5, 3.5, 90.0, 270.0)     # bulge left
    points.append((15.0, 5.0))
    for cx, cy, radius in ROUTE_CIRCLES:
        points += _arc_points(cx, cy, radius, 0.0, 360.0)
    return points


def _stroke_discs(pixel_per_unit: float, stroke_units: float = STROKE_UNITS) -> list[tuple[float, float, float]]:
    """Turn the centreline into discs: stamping a disc per sample gives round caps."""
    radius = stroke_units / 2.0 * pixel_per_unit
    return [(x * pixel_per_unit, y * pixel_per_unit, radius) for x, y in _route_centreline()]


def _rounded_rect_hit(cx: float, cy: float, size: float, radius: float) -> bool:
    nearest_x = min(max(cx, radius), size - radius)
    nearest_y = min(max(cy, radius), size - radius)
    dx = cx - nearest_x
    dy = cy - nearest_y
    return dx * dx + dy * dy <= radius * radius


def _stamp_disc(mask: bytearray, width: int, height: int, cx: float, cy: float, radius: float) -> None:
    r2 = radius * radius
    for y in range(max(int(cy - radius), 0), min(int(cy + radius) + 2, height)):
        dy = y + 0.5 - cy
        dy2 = dy * dy
        if dy2 > r2:
            continue
        base = y * width
        for x in range(max(int(cx - radius), 0), min(int(cx + radius) + 2, width)):
            dx = x + 0.5 - cx
            if dx * dx + dy2 <= r2:
                mask[base + x] = 1


def _render_rgba(size: int) -> list[bytes]:
    """Render one square icon as PNG-ready RGBA rows."""
    hi = size * SUPERSAMPLE
    corner = size * CORNER_RATIO
    # Glyph mapping: centre the 24-unit box after scaling it into the canvas.
    scale = size * GLYPH_SCALE / GLYPH_UNITS
    offset = (size - GLYPH_UNITS * scale) / 2.0

    background = bytearray(hi * hi)
    for y in range(hi):
        cy = (y + 0.5) / SUPERSAMPLE
        for x in range(hi):
            if _rounded_rect_hit((x + 0.5) / SUPERSAMPLE, cy, float(size), corner):
                background[y * hi + x] = 1

    glyph = bytearray(hi * hi)
    for gx, gy, radius in _stroke_discs(scale):
        _stamp_disc(glyph, hi, hi, offset + gx, offset + gy, radius)

    rows: list[bytes] = []
    block = SUPERSAMPLE * SUPERSAMPLE
    for y in range(size):
        row = bytearray()
        for x in range(size):
            bg_hits = glyph_hits = 0
            for sy in range(y * SUPERSAMPLE, (y + 1) * SUPERSAMPLE):
                base = sy * hi
                for sx in range(x * SUPERSAMPLE, (x + 1) * SUPERSAMPLE):
                    index = base + sx
                    if background[index]:
                        bg_hits += 1
                        if glyph[index]:
                            glyph_hits += 1
            if not bg_hits:
                row += b"\x00\x00\x00\x00"
                continue
            # Covered pixels are either the brand square or the white glyph; mixing
            # them per sample keeps the edges smooth without a dark fringe.
            red = (BRAND_RGB[0] * (bg_hits - glyph_hits) + GLYPH_RGB[0] * glyph_hits) // bg_hits
            green = (BRAND_RGB[1] * (bg_hits - glyph_hits) + GLYPH_RGB[1] * glyph_hits) // bg_hits
            blue = (BRAND_RGB[2] * (bg_hits - glyph_hits) + GLYPH_RGB[2] * glyph_hits) // bg_hits
            row += bytes((red, green, blue, (bg_hits * 255) // block))
        rows.append(bytes(row))
    return rows


def _png(width: int, height: int, rows: list[bytes]) -> bytes:
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + row for row in rows)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _ico(entries: list[tuple[int, bytes]]) -> bytes:
    """Pack PNG payloads into an ICO, one directory entry per size."""
    offset = 6 + 16 * len(entries)
    directory = bytearray()
    payload = bytearray()
    for size, data in entries:
        # A dimension byte of 0 means 256 in the ICO format.
        dimension = 0 if size >= 256 else size
        directory += struct.pack("<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        payload += data
    return struct.pack("<HHH", 0, 1, len(entries)) + bytes(directory) + bytes(payload)


def _favicon_svg() -> str:
    """The same mark as vector, for the browser tab."""
    offset = (CANVAS - GLYPH_UNITS * GLYPH_SCALE) / 2.0
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="32" height="32"'
        ' role="img" aria-label="All In">\n'
        f'  <rect width="32" height="32" rx="{CANVAS * CORNER_RATIO:g}" fill="#{BRAND_RGB[0]:02X}{BRAND_RGB[1]:02X}{BRAND_RGB[2]:02X}"/>\n'
        f'  <g transform="translate({offset:g} {offset:g}) scale({GLYPH_SCALE:g})" fill="none"'
        ' stroke="#FFFFFF" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">\n'
        '    <circle cx="6" cy="19" r="3"/>\n'
        '    <path d="M9 19h8.5a3.5 3.5 0 0 0 0-7h-11a3.5 3.5 0 0 1 0-7H15"/>\n'
        '    <circle cx="18" cy="5" r="3"/>\n'
        '  </g>\n'
        '</svg>\n'
    )


def main() -> None:
    SVG_PATH.parent.mkdir(parents=True, exist_ok=True)
    SVG_PATH.write_text(_favicon_svg(), encoding="utf-8")
    print(f"favicon  -> {SVG_PATH.relative_to(REPO_ROOT)}")

    ICO_PATH.parent.mkdir(parents=True, exist_ok=True)
    entries = [(size, _png(size, size, _render_rgba(size))) for size in ICO_SIZES]
    ICO_PATH.write_bytes(_ico(entries))
    print(f"icon     -> {ICO_PATH.relative_to(REPO_ROOT)} ({', '.join(f'{s}x{s}' for s in ICO_SIZES)})")


if __name__ == "__main__":
    main()
