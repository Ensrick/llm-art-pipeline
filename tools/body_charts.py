"""Labelled body-part charts for the shared humanoid (Blender 4.4, headless).

Renders the character from named views and overlays every anatomy role (anatomy_map.json),
every named joint, and every socket / landmark / prop socket from attachment manifests
(attachment_sockets.py's attachment_frames.json schema). The character's RIGHT side is orange, LEFT is blue,
centre is grey; sockets are yellow with X/Y/Z axis ticks (red/green/blue).

Labels are drawn by Blender itself (text objects in a separate overlay scene rendered with
Workbench, then alpha-composited in numpy), so the charts need no Pillow and no GPU module.
Nothing is saved to the input .blend.

    import body_charts
    body_charts.render_all(out_dir, anatomy, manifests)          # full body + hand close-ups
"""

import json
import math
from pathlib import Path

import bpy
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Matrix, Quaternion, Vector

RIG_NAME = "Shared_Humanoid_CC0_Rig"
SIDE_COLOR = {"right": (1.0, 0.45, 0.10), "left": (0.25, 0.60, 1.00), "center": (0.80, 0.80, 0.80)}
SOCKET_COLOR = (1.0, 0.86, 0.10)
LANDMARK_COLOR = (1.0, 0.35, 0.35)
PROP_SOCKET_COLOR = (0.30, 1.0, 0.80)
AXIS_COLOR = {0: (1.0, 0.2, 0.2), 1: (0.2, 1.0, 0.2), 2: (0.3, 0.5, 1.0)}
BOX_COLOR = (0.06, 0.06, 0.07)
FONT_SIZE = 15.0
LINE_GAP = 23.0
BODY_MESHES = ("Male_Peasant_Arms", "Male_Peasant_Body", "Male_Peasant_Legs", "Male_Peasant_Feet",
               "CC0_Head_Only", "Padded_Sleeve_L", "Padded_Sleeve_R",
               "Quilted_Cuirass", "Fitted_Helmet", "Left_Forearm_Shield")

# name: (camera look direction, image height px)
VIEWS = {
    "front": ((0.0, 1.0, 0.0), 1000),
    "back": ((0.0, -1.0, 0.0), 1000),
    "right_side": ((1.0, 0.0, 0.0), 1000),
    "left_side": ((-1.0, 0.0, 0.0), 1000),
    "three_quarter": ((2.7, 5.0, -0.85), 1000),
    "game_camera_30deg": ((0.0, math.cos(math.radians(30)), -math.sin(math.radians(30))), 1000),
}


def _local_matrix(entry):
    return Matrix.Translation(Vector(entry["translation_m"])) @ Quaternion(entry["rotation_wxyz"]).normalized().to_matrix().to_4x4()


def collect_labels(rig, anatomy, manifests, finger_mode="exclude"):
    """Label records: text, colour, kind, world anchor, optional world frame for axis ticks.

    finger_mode: "exclude" (full-body charts), or "r"/"l" (only that hand's fingers + hand).
    """
    rw = rig.matrix_world
    labels = []
    fingers = {r for r, it in anatomy["roles"].items() if it["group"] == "Fingers (protected)"}
    for role, item in anatomy["roles"].items():
        side = item["side"]
        if finger_mode == "exclude" and role in fingers:
            continue
        if finger_mode in ("r", "l"):
            want_side = "right" if finger_mode == "r" else "left"
            if side != want_side or not (role in fingers or role.endswith("_hand") or role.endswith("forearm")):
                continue
        pb = rig.pose.bones[item["bone"]]
        anchor = rw @ ((pb.head + pb.tail) * 0.5)
        labels.append(dict(text=f"{role}  ({item['bone']})", color=SIDE_COLOR[side], kind="role", anchor=anchor))
    for joint, item in anatomy["joints"].items():
        role = anatomy["roles"][item["bone_role"]]
        if finger_mode in ("r", "l") and not joint.endswith("wrist"):
            continue
        if finger_mode in ("r", "l") and role["side"] != ("right" if finger_mode == "r" else "left"):
            continue
        pb = rig.pose.bones[role["bone"]]
        anchor = rw @ getattr(pb, item["endpoint"])
        labels.append(dict(text=f"{joint}  (joint)", color=SIDE_COLOR[role["side"]], kind="joint", anchor=anchor))
    for mname, manifest in manifests.items():
        for name, entry in manifest.get("body_sockets", {}).items():
            role = anatomy["roles"][entry["bone_role"]]
            if finger_mode in ("r", "l") and role["side"] != ("right" if finger_mode == "r" else "left"):
                continue
            world = rw @ rig.pose.bones[role["bone"]].matrix @ _local_matrix(entry)
            labels.append(dict(text=f"SOCKET {name}", color=SOCKET_COLOR, kind="socket",
                               anchor=world.translation.copy(), frame=world))
        for name, entry in manifest.get("body_landmarks", {}).items():
            role = anatomy["roles"][entry["bone_role"]]
            if finger_mode in ("r", "l") and role["side"] != ("right" if finger_mode == "r" else "left"):
                continue
            anchor = rw @ rig.pose.bones[role["bone"]].matrix @ Vector(entry["point_bone_local_m"])
            labels.append(dict(text=f"LANDMARK {name}", color=LANDMARK_COLOR, kind="landmark", anchor=anchor))
        for name, entry in manifest.get("prop_sockets", {}).items():
            obj = bpy.data.objects.get(entry["object"])
            if obj is None or obj.hide_render:
                continue
            world = obj.matrix_world @ _local_matrix(entry)
            if finger_mode in ("r", "l"):
                hand = rig.pose.bones["hand_" + finger_mode]
                if (world.translation - rw @ hand.head).length > 0.25:
                    continue
            labels.append(dict(text=f"PROP SOCKET {name}", color=PROP_SOCKET_COLOR, kind="prop_socket",
                               anchor=world.translation.copy(), frame=world))
    return labels


def _camera(name, direction):
    cam = bpy.data.objects.get(name)
    if cam is None:
        cam = bpy.data.objects.new(name, bpy.data.cameras.new(name))
        bpy.context.scene.collection.objects.link(cam)
    cam.data.type = "ORTHO"
    cam.data.sensor_fit = "VERTICAL"
    cam.data.clip_start, cam.data.clip_end = 0.01, 200.0
    cam.rotation_euler = Vector(direction).normalized().to_track_quat("-Z", "Y").to_euler()
    return cam


def _fit(cam, points, height_px, label_room_px=360, top_px=112, bottom_px=14):
    """Place an ortho camera so `points` fill the image height below the title block, with room
    for a label column on each side."""
    rot = cam.rotation_euler.to_matrix()
    right, up, back = rot.col[0], rot.col[1], rot.col[2]
    s = [p.dot(right) for p in points]
    t = [p.dot(up) for p in points]
    s0, s1, t0, t1 = min(s), max(s), min(t), max(t)
    ppm = (height_px - top_px - bottom_px) / (t1 - t0)
    cam.data.ortho_scale = height_px / ppm
    width = int(round((s1 - s0) * ppm + 2 * label_room_px))
    width += width % 2
    t_center = (t0 + t1) / 2 + (top_px - bottom_px) / 2 / ppm
    center = right * ((s0 + s1) / 2) + up * t_center
    cam.location = center + back * 50.0
    return width, ppm


def _to_px(scene, cam, point, width, height):
    co = world_to_camera_view(scene, cam, point)
    return co.x * width, (1.0 - co.y) * height


def _layout_column(items, height, top=130, bottom=20):
    """items: list of dicts with 'py'; assigns 'ly' with LINE_GAP spacing near their anchors."""
    items.sort(key=lambda it: it["py"])
    prev = top - LINE_GAP
    for it in items:
        it["ly"] = max(it["py"], prev + LINE_GAP)
        prev = it["ly"]
    limit = height - bottom
    for it in reversed(items):
        if it["ly"] > limit:
            it["ly"] = limit
        limit = it["ly"] - LINE_GAP
    prev = top - LINE_GAP
    for it in items:            # final forward pass keeps spacing if the top was crowded
        it["ly"] = max(it["ly"], prev + LINE_GAP)
        prev = it["ly"]


def _quad(name, a, b, width, color, z, coll):
    a, b = Vector((a[0], a[1], 0)), Vector((b[0], b[1], 0))
    d = b - a
    if d.length < 1e-6:
        d = Vector((1, 0, 0))
    n = Vector((-d.y, d.x, 0)).normalized() * (width / 2)
    verts = [a + n, b + n, b - n, a - n]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(v.x, v.y, z) for v in verts], [], [(0, 1, 2, 3)])
    obj = bpy.data.objects.new(name, mesh)
    obj.color = (*color, 1.0)
    coll.objects.link(obj)
    return obj


def _disc(name, center, radius, color, z, coll, hole=0.0, segments=20):
    cx, cy = center
    outer = [(cx + radius * math.cos(2 * math.pi * k / segments), cy + radius * math.sin(2 * math.pi * k / segments), z)
             for k in range(segments)]
    if hole > 0:
        inner = [(cx + hole * math.cos(2 * math.pi * k / segments), cy + hole * math.sin(2 * math.pi * k / segments), z)
                 for k in range(segments)]
        faces = [(k, (k + 1) % segments, segments + (k + 1) % segments, segments + k) for k in range(segments)]
        verts = outer + inner
    else:
        verts, faces = outer, [tuple(range(segments))]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    obj = bpy.data.objects.new(name, mesh)
    obj.color = (*color, 1.0)
    coll.objects.link(obj)
    return obj


def _text(name, body, color, coll, size=FONT_SIZE, align="LEFT"):
    curve = bpy.data.curves.new(name, "FONT")
    curve.body = body
    curve.size = size
    curve.align_x = align
    curve.align_y = "CENTER"
    obj = bpy.data.objects.new(name, curve)
    obj.color = (*color, 1.0)
    coll.objects.link(obj)
    return obj


def _text_widths(scene, objs):
    """Evaluated widths of text objects living in a non-active scene (fallback: estimate)."""
    depsgraph = scene.view_layers[0].depsgraph
    depsgraph.update()
    out = []
    for obj in objs:
        w = obj.evaluated_get(depsgraph).dimensions.x
        out.append(w if w > 1e-3 else 0.58 * obj.data.size * len(obj.data.body))
    return out


def _overlay_scene(width, height):
    scene = bpy.data.scenes.get("ChartOverlay") or bpy.data.scenes.new("ChartOverlay")
    for obj in list(scene.collection.all_objects):
        data = obj.data
        bpy.data.objects.remove(obj)
        if data is not None and data.users == 0:
            for store in (bpy.data.meshes, bpy.data.curves, bpy.data.cameras):
                if data.name in store and store[data.name] == data:
                    store.remove(data)
                    break
    cam = bpy.data.objects.new("ChartOverlayCam", bpy.data.cameras.new("ChartOverlayCam"))
    scene.collection.objects.link(cam)
    cam.data.type = "ORTHO"
    cam.data.sensor_fit = "VERTICAL"
    cam.data.ortho_scale = height
    cam.location = (0, 0, 50)
    scene.camera = cam
    r = scene.render
    r.engine = "BLENDER_WORKBENCH"
    r.resolution_x, r.resolution_y, r.resolution_percentage = width, height, 100
    r.film_transparent = True
    r.image_settings.file_format, r.image_settings.color_mode = "PNG", "RGBA"
    scene.display.render_aa = "16"
    sh = scene.display.shading
    sh.light = "FLAT"
    sh.color_type = "OBJECT"
    sh.show_shadows = sh.show_cavity = sh.show_object_outline = sh.show_specular_highlight = False
    scene.view_settings.view_transform = "Standard"
    return scene


def _read_rgba(path):
    img = bpy.data.images.load(str(path), check_existing=False)
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    return px.reshape(h, w, 4)


def _write_rgba(arr, path):
    h, w = arr.shape[:2]
    img = bpy.data.images.new("chart_out", w, h, alpha=True)
    img.pixels.foreach_set(arr.astype(np.float32).ravel())
    img.filepath_raw, img.file_format = str(path), "PNG"
    img.save()
    bpy.data.images.remove(img)


def render_chart(out_path, view, direction, labels, fit_points, height=1000, title="", notes=(),
                 character_scene=None, samples=24):
    """Render one labelled chart; returns a dict of anchors in pixels for tests."""
    scene = character_scene or bpy.context.scene
    cam = _camera("ChartCam_" + view, direction)
    width, ppm = _fit(cam, fit_points, height)
    scene.camera = cam
    r = scene.render
    r.resolution_x, r.resolution_y, r.resolution_percentage = width, height, 100
    r.film_transparent = False
    r.image_settings.file_format, r.image_settings.color_mode = "PNG", "RGBA"
    if r.engine == "BLENDER_EEVEE_NEXT":
        scene.eevee.taa_render_samples = samples
    base_path = Path(out_path).with_suffix(".base.png")
    r.filepath = str(base_path)
    bpy.ops.render.render(write_still=True, scene=scene.name)
    # label layout in pixels (x right, y down)
    for lab in labels:
        lab["px"], lab["py"] = _to_px(scene, cam, lab["anchor"], width, height)
    xs = [_to_px(scene, cam, p, width, height)[0] for p in fit_points]
    body_left, body_right = min(xs), max(xs)
    mid = 0.5 * (body_left + body_right)
    left = [l for l in labels if l["px"] < mid]
    right = [l for l in labels if l["px"] >= mid]
    _layout_column(left, height)
    _layout_column(right, height)
    ov = _overlay_scene(width, height)
    coll = ov.collection

    def P(x, y):                  # pixel -> overlay units
        return (x - width / 2, height / 2 - y)

    for i, lab in enumerate(labels):
        on_left = any(lab is l for l in left)
        lx = body_left - 24 if on_left else body_right + 24
        t = _text(f"t{i}", lab["text"], lab["color"], coll, align="RIGHT" if on_left else "LEFT")
        t.location = (*P(lx, lab["ly"]), 3.0)
        lab["_text"], lab["_lx"], lab["_left"] = t, lx, on_left
    widths = _text_widths(ov, [lab["_text"] for lab in labels])
    for i, lab in enumerate(labels):
        tw = widths[i]
        x0 = lab["_lx"] - tw - 5 if lab["_left"] else lab["_lx"] - 5
        x1 = lab["_lx"] + 5 if lab["_left"] else lab["_lx"] + tw + 5
        y0, y1 = lab["ly"] - LINE_GAP / 2 + 2, lab["ly"] + LINE_GAP / 2 - 2
        box = _quad(f"b{i}", P(x0, (y0 + y1) / 2), P(x1, (y0 + y1) / 2), y1 - y0, BOX_COLOR, 2.0, coll)
        edge = x1 if lab["_left"] else x0
        _quad(f"l{i}", P(lab["px"], lab["py"]), P(edge, lab["ly"]), 1.6, lab["color"], 1.0, coll)
        c = P(lab["px"], lab["py"])
        if lab["kind"] == "joint":
            _disc(f"d{i}", c, 6.5, (0, 0, 0), 4.0, coll)
            _disc(f"e{i}", c, 5.5, lab["color"], 4.1, coll, hole=3.0)
        elif lab["kind"] in ("socket", "prop_socket"):
            _disc(f"d{i}", c, 6.0, (0, 0, 0), 4.0, coll, segments=4)
            _disc(f"e{i}", c, 4.5, lab["color"], 4.1, coll, segments=4)
            fr = lab["frame"]
            for axis in range(3):
                tip = fr.translation + fr.to_3x3().col[axis].normalized() * 0.06
                tx, ty = _to_px(scene, cam, tip, width, height)
                _quad(f"a{i}{axis}", c, P(tx, ty), 2.2, AXIS_COLOR[axis], 3.5, coll)
        else:
            _disc(f"d{i}", c, 5.0, (0, 0, 0), 4.0, coll)
            _disc(f"e{i}", c, 3.8, lab["color"], 4.1, coll)
    lines = [title, *notes]
    titles = []
    for k, line in enumerate(lines):
        t = _text(f"title{k}", line, (1, 1, 1) if k == 0 else (0.85, 0.85, 0.85), coll,
                  size=FONT_SIZE + (2 if k == 0 else -1))
        t.location = (*P(12, 16 + 19 * k), 3.0)
        titles.append(t)
    tw = max(_text_widths(ov, titles))
    _quad("titlebox", P(4, 4 + 19 * len(lines) / 2 + 2), P(20 + tw, 4 + 19 * len(lines) / 2 + 2),
          19 * len(lines) + 6, BOX_COLOR, 2.0, coll)
    ov_path = Path(out_path).with_suffix(".overlay.png")
    ov.render.filepath = str(ov_path)
    bpy.ops.render.render(write_still=True, scene=ov.name)
    base, over = _read_rgba(base_path), _read_rgba(ov_path)
    a = over[..., 3:4]
    out = base.copy()
    out[..., :3] = over[..., :3] * a + base[..., :3] * (1 - a)
    out[..., 3] = 1.0
    _write_rgba(out, out_path)
    base_path.unlink()
    ov_path.unlink()
    return {l["text"]: (round(l["px"], 1), round(l["py"], 1)) for l in labels}, (width, height)


def annotate(base_png, out_png, lines, marks=()):
    """Composite a caption block (and optional marks: [(px, py, colour)]) onto a rendered PNG."""
    base = _read_rgba(base_png)
    height, width = base.shape[:2]
    ov = _overlay_scene(width, height)
    coll = ov.collection

    def P(x, y):
        return (x - width / 2, height / 2 - y)

    texts = []
    for k, line in enumerate(lines):
        t = _text(f"cap{k}", line, (1, 1, 1) if k == 0 else (0.9, 0.9, 0.9), coll, size=FONT_SIZE - (0 if k == 0 else 1))
        t.location = (*P(10, 14 + 18 * k), 3.0)
        texts.append(t)
    tw = max(_text_widths(ov, texts))
    _quad("capbox", P(3, 4 + 18 * len(lines) / 2 + 1), P(18 + tw, 4 + 18 * len(lines) / 2 + 1), 18 * len(lines) + 6,
          BOX_COLOR, 2.0, coll)
    for i, (px, py, color) in enumerate(marks):
        _disc(f"mk{i}", P(px, py), 6.0, (0, 0, 0), 4.0, coll, segments=4)
        _disc(f"mi{i}", P(px, py), 4.5, color, 4.1, coll, segments=4)
    ov_path = Path(out_png).with_suffix(".cap.png")
    ov.render.filepath = str(ov_path)
    bpy.ops.render.render(write_still=True, scene=ov.name)
    over = _read_rgba(ov_path)
    a = over[..., 3:4]
    out = base.copy()
    out[..., :3] = over[..., :3] * a + base[..., :3] * (1 - a)
    out[..., 3] = 1.0
    _write_rgba(out, out_png)
    ov_path.unlink()
    return str(out_png)


def project_px(cam, point, width, height, scene=None):
    return _to_px(scene or bpy.context.scene, cam, point, width, height)


def view_notes(rig, cam_direction):
    """Plain-language orientation notes: where the character's right and forward point on screen."""
    rot = Vector(cam_direction).normalized().to_track_quat("-Z", "Y").to_matrix()
    right_screen, up_screen = rot.col[0], rot.col[1]
    his_right, his_forward = Vector((-1, 0, 0)), Vector((0, -1, 0))

    def where(v):
        x, y = v.dot(right_screen), v.dot(up_screen)
        if abs(x) < 0.2 and abs(y) < 0.2:
            return "towards/away from you"
        return ("image RIGHT" if x > 0 else "image LEFT") if abs(x) >= abs(y) else ("image UP" if y > 0 else "image DOWN")

    d = Vector(cam_direction).normalized()
    fwd, rgt = his_forward.dot(d), his_right.dot(d)
    facing = "he faces YOU" if fwd < -0.7 else "he faces AWAY from you" if fwd > 0.7 else f"he faces {where(his_forward)}"
    if rgt < -0.7:
        side = "His RIGHT side faces YOU (his left is hidden behind)"
    elif rgt > 0.7:
        side = "His LEFT side faces YOU (his right is hidden behind)"
    else:
        side = f"His RIGHT side -> {where(his_right)}"
    return f"{side}; {facing}."


def fit_points_body(names=BODY_MESHES, step=7):
    pts = []
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for n in names:
        obj = bpy.data.objects.get(n)
        if obj is None or obj.hide_render:
            continue
        ev = obj.evaluated_get(depsgraph)
        mesh = ev.to_mesh()
        verts = mesh.vertices
        pts += [ev.matrix_world @ verts[i].co for i in range(0, len(verts), step)]
        ev.to_mesh_clear()
    return pts


def render_all(out_dir, anatomy, manifests, views=VIEWS, hands=True, samples=24):
    """Full-body charts for `views` plus right/left hand close-ups. Returns {png: anchors}."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rig = bpy.data.objects[anatomy["rig"]]
    scene = bpy.context.scene
    legend = ("Colours: orange = his RIGHT (weapon arm), blue = his LEFT (shield arm), grey = centre.",
              "Marks: dot = bone (label at the bone's middle), ring = joint, yellow diamond = body socket, "
              "cyan = prop socket, red = landmark (never a grip).",
              "Socket axis ticks (6 cm): X red, Y green, Z blue. Labels read 'role  (bone)'.")
    results = {}
    body_pts = fit_points_body()
    for view, (direction, height) in views.items():
        labels = collect_labels(rig, anatomy, manifests, "exclude")
        path = out_dir / f"chart_{view}.png"
        results[path.name] = render_chart(
            path, view, direction, labels, body_pts, height,
            title=f"Shared spearman - {view.replace('_', ' ').upper()} view - anatomy roles + joints "
                  f"(anatomy_map.json) + sockets ({', '.join(manifests)})",
            notes=(view_notes(rig, direction), *legend), character_scene=scene, samples=samples)
    if hands:
        rw = rig.matrix_world
        hidden = [o for o in bpy.data.objects if o.type == "MESH" and not o.hide_render and (
            o.parent_type == "BONE" or (o.parent and o.parent.parent_type == "BONE"))]
        for o in hidden:
            o.hide_render = True
        try:
            for side, direction in (("r", (0.35, 1.0, -0.25)), ("l", (-0.35, 1.0, -0.25))):
                labels = collect_labels(rig, anatomy, manifests, side)
                bones = [pb for pb in rig.pose.bones if pb.name.endswith("_" + side)
                         and pb.name.split("_")[0] in ("hand", "thumb", "index", "middle", "ring", "pinky")]
                pts = [rw @ pb.head for pb in bones] + [rw @ pb.tail for pb in bones]
                c = sum(pts, Vector()) / len(pts)
                pts = [c + (p - c) * 1.6 for p in pts]
                path = out_dir / f"chart_hand_{'right' if side == 'r' else 'left'}.png"
                results[path.name] = render_chart(
                    path, "hand_" + side, direction, labels, pts, 1000,
                    title=f"Shared spearman - HIS {'RIGHT' if side == 'r' else 'LEFT'} hand close-up "
                          f"(props hidden) - finger roles, wrist, hand sockets",
                    notes=(view_notes(rig, direction), *legend), character_scene=scene, samples=samples)
        finally:
            for o in hidden:
                o.hide_render = False
    return results
