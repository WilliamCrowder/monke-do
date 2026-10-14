"""Turn the source art into the addon's 64x64 icons and the store-page images.

    uv run --with pillow python tools/make_media.py <folder with the source PNGs>
    uv run --with pillow python tools/make_media.py        # only the drawn images (the arrow)

The Now line's pointer, a gorilla hand pointing straight up ("Monke finger.png", on a clear
background), is cut off at the wrist, given a pale gold rim and centred so the game can turn
it any way.

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
# source file name fragment -> output: the hand the Now line turns toward the quest.
POINTER = ("Monke finger.png", "finger.png")
STORE = {
    "PM-3.png": ("avatar.png", (512, 512)),   # CurseForge / Wago project avatar
    "PM-4.png": ("banner.png", (1774, 887)),  # page header
}
SIZE = 64
# Drawn here rather than cut from art: the Now line's arrow, pointing up (the addon turns it).
ARROW = "arrow.png"
GOLD = (255, 209, 0, 255)   # Blizzard's gold, 1 / 0.82 / 0
OUTLINE = (40, 20, 0, 255)  # dark brown, so the arrow reads on grass, snow and stone alike
# The finger is dark fur, which vanishes on the dark strip and on wood and earth behind it: a
# pale gold rim (then the arrow's dark edge) gives it a silhouette on any background.
RIM = (255, 222, 130, 255)
RIM_WIDTH = 3   # px at 64x64
EDGE_WIDTH = 1


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


def draw_arrow() -> Image.Image:
    """A navigation arrowhead pointing up on a clear 64x64 square, drawn at 8x and shrunk smooth.

    The addon turns the texture about its centre, so the arrow sits on the middle of the square.
    """
    scale = 8
    big = Image.new("RGBA", (SIZE * scale, SIZE * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(big)
    shape = [(32, 5), (55, 57), (32, 45), (9, 57)]  # tip, right corner, notch, left corner
    points = [(x * scale, y * scale) for x, y in shape]
    draw.line(points + points[:2], fill=OUTLINE, width=5 * scale, joint="curve")
    draw.polygon(points, fill=GOLD)
    return big.resize((SIZE, SIZE), Image.LANCZOS)


def pointer(image: Image.Image) -> Image.Image:
    """The pointing hand, ready to be turned about the middle of its square.

    Below the wrist (the narrowest row under the widest one, the fist) the forearm fades out.
    What is left is centred in a square whose inscribed circle holds all of it, so no turn cuts
    a fingertip or a knuckle off.
    """
    rgba = image.convert("RGBA")
    width, height = rgba.size
    alpha = rgba.getchannel("A")
    solid = alpha.load()
    spans = {}
    for y in range(height):
        xs = [x for x in range(width) if solid[x, y] > 128]
        if xs:
            spans[y] = (xs[0], xs[-1])
    rows = sorted(spans)
    span = lambda y: spans[y][1] - spans[y][0]  # noqa: E731
    fist = max(rows[: len(rows) * 4 // 5], key=span)
    wrist = min((y for y in rows if fist < y < rows[-1] - height // 20), key=span)
    fade = max(1, (wrist - fist) // 3)
    ramp = Image.new("L", (1, height), 0)
    for y in range(height):
        ramp.putpixel((0, y), 255 if y < wrist - fade else max(0, round(255 * (wrist - y) / fade)))
    rgba.putalpha(ImageChops.multiply(alpha, ramp.resize((width, height))))

    kept = [y for y in rows if y < wrist]
    left = min(spans[y][0] for y in kept)
    right = max(spans[y][1] for y in kept)
    cx, cy = (left + right) / 2, (kept[0] + kept[-1]) / 2
    radius = max(max(abs(spans[y][0] - cx), abs(spans[y][1] - cx)) ** 2 + (y - cy) ** 2 for y in kept) ** 0.5
    side = int(radius * 2.04) + 2
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(rgba, (round(side / 2 - cx), round(side / 2 - cy)))
    return rimmed(square.resize((SIZE, SIZE), Image.LANCZOS))


def rimmed(hand: Image.Image) -> Image.Image:
    """The 64x64 hand, shrunk to leave room in the square for a RIM ring and a dark edge round it.

    Worked at 4x so the rings come out smooth. The rings stay inside the square's inscribed
    circle, as the hand did, so a turn still cuts nothing off.
    """
    scale = 4
    margin = RIM_WIDTH + EDGE_WIDTH + 1
    inner = (SIZE - 2 * margin) * scale
    canvas = Image.new("RGBA", (SIZE * scale, SIZE * scale), (0, 0, 0, 0))
    canvas.paste(hand.resize((inner, inner), Image.LANCZOS), (margin * scale, margin * scale))
    solid = canvas.getchannel("A").point(lambda v: 255 if v > 96 else 0)
    rim = solid.filter(ImageFilter.MaxFilter(2 * RIM_WIDTH * scale + 1))
    edge = rim.filter(ImageFilter.MaxFilter(2 * EDGE_WIDTH * scale + 1))
    out = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    for colour, mask in ((OUTLINE, edge), (RIM, rim)):
        layer = Image.new("RGBA", canvas.size, colour)
        layer.putalpha(mask.filter(ImageFilter.GaussianBlur(scale / 2)))
        out = Image.alpha_composite(out, layer)
    out = Image.alpha_composite(out, canvas)
    return out.resize((SIZE, SIZE), Image.LANCZOS)


def find(folder: Path, fragment: str) -> Path:
    matches = [p for p in folder.glob("*.png") if p.name.endswith(fragment)]
    if len(matches) != 1:
        raise SystemExit(f"expected one file ending in {fragment!r} in {folder}, found {len(matches)}")
    return matches[0]


def main(folder: Path | None) -> None:
    MEDIA.mkdir(parents=True, exist_ok=True)
    draw_arrow().save(MEDIA / ARROW, optimize=True)
    print(f"{ARROW}: {SIZE}x{SIZE} -> {MEDIA / ARROW}")
    if folder is None:
        return
    ART.mkdir(parents=True, exist_ok=True)
    for fragment, name in EMBLEMS.items():
        emblem = cut_out(Image.open(find(folder, fragment)))
        emblem.resize((512, 512), Image.LANCZOS).save(ART / name)          # master, for the page
        emblem.resize((SIZE, SIZE), Image.LANCZOS).save(MEDIA / name, optimize=True)
        print(f"{name}: {SIZE}x{SIZE} -> {MEDIA / name}")
    fragment, name = POINTER
    pointer(Image.open(find(folder, fragment))).save(MEDIA / name, optimize=True)
    print(f"{name}: {SIZE}x{SIZE} -> {MEDIA / name}")
    for fragment, (name, size) in STORE.items():
        image = Image.open(find(folder, fragment)).convert("RGB")
        image.resize(size, Image.LANCZOS).save(ART / name, optimize=True)
        print(f"{name}: {size[0]}x{size[1]} -> {ART / name}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
