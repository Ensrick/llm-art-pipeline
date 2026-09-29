"""Validate finished sprite frames against measurements taken from the actual game (system Python +
Pillow - no Blender needed). Run this on one or more `finish_sprites.py` output folders, after
rendering and before (or instead of) packing - a failure here means a re-render, not a bad atlas.

Every check prints a number, not just pass or fail, and the checks below are all built from facts
this project measured directly from the installed game's own shipped sprites and observed timing -
see docs/SHCDE.md. None of it is Firefly's files, an extracted asset, or decompiled code (see
docs/RUNTIME.md section 1 for that line) - a pixel-height range or a slot name is exactly as public
as looking at your own installed game.

Checks:
  - mask contract: alpha channel matches the beauty render's alpha; every channel is in 0-255.
  - native frame size (--carrier, --block): this render's bounds fall in a plausible range of the
    installed game's own shipped sprites for the same kind of pose (docs/SHCDE.md section 5's
    method, generalized past the one worked example there - see --native-heights to supply your
    own carrier's numbers instead of tools/pikeman_carrier.py's).
  - slot coverage (--carrier, --file): every slot a block is supposed to fill is filled exactly
    once, using tools/pikeman_carrier.py's measured slot tables.
  - facing-side (config `checks.facing_side_rule`): a tracked object's on-screen pixel position
    agrees in side and depth-ordering with its 3D geometry, across facings - catches a mirrored
    rig, a flipped facing convention, or a part parented to the wrong bone, all of which can
    otherwise look "close enough" in a single still.

    py -3 tools/validate_sprites.py --frames out/frames/walk --config my_scene.json --carrier pikeman --block walk
"""

import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image


def parse():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--frames", nargs="+", required=True, type=Path, help="finish_sprites.py output folder(s)")
    p.add_argument("--config", type=Path, help="the sprite_scene.json used to render these frames (for checks.*)")
    p.add_argument("--carrier", choices=["pikeman"], help="use tools/<carrier>_carrier.py's measured tables")
    p.add_argument("--block", help="this frame set's block name in the carrier's tables (for the native-size check)")
    p.add_argument("--file", dest="file_name", default="body_pikeman", help="carrier sprite file name, for slot names")
    p.add_argument("--native-heights", type=Path,
                   help="JSON {height:[min,med,max], width:[med,max], top:[med,max], below:max} instead of --carrier")
    return p.parse_args()


def check(name, ok, **detail):
    return {"check": name, "pass": bool(ok), **detail}


def load(paths):
    groups, records = [], []
    for path in paths:
        man = json.loads((path / "frames.json").read_text(encoding="utf-8"))
        groups.append((path, man))
        for f in man["frames"]:
            records.append(dict(f, _dir=path))
    return groups, records


def check_mask_contract(records):
    bad = []
    for r in records:
        m = np.asarray(Image.open(r["_dir"] / r["mask"]))
        c = np.asarray(Image.open(r["_dir"] / r["image"]))
        if not np.array_equal(m[:, :, 3], c[:, :, 3]):
            bad.append(f"{r['key']}: mask alpha != colour alpha")
    return check("mask: alpha channel matches the colour render", not bad, failures=bad[:50])


def check_native_frame_size(records, native):
    """`native` = {height:[min,med,max], width:[med,max], top:[med,max], below:max}, in pixels,
    measured from the installed game (docs/SHCDE.md section 5). Not a pass/fail gate by itself -
    reports how this render compares, for a human to judge whether an outlier is a mistake or just
    a different pose."""
    heights = [r["finished_bounds"][3] - r["finished_bounds"][1] for r in records if r.get("finished_bounds")]
    widths = [r["finished_bounds"][2] - r["finished_bounds"][0] for r in records if r.get("finished_bounds")]
    if not heights:
        return check("native frame size comparison", True, note="no finished_bounds to compare")
    ours = {"height_min_med_max": [min(heights), round(float(np.median(heights)), 1), max(heights)],
            "width_med_max": [round(float(np.median(widths)), 1), max(widths)]}
    within = native["height"][0] * 0.5 <= ours["height_min_med_max"][1] <= native["height"][2] * 1.5
    return check("native frame size comparison (measured from the game; a loose sanity range, not a spec)",
                 within, ours=ours, native=native)


def check_slot_coverage(records, carrier, file_name, block):
    # Matched by slot number, not by re-deriving a name, since a frame record here only carries
    # whatever slot number your own --slot-map assigned it (pack_atlas.py), not a (phase, facing).
    got_slots = {r["slot"] for r in records if r.get("slot") is not None}
    expected_slots = {carrier.slot(block, p, f) for p, f, _n in carrier.block_frames(block, file_name)}
    missing = sorted(expected_slots - got_slots)
    unknown = sorted(got_slots - expected_slots)
    return check(f"slot coverage for block '{block}'", not missing and not unknown,
                filled=len(got_slots), expected=len(expected_slots), missing=missing[:50], unknown=unknown[:50])


def check_facing_side(records, rule, cfg):
    """A tracked object's on-screen side and depth ordering agree with the 3D geometry, across
    facings - both measurements come from render_sprites.py/finish_sprites.py's "tracked" field."""
    fails, notes = [], []
    by_pose = {}
    for r in records:
        by_pose.setdefault((r.get("action"), r.get("frame")), {})[r["facing"]] = r
    tracked_names = [t["name"] for t in cfg.get("checks", {}).get("tracked_objects", [])] if cfg else []
    for name in tracked_names:
        for pose, fac in sorted(by_pose.items(), key=lambda kv: (str(kv[0][0]), kv[0][1] if kv[0][1] is not None else 0)):
            front, back = rule["front_facing"], rule["back_facing"]
            for f, r in fac.items():
                tr = r.get("tracked", {})
                t = tr.get(name)
                ref_px = tr.get("_reference_px")
                if not t or t.get("dx_px") is None:
                    continue
                geo = t["dx_px"]
                pix = (t["px_centroid"][0] - ref_px[0]) if t.get("px_centroid") and ref_px else None
                if f == front and not geo > 0:
                    fails.append(f"{name} {pose} facing {f} (front): expected screen-right (geometry), got {geo:+.1f} px")
                if f == back and not geo < 0:
                    fails.append(f"{name} {pose} facing {f} (back): expected screen-left (geometry), got {geo:+.1f} px")
                # The rendered pixels should agree with the geometry once the object is big and
                # clear enough on screen to trust its centroid (weight) and it's not near-centred
                # (small geo) where either measurement's noise can flip the sign.
                weight = t.get("px_weight") or 0
                if pix is not None and abs(geo) >= 3 and weight >= 20 and math.copysign(1, geo) != math.copysign(1, pix):
                    fails.append(f"{name} {pose} facing {f}: pixels ({pix:+.1f} px) disagree with geometry ({geo:+.1f} px)")
            near, far = rule.get("near_facing"), rule.get("far_facing")
            if near in fac and far in fac:
                tn, tf = fac[near].get("tracked", {}).get(name), fac[far].get("tracked", {}).get(name)
                if tn and tf and tn.get("depth_m") is not None and tf.get("depth_m") is not None:
                    if not tn["depth_m"] < tf["depth_m"]:
                        notes.append(f"{name} {pose}: not nearer the camera at facing {near} than {far}")
    return check(f"facing-side check ({', '.join(tracked_names) or 'no tracked objects configured'})",
                not fails, failures=fails[:50], notes=notes[:50])


def main():
    args = parse()
    cfg = json.loads(args.config.read_text(encoding="utf-8")) if args.config else None
    _groups, records = load(args.frames)
    assert records, "no frames found under --frames"
    checks = [check_mask_contract(records)]

    if args.native_heights:
        checks.append(check_native_frame_size(records, json.loads(args.native_heights.read_text(encoding="utf-8"))))
    elif args.carrier == "pikeman" and args.block:
        import pikeman_carrier as carrier
        if args.block in carrier.NATIVE_FRAME_SIZES_PX:
            checks.append(check_native_frame_size(records, carrier.NATIVE_FRAME_SIZES_PX[args.block]))
        if "slot" in (records[0] if records else {}):
            checks.append(check_slot_coverage(records, carrier, args.file_name, args.block))

    if cfg and cfg.get("checks", {}).get("facing_side_rule"):
        checks.append(check_facing_side(records, cfg["checks"]["facing_side_rule"], cfg))

    for c in checks:
        print(("PASS " if c["pass"] else "FAIL ") + c["check"])
        for k, v in c.items():
            if k not in ("check", "pass"):
                print(f"  {k}: {v}")
    if not all(c["pass"] for c in checks):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
