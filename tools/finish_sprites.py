"""Composite the ground shadow under each raw frame and build the game-ready mask (system Python +
Pillow - no Blender needed). This is the finishing half of "making sprites look native"; run it on
`render_sprites.py`'s output. See docs/SPRITES.md for the reasoning.

Per frame, from --raw/frames.json to --out/:
  - shadow: the union of the projected, sheared silhouette triangles rasterised at N x supersample
    and downsampled (Lanczos), multiplied once by shadow.alpha/255, pure black, composited UNDER
    the straight-alpha beauty render.
  - <key>_m.png: R and B pass through the raw mask, weighted by (body alpha / final alpha) so
    shadow-only and edge pixels get none of whatever that channel encodes (team colour by default -
    see render_sprites.py's mask config); A = the final alpha. G is special-cased: if the config's
    `mask.green_channel` is set, G becomes SHCDE's own row-based cutaway ramp (docs/SHCDE.md
    section 7), measured from the game, replacing whatever render_sprites.py put there (such as a
    tracked object's flag - see below) for the raw mask only.
  - tracked-object measurement: for each of the config's `checks.tracked_objects`, this pass finds
    its alpha-weighted pixel centroid on the *raw* mask's flagged channel, before that channel is
    possibly overwritten by the ramp above, and adds it next to render_sprites.py's own 3D
    measurement of the same object - `validate_sprites.py` compares the two.
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


def green_ramp(intercept, slope_per_px, pivot_row_from_top, width, height):
    """SHCDE's own cutaway ramp (docs/SHCDE.md section 7), measured from the game: one row value
    per canvas row, broadcast across the width. Row 0 is the canvas top."""
    rows = np.arange(height, dtype=np.float64)[:, None]
    value = np.clip(np.rint(intercept + slope_per_px * (rows - pivot_row_from_top)), 0, 255)
    return np.broadcast_to(value, (height, width)).astype(np.uint8)


_CHANNEL_INDEX = {"Red": 0, "Green": 1, "Blue": 2}


def centroid(weight):
    """Alpha-weighted pixel centroid of a 2D weight image, top-left origin, pixel centres at
    x.5/y.5; (None, 0.0) when nothing is set."""
    total = float(weight.sum())
    if total <= 0:
        return None, 0.0
    ys, xs = np.indices(weight.shape)
    return [round(float((xs * weight).sum() / total) + 0.5, 2),
            round(float((ys * weight).sum() / total) + 0.5, 2)], total


def finish(args):
    man = json.loads((args.raw / "frames.json").read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    cam, sh = man["camera"], man["shadow"]
    W, H = cam["canvas"]
    tracked_cfg = man.get("checks", {}).get("tracked_objects", [])
    green_cfg = man.get("mask", {}).get("green_channel")
    ramp = green_ramp(green_cfg["intercept"], green_cfg["slope_per_px"], cam["pivot_px_top_left"][1],
                      W, H) if green_cfg else None
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

        # tracked-object centroids, from the RAW mask's flagged channel (before any of it is
        # overwritten below) weighted by the beauty alpha - the pixel half of the facing-side check.
        tracked = dict(f.get("tracked", {}))
        alpha_share = body_a.astype(np.float64) / 255.0
        for spec in tracked_cfg:
            if "mask_channel" not in spec:
                continue
            idx = _CHANNEL_INDEX[spec["mask_channel"]]
            px_centroid, px_weight = centroid((raw[:, :, idx] / 255.0) * alpha_share)
            tracked.setdefault(spec["name"], {})
            tracked[spec["name"]]["px_centroid"] = px_centroid
            tracked[spec["name"]]["px_weight"] = round(px_weight, 1)

        # mask: R and B pass through weighted by how much of the final pixel is actual body (not
        # shadow-only or a soft edge), so nothing you flagged in render_sprites.py bleeds onto the
        # shadow; G is the measured cutaway ramp when configured, overwriting whatever was there.
        m = np.zeros((H, W, 4), dtype=np.uint8)
        share = body_a.astype(np.float64) / np.maximum(out_a.astype(np.float64), 1.0)
        m[:, :, :3] = np.rint(np.clip(raw[:, :, :3] * share[:, :, None], 0, 255)).astype(np.uint8)
        if ramp is not None:
            m[:, :, 1] = ramp
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
                    "raw_mask_alpha_max_diff": int(np.abs(raw[:, :, 3] - body_a).max()),
                    "tracked": tracked})
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
