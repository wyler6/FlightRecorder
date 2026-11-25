"""Build high-resolution continent maps and cut them into a tile pyramid.

Run:  py -I tools/build_hires_maps.py [--keep DIR]

Art source: the OpenMap addon (https://github.com/openmap-world/openmap, MIT code; the art is
Blizzard's, see its OpenMap/Media/Textures/Forever/NOTICE.md). Its MapZones/<i>_<j>.blp tiles are
"every zone map composited onto the world as the map draws it at full detail" (512 px tiles, 16 px
per world unit, i*256+j listed in OpenMap/Data/Forever/ZoneArt.lua). The "world" is the art of
Azeroth's map (uiMap 947), 1002x668 units.

Mapping (tile pixel -> continent canvas), derived from OpenMap tools/map-preview/render.py rect()
and Map/Stitch.lua Baked.Build/Baked.Cull, using the game's UiMapAssignment rows (embedded below):
  * tile (i, j) covers world x in [i*T, (i+1)*T), y in [j*T, (j+1)*T), T = 510/16 = 31.875 units.
    Its 512 px tile has a 1 px border that belongs to the neighbors, so tile px p (pixel edges) is
    world x = i*T + (p - 1)/16.
  * a continent's canvas (uiMap 1414/1415, 0-1 on both axes, the frame of map/maps/*.jpg) spans the
    rectangle (l, r, t, b) of the world map (fractions of 1002x668), so
    canvas u = (wx/1002 - l)/(r - l), v = (wy/668 - t)/(b - t).
Where the tiles have no art the base jpg, upscaled 4x, shows through.

Steps per continent: upscale the base jpg 4x (Lanczos) to 8016x5344, composite the tiles on top
(Lanczos, premultiplied alpha), then write map/tiles/<name>/<z>/<col>_<row>.jpg: z=2 is the full
image, z=1 is half size; tiles sit on a 512 px grid from the top-left, JPEG q82. Each tile also
carries GUTTER extra px from its right and bottom neighbors (edge tiles stop at the image bound), so
the page can overlap tiles at exact scale and hide antialiasing seams.
Tiles are cached in .cache/openmap/<sha>/ (git-ignored). Safe to re-run.
"""
import math
import os
import re
import shutil
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

SHA = "6c2299f6e1f9bdce1bbd92145f84a05b0c6c05a7"   # OpenMap commit the art is pinned to
RAW = "https://raw.githubusercontent.com/openmap-world/openmap/%s/OpenMap/" % SHA
ZONES_URL = RAW + "Media/Textures/Forever/MapZones/%d_%d.blp"
ZONEART_URL = RAW + "Data/Forever/ZoneArt.lua"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache", "openmap", SHA)
OUT_W, OUT_H = 8016, 5344            # 4x the 2004x1336 base
WORLD_W, WORLD_H = 1002.0, 668.0     # Azeroth map (947) art px = world units
PX = 16.0                            # tile px per world unit
GUTTER = 2                           # extra px a tile carries from its right/bottom neighbors
TILE, STEP = 512, 510                # tile px; px of it that belong to the tile (rest: neighbors')
T = STEP / PX                        # world units a tile covers
SPLIT_X = 480.0                      # world x between the two continents (Kalimdor left of it)

# UiMapAssignment rows (Forever build 1.60.1.70245, wago.tools). Region = (y0, x0, ., y1, x1, .) in game
# yards as Region_0..Region_4: the code below names them as in the table.
# continent map: Region_0, Region_1, Region_3, Region_4 ; world-map (947) placement: same plus UiMin/UiMax
CONTINENTS = {
    "kalimdor": dict(
        uimap=1414, base="kalimdor.jpg",
        own=(-11733.299804688, -19733.2109375, 12799.900390625, 17066.599609375),
        world=(-12800.0, -9600.0, 12266.700195312, 6933.2998046875),
        ui=(0.03990000114, 0.08550000191, 0.40830001235, 0.92339998484)),
    "eastern_kingdoms": dict(
        uimap=1415, base="eastern_kingdoms.jpg",
        own=(-16000.0, -19199.900390625, 7466.6000976562, 16000.0),
        world=(-16000.0, -7466.7001953125, 6933.2998046875, 8000.0),
        ui=(0.55049997568, 0.09939999878, 0.89660000801, 0.86909997463)),
}


def continent_rect(c):
    """Rectangle (l, r, t, b) of the continent canvas on Azeroth's map, as fractions (render.py rect())."""
    o0, o1, o3, o4 = c["own"]
    w0, w1, w3, w4 = c["world"]
    um0, um1, uM0, uM1 = c["ui"]
    U = lambda y: um0 + (w4 - y) / (w4 - w1) * (uM0 - um0)
    V = lambda x: um1 + (w3 - x) / (w3 - w0) * (uM1 - um1)
    return U(o4), U(o1), V(o3), V(o0)


def fetch(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "map-art-build/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def tile_list():
    p = os.path.join(CACHE, "ZoneArt.lua")
    fetch(ZONEART_URL, p)
    src = open(p, encoding="utf-8").read()
    body = re.search(r"tiles\s*=\s*\{(.*?)\}", src, re.S).group(1)
    return [(k // 256, k % 256) for k in map(int, re.findall(r"\d+", body))]


def tiles_for(c, tiles):
    """Tiles whose world box meets this continent's canvas, on its side of SPLIT_X."""
    l, r, t, b = continent_rect(c)
    left = c["uimap"] == 1414
    out = []
    for i, j in tiles:
        x0, x1, y0, y1 = i * T, (i + 1) * T, j * T, (j + 1) * T
        if left and x0 >= SPLIT_X:
            continue
        if not left and x1 <= SPLIT_X:
            continue
        if x1 > l * WORLD_W and x0 < r * WORLD_W and y1 > t * WORLD_H and y0 < b * WORLD_H:
            out.append((i, j))
    return out


def tile_path(i, j):
    return os.path.join(CACHE, "MapZones", "%d_%d.blp" % (i, j))


def download(tiles):
    todo = [(i, j) for i, j in tiles if not os.path.exists(tile_path(i, j))]
    if todo:
        print("downloading %d tiles to %s" % (len(todo), CACHE))
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(lambda ij: fetch(ZONES_URL % ij, tile_path(*ij)), todo))


def composite(name, stats=None):
    """Return the 8016x5344 RGB composite for one continent."""
    c = CONTINENTS[name]
    base = Image.open(os.path.join(ROOT, "map", "maps", c["base"])).convert("RGB")
    canvas = base.resize((OUT_W, OUT_H), Image.LANCZOS).convert("RGBA")
    l, r, t, b = continent_rect(c)
    left = c["uimap"] == 1414
    for i, j in tiles_for(c, tile_list()):
        im = Image.open(tile_path(i, j))
        im.load()
        im = im.convert("RGBA")
        if stats is not None:
            lo, hi = im.getchannel("A").getextrema()
            stats.append((i, j, lo, hi))
        # world box of the tile, clipped to this continent's side of the world
        wx0, wx1 = i * T, (i + 1) * T
        wy0, wy1 = j * T, (j + 1) * T
        if left:
            wx1 = min(wx1, SPLIT_X)
        else:
            wx0 = max(wx0, SPLIT_X)
        X0 = max(0, math.ceil((wx0 / WORLD_W - l) / (r - l) * OUT_W))
        X1 = min(OUT_W, math.ceil((wx1 / WORLD_W - l) / (r - l) * OUT_W))
        Y0 = max(0, math.ceil((wy0 / WORLD_H - t) / (b - t) * OUT_H))
        Y1 = min(OUT_H, math.ceil((wy1 / WORLD_H - t) / (b - t) * OUT_H))
        if X1 <= X0 or Y1 <= Y0:
            continue
        # canvas px edge -> world -> tile px edge
        def px_of(X, axis):
            if axis == 0:
                wx = (l + X / OUT_W * (r - l)) * WORLD_W
                return 1 + (wx - i * T) * PX
            wy = (t + X / OUT_H * (b - t)) * WORLD_H
            return 1 + (wy - j * T) * PX
        box = (max(0, px_of(X0, 0)), max(0, px_of(Y0, 1)), min(TILE, px_of(X1, 0)), min(TILE, px_of(Y1, 1)))
        piece = im.resize((X1 - X0, Y1 - Y0), Image.LANCZOS, box=box)   # RGBA is premultiplied by Pillow
        region = canvas.crop((X0, Y0, X1, Y1))
        canvas.paste(Image.alpha_composite(region, piece), (X0, Y0))
    return canvas.convert("RGB")


def cut_pyramid(name, img):
    base = os.path.join(ROOT, "map", "tiles", name)
    if os.path.isdir(base):
        shutil.rmtree(base)
    report = {}
    for z, size in ((2, (OUT_W, OUT_H)), (1, (OUT_W // 2, OUT_H // 2))):
        level = img if z == 2 else img.resize(size, Image.LANCZOS)
        d = os.path.join(base, str(z))
        os.makedirs(d)
        n = total = 0
        for row in range(math.ceil(size[1] / 512)):
            for col in range(math.ceil(size[0] / 512)):
                tile = level.crop((col * 512, row * 512, min(size[0], col * 512 + 512 + GUTTER), min(size[1], row * 512 + 512 + GUTTER)))
                p = os.path.join(d, "%d_%d.jpg" % (col, row))
                tile.save(p, "JPEG", quality=82, optimize=True)
                n += 1
                total += os.path.getsize(p)
        report[z] = (n, total)
    return report


def main():
    keep = None
    if "--keep" in sys.argv:
        keep = sys.argv[sys.argv.index("--keep") + 1]
        os.makedirs(keep, exist_ok=True)
    tiles = tile_list()
    need = set()
    for name, c in CONTINENTS.items():
        need.update(tiles_for(c, tiles))
    download(sorted(need))
    for name in CONTINENTS:
        stats = []
        img = composite(name, stats)
        partial = sum(1 for s in stats if s[2] < 255)
        print("%s: %d tiles used, %d with some transparency (min alpha %d)" % (
            name, len(stats), partial, min(s[2] for s in stats)))
        if keep:
            img.save(os.path.join(keep, name + "_8016.png"))
        for z, (n, total) in cut_pyramid(name, img).items():
            print("  z=%d: %d tiles, %.1f MB" % (z, n, total / 1048576))


if __name__ == "__main__":
    main()
