"""Turntable, multi-view and game-timed review rendering (Blender 4.4, headless).

This is the rendering backbone behind the review clips described in
`docs/PROCESS.md`: fitted multi-view stills for a turnaround or a before/after,
a game-timed MP4 for a looping action, and a loop-seam check that reports how
cleanly a cyclic action closes. It sits next to `anim_cookbook.py` and
`gear_kit.py` in this folder and imports both.

Typical use from a unit's own review script:

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    import review_render as rr

    tt = rr.review_turntable([my_rig])
    manifest = rr.render_views(
        "out/work", "turnaround", count=8,
        pose=lambda i: rr.facing_pose(tt, i),
        meshes=lambda: my_meshes,
        labels=[f"facing {i}" for i in range(8)],
        views={"front": {"direction": (0, 1, -0.3), "ppm": 120.0}},
    )

Nothing here reads or writes a specific project's file layout: every path is a
parameter, and the camera directions / pixels-per-metre used below are example
defaults from one such project, not requirements. Bring your own `views` dict
to replace them.
"""

import json
import math
from pathlib import Path

import bpy
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Matrix, Vector

import anim_cookbook as ac
import gear_kit as gk

REVIEW_TURNTABLE = "Review_Turntable"

# Example presets, not requirements: a "game" camera looking down at 30 degrees, and a
# three-quarter reviewing angle. Pass your own `dirs=` / `views=` to use different ones.
GAME_DIR = (0.0, math.cos(math.radians(30)), -math.sin(math.radians(30)))
THREE_Q_DIR = (2.7, 5.0, -0.85)
DEFAULT_PPM = {"3q": 120.0, "mp4": 150.0}


def facing_turn(native, count=8):
    """Turntable Z rotation (radians) that shows facing `native` of `count` evenly spaced
    facings, with facing 3 (of 8) as the front at turn 0. Matches the common convention for an
    8-direction sprite set; pass a different `count` for any other facing count."""
    return math.radians((3 - native) * (360 / count))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- playback and sampling

def play(rig, action):
    ac.play(rig, action)


def frame_set(t):
    """Set the scene to a possibly fractional frame `t` (Blender subframes)."""
    f = math.floor(t)
    bpy.context.scene.frame_set(int(f), subframe=float(t - f))


def mesh_points(obj):
    return ac.world_mesh(obj)[0]


def bone_points(rig):
    """Every pose bone's world-space head and tail, as one (2N, 3) array."""
    mw = rig.matrix_world
    return np.array([list(mw @ pb.head) + list(mw @ pb.tail) for pb in rig.pose.bones]).reshape(-1, 3)


def meshes_under(rig):
    """Every mesh object parented (directly, or through other objects) under `rig`."""
    def under(o):
        while o.parent is not None:
            if o.parent == rig:
                return True
            o = o.parent
        return False
    return [o for o in bpy.data.objects if o.type == "MESH" and under(o)]


# --------------------------------------------------------------------------- turntable and scene setup

def review_turntable(children, name=REVIEW_TURNTABLE):
    """One empty at the origin that turns every child together, for facing renders. Parenting
    preserves each child's current world transform."""
    tt = bpy.data.objects.get(name)
    if tt is None:
        tt = bpy.data.objects.new(name, None)
        bpy.context.scene.collection.objects.link(tt)
    bpy.context.view_layer.update()                # world matrices of freshly moved children
    for child in children:
        mw = child.matrix_world.copy()
        child.parent = tt
        child.matrix_parent_inverse = Matrix.Identity(4)
        child.matrix_world = mw
    return tt


def facing_pose(turntable, native, count=8):
    """Convenience `pose(i)` helper: turn `turntable` to show facing `i` of `count`."""
    turntable.rotation_euler.z = facing_turn(native, count)


def setup_render(transparent=True):
    """Fast, flat Workbench setup for motion review. For material, metal or shine review, render
    through your game engine's own path instead (Workbench does not show node metallic)."""
    scene = bpy.context.scene
    r = scene.render
    r.engine = "BLENDER_WORKBENCH"
    r.film_transparent = transparent
    scene.display.render_aa = "8"
    sh = scene.display.shading
    sh.light = "STUDIO"
    sh.color_type = "TEXTURE"
    sh.show_shadows = sh.show_cavity = sh.show_object_outline = sh.show_specular_highlight = False
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"


def _axes(cam):
    m = cam.matrix_world.to_3x3()
    return np.array(m.col[0]), np.array(m.col[1])


# --------------------------------------------------------------------------- rendering

def render_views(out_dir, state, count, pose, meshes, labels, views, *, tag="phase", ppm=None,
                  dirs=None, transparent=True, turntable=None, ground_z=0.0):
    """Render `count` frames from each named view onto one canvas per view, fitted to the
    subject so nothing is clipped and nothing wastes pixels.

    `pose(i)` poses the scene for frame `i` (0-indexed). `meshes()` returns the objects whose
    bounds should frame the camera (call it fresh each time; visibility may change frame to
    frame). `labels` names each frame, for the manifest.

    `views` is an iterable of view names. For each name, in order:
    - if `dirs` (a dict) has that name, its `(x, y, z)` camera direction is used, turntable at 0;
    - otherwise, a name starting with "g" is treated as a game facing: `facing_turn(int(name[1:]))`
      turns the turntable and the camera looks from `GAME_DIR`;
    - any other name gets a fixed camera at `THREE_Q_DIR`.
    Override `ppm` (pixels per metre) per view via the `ppm` dict; unlisted views fall back to
    `DEFAULT_PPM`, then 120.0.

    Returns a manifest: `{"state", "tag", "labels", "views": {name: {"paths", "size", "px_per_m",
    "pivot_px"}}}`. `pivot_px` is where world `(0, 0, ground_z)` lands in the image, top-left
    origin - useful as a sprite's pivot point.
    """
    ppm = dict(DEFAULT_PPM, **(ppm or {}))
    dirs = dict(dirs or {})
    setup_render(transparent)
    turntable = turntable or bpy.data.objects[REVIEW_TURNTABLE]
    out_dir = Path(out_dir) / state
    out_dir.mkdir(parents=True, exist_ok=True)
    cams, view_dirs, turn = {}, {}, {}
    for view in views:
        if view in dirs:
            view_dirs[view], turn[view] = dirs[view], 0.0
        elif view.startswith("g"):
            view_dirs[view], turn[view] = GAME_DIR, facing_turn(int(view[1:]))
        else:
            view_dirs[view], turn[view] = THREE_Q_DIR, 0.0
        cams[view] = gk.aim_camera(gk.ensure_camera(f"Review_{view}_Camera"), (0.0, 0.0, 1.0), view_dirs[view], 3.0)
    manifest = {"state": state, "tag": tag, "labels": list(labels), "views": {}}
    for view in views:
        cam = cams[view]
        px_per_m = ppm.get(view, 120.0)
        turntable.rotation_euler.z = turn[view]
        bpy.context.view_layer.update()
        right, up = _axes(cam)
        b = [math.inf, -math.inf, math.inf, -math.inf]
        for i in range(count):
            pose(i)
            pts = np.vstack([mesh_points(o) for o in meshes() if not o.hide_render])
            u, v = pts @ right, pts @ up
            b = [min(b[0], u.min()), max(b[1], u.max()), min(b[2], v.min()), max(b[3], v.max())]
        margin = 0.05
        w = int(math.ceil((b[1] - b[0] + 2 * margin) * px_per_m / 2) * 2)
        h = int(math.ceil((b[3] - b[2] + 2 * margin) * px_per_m / 2) * 2)
        target = Vector(right * 0.5 * (b[0] + b[1]) + up * 0.5 * (b[2] + b[3]))
        gk.aim_camera(cam, target, view_dirs[view], max(w, h) / px_per_m)
        bpy.context.scene.render.resolution_x, bpy.context.scene.render.resolution_y = w, h
        bpy.context.view_layer.update()
        x, y, _z = world_to_camera_view(bpy.context.scene, cam, Vector((0.0, 0.0, ground_z)))
        paths = []
        for i in range(count):
            pose(i)
            path = out_dir / f"{tag}_{view}_{i:02d}.png"
            gk.render_png(cam, path, (w, h))
            paths.append(str(path))
        manifest["views"][view] = {"paths": paths, "size": [w, h], "px_per_m": px_per_m,
                                   "pivot_px": [round(x * w, 1), round((1 - y) * h, 1)]}
    turntable.rotation_euler.z = 0.0
    bpy.context.view_layer.update()
    return manifest


def render_mp4(review_dir, out_dir, state, count, pose, meshes, sequence, name, *, view="mp4",
                ppm=None, dirs=None, fps=40, turntable=None, world_color=(0.30, 0.31, 0.33)):
    """A movie at a fixed game-style timing: `sequence` is `[(frame_index, holds), ...]`, where
    each entry holds that already-rendered frame for `holds` output frames at `fps`. Frames are
    rendered once each (via `render_views`) and held by the video sequencer, so a 12-pose action
    costs 12 renders no matter how long the movie plays.

    Returns the output `.mp4` path (under `review_dir`).
    """
    review_dir = Path(review_dir)
    scene = bpy.context.scene
    world = scene.world or bpy.data.worlds.new("Review_World")
    scene.world = world
    world.color = world_color
    manifest = render_views(out_dir, state, count, pose, meshes, [str(i) for i in range(count)],
                            views=(view,), tag=f"mp4_{name}", ppm=ppm, dirs=dirs,
                            transparent=False, turntable=turntable)
    frames = manifest["views"][view]["paths"]
    w, h = manifest["views"][view]["size"]
    movie = review_dir / f"{name}_game_timing_{fps}fps.mp4"
    review_dir.mkdir(parents=True, exist_ok=True)
    seq_scene = bpy.data.scenes.new("Review_MP4")
    editor = seq_scene.sequence_editor_create()
    t = 1
    for index, holds in sequence:
        strip = editor.strips.new_image(f"s{t}", frames[index], channel=1, frame_start=t)
        strip.frame_final_duration = holds
        t += holds
    r = seq_scene.render
    r.resolution_x, r.resolution_y, r.resolution_percentage = w, h, 100
    r.fps, r.fps_base = fps, 1.0
    r.use_sequencer, r.use_compositing = True, False
    r.image_settings.file_format = "FFMPEG"
    r.ffmpeg.format, r.ffmpeg.codec = "MPEG4", "H264"
    r.ffmpeg.constant_rate_factor, r.ffmpeg.ffmpeg_preset = "HIGH", "GOOD"
    seq_scene.frame_start, seq_scene.frame_end = 1, t - 1
    r.filepath = str(movie)
    bpy.ops.render.render(animation=True, scene=seq_scene.name)
    bpy.data.scenes.remove(seq_scene)
    setup_render(transparent=True)
    clip = bpy.data.movieclips.load(str(movie))
    assert clip.frame_duration == t - 1 and tuple(clip.size) == (w, h), (clip.frame_duration, tuple(clip.size))
    bpy.data.movieclips.remove(clip)
    print("## movie", movie, t - 1, "frames", w, "x", h)
    return str(movie)


# --------------------------------------------------------------------------- the loop-seam check

def loop_report(rig, mesh, action, first, cycle):
    """How cleanly a cyclic action closes: the pose at `first + cycle` against `first` (bone
    joints and skinned mesh, in mm), and the seam step (the last sampled frame back to the first)
    against the steps found inside the loop.

    A clean loop has `end_vs_start_*_mm` near zero (the end pose should equal the start pose) and
    `seam_step_mm` in the same range as `inner_step_mm`'s median (the jump across the seam should
    not be bigger than an ordinary step inside the loop). `docs/ANIMATION.md`'s loop-seam check
    also compares pose angle and, separately, foot-contact phase; this function covers the
    positional half.
    """
    play(rig, action)
    frames = [first + i for i in range(int(cycle))]
    pts = []
    for f in frames + [first + cycle]:
        frame_set(f)
        pts.append(mesh_points(mesh))
    frame_set(first)
    b0 = bone_points(rig)
    frame_set(first + cycle)
    b1 = bone_points(rig)
    steps = [float(np.linalg.norm(pts[i + 1] - pts[i], axis=1).max()) for i in range(len(frames) - 1)]
    seam = float(np.linalg.norm(pts[0] - pts[len(frames) - 1], axis=1).max())
    return {"end_vs_start_bones_mm": round(float(np.linalg.norm(b1 - b0, axis=1).max()) * 1000, 1),
            "end_vs_start_mesh_mm": round(float(np.linalg.norm(pts[-1] - pts[0], axis=1).max()) * 1000, 1),
            "seam_step_mm": round(seam * 1000, 1),
            "inner_step_mm": [round(min(steps) * 1000, 1), round(float(np.median(steps)) * 1000, 1),
                              round(max(steps) * 1000, 1)]}


def write_sheet_manifest(out_dir, state, blocks, title, notes, movie=None, per_row=12):
    """Write a small JSON describing a contact sheet for a separate image-composing step to read
    (this module only renders frames; laying them out with labels is left to your own compositor,
    since fonts and layout vary a lot by taste)."""
    return write_json(Path(out_dir) / state / "sheet.json", {"state": state, "title": title, "notes": notes,
                                                              "blocks": blocks, "movie": movie, "per_row": per_row})
