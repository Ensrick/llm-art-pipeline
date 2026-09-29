"""Render facings of one action as raw game-sprite frames: beauty, mask and ground-shadow geometry
(headless Blender 4.4). This is the renderer half of "making sprites look native" - see
docs/SPRITES.md for the reasoning behind every number, and examples/sprite_scene.example.json for
a filled-in config.

For every (frame, facing) it writes, under --out/:
  <key>.png            beauty: Cycles CPU, straight alpha, the config's view transform (Standard/None)
  <key>_raw_m.png      mask pass (Raw view, one flat-emission override material): channels you wire
                       up in the config (by default, red = the team-colour region)
  <key>.shadow.npz     the rendered mesh (minus any excluded objects) sheared onto the ground and
                       projected to pixels - `finish_sprites.py` turns this into the actual shadow
  frames.json          camera, canvas, pivot and per-frame bounds, for the finisher and the packer

Camera and scale are fixed for the whole run (from the config): orthographic, at a fixed elevation,
one canvas, the ground origin on one whole pixel. Facings turn a turntable object by
(front_facing - facing) * (360 / facing_count) degrees; the camera and lights never move.

Run headless, e.g.:
  blender --background -t 2 --factory-startup --python-exit-code 1 --python tools/render_sprites.py -- \
      --config sprite_scene.json --rig my_unit.blend --action Walk_Loop --frames 0 2 4 6 8 10 12 14 --out out/raw/walk
"""

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path

import bpy
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import anim_cookbook as ac  # noqa: E402
import gear_kit as gk  # noqa: E402
import review_render as rr  # noqa: E402


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parse():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", type=Path, required=True, help="a sprite_scene.json (see examples/)")
    p.add_argument("--rig", type=Path, required=True, help="the .blend to open (never saved)")
    p.add_argument("--rig-object", help="the armature to play the action on (default: the file's only armature)")
    p.add_argument("--turntable-objects", nargs="*", default=[],
                   help="extra top-level objects to turn for facings, beyond the rig (default: just the rig)")
    p.add_argument("--meshes", nargs="*", default=[],
                   help="mesh object names to render/measure (default: every mesh under the rig)")
    p.add_argument("--action", required=True, help="the Blender action name to play")
    p.add_argument("--frames", nargs="+", type=int, required=True, help="action frame numbers to render")
    p.add_argument("--facings", nargs="*", type=int, default=list(range(8)), help="facing indices (default: 0-7)")
    p.add_argument("--facing-count", type=int, default=8)
    p.add_argument("--front-facing", type=int, default=3, help="which facing index is the front (default 3)")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--preset", help="lighting preset name (default: the config's lighting.preset)")
    p.add_argument("--samples", type=int, help="override the config's render.samples")
    p.add_argument("--shaft-scale", type=float, help="override the config's readability.shaft_scale")
    p.add_argument("--resume", action="store_true", help="skip frames already rendered with the same fingerprint")
    p.add_argument("--geometry-only", action="store_true", help="pass A only (bounds + shadow); no rendering")
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    args = p.parse_args(argv)
    for k, v in vars(args).items():
        if isinstance(v, Path):
            setattr(args, k, v.resolve())
    return args


# --------------------------------------------------------------------------- scene set-up

def setup_render(cfg, samples):
    scene = bpy.context.scene
    r, c = cfg["render"], scene.cycles
    scene.render.engine = "CYCLES"
    c.device = r.get("device", "CPU")
    c.samples = samples
    c.use_adaptive_sampling = r["adaptive_sampling"]
    c.use_denoising = r["denoise"]
    c.filter_width = r["filter_width"]
    c.seed = r["seed"]
    c.use_animated_seed = False
    scene.render.threads_mode = "FIXED"
    scene.render.threads = r["threads"]
    scene.render.use_persistent_data = r["persistent_data"]
    scene.render.film_transparent = True
    scene.render.use_compositing = False
    scene.render.use_sequencer = False
    scene.render.resolution_percentage = 100
    scene.render.pixel_aspect_x = scene.render.pixel_aspect_y = 1.0
    s = scene.render.image_settings
    s.file_format, s.color_mode, s.color_depth, s.compression = "PNG", "RGBA", "8", 15
    scene.display_settings.display_device = "sRGB"
    set_view(scene, r["view_transform"], r["look"])


def set_view(scene, transform, look="None"):
    vs = scene.view_settings
    vs.view_transform = transform
    vs.look = look
    vs.exposure, vs.gamma = 0.0, 1.0
    vs.use_curve_mapping = False


def setup_lights(cfg, preset_name):
    """The sprite rig's own key and fill (disk area lights) and world; any other lights in the file
    are hidden from this render (they're presumably for viewport/review use, per docs/PROCESS.md)."""
    scene = bpy.context.scene
    for o in bpy.data.objects:
        if o.type == "LIGHT" and not o.name.startswith("Sprite_"):
            o.hide_render = True
    lcfg = cfg["lighting"]
    preset = lcfg["presets"][preset_name]
    target = Vector(lcfg["target_m"])
    made = {}
    for role in ("key", "fill"):
        spec = preset[role]
        name = f"Sprite_{role.capitalize()}"
        obj = bpy.data.objects.get(name)
        if obj is None:
            obj = bpy.data.objects.new(name, bpy.data.lights.new(name, "AREA"))
            scene.collection.objects.link(obj)
        light = obj.data
        light.shape, light.size = "DISK", spec["size_m"]
        light.energy = spec["energy_w"]
        light.color = (1.0, 1.0, 1.0)
        obj.location = target + Vector(spec["offset_m"])
        if spec.get("aim", True):
            obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()
        else:
            obj.rotation_euler = spec["rotation_euler"]
        obj.hide_render = False
        made[role] = {"location_m": [round(v, 4) for v in obj.location], "energy_w": light.energy,
                      "size_m": light.size, "aimed_at_target": spec.get("aim", True)}
    world = bpy.data.worlds.get("Sprite_World") or bpy.data.worlds.new("Sprite_World")
    world.use_nodes = True
    bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
    bg.inputs["Color"].default_value = (*preset["world"]["color"], 1.0)
    bg.inputs["Strength"].default_value = preset["world"]["strength"]
    scene.world = world
    made["world"] = preset["world"]
    made["preset"] = preset_name
    return made


class Camera:
    """Orthographic sprite camera at a fixed elevation, fixed scale, the ground origin on a whole
    pixel. Config-driven only - see examples/sprite_scene.example.json's "camera"/"canvas" keys."""

    def __init__(self, cfg):
        scene = bpy.context.scene
        cc, canvas = cfg["camera"], cfg["canvas"]
        self.W, self.H = canvas["width"], canvas["height"]
        self.px, self.py = canvas["pivot_px"]
        self.ppm = cfg["px_per_m"]
        e = math.radians(cc["elevation_deg"])
        self.d = Vector((0.0, math.cos(e), -math.sin(e)))          # view direction (looking from -Y)
        self.up = Vector((0.0, math.sin(e), math.cos(e)))
        self.right = Vector((1.0, 0.0, 0.0))
        self.ground = Vector((0.0, 0.0, cfg["ground_z"]))
        self.loc = (self.ground - self.right * ((self.px - self.W / 2) / self.ppm)
                    - self.up * ((self.py - self.H / 2) / self.ppm) - self.d * cc["distance_m"])
        cam = bpy.data.objects.get("Sprite_Camera")
        if cam is None:
            cam = bpy.data.objects.new("Sprite_Camera", bpy.data.cameras.new("Sprite_Camera"))
            scene.collection.objects.link(cam)
        cam.data.type = "ORTHO"
        cam.data.sensor_fit = "AUTO"
        cam.data.ortho_scale = max(self.W, self.H) / self.ppm
        cam.data.shift_x = cam.data.shift_y = 0.0
        cam.data.clip_start, cam.data.clip_end = 0.1, 2.0 * cc["distance_m"]
        cam.location = self.loc
        cam.rotation_euler = self.d.to_track_quat("-Z", "Y").to_euler()
        scene.camera = cam
        scene.render.resolution_x, scene.render.resolution_y = self.W, self.H
        bpy.context.view_layer.update()
        self.cam = cam
        m = cam.matrix_world.to_3x3()
        assert (m.col[0] - self.right).length < 1e-6 and (m.col[1] - self.up).length < 1e-6, "camera axes"
        x, y, _z = world_to_camera_view(scene, cam, self.ground)
        self.pivot_check = [x * self.W, y * self.H]
        assert abs(self.pivot_check[0] - self.px) < 1e-3 and abs(self.pivot_check[1] - self.py) < 1e-3, \
            ("pivot does not land on its pixel", self.pivot_check)
        self.R, self.U, self.D, self.C = np.array(self.right), np.array(self.up), np.array(self.d), np.array(self.loc)

    def to_px(self, pts):
        """World points (N, 3) -> pixel coords (N, 2), x from the left, y from the TOP (image rows)."""
        rel = pts - self.C
        x = self.W / 2 + (rel @ self.R) * self.ppm
        y = self.H - (self.H / 2 + (rel @ self.U) * self.ppm)
        return np.stack([x, y], axis=1)

    def info(self):
        return {"type": "ORTHO", "px_per_m": self.ppm, "ortho_scale_m": round(self.cam.data.ortho_scale, 9),
                "canvas": [self.W, self.H], "pivot_px_bottom_left": [self.px, self.py],
                "pivot_px_top_left": [self.px, self.H - self.py],
                "pivot_projected_check": [round(v, 6) for v in self.pivot_check],
                "location_m": [round(v, 6) for v in self.loc], "view_dir": [round(v, 6) for v in self.d],
                "ground_point_m": list(self.ground)}


# --------------------------------------------------------------------------- team region and mask pass

def _linear(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def image_mean_luminance(img):
    px = np.empty(img.size[0] * img.size[1] * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    rgb = px.reshape(-1, 4)[:, :3].astype(np.float64)
    if not img.is_float and img.colorspace_settings.name == "sRGB":
        rgb = _linear(rgb)
    return float((rgb @ np.array([0.2126, 0.7152, 0.0722])).mean())


def select_region_faces(obj, reg):
    """Intersect optional material, skin-group and polygon-size selectors on a render-copy mesh."""
    mesh = obj.data
    sel = np.ones(len(mesh.polygons), dtype=bool)
    assert any(k in reg for k in ("material", "vertex_group", "polygon_vertex_count")), reg
    if "material" in reg:
        idx = [i for i, m in enumerate(mesh.materials) if m and m.name == reg["material"]]
        assert idx, f"{obj.name} has no material {reg['material']}"
        mats = np.zeros(len(mesh.polygons), dtype=np.int32)
        mesh.polygons.foreach_get("material_index", mats)
        sel &= np.isin(mats, idx)
    if "vertex_group" in reg:
        g = obj.vertex_groups[reg["vertex_group"]].index
        w = np.zeros(len(mesh.vertices))
        for v in mesh.vertices:
            for e in v.groups:
                if e.group == g:
                    w[v.index] = e.weight
        sel &= np.array([all(w[i] >= reg.get("min_weight", 0.5) for i in p.vertices) for p in mesh.polygons])
    if "polygon_vertex_count" in reg:
        sel &= np.array([len(p.vertices) == reg["polygon_vertex_count"] for p in mesh.polygons])
    return sel


def mark_team_region(tcfg):
    """Face attribute sprite_team = 1 on the configured team faces; returns ({material: face count}
    touched, a report list) so the caller can neutralize those materials and record what happened."""
    touched, report = {}, []
    for reg in tcfg.get("regions", []):
        obj = bpy.data.objects[reg["object"]]
        mesh = obj.data
        attr = mesh.attributes.get("sprite_team") or mesh.attributes.new("sprite_team", "FLOAT", "FACE")
        vals = np.zeros(len(mesh.polygons), dtype=np.float32)
        attr.data.foreach_get("value", vals)
        sel = select_region_faces(obj, reg)
        assert sel.any(), f"empty team-colour region: {reg}"
        vals[sel] = 1.0
        attr.data.foreach_set("value", vals)
        mesh.update()
        for p in np.nonzero(sel)[0]:
            mat = obj.material_slots[mesh.polygons[int(p)].material_index].material
            touched[mat.name] = touched.get(mat.name, 0) + 1
        report.append({**reg, "faces": int(sel.sum()), "of": len(mesh.polygons)})
    return touched, report


def remap_render_materials(specs):
    """Reassign selected faces to a different, already-present material slot, in the unsaved render
    copy only - for a render-only look tweak that shouldn't touch the approved file."""
    report = []
    for reg in specs:
        obj = bpy.data.objects[reg["object"]]
        mesh = obj.data
        target = mesh.materials.find(reg["to_material"])
        assert target >= 0, f"{obj.name} has no target material {reg['to_material']}"
        selected = select_region_faces(obj, reg)
        assert selected.any(), f"empty render material override: {reg}"
        for index in np.nonzero(selected)[0]:
            mesh.polygons[int(index)].material_index = target
        mesh.update()
        report.append({**reg, "faces": int(selected.sum()), "of": len(mesh.polygons)})
    return report


def neutralize_team(material, albedo):
    """Beauty pass: on faces with sprite_team = 1, the base colour becomes a bright neutral grey
    that keeps the texture's own light/dark variation. Needed because a multiply-based team-colour
    shader darkens whatever colour it's given - rendering the "real" colour here would double it up
    with the tint the engine applies at runtime."""
    nt = material.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    sock = bsdf.inputs["Base Color"]
    if sock.is_linked:
        src = sock.links[0].from_socket
        node = sock.links[0].from_node
        ref = image_mean_luminance(node.image) if node.type == "TEX_IMAGE" and node.image else None
    else:
        rgb = nt.nodes.new("ShaderNodeRGB")
        rgb.outputs[0].default_value = sock.default_value
        src, ref = rgb.outputs[0], None
    if ref is None:
        c = np.array(sock.default_value[:3])
        ref = float(c @ np.array([0.2126, 0.7152, 0.0722]))
    attr = nt.nodes.new("ShaderNodeAttribute")
    attr.attribute_type, attr.attribute_name = "GEOMETRY", "sprite_team"
    bw = nt.nodes.new("ShaderNodeRGBToBW")
    nt.links.new(src, bw.inputs["Color"])
    mul = nt.nodes.new("ShaderNodeMath")
    mul.operation, mul.use_clamp = "MULTIPLY", True
    mul.inputs[1].default_value = albedo / max(ref, 1e-6)
    nt.links.new(bw.outputs[0], mul.inputs[0])
    grey = nt.nodes.new("ShaderNodeCombineColor")
    for ch in ("Red", "Green", "Blue"):
        nt.links.new(mul.outputs[0], grey.inputs[ch])
    mix = nt.nodes.new("ShaderNodeMixRGB")
    mix.blend_type = "MIX"
    nt.links.new(attr.outputs["Fac"], mix.inputs["Fac"])
    nt.links.new(src, mix.inputs["Color1"])
    nt.links.new(grey.outputs["Color"], mix.inputs["Color2"])
    nt.links.new(mix.outputs["Color"], sock)
    return {"material": material.name, "texture_mean_linear_luminance": round(ref, 5),
            "gain": round(albedo / max(ref, 1e-6), 4), "neutral_albedo": albedo}


def mask_material(channels=(("Red", "sprite_team", "GEOMETRY"),)):
    """One flat-emission override material for the mask pass, rendered under the config's Raw view
    transform so the engine gets clean, unprocessed channel data. `channels` is a list of
    `(output_channel, attribute_name, attribute_type)`: `"GEOMETRY"` reads a per-face attribute
    (as `mark_team_region` writes), `"OBJECT"` reads a custom property set directly on an object
    (`obj["some_name"] = 1.0`). Unlisted channels of Red/Green/Blue read as 0."""
    mat = bpy.data.materials.get("Sprite_Mask_Override") or bpy.data.materials.new("Sprite_Mask_Override")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    comb = nt.nodes.new("ShaderNodeCombineColor")
    for channel, attr_name, attr_type in channels:
        node = nt.nodes.new("ShaderNodeAttribute")
        node.attribute_type, node.attribute_name = attr_type, attr_name
        nt.links.new(node.outputs["Fac"], comb.inputs[channel])
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Strength"].default_value = 1.0
    nt.links.new(comb.outputs["Color"], em.inputs["Color"])
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    return mat


# --------------------------------------------------------------------------- shaft readability (render copy)

class Shafts:
    """Render-copy thickening of thin rigid parts (docs/ANIMATION.md 5.9, "thin parts at small
    scale"): the faces of one material are scaled about the object's local Z axis, by `factor` from
    the ORIGINAL coordinates (so it can be re-applied at another factor later in the same session).
    Other materials on the same object must not share vertices with the scaled one. The source file
    this was opened from is never saved."""

    def __init__(self, ppm):
        self.ppm, self.orig, self.report = ppm, {}, {}

    def apply(self, obj, material, factor):
        me = obj.data
        mi = me.materials.find(material)
        assert mi >= 0, f"{obj.name} has no material {material}"
        mats = np.zeros(len(me.polygons), dtype=np.int32)
        me.polygons.foreach_get("material_index", mats)
        shaft = {v for p in me.polygons if p.material_index == mi for v in p.vertices}
        other = {v for p in me.polygons if p.material_index != mi for v in p.vertices}
        assert shaft and not shaft & other, f"{obj.name}: shaft vertices shared with other materials"
        if obj.name not in self.orig:
            co = np.empty(len(me.vertices) * 3)
            me.vertices.foreach_get("co", co)
            self.orig[obj.name] = co.reshape(-1, 3)
        co = self.orig[obj.name].copy()
        idx = np.array(sorted(shaft))
        r0 = np.hypot(co[idx, 0], co[idx, 1])
        co[idx, :2] *= factor
        me.vertices.foreach_set("co", co.ravel())
        me.update()
        self.report[obj.name] = {
            "material": material, "factor": factor,
            "radius_m_before": [round(float(r0.min()), 4), round(float(r0.max()), 4)],
            "radius_m_after": [round(float(r0.min() * factor), 4), round(float(r0.max() * factor), 4)],
            "width_px_before": [round(float(2 * r0.min() * self.ppm), 2), round(float(2 * r0.max() * self.ppm), 2)],
            "width_px_after": [round(float(2 * r0.min() * factor * self.ppm), 2),
                               round(float(2 * r0.max() * factor * self.ppm), 2)]}
        return self.report[obj.name]


# --------------------------------------------------------------------------- per-frame geometry and shadow

class Geometry:
    """World-space bounds and the sheared ground shadow for every rendered frame."""

    def __init__(self, cfg, meshes, cam):
        self.meshes, self.cam = meshes, cam
        self.excl = set(cfg["shadow"].get("exclude_objects", []))
        self.shear = cfg["shadow"]["shear"]
        self.ground_z = cfg["ground_z"]
        self.topology = None

    def visible(self):
        objs = [o for o in self.meshes if not o.hide_render]
        shadow = [o for o in objs if not any(o.name == e or o.name.startswith(e + ".") for e in self.excl)]
        return objs, shadow

    def frame(self, key, out_dir):
        objs, shadow_objs = self.visible()
        cam = self.cam
        ev = {o.name: gk.world_mesh(o) for o in objs}
        allpts = np.vstack([w for w, _t in ev.values()])
        body_px = cam.to_px(allpts)
        pts, tris, off = [], [], 0
        for o in shadow_objs:
            w, t = ev[o.name]
            z = np.maximum(0.0, w[:, 2] - self.ground_z)
            g = np.stack([w[:, 0] + self.shear[0] * z, w[:, 1] + self.shear[1] * z,
                          np.full(len(w), self.ground_z)], axis=1)
            pts.append(cam.to_px(g))
            tris.append(t + off)
            off += len(w)
        pts, tris = np.vstack(pts), np.vstack(tris)
        # cache the triangle topology to disk once per distinct mesh set, not once per frame
        if self.topology is None or len(self.topology) != len(tris) or not np.array_equal(self.topology, tris):
            self.topology = tris
            self.topology_file = out_dir / f"{key}.topology.npy"
            np.save(self.topology_file, tris)
        q = np.round(pts * 32.0).astype(np.int32)         # 1/32 px fixed point, ample for a sprite canvas
        assert np.abs(q).max() < 2 ** 31 - 1
        np.savez_compressed(out_dir / f"{key}.shadow.npz", pts32=q, topology=np.array(self.topology_file.name))
        both = np.vstack([body_px, pts])
        return {"bounds_px": [round(float(both[:, 0].min()), 2), round(float(both[:, 1].min()), 2),
                              round(float(both[:, 0].max()), 2), round(float(both[:, 1].max()), 2)],
                "body_bounds_px": [round(float(body_px[:, 0].min()), 2), round(float(body_px[:, 1].min()), 2),
                                   round(float(body_px[:, 0].max()), 2), round(float(body_px[:, 1].max()), 2)],
                "shadow_vertices": int(len(pts)), "shadow_triangles": int(len(tris)),
                "shadow_objects": len(shadow_objs), "rendered_objects": len(objs)}


def fingerprint(cfg, preset, samples, action, frames, facings, shaft_scale):
    body = json.dumps({"render": cfg["render"], "camera": cfg["camera"], "canvas": cfg["canvas"],
                       "px_per_m": cfg["px_per_m"], "ground_z": cfg["ground_z"], "shadow": cfg["shadow"],
                       "team": cfg.get("team_colour", {}),
                       "lighting": cfg["lighting"]["presets"][preset], "preset": preset, "samples": samples,
                       "action": action, "frames": frames, "facings": facings, "shaft_scale": shaft_scale},
                      sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()


def render_to(path):
    scene = bpy.context.scene
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    assert Path(path).is_file(), path


def main():
    args = parse()
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    samples = args.samples or cfg["render"]["samples"]

    bpy.ops.wm.open_mainfile(filepath=str(args.rig))
    rig = (bpy.data.objects[args.rig_object] if args.rig_object
           else next(o for o in bpy.data.objects if o.type == "ARMATURE"))
    meshes = ([bpy.data.objects[n] for n in args.meshes] if args.meshes else rr.meshes_under(rig))
    assert meshes, "no mesh objects found under the rig - pass --meshes explicitly"
    turntable = rr.review_turntable([rig] + [bpy.data.objects[n] for n in args.turntable_objects])

    setup_render(cfg, samples)
    cam = Camera(cfg)
    team_touched, team_regions = mark_team_region(cfg.get("team_colour", {}))
    material_overrides = remap_render_materials(cfg.get("render_material_overrides", []))
    tcfg = cfg.get("team_colour", {})
    albedo_by_material = tcfg.get("neutral_albedo_by_material", {})
    neutral = [neutralize_team(bpy.data.materials[m], albedo_by_material.get(m, tcfg.get("neutral_albedo", 0.7)))
               for m in team_touched]
    mask_channels = [("Red", "sprite_team", "GEOMETRY")] if team_touched else []
    for extra in cfg.get("mask", {}).get("extra_channels", []):
        for name in extra["objects"]:
            bpy.data.objects[name][extra["property"]] = 1.0
        mask_channels.append((extra["channel"], extra["property"], "OBJECT"))
    mask_mat = mask_material(mask_channels) if mask_channels else mask_material([])

    read = cfg.get("readability", {})
    shafts = Shafts(cfg["px_per_m"])
    scale = args.shaft_scale if args.shaft_scale is not None else read.get("shaft_scale", 1.0)
    for spec in read.get("shafts", []):
        if spec["object"] in bpy.data.objects:
            shafts.apply(bpy.data.objects[spec["object"]], spec["material"], scale)

    geo = Geometry(cfg, meshes, cam)
    preset = args.preset or cfg["lighting"]["preset"]
    light_info = setup_lights(cfg, preset)

    records = []
    for frame in args.frames:
        for facing in args.facings:
            records.append({"key": f"{args.action}_f{frame:03d}_t{facing}", "action": args.action,
                            "frame": frame, "facing": facing,
                            "turntable_deg": round(math.degrees(rr.facing_turn(facing, args.facing_count)), 3)})

    fp = fingerprint(cfg, preset, samples, args.action, args.frames, args.facings, scale)
    args.out.mkdir(parents=True, exist_ok=True)
    man_path = args.out / "frames.json"
    old = {}
    if args.resume and man_path.exists():
        prev = json.loads(man_path.read_text(encoding="utf-8"))
        if prev.get("fingerprint") == fp:
            old = {f["key"]: f for f in prev["frames"]}

    def pose(rec):
        turntable.rotation_euler.z = math.radians(
            (args.front_facing - rec["facing"]) * (360 / args.facing_count))
        ac.play(rig, bpy.data.actions[rec["action"]])
        rr.frame_set(rec["frame"])
        bpy.context.view_layer.update()

    # pass A: geometry, bounds, shadow; refuse before rendering if anything reaches the canvas edge
    t0 = time.time()
    clipped = []
    margin = cfg["canvas"]["margin_px"]
    for rec in records:
        pose(rec)
        rec.update(geo.frame(rec["key"], args.out))
        x0, y0, x1, y1 = rec["bounds_px"]
        if x0 < margin or y0 < margin or x1 > cam.W - margin or y1 > cam.H - margin:
            clipped.append((rec["key"], rec["bounds_px"]))
    print(f"## geometry {len(records)} frames {time.time() - t0:.1f}s")
    for k, b in clipped:
        print("## CLIPS", k, b)
    if args.geometry_only:
        (args.out / "geometry.json").write_text(json.dumps(records, indent=1), encoding="utf-8")
        return
    if clipped:
        raise SystemExit(f"{len(clipped)} frames reach the {cam.W}x{cam.H} canvas edge: enlarge the canvas "
                         "in the config (never shrink the model - docs/SPRITES.md)")

    # pass B: beauty; pass C: mask (one override material, Raw view)
    vl = bpy.context.view_layer
    for pass_name in ("beauty", "mask"):
        scene = bpy.context.scene
        if pass_name == "beauty":
            vl.material_override = None
            set_view(scene, cfg["render"]["view_transform"], cfg["render"]["look"])
        else:
            vl.material_override = mask_mat
            set_view(scene, cfg["render"]["mask_view_transform"])
        t0 = time.time()
        for i, rec in enumerate(records):
            name = f"{rec['key']}.png" if pass_name == "beauty" else f"{rec['key']}_raw_m.png"
            path = args.out / name
            if old.get(rec["key"]) and path.is_file():
                continue
            pose(rec)
            t1 = time.time()
            render_to(path)
            rec[f"{pass_name}_seconds"] = round(time.time() - t1, 2)
            print(f"## {pass_name} {i + 1}/{len(records)} {rec['key']} {rec.get(f'{pass_name}_seconds', 0)}s", flush=True)
        print(f"## {pass_name} pass {len(records)} frames {time.time() - t0:.1f}s", flush=True)
    vl.material_override = None
    set_view(bpy.context.scene, cfg["render"]["view_transform"], cfg["render"]["look"])

    for rec in records:
        rec["image"], rec["raw_mask"], rec["shadow"] = (f"{rec['key']}.png", f"{rec['key']}_raw_m.png",
                                                        f"{rec['key']}.shadow.npz")
    manifest = {"schema": "sprite_frames_raw/1", "rig": str(args.rig), "rig_sha256": sha256(args.rig),
                "action": args.action, "camera": cam.info(), "render": dict(cfg["render"], samples=samples),
                "shadow": cfg["shadow"], "team_colour": {"regions": team_regions, "neutral": neutral},
                "render_material_overrides": material_overrides, "lighting": light_info, "fingerprint": fp,
                "readability": {"shaft_scale": scale, "shafts": shafts.report},
                "atlas_pixels_per_unit": cfg.get("atlas", {}).get("pixels_per_unit"),
                "blender": bpy.app.version_string, "frames": records}
    man_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print("## manifest", man_path, len(records))


if __name__ == "__main__":
    main()
