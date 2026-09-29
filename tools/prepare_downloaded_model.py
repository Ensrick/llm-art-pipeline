"""Prepare one downloaded 3D model for the pipeline: measure it, reorient and scale it to your
convention, record its licence on the result, and save it separately from the source (Blender
4.4, headless). This distils the model-prep step described in `docs/PROCESS.md` and
`docs/GEAR.md` into a config-driven tool instead of one hand-written script per model.

Why this exists: a downloaded prop rarely arrives at the right size, with its origin at the right
point, facing the right way. Fixing that by eye, per model, doesn't repeat and doesn't record
where the model came from. This script instead:

1. Opens the source `.blend` (convert FBX/OBJ/glTF/DAE to `.blend` first, with Blender's own
   importer - a few lines of `bpy.ops.import_scene.<format>(filepath=...)` and a save, since
   which importer applies depends on the file), bakes down modifiers, and joins every mesh under
   the named source object into one.
2. Finds the object's own long axis by PCA, unless you give one, and builds an orthonormal frame
   from it (`gear_kit.frame`) so the result has one clean local origin and axes, whatever mess of
   transforms the download arrived with.
3. Scales it **uniformly** (never per-axis - a non-uniform scale on a rigid prop is a modelling
   bug: see `docs/GEAR.md` on why height-only scale stretched a spear) to a target length along
   that axis.
4. Optionally measures the diameter at a point along the axis (for a grip: see
   `docs/GEAR.md`'s grip checks), by raycasting the surface, so you know before fitting it whether
   a hand-held shaft is close to your target size.
5. Refuses to run without a licence on file, and bakes the source's title, author, licence and URL
   onto the result as custom properties, so provenance travels with the mesh instead of living
   only in a person's memory or a commit message.
6. Writes the result next to a `.json` measurement report, and never overwrites a previous run of
   the same key: an existing output is renamed `<name>.bak.v<n>` first.

The source file is opened read-only in spirit: this script never saves over it, and doesn't stage
it for git either - see `docs/PROCESS.md` section 9 on why downloaded sources don't get committed,
only what's built from them.

Usage:
    & 'C:\\Program Files\\Blender Foundation\\Blender 4.4\\blender.exe' --background \
        --factory-startup --python-exit-code 1 \
        --python tools/prepare_downloaded_model.py -- my_model.json

See `examples/prepare_downloaded_model.example.json` for the config shape.
"""

import json
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gear_kit as gk  # noqa: E402


def pca_axis(points):
    """The point cloud's centre and its largest-variance direction (a unit Vector)."""
    centre = points.mean(axis=0)
    _values, vectors = np.linalg.eigh(np.cov((points - centre).T))
    return Vector(centre), Vector(vectors[:, -1]).normalized()  # eigh sorts ascending; take the last


def baked_mesh(obj_name):
    """World-space vertices and triangle indices of `obj_name`'s evaluated mesh (modifiers baked
    in), via `gear_kit.world_mesh`."""
    return gk.world_mesh(bpy.data.objects[obj_name])


def join_under(root_name):
    """Every mesh object at or under `root_name` in the object hierarchy, merged into one set of
    world-space vertices and triangles (as if joined), without changing the source file."""
    root = bpy.data.objects[root_name]

    def under(o):
        while o is not None:
            if o == root:
                return True
            o = o.parent
        return False
    meshes = [o for o in bpy.data.objects if o.type == "MESH" and under(o)]
    if not meshes:
        raise ValueError(f"no mesh objects under {obj_name!r}" if (obj_name := root_name) else "no mesh objects")
    all_co, all_tris, offset = [], [], 0
    for obj in meshes:
        co, tris = gk.world_mesh(obj)
        all_co.append(co)
        all_tris.append(tris + offset)
        offset += len(co)
    return np.vstack(all_co), np.vstack(all_tris)


def measure_diameter(points, tris, point_local, axis_local, samples=16):
    """Surface-to-surface width around `point_local` (already in the object's own space, after
    reorienting) perpendicular to `axis_local`, averaged over `samples` directions - a quick
    stand-in for "is this a round 33 mm shaft" without a human opening Blender. Raycasts the
    surface both ways from the point, like measuring a haft with calipers at several angles."""
    tree = BVHTree.FromPolygons(points.tolist(), tris.tolist(), all_triangles=True)
    axis = Vector(axis_local).normalized()
    arbitrary = Vector((1, 0, 0)) if abs(axis.z) < 0.9 else Vector((0, 1, 0))
    a = (arbitrary - axis * arbitrary.dot(axis)).normalized()
    b = axis.cross(a)
    widths = []
    for i in range(samples):
        theta = 2 * np.pi * i / samples
        direction = (a * np.cos(theta) + b * np.sin(theta)).normalized()
        origin = Vector(point_local)
        hit_pos, hit_neg = tree.ray_cast(origin, direction, 0.5), tree.ray_cast(origin, -direction, 0.5)
        if hit_pos[0] is None or hit_neg[0] is None:
            continue
        widths.append((hit_pos[0] - hit_neg[0]).length)
    if not widths:
        return None
    return {"mean_m": round(float(np.mean(widths)), 5), "min_m": round(float(np.min(widths)), 5),
            "max_m": round(float(np.max(widths)), 5), "samples": len(widths)}


def prepare(cfg):
    src = cfg["provenance"]
    for field in ("title", "author", "license", "url"):
        if not src.get(field):
            raise ValueError(f"provenance.{field} is required and must be verified before use "
                              f"(docs/PROCESS.md section 9: no material goes in without a recorded, "
                              f"verified licence)")

    bpy.ops.wm.open_mainfile(filepath=str(Path(cfg["input_blend"]).resolve()))
    points, tris = join_under(cfg["source_object"])

    orient = cfg.get("orient", {})
    if orient.get("axis") == "auto" or "axis" not in orient:
        centre, axis = pca_axis(points)
    else:
        centre, axis = Vector(points.mean(axis=0)), Vector(orient["axis"]).normalized()
    if orient.get("flip"):
        axis = -axis

    proj = points @ np.array(axis)
    span = float(proj.max() - proj.min())
    if "origin_world" in orient:
        origin = Vector(orient["origin_world"])
    else:
        fraction = orient.get("origin_fraction_along_axis", 0.5)  # 0 = the low end, 1 = the high end
        origin = Vector(centre) + axis * (proj.min() + fraction * span - float(np.array(centre) @ np.array(axis)))
    secondary_world = Vector(orient.get("secondary_world", (0.0, 0.0, 1.0)))
    primary_axis, secondary_axis = orient.get("primary_axis", "Z"), orient.get("secondary_axis", "Y")

    target_frame = gk.frame(origin, axis, secondary_world, primary_axis, secondary_axis)
    to_local = target_frame.inverted()
    local_pts = np.array([to_local @ Vector(p) for p in points])

    scale_cfg = cfg.get("scale", {})
    target_length = scale_cfg.get("target_length_m")
    scale = (target_length / span) if target_length else scale_cfg.get("factor", 1.0)
    local_pts *= scale

    report = {
        "key": cfg["key"], "source": src,
        "measured_span_m_before_scale": round(span, 5),
        "applied_uniform_scale": round(float(scale), 6),
        "final_span_m": round(span * scale, 5),
        "orient": {"axis": [round(v, 5) for v in axis], "origin_world": [round(v, 5) for v in origin],
                   "primary_axis": primary_axis, "secondary_axis": secondary_axis},
    }

    diam_cfg = cfg.get("measure_diameter_at")
    if diam_cfg:
        point_local = np.array(diam_cfg.get("point_local", [0.0, 0.0, 0.0])) * scale
        axis_local = diam_cfg.get("axis_local", [0.0, 0.0, 1.0])
        report["diameter"] = measure_diameter(local_pts, tris, point_local, axis_local)

    # Drop the opened source file entirely now that `local_pts`/`tris` (plain numpy, not tied to
    # any Blender datablock) hold everything measured from it. Building the result in a fresh
    # empty file, rather than saving over the still-open source file, guarantees the output never
    # carries the source's own objects, materials or textures along with it.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    mesh = bpy.data.meshes.new(cfg["key"])
    mesh.from_pydata(local_pts.tolist(), [], tris.tolist())
    mesh.update()
    mesh.validate()
    obj = bpy.data.objects.new(cfg["key"], mesh)
    bpy.context.scene.collection.objects.link(obj)
    for prop, value in (("gear_model", cfg["key"]), ("gear_title", src["title"]), ("gear_author", src["author"]),
                        ("gear_licence", src["license"]), ("gear_url", src["url"])):
        obj[prop] = value
        mesh[prop] = value

    out_dir = Path(cfg["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{cfg['key']}.blend"
    if out_path.exists():
        n = 1
        while out_path.with_name(f"{out_path.name}.bak.v{n}").exists():
            n += 1
        out_path.rename(out_path.with_name(f"{out_path.name}.bak.v{n}"))
        print(f"## existing output kept as {out_path.name}.bak.v{n}")

    bpy.ops.wm.save_as_mainfile(filepath=str(out_path))
    report_path = out_dir / f"{cfg['key']}.json"
    report_path.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"## wrote {out_path} and {report_path}")
    print(json.dumps(report, indent=1))
    return report


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if not argv:
        raise SystemExit("prepare_downloaded_model.py: pass a config path after --, e.g. "
                          "... --python tools/prepare_downloaded_model.py -- my_model.json")
    config = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    prepare(config)
