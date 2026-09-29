"""Pack finished sprite frames into a colour + mask atlas with a pivot-indexed rect list (system
Python + Pillow - no Blender needed). Run this on one or more `finish_sprites.py` output folders.

Packing: crop every frame to its own opaque bounding box, dedupe identical crops (same pixels,
same box) so a still pose used at several key frames costs one image, shelf-pack sorted by height
into a fixed-width atlas with a small gutter between entries, and round the atlas height up to a
power of two. The pivot is stored per entry, in the entry's own rect, both as pixels and as a
fraction of the rect's size (Unity's `Sprite.pivot`, for example, wants the fraction) - never as a
fixed offset from the atlas corner, since every entry has a different crop.

Outputs, under --out:
  atlas.png, atlas_m.png    the packed colour and mask atlases (binaries - keep these local, don't
                            commit them; see this repo's own README/.gitignore for why)
  atlas_index.json          every entry: which source frame, its rect, its pivot, and a couple of
                            cheap self-checks (see below)

Two checks run automatically and fail the build (exit 1) rather than silently shipping a bad atlas:
  - every pivot lands on a whole pixel of its own rect (a fractional pivot means the camera/canvas
    pivot from render_sprites.py wasn't on a whole pixel to begin with);
  - every packed rect's pixels are byte-identical to the crop that went in (catches a packing bug,
    not just a source-data bug).

    py -3 tools/pack_atlas.py --frames out/frames/walk out/frames/idle --out out/atlas --config sprite_scene.json
"""

import argparse
import hashlib
import json
import math
from pathlib import Path

from PIL import Image


def parse():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--frames", nargs="+", required=True, type=Path,
                   help="one or more finish_sprites.py output folders (each has frames.json)")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--config", type=Path, help="a sprite_scene.json, for atlas.width/padding/pixels_per_unit")
    p.add_argument("--width", type=int, help="override the config's atlas.width (default 2048)")
    p.add_argument("--padding", type=int, help="override the config's atlas.padding (default 2)")
    p.add_argument("--pixels-per-unit", type=float, help="override the config's atlas.pixels_per_unit")
    return p.parse_args()


def load_frames(paths):
    groups, records = [], []
    for path in paths:
        man = json.loads((path / "frames.json").read_text(encoding="utf-8"))
        groups.append((path, man))
        for f in man["frames"]:
            records.append(dict(f, _dir=path))
    return groups, records


def pack(records, width, padding):
    crops, where = {}, {}
    for r in records:
        colour = Image.open(r["_dir"] / r["image"]).convert("RGBA")
        mask = Image.open(r["_dir"] / r["mask"]).convert("RGBA")
        box = colour.getchannel("A").getbbox()
        if box is None:
            raise ValueError(f"{r['key']}: fully transparent frame - nothing to pack")
        c, m = colour.crop(box), mask.crop(box)
        h = hashlib.sha256(c.tobytes() + m.tobytes() + str(box).encode()).hexdigest()
        if h not in crops:
            crops[h] = {"colour": c, "mask": m, "box": box}
        where[r["key"]] = h

    x, y, row_h = padding, padding, 0
    for h in sorted(crops, key=lambda k: (-crops[k]["colour"].height, k)):
        it = crops[h]
        cw, ch = it["colour"].size
        assert cw + 2 * padding <= width, f"a frame ({cw}px) is wider than the atlas ({width}px)"
        if x + cw + padding > width:
            x, y, row_h = padding, y + row_h + padding, 0
        it["x"], it["top"] = x, y
        row_h = max(row_h, ch)
        x += cw + padding
    height = 2 ** math.ceil(math.log2(max(1, y + row_h + padding)))

    atlas, atlas_m = Image.new("RGBA", (width, height)), Image.new("RGBA", (width, height))
    for it in crops.values():
        atlas.paste(it["colour"], (it["x"], it["top"]))
        atlas_m.paste(it["mask"], (it["x"], it["top"]))
    return atlas, atlas_m, crops, where, height


def main():
    args = parse()
    cfg = json.loads(args.config.read_text(encoding="utf-8")) if args.config else {}
    acfg = cfg.get("atlas", {})
    width = args.width or acfg.get("width", 2048)
    padding = args.padding if args.padding is not None else acfg.get("padding", 2)
    ppu = args.pixels_per_unit or acfg.get("pixels_per_unit")

    groups, records = load_frames(args.frames)
    assert records, "no frames found under --frames"
    atlas, atlas_m, crops, where, height = pack(records, width, padding)

    args.out.mkdir(parents=True, exist_ok=True)
    atlas.save(args.out / "atlas.png", optimize=True)
    atlas_m.save(args.out / "atlas_m.png", optimize=True)

    cam = groups[0][1]["camera"]
    px, py = cam["pivot_px_bottom_left"]
    _W, H = cam["canvas"]
    entries, pivot_bad, pixel_bad = [], [], []
    for r in records:
        it = crops[where[r["key"]]]
        left, _top, _right, bottom = it["box"]
        cw, ch = it["colour"].size
        piv_x, piv_y = px - left, py - (H - bottom)          # pivot in rect pixels, from the rect's bottom-left
        if piv_x != int(piv_x) or piv_y != int(piv_y):
            pivot_bad.append(r["key"])
        rect = {"x": it["x"], "y": height - it["top"] - ch, "w": cw, "h": ch}   # y from the atlas's bottom
        back = atlas.crop((it["x"], it["top"], it["x"] + cw, it["top"] + ch))
        back_m = atlas_m.crop((it["x"], it["top"], it["x"] + cw, it["top"] + ch))
        if back.tobytes() != it["colour"].tobytes() or back_m.tobytes() != it["mask"].tobytes():
            pixel_bad.append(r["key"])
        entries.append({"key": r["key"], "action": r.get("action"), "frame": r.get("frame"), "facing": r.get("facing"),
                        "rect": rect, "pivot": {"x": piv_x / cw, "y": piv_y / ch},
                        "pivot_px": {"x": piv_x, "y": piv_y}, "pixels_per_unit": ppu})

    index = {"schema": "sprite_atlas_index/1", "pixels_per_unit": ppu,
             "atlas": {"colour": "atlas.png", "mask": "atlas_m.png", "size": [width, height]},
             "rect_origin": "bottom-left", "pivot": "fraction of the rect from its bottom-left; pivot_px in rect pixels",
             "camera": cam, "unique_images": len(crops), "frames": entries,
             "checks": {"pivot_on_whole_pixel": not pivot_bad, "pixel_roundtrip_exact": not pixel_bad,
                        "pivot_failures": pivot_bad, "roundtrip_failures": pixel_bad}}
    (args.out / "atlas_index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    print(f"atlas {width}x{height}, {len(crops)} unique images for {len(entries)} frames")
    if pivot_bad or pixel_bad:
        print("## CHECK FAILURES: pivot not on a whole pixel:", pivot_bad)
        print("## CHECK FAILURES: packed pixels changed from the source crop:", pixel_bad)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
