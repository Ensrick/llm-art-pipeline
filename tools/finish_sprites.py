"""Composite the ground shadow under each raw frame and build the game-ready mask (system Python +
Pillow - no Blender needed). This is the finishing half of "making sprites look native"; run it on
`render_sprites.py`'s output. See docs/SPRITES.md for the reasoning.

Per frame, from --raw/frames.json to --out/:
  - shadow: the union of the projected, sheared silhouette triangles rasterised at N x supersample
    and downsampled (Lanczos), multiplied once by shadow.alpha/255, pure black, composited UNDER
    the straight-alpha beauty render.
  - <key>_m.png: every channel of the raw mask, weighted by (body alpha / final alpha) so
    shadow-only and edge pixels get none of whatever that channel encodes (team colour, or
    anything else you wired up in render_sprites.py's mask config); A = the final alpha.
  - refusal: if any pixel of the body or its shadow reaches the canvas border, the run stops
    (exit 2) instead of shipping a clipped sprite - enlarge the canvas, never shrink the model.

    py -3 tools/finish_sprites.py --raw out/raw/walk --out out/frames/walk
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def parse():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--raw", type=Path, required=True, help="a render_sprites.py output folder (has frames.json)")
    p.add_argument("--out", type=Path, required=True)
    return p.parse_args()


def shadow_coverage(pts, tris, size, supersample):
    """Union of projected triangles as one opaque coverage, rasterised at `supersample` x and
    Lanczos-reduced back to `size` (softens the shadow edge without a separate blur pass)."""
    w, h = size
    big = Image.new("L", (w * supersample, h * supersample), 0)
    draw = ImageDraw.Draw(big)
    p = pts * supersample - 0.5                      # pixel-edge coords -> Pillow's pixel-centre coords
    for a, b, c in tris:
        draw.polygon([tuple(p[a]), tuple(p[b]), tuple(p[c])], fill=255)
    return big.resize((w, h), Image.Resampling.LANCZOS)


def finish(args):
    man = json.loads((args.raw / "frames.json").read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    cam, sh = man["camera"], man["shadow"]
    W, H = cam["canvas"]
    topo_cache = {}
    finished, clipped = [], []
    for f in man["frames"]:
        beauty = Image.open(args.raw / f["image"]).convert("RGBA")
        raw_m = Image.open(args.raw / f["raw_mask"]).convert("RGBA")
        assert beauty.size == raw_m.size == (W, H), (f["key"], beauty.size, raw_m.size)
        body_a = np.asarray(beauty.getchannel("A"))
        raw = np.asarray(raw_m).astype(np.float64)

        npz = np.load(args.raw / f["shadow"])
        topo_name = str(npz["topology"])
        if topo_name not in topo_cache:
            topo_cache[topo_name] = np.load(args.raw / topo_name)
        pts = npz["pts32"].astype(np.float64) / 32.0
        cover = shadow_coverage(pts, topo_cache[topo_name], (W, H), sh["supersample"])
        shadow = cover.point(lambda v: round(v * sh["alpha"] / 255))
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        layer.putalpha(shadow)
        combined = Image.alpha_composite(layer, beauty)      # shadow first, beauty on top
        out_a = np.asarray(combined.getchannel("A"))

        # mask: every channel weighted by how much of the final pixel is actual body (not shadow-only
        # or a soft edge), so nothing you flagged in render_sprites.py bleeds onto the shadow
        m = np.zeros((H, W, 4), dtype=np.uint8)
        share = body_a.astype(np.float64) / np.maximum(out_a.astype(np.float64), 1.0)
        m[:, :, :3] = np.rint(np.clip(raw[:, :, :3] * share[:, :, None], 0, 255)).astype(np.uint8)
        m[:, :, 3] = out_a
        m[out_a == 0] = 0
        mask = Image.fromarray(m)
        assert np.array_equal(np.asarray(mask.getchannel("A")), out_a)

        bounds = combined.getchannel("A").getbbox()
        if not (bounds and bounds[0] > 0 and bounds[1] > 0 and bounds[2] < W and bounds[3] < H):
            clipped.append({"key": f["key"], "bounds": list(bounds or []), "canvas": [W, H]})
        combined.save(args.out / f["image"])
        mask.save(args.out / f"{f['key']}_m.png")

        rec = dict(f)
        rec.update({"mask": f"{f['key']}_m.png", "finished_bounds": list(bounds) if bounds else None,
                    "body_bounds": list(beauty.getchannel("A").getbbox() or []),
                    "shadow_bounds": list(shadow.getbbox() or []),
                    "shadow_alpha_max": int(np.asarray(shadow).max()),
                    "raw_mask_alpha_max_diff": int(np.abs(raw[:, :, 3] - body_a).max())})
        finished.append(rec)

    out = dict(man, frames=finished,
               finish={"shadow_alpha": sh["alpha"], "supersample": sh["supersample"], "outline": False})
    (args.out / "frames.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    (args.out / "clipping.json").write_text(json.dumps(clipped, indent=1), encoding="utf-8")
    print(f"FINISHED {args.raw.name}: {len(finished)} frames, {len(clipped)} touching the canvas edge")
    return clipped


def main():
    args = parse()
    clipped = finish(args)
    if clipped:
        for c in clipped[:40]:
            print("  CLIPPED", c)
        print("Re-render with a larger canvas in the scene config; never shrink the model.")
        sys.exit(2)


if __name__ == "__main__":
    main()
