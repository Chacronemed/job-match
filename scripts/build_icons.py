"""Write the dashboard's app icons (PWA manifest, apple-touch-icon). Run once; the PNGs are
committed under src/job_match/dashboard/assets/icons/.

Pure Python (zlib + struct), no image library: a flat primary square, the swipe-to-keep tick in
white. `icon-*.png` has rounded corners on a transparent ground; the maskable one is full bleed
with the tick inside the 80 % safe zone, as Android crops it into its own shape.
Run: .venv\\Scripts\\python scripts/build_icons.py
"""
import math
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).parent.parent / "src" / "job_match" / "dashboard" / "assets" / "icons"
PRIMARY = (110, 86, 207)  # DESIGN.md --accent (Radix violet-9, #6e56cf)
WHITE = (255, 255, 255)


def _seg_dist(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _cover(d: float, edge: float) -> float:
    """Anti-aliased coverage of a shape whose edge is at distance `edge` (1px ramp)."""
    return max(0.0, min(1.0, edge - d + 0.5))


def render(size: int, maskable: bool) -> bytes:
    s = size
    radius = 0 if maskable else s * 0.22
    scale = 0.62 if maskable else 0.78  # the tick's extent within the square
    # Tick points, in units of the square, centred.
    pts = [(-0.30, 0.02), (-0.08, 0.24), (0.32, -0.20)]
    pts = [(s / 2 + x * s * scale, s / 2 + y * s * scale) for x, y in pts]
    half_stroke = s * 0.075 * scale / 0.78
    rows = bytearray()
    for y in range(s):
        rows.append(0)  # filter: none
        for x in range(s):
            px, py = x + 0.5, y + 0.5
            # Rounded-square ground.
            if radius:
                cx = min(max(px, radius), s - radius)
                cy = min(max(py, radius), s - radius)
                ground = _cover(math.hypot(px - cx, py - cy), radius)
            else:
                ground = 1.0
            d = min(_seg_dist(px, py, *pts[0], *pts[1]), _seg_dist(px, py, *pts[1], *pts[2]))
            mark = _cover(d, half_stroke)
            r, g, b = (round(PRIMARY[i] + (WHITE[i] - PRIMARY[i]) * mark) for i in range(3))
            rows += bytes((r, g, b, round(255 * ground)))
    return _png(s, s, bytes(rows))


def _png(w: int, h: int, raw: bytes) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = struct.pack(">I", zlib.crc32(kind + data))
        return struct.pack(">I", len(data)) + kind + data + crc

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)  # 8-bit RGBA
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, size, maskable in (("icon-192.png", 192, False), ("icon-512.png", 512, False),
                                 ("icon-maskable-512.png", 512, True),
                                 ("apple-touch-icon.png", 180, True)):
        (OUT / name).write_bytes(render(size, maskable))
        print(f"wrote {name}")


if __name__ == "__main__":
    main()
