"""Assemble rendered frame images into a looping review GIF (system Python + Pillow; no Blender
needed - run this after `review_render.py` has written PNG frames, or on any other frame sequence).

The review workflow in `docs/PROCESS.md` asks for each changed action as "a looping GIF (under
about 5 MB) or an MP4, at game speed". `review_render.render_mp4` covers the MP4; this covers the
GIF, using one shared adaptive palette across all frames so flat art colours don't dither or shift
between frames the way independently palettized frames do.

    py -3 frames_to_gif.py out.gif frame_00.png frame_01.png frame_02.png --fps 12
    py -3 frames_to_gif.py out.gif --frames-json sequence.json --fps 40

`sequence.json` is for uneven timing (e.g. a game's per-frame hold pattern): a JSON list of either
image paths (one output frame each) or `[path, holds]` pairs, `holds` counted in output frames at
--fps. Without --frames-json, positional frame paths are shown one output frame each.
"""

import argparse
import json
from pathlib import Path

from PIL import Image


def frames_to_gif(frame_paths, out_path, durations_ms, *, colors=255, loop=0, background=None):
    """Write an animated GIF to `out_path` from `frame_paths`, each shown for the matching entry
    in `durations_ms` (milliseconds; a list the same length as `frame_paths`, or one number used
    for every frame).

    One adaptive palette is built from the first frame and reused for every frame - this keeps
    flat game-art colours stable instead of flickering between independently palettized frames.
    Frames with an alpha channel are flattened onto `background` (an RGB tuple; white if not
    given) before palettizing, since GIF has no partial transparency.
    """
    frame_paths = [Path(p) for p in frame_paths]
    if not frame_paths:
        raise ValueError("no frames given")
    if isinstance(durations_ms, (int, float)):
        durations_ms = [durations_ms] * len(frame_paths)
    if len(durations_ms) != len(frame_paths):
        raise ValueError(f"{len(frame_paths)} frames but {len(durations_ms)} durations")

    def flatten(img):
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            img = img.convert("RGBA")
            flat = Image.new("RGB", img.size, background or (255, 255, 255))
            flat.paste(img, mask=img.split()[-1])
            return flat
        return img.convert("RGB")

    frames = [flatten(Image.open(p)) for p in frame_paths]
    palette_source = frames[0].convert("P", palette=Image.Palette.ADAPTIVE, colors=colors)
    paletted = [f.quantize(palette=palette_source, dither=Image.Dither.NONE) for f in frames]

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    paletted[0].save(out_path, save_all=True, append_images=paletted[1:], duration=durations_ms,
                      loop=loop, disposal=2, optimize=False)

    size_mb = out_path.stat().st_size / 1e6
    total_s = sum(durations_ms) / 1000
    print(f"wrote {out_path}: {len(frames)} frames, {total_s:.2f} s, {size_mb:.2f} MB")
    if size_mb > 5:
        print(f"## over the ~5 MB review budget ({size_mb:.2f} MB): use fewer frames, a smaller "
              f"canvas, or fewer --colors")
    return str(out_path)


def _load_sequence(frame_args, frames_json, fps):
    if frames_json:
        entries = json.loads(Path(frames_json).read_text(encoding="utf-8"))
        paths, holds = [], []
        for entry in entries:
            if isinstance(entry, str):
                paths.append(entry)
                holds.append(1)
            else:
                path, hold = entry
                paths.append(path)
                holds.append(hold)
        return paths, [hold * 1000 / fps for hold in holds]
    return frame_args, [1000 / fps] * len(frame_args)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out_gif")
    ap.add_argument("frames", nargs="*", help="frame image paths, in order")
    ap.add_argument("--frames-json", help="JSON list of paths, or [path, holds] pairs, instead of positional frames")
    ap.add_argument("--fps", type=float, default=12.0, help="playback rate the durations are computed at (default 12)")
    ap.add_argument("--colors", type=int, default=255, help="shared palette size, 2-255 (default 255)")
    ap.add_argument("--background", default=None, help="'R,G,B' to flatten transparency onto (default white)")
    ap.add_argument("--loop", type=int, default=0, help="loop count, 0 = forever (default)")
    args = ap.parse_args(argv)
    if not args.frames and not args.frames_json:
        ap.error("pass frame paths, or --frames-json")
    paths, durations = _load_sequence(args.frames, args.frames_json, args.fps)
    background = tuple(int(v) for v in args.background.split(",")) if args.background else None
    frames_to_gif(paths, args.out_gif, durations, colors=args.colors, loop=args.loop, background=background)


if __name__ == "__main__":
    main()
