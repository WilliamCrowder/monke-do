"""Turn the source art into the addon's 64x64 icons and the store-page images.

    uv run --with pillow python tools/make_media.py <folder with the source PNGs>

The round emblems come on a black square. WoW draws icons on dark and light backgrounds, so
the black outside the emblem is made transparent: everything outside the convex hull of the
non-black pixels (grown a little to keep the outline) gets alpha 0.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
MEDIA = ROOT / "addon" / "MonkeDo" / "Media"
ART = ROOT / "art"

# source file name fragment -> output. Emblems are cut out and shrunk to 64x64.
EMBLEMS = {
    "PM-1.png": "icon.png",             # crowned gorilla: AddOns list icon
    "PM-2.png": "minimap.png",          # banana chain: minimap button, reads at 18 px
    "12_37_57 PM.png": "toggle.png",    # Wrinkle Brain: click for the original text
    "12_38_21 PM.png": "toggle_monke.png",  # fist and club: click for Monke Do text
}
STORE = {
    "PM-3.png": ("avatar.png", (512, 512)),   # CurseForge / Wago project avatar
    "PM-4.png": ("banner.png", (1774, 887)),  # page header
}
SIZE = 64


def hull(points: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Convex hull, monotone chain."""
    points = sorted(set(points))
    if len(points) < 3:
        return points

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list = []
    for p in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list = []
    for p in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def cut_out(image: Image.Image) -> Image.Image:
    rgb = image.convert("RGB")
    small = rgb.resize((rgb.width // 4, rgb.height // 4), Image.BOX)
    # Strongest channel, not luminance: the dark red and navy discs are dimmer than the
    # threshold in grey but far from black in their own colour.
    r, g, b = small.split()
    strongest = ImageChops.lighter(ImageChops.lighter(r, g), b)
    bright = strongest.point(lambda v: 255 if v > 28 else 0)
    px = bright.load()
    edge = []
    for y in range(bright.height):  # first and last bright pixel per row is enough for a hull
        row = [x for x in range(bright.width) if px[x, y]]
        if row:
            edge += [(row[0], y), (row[-1], y)]
    polygon = [(x * 4 + 2, y * 4 + 2) for x, y in hull(edge)]
    mask = Image.new("L", rgb.size, 0)
    ImageDraw.Draw(mask).polygon(polygon, fill=255)
    mask = mask.filter(ImageFilter.MaxFilter(15))       # keep the dark outline
    mask = mask.filter(ImageFilter.GaussianBlur(2))     # soft edge survives the downscale
    out = rgb.convert("RGBA")
    out.putalpha(mask)
    box = mask.point(lambda v: 255 if v > 8 else 0).getbbox()
    side = max(box[2] - box[0], box[3] - box[1])
    cx, cy = (box[0] + box[2]) // 2, (box[1] + box[3]) // 2
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(out, (side // 2 - cx, side // 2 - cy))
    return square


def find(folder: Path, fragment: str) -> Path:
    matches = [p for p in folder.glob("*.png") if p.name.endswith(fragment)]
    if len(matches) != 1:
        raise SystemExit(f"expected one file ending in {fragment!r} in {folder}, found {len(matches)}")
    return matches[0]


def main(folder: Path) -> None:
    MEDIA.mkdir(parents=True, exist_ok=True)
    ART.mkdir(parents=True, exist_ok=True)
    for fragment, name in EMBLEMS.items():
        emblem = cut_out(Image.open(find(folder, fragment)))
        emblem.resize((512, 512), Image.LANCZOS).save(ART / name)          # master, for the page
        emblem.resize((SIZE, SIZE), Image.LANCZOS).save(MEDIA / name, optimize=True)
        print(f"{name}: {SIZE}x{SIZE} -> {MEDIA / name}")
    for fragment, (name, size) in STORE.items():
        image = Image.open(find(folder, fragment)).convert("RGB")
        image.resize(size, Image.LANCZOS).save(ART / name, optimize=True)
        print(f"{name}: {size[0]}x{size[1]} -> {ART / name}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
