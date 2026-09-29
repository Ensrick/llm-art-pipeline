"""Outfit and weapon swaps for the shared humanoid on top of attachment_sockets (Blender 4.4).

Tested headless in Blender 4.4.0 (--background --factory-startup) by gear_kit_selftest.py, which
prints one "## ... ok" line per helper. Intended to sit next to tools/attachment_sockets.py:

    import attachment_sockets as sockets, attachment_nudge as nudge, gear_kit as gk
    frames = gk.load_frames([socket_manifest, gear_manifest])   # attachment_sockets' schema, merged in memory
    gk.apply_loadout(rig, loadout, items, frames, anatomy, sockets)   # one call per swap

Body sockets are attachment_sockets' bone-local frames (translation_m + rotation_wxyz, relative to the animated
pose bone's head frame); props carry named prop sockets in object space; attaching is
attachment_sockets.align_by_names. Nothing here adds bones or edits weights of the body.

Rig-scale note (measured): the shared rig inherits a Z-only 0.9 scale from Shared_Humanoid_Height.
A prop that align_by_names bone-parents is squashed along world Z like the body (the spear becomes
2.574 m tall). With true_size=True (default) apply_loadout bakes a per-socket compensation into a
copy of the prop mesh so that at the standing pose the prop has its authored size and the grip
frame is exact; like the approved builder's 1/0.9 object scale, the compensation is exact only at
that pose (a spear pitched to horizontal in the thrust still reads ~11% long).
"""

import json
import math
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector
from mathutils.bvhtree import BVHTree

RIG_NAME = "Shared_Humanoid_CC0_Rig"
LOADOUT_SCHEMA = "gear_loadout/1"
ITEMS_SCHEMA = "gear_items/1"

# --------------------------------------------------------------------------- mesh helpers


def world_mesh(obj):
    """Evaluated (skinned, modified) vertices in world space and triangle indices (numpy)."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        co = np.empty(len(mesh.vertices) * 3)
        mesh.vertices.foreach_get("co", co)
        world = np.array(evaluated.matrix_world)
        co = co.reshape(-1, 3) @ world[:3, :3].T + world[:3, 3]
        mesh.calc_loop_triangles()
        tris = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int32)
        mesh.loop_triangles.foreach_get("vertices", tris)
    finally:
        evaluated.to_mesh_clear()
    return co, tris.reshape(-1, 3)


def world_bvh(obj):
    """BVHTree of the evaluated mesh in WORLD space (BVHTree.FromObject is object-local)."""
    co, tris = world_mesh(obj)
    return BVHTree.FromPolygons(co.tolist(), tris.tolist(), all_triangles=True)


class FrameTrees:
    """World-space BVH trees of evaluated meshes, built once per frame on demand."""

    def __init__(self):
        self.trees = {}

    def get(self, obj):
        if obj.name not in self.trees:
            self.trees[obj.name] = world_bvh(obj)
        return self.trees[obj.name]

    def overlap(self, a, b):
        return len(self.get(a).overlap(self.get(b)))


def matrix_error(a, b):
    return max(abs(x - y) for ra, rb in zip(a, b) for x, y in zip(ra, rb))


# --------------------------------------------------------------------------- frames


def frame(origin, primary, secondary, primary_axis="Z", secondary_axis="Y"):
    """Orthonormal 4x4: `primary_axis` exactly along `primary`, `secondary_axis` = `secondary` made
    perpendicular to it, the third axis completing a right-handed frame."""
    p = Vector(primary).normalized()
    s = Vector(secondary) - p * Vector(secondary).dot(p)
    if s.length < 1e-9:
        raise ValueError("secondary direction is parallel to the primary")
    s.normalize()
    axes = {primary_axis: p, secondary_axis: s}
    third = ({"X", "Y", "Z"} - set(axes)).pop()
    order = "XYZ"
    i = order.index(third)
    axes[third] = axes[order[(i + 1) % 3]].cross(axes[order[(i + 2) % 3]])
    m = Matrix((axes["X"], axes["Y"], axes["Z"])).transposed().to_4x4()
    m.translation = Vector(origin)
    return m


def orthonormal(matrix, primary_axis="Z", secondary_axis="Y"):
    """Gram-Schmidt of a possibly scaled/sheared 4x4 frame (origin and primary axis exact)."""
    m3 = matrix.to_3x3()
    idx = "XYZ"
    return frame(matrix.translation, m3.col[idx.index(primary_axis)], m3.col[idx.index(secondary_axis)],
                 primary_axis, secondary_axis)


def local_matrix(entry):
    """Same convention as attachment_sockets.local_matrix."""
    q = Quaternion(entry["rotation_wxyz"])
    q.normalize()
    return Matrix.Translation(Vector(entry["translation_m"])) @ q.to_matrix().to_4x4()


def frame_entry(matrix, digits=9):
    q = matrix.to_quaternion().normalized()
    return {"translation_m": [round(float(x), digits) for x in matrix.translation],
            "rotation_wxyz": [round(float(x), digits) for x in q]}


def body_local_from_world(rig, bone_name, world_frame, primary_axis="Z", secondary_axis="Y"):
    """Bone-local frame (attachment_sockets' schema) whose Gram-Schmidt world image is exactly `world_frame`
    (origin, primary and secondary directions), even under a non-uniformly scaled rig."""
    pose_world = rig.matrix_world @ rig.pose.bones[bone_name].matrix
    inv = pose_world.inverted()
    inv3 = inv.to_3x3()
    w3 = world_frame.to_3x3()
    i = "XYZ"
    return frame(inv @ world_frame.translation, inv3 @ w3.col[i.index(primary_axis)],
                 inv3 @ w3.col[i.index(secondary_axis)], primary_axis, secondary_axis)


# --------------------------------------------------------------------------- manifests


def load_frames(paths, sockets_module=None):
    """Merge several manifests in attachment_sockets' schema (validated with attachment_sockets.load_manifest
    when the module is given). Names must be unique across files."""
    merged = {"schema_version": 1, "units": "meters", "quaternion_order": "wxyz",
              "body_sockets": {}, "prop_sockets": {}, "body_landmarks": {}, "sources": []}
    for path in paths:
        data = sockets_module.load_manifest(path) if sockets_module else json.loads(Path(path).read_text("utf-8"))
        for key in ("body_sockets", "prop_sockets", "body_landmarks"):
            clash = set(merged[key]) & set(data.get(key, {}))
            if clash:
                raise ValueError(f"{path}: duplicate {key} {sorted(clash)}")
            merged[key].update(data.get(key, {}))
        merged["sources"].append(str(path))
    return merged


# --------------------------------------------------------------------------- placeholder weapons


def _material(name, color, metallic=0.0, roughness=0.6):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        bsdf.inputs["Base Color"].default_value = (*color, 1.0)
        bsdf.inputs["Metallic"].default_value = metallic
        bsdf.inputs["Roughness"].default_value = roughness
        mat.diffuse_color = (*color, 1.0)
    return mat


def _hull(bm, points, material_index):
    import bmesh
    verts = [bm.verts.new(p) for p in points]
    result = bmesh.ops.convex_hull(bm, input=verts)
    new = set(verts)
    for f in bm.faces:
        if any(v in new for v in f.verts):
            f.material_index = material_index
    loose = [g for key in ("geom_interior", "geom_unused") for g in result.get(key, [])
             if isinstance(g, bmesh.types.BMVert) and not g.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")


def _haft(bm, z0, z1, radius, segments=12):
    import bmesh
    bmesh.ops.create_cone(bm, cap_ends=True, segments=segments, radius1=radius, radius2=radius,
                          depth=z1 - z0, matrix=Matrix.Translation((0.0, 0.0, (z0 + z1) / 2)))


def _finish(name, bm, collection):
    mesh = bpy.data.meshes.new(name + "_mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.materials.append(_material("gear_wood", (0.30, 0.18, 0.09)))
    mesh.materials.append(_material("gear_iron", (0.45, 0.46, 0.48), 0.8, 0.4))
    obj = bpy.data.objects.new(name, mesh)
    (collection or bpy.context.scene.collection).objects.link(obj)
    return obj


def build_axe(name="Gear_Axe", collection=None):
    """Placeholder one-handed axe: haft along +Z from the butt (z=0) to the head (z 0.62-0.72),
    blade edge towards +Y (edge z 0.56-0.78). Use prop socket translation (0, 0, 0.12) = grip,
    +Z towards the head."""
    import bmesh
    bm = bmesh.new()
    _haft(bm, 0.0, 0.72, 0.016)
    for f in bm.faces:
        f.material_index = 0
    _hull(bm, [(x, y, z) for x in (-0.02, 0.02) for y in (-0.045, 0.028) for z in (0.62, 0.72)], 1)
    blade = [(x, 0.028, z) for x in (-0.010, 0.010) for z in (0.63, 0.71)]
    blade += [(x, 0.165, z) for x in (-0.002, 0.002) for z in (0.56, 0.78)]
    _hull(bm, blade, 1)
    return _finish(name, bm, collection)


def build_mace(name="Gear_Mace", collection=None):
    """Placeholder flanged mace: haft along +Z from the butt (z=0) to the head centre (z=0.60),
    six flanges (z 0.54-0.66, one towards +Y). Use prop socket translation (0, 0, 0.10) = grip."""
    import bmesh
    bm = bmesh.new()
    _haft(bm, 0.0, 0.58, 0.015)
    for f in bm.faces:
        f.material_index = 0
    core = bmesh.ops.create_icosphere(bm, subdivisions=2, radius=0.042, matrix=Matrix.Translation((0, 0, 0.60)))
    for f in {f for v in core["verts"] for f in v.link_faces}:
        f.material_index = 1
    for k in range(6):
        a = 2 * math.pi * k / 6
        d = Vector((math.sin(a), math.cos(a), 0.0))
        t = Vector((math.cos(a), -math.sin(a), 0.0)) * 0.004
        pts = [Vector((0, 0, z)) + d * r + t * s for z in (0.54, 0.66) for r in (0.03, 0.062) for s in (-1, 1)]
        _hull(bm, [tuple(p) for p in pts], 1)
    return _finish(name, bm, collection)


# --------------------------------------------------------------------------- true size under the rig scale


def true_size_matrix(rig, bone_name, body_local, prop_local, primary_axis="Z", secondary_axis="Y"):
    """Mesh-space matrix C that gives a bone-parented prop its authored size at the current pose.

    After align_by_names the prop's world matrix is W = rig_world @ pose @ body_local @ prop_local^-1
    (sheared by a non-uniform rig scale). With mesh vertices replaced by C @ v the prop's world
    shape is F_o @ prop_local^-1, where F_o is the Gram-Schmidt of the socket's world frame, i.e. a
    rigid placement with the grip frame exact. C is identity for a uniformly scaled rig.
    """
    pose_world = rig.matrix_world @ rig.pose.bones[bone_name].matrix
    socket_world = pose_world @ body_local
    placement = pose_world @ body_local @ prop_local.inverted()
    rigid = orthonormal(socket_world, primary_axis, secondary_axis) @ prop_local.inverted()
    return placement.inverted() @ rigid


def _true_mesh(obj):
    name = obj.get("gear_true_mesh")
    if name is None:
        obj["gear_true_mesh"] = obj.data.name
        name = obj.data.name
    return bpy.data.meshes[name]


def parent_relative(obj):
    """Transform relative to the parent, from stored data. Object.matrix_local is derived from
    WORLD matrices, which are stale for objects excluded from evaluation (hide_viewport)."""
    return obj.matrix_parent_inverse @ obj.matrix_basis


def apply_true_size(obj, key, matrix, children=()):
    """Swap `obj` (and render children parented to it) to meshes compensated by `matrix`,
    cached per `key` (a dict on each object; Blender truncates ID names to 63 characters, so
    long composite names cannot be looked up). The authored meshes stay untouched."""
    for o, m in [(obj, matrix)] + [(c, parent_relative(c).inverted() @ matrix @ parent_relative(c))
                                   for c in children]:
        true = _true_mesh(o)
        cache = dict(o.get("gear_true_size_cache", {}))
        cached = bpy.data.meshes.get(cache.get(key, ""))
        if cached is None:
            cached = true.copy()
            cached.name = f"{true.name[:40]}.ts"
            cached.transform(m)
            cached.update()
            cache[key] = cached.name
            o["gear_true_size_cache"] = cache
        o.data = cached


def restore_true_mesh(obj, children=()):
    for o in (obj, *children):
        if o.get("gear_true_mesh"):
            o.data = bpy.data.meshes[o["gear_true_mesh"]]


# --------------------------------------------------------------------------- loadouts
#
# items  {"schema": "gear_items/1", "items": {id: {"object": name, "kind": "prop" | "skinned",
#          "prop_socket": name (props), "hides": [region, ...] (optional),
#          "parts": [child object names that ride along], "parts_on": [body sockets] (optional)}}}
# loadout {"schema": "gear_loadout/1", "unit": str, "name": str,
#          "frames": [manifest files], "nudges": nudge file (optional),
#          "slots": {slot: null | {"item": id, "attach": "socket" | "skinned",
#                                  "socket": body socket name, "hides": [region, ...] (optional)}}}


def set_visible(obj, visible):
    obj.hide_render = not visible
    obj.hide_viewport = not visible
    if obj.name in bpy.context.view_layer.objects:
        obj.hide_set(not visible)


def ensure_skinned(obj, rig):
    if obj.parent is not rig:
        world = obj.matrix_world.copy()
        obj.parent, obj.parent_type = rig, "OBJECT"
        obj.matrix_parent_inverse = Matrix.Identity(4)
        obj.matrix_world = world
    if not any(m.type == "ARMATURE" and m.object is rig for m in obj.modifiers):
        obj.modifiers.new("Armature", "ARMATURE").object = rig


def hide_region_modifiers(rig):
    out = {}
    for obj in bpy.data.objects:
        if obj.type == "MESH" and obj.parent is rig:
            for mod in obj.modifiers:
                if mod.type == "MASK" and mod.name.startswith("gear_hide:"):
                    out.setdefault(mod.name.split(":", 1)[1], []).append(mod)
    return out


def create_hide_region(body, region, vertex_indices):
    """Vertex group + inverted Mask modifier, first in the stack and off until a loadout asks for
    it. Toggling hides/shows the body under a garment without deleting faces."""
    group = body.vertex_groups.get(region) or body.vertex_groups.new(name=region)
    group.add(list(vertex_indices), 1.0, "REPLACE")
    mod = body.modifiers.get("gear_hide:" + region) or body.modifiers.new("gear_hide:" + region, "MASK")
    mod.mode = "VERTEX_GROUP"
    mod.vertex_group = region
    mod.invert_vertex_group = True
    mod.show_viewport = mod.show_render = False
    index = list(body.modifiers).index(mod)
    if index != 0:
        body.modifiers.move(index, 0)
    return mod


def detach(obj):
    world = obj.matrix_world.copy()
    obj.parent = None
    obj.parent_type = "OBJECT"
    obj.parent_bone = ""
    obj.matrix_parent_inverse = Matrix.Identity(4)
    obj.matrix_world = world


def apply_loadout(rig, loadout, items, frames, anatomy, sockets_module, nudges=None, nudge_module=None,
                  true_size=True):
    """Make the scene match `loadout` in one call; a swap is this call with the edited loadout.

    Props: attachment_sockets.align_by_names on the named body socket (after an optional
    attachment_nudge entry keyed by the item id) and, with true_size, a per-socket compensated
    mesh copy. Skinned items: shown with an Armature modifier. Items not in the loadout are
    hidden (props also unparented). Body hide regions asked for by equipped items or slots are
    switched on, all others off. Must run at the saved standing pose (no action).
    Returns {item_id: object}.
    """
    ad = rig.animation_data
    if ad is not None and ad.action is not None:
        raise RuntimeError("apply_loadout runs at the saved standing pose: clear the rig's action first")
    registry = items["items"] if "items" in items else items
    wanted, hides = {}, set()
    for slot, spec in loadout.get("slots", {}).items():
        if not spec:
            continue
        if spec["item"] in wanted:
            raise ValueError(f"item {spec['item']!r} is used by two slots")
        wanted[spec["item"]] = dict(spec, slot=slot)
        hides.update(registry[spec["item"]].get("hides", []))
        hides.update(spec.get("hides", []))
    for item_id, item in registry.items():
        obj = bpy.data.objects[item["object"]]
        parts = [bpy.data.objects[p] for p in item.get("parts", [])]
        if item_id not in wanted:
            if item["kind"] == "prop" and obj.parent is not None:
                detach(obj)
            for o in (obj, *parts):
                set_visible(o, False)
    equipped = {}
    for item_id, spec in wanted.items():
        item = registry[item_id]
        obj = bpy.data.objects[item["object"]]
        parts = [bpy.data.objects[p] for p in item.get("parts", [])]
        attach = spec.get("attach", "socket" if item["kind"] == "prop" else "skinned")
        if attach == "socket":
            body_name, prop_name = spec["socket"], item["prop_socket"]
            use_frames = frames
            if nudges and nudge_module and item_id in nudges.get("nudges", {}):
                entry = nudges["nudges"][item_id]
                if entry["body_socket"] != body_name:
                    raise ValueError(f"nudge for {item_id} is for {entry['body_socket']}, slot uses {body_name}")
                use_frames, body_name, _ = nudge_module.nudged_manifest(frames, anatomy, rig, nudges, item_id)
            restore_true_mesh(obj, parts)
            if obj.parent is not None and (obj.parent is not rig or obj.parent_type != "BONE" or obj.parent_bone
                                           != anatomy["roles"][use_frames["body_sockets"][body_name]["bone_role"]]["bone"]):
                detach(obj)
            sockets_module.align_by_names(rig, obj, use_frames, anatomy, body_name, prop_name)
            if true_size:
                bone = anatomy["roles"][use_frames["body_sockets"][body_name]["bone_role"]]["bone"]
                c = true_size_matrix(rig, bone, local_matrix(use_frames["body_sockets"][body_name]),
                                     local_matrix(use_frames["prop_sockets"][prop_name]))
                apply_true_size(obj, body_name, c, parts)
            on = item.get("parts_on")
            for p in parts:
                set_visible(p, on is None or spec["socket"] in on)
            obj["gear_slot"], obj["gear_body_socket"] = spec["slot"], spec["socket"]
        elif attach == "skinned":
            ensure_skinned(obj, rig)
        else:
            raise ValueError(f"{item_id}: unknown attach type {attach!r}")
        set_visible(obj, True)
        equipped[item_id] = obj
    known = hide_region_modifiers(rig)
    missing = hides - set(known)
    if missing:
        raise KeyError(f"hide regions without a Mask modifier: {sorted(missing)}")
    for region, mods in known.items():
        for mod in mods:
            mod.show_viewport = mod.show_render = region in hides
    bpy.context.view_layer.update()
    return equipped


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- skinned garments


def rest_pose(rig, rest=True):
    rig.data.pose_position = "REST" if rest else "POSE"
    bpy.context.view_layer.update()


def shell_garment(name, targets, rig, z_range, offset=0.020, segments=40, ring_step=0.02,
                  radii=(0.34, 0.30), center=(0.0, 0.02), slit_below=0.96, slit_half_width=0.035,
                  smooth_iterations=6, collection=None):
    """New tube-topology garment shrink-wrapped (projected along its normals) onto the REST-pose
    body at `offset` metres, with front and back riding slits below `slit_below` (armature z) so
    no face bridges the two legs, then smoothed. z_range is armature space. No weights yet.
    Measured on the shared spearman: 12 mm, no slits, no smoothing -> 93 body + 50 leg triangle
    pairs intersecting at REST; 20 mm + slits + 6 smoothing passes -> 0 and 0."""
    z0, z1 = z_range
    rings = int(round((z1 - z0) / ring_step)) + 1
    verts = [(center[0] + radii[0] * math.cos(2 * math.pi * j / segments),
              center[1] + radii[1] * math.sin(2 * math.pi * j / segments), z0 + (z1 - z0) * i / (rings - 1))
             for i in range(rings) for j in range(segments)]
    faces = [(i * segments + j, i * segments + (j + 1) % segments, (i + 1) * segments + (j + 1) % segments,
              (i + 1) * segments + j) for i in range(rings - 1) for j in range(segments)]
    mesh = bpy.data.meshes.new(name + "_mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    (collection or bpy.context.scene.collection).objects.link(obj)
    obj.parent = rig
    obj.matrix_parent_inverse = Matrix.Identity(4)
    target = join_copies(targets, name + "_wrap_target")
    try:
        mod = obj.modifiers.new("wrap", "SHRINKWRAP")
        mod.target = target
        mod.wrap_method = "PROJECT"
        mod.use_negative_direction = True
        mod.use_positive_direction = False
        mod.offset = offset
        with bpy.context.temp_override(active_object=obj, object=obj, selected_objects=[obj],
                                       selected_editable_objects=[obj]):
            bpy.ops.object.modifier_apply(modifier=mod.name)
    finally:
        tm = target.data
        bpy.data.objects.remove(target)
        bpy.data.meshes.remove(tm)
    if slit_below is not None:
        import bmesh
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        doomed = [f for f in bm.faces if abs(f.calc_center_median().x - center[0]) < slit_half_width
                  and f.calc_center_median().z < slit_below]
        bmesh.ops.delete(bm, geom=doomed, context="FACES")
        bm.to_mesh(obj.data)
        bm.free()
    if smooth_iterations:
        mod = obj.modifiers.new("smooth", "SMOOTH")
        mod.iterations = smooth_iterations
        mod.factor = 0.5
        with bpy.context.temp_override(active_object=obj, object=obj, selected_objects=[obj],
                                       selected_editable_objects=[obj]):
            bpy.ops.object.modifier_apply(modifier=mod.name)
    for p in obj.data.polygons:
        p.use_smooth = True
    return obj


def join_copies(objects, name):
    """Modifier-free joined copy of several meshes (rest shape, vertex groups merged by name)."""
    copies = []
    for obj in objects:
        c = obj.copy()
        c.data = obj.data.copy()
        c.modifiers.clear()
        if c.data.shape_keys:
            c.shape_key_clear()
        bpy.context.scene.collection.objects.link(c)
        copies.append(c)
    with bpy.context.temp_override(active_object=copies[0], object=copies[0],
                                   selected_objects=copies, selected_editable_objects=copies):
        bpy.ops.object.join()
    copies[0].name = name
    return copies[0]


def transfer_weights(target, sources, mapping="POLYINTERP_NEAREST", limit=4):
    """Skin weights from body meshes onto a garment authored in the REST pose.

    Data Transfer modifier (vertex groups; POLYINTERP_NEAREST = nearest face interpolated),
    object.datalayout_transfer to create the groups, apply, vertex_group_limit_total(limit),
    vertex_group_normalize_all. Sources are joined into one modifier-free copy first.
    Returns (max influences per vertex, max |weight sum - 1|).
    """
    source = join_copies(sources, "gear_weight_source")
    try:
        mod = target.modifiers.new("gear_weight_transfer", "DATA_TRANSFER")
        mod.object = source
        mod.use_object_transform = True
        mod.use_vert_data = True
        mod.data_types_verts = {"VGROUP_WEIGHTS"}
        mod.vert_mapping = mapping
        mod.layers_vgroup_select_src = "ALL"
        mod.layers_vgroup_select_dst = "NAME"
        index = list(target.modifiers).index(mod)
        if index != 0:
            target.modifiers.move(index, 0)
        # The vertex-group operators act on the view layer's REAL active object and ignore
        # temp_override (measured in 4.4: limit_total returned FINISHED on another object), so
        # make the garment active and selected for the whole sequence.
        view_layer = bpy.context.view_layer
        previous = view_layer.objects.active
        view_layer.objects.active = target
        target.select_set(True)
        try:
            with bpy.context.temp_override(active_object=target, object=target, selected_objects=[target],
                                           selected_editable_objects=[target]):
                bpy.ops.object.datalayout_transfer(modifier=mod.name)
                bpy.ops.object.modifier_apply(modifier=mod.name)
                bpy.ops.object.vertex_group_limit_total(group_select_mode="ALL", limit=limit)
                bpy.ops.object.vertex_group_normalize_all(group_select_mode="ALL", lock_active=False)
        finally:
            target.select_set(False)
            view_layer.objects.active = previous
    finally:
        mesh = source.data
        bpy.data.objects.remove(source)
        bpy.data.meshes.remove(mesh)
    most, worst = influence_stats(target)
    if most > limit:
        raise RuntimeError(f"{target.name}: {most} influences after limit_total({limit})")
    return most, worst


def influence_stats(obj):
    """(max non-zero influences per vertex, max |weight sum - 1|)."""
    most, worst = 0, 0.0
    for v in obj.data.vertices:
        ws = [g.weight for g in v.groups if g.weight > 0.0]
        most = max(most, len(ws))
        worst = max(worst, abs(sum(ws) - 1.0) if ws else 1.0)
    return most, worst


def covered_vertices(body, garment, reach=0.04, erode=1):
    """Body vertices (rest mesh) whose outward normal hits `garment` (rest) within `reach` m,
    shrunk by `erode` edge rings so the mask never opens a gap at the garment's edge."""
    tree = BVHTree.FromObject(garment, bpy.context.evaluated_depsgraph_get(), deform=False)
    to_garment = garment.matrix_world.inverted() @ body.matrix_world
    rot = to_garment.to_3x3()
    covered = set()
    for v in body.data.vertices:
        if tree.ray_cast(to_garment @ v.co, (rot @ v.normal).normalized(), reach)[0] is not None:
            covered.add(v.index)
    for _ in range(erode):
        edge = set()
        for e in body.data.edges:
            a, b = e.vertices
            if (a in covered) != (b in covered):
                edge.add(a if a in covered else b)
        covered -= edge
    return covered


def edge_strain(obj, rig, rest_co, frames_co):
    """Max |edge length / rest length - 1| over the given evaluated vertex sets, in ARMATURE
    space (the rig's non-uniform world scale would otherwise read as strain)."""
    edges = np.array([tuple(e.vertices) for e in obj.data.edges])
    inv = np.array(rig.matrix_world.inverted())

    def arm(co):
        return co @ inv[:3, :3].T + inv[:3, 3]

    r = arm(rest_co)
    rest = np.linalg.norm(r[edges[:, 0]] - r[edges[:, 1]], axis=1)
    ok = rest > 1e-6
    worst = 0.0
    for co in frames_co:
        c = arm(co)
        now = np.linalg.norm(c[edges[:, 0]] - c[edges[:, 1]], axis=1)
        worst = max(worst, float(np.abs(now[ok] / rest[ok] - 1.0).max()))
    return worst


# --------------------------------------------------------------------------- validation


def play(rig, action, frame=None):
    ad = rig.animation_data_create()
    for track in ad.nla_tracks:
        track.mute = True
    ad.action = action
    ad.action_slot = action.slots[0]
    if frame is not None:
        bpy.context.scene.frame_set(frame)


def validate_loadout(rig, attached, pairs, actions, frames, anatomy, sockets_module, standing):
    """Grip drift, prop size and intersections for one loadout through every action frame.

    attached: [(prop, body_socket_entry, bone_name, prop_socket_entry, (vertex a, vertex b))]; the
    world distance between the two mesh vertices (e.g. butt and tip) is reported, so a size
    compensation baked into the mesh is included. pairs: [(obj_a, obj_b)] evaluated-mesh
    intersection pairs. The baseline is the standing pose. Returns a JSON-friendly dict.
    """
    scene = bpy.context.scene
    trees = FrameTrees()
    res = {"drift_mm_deg": {}, "length_m": {}, "pairs": {}}

    def span(prop, a, b):
        v = prop.data.vertices
        return ((prop.matrix_world @ v[a].co) - (prop.matrix_world @ v[b].co)).length

    for prop, _b, _n, _p, (a, b) in attached:
        res["drift_mm_deg"][prop.name] = [0.0, 0.0]
        d = span(prop, a, b)
        res["length_m"][prop.name] = {"standing": round(d, 4), "min": d, "max": d}
    for x, y in pairs:
        res["pairs"][f"{x.name}|{y.name}"] = {"standing": trees.overlap(x, y)}
    try:
        for action, last in actions:
            play(rig, action)
            for f in range(int(last) + 1):
                scene.frame_set(f)
                trees = FrameTrees()
                for prop, body_entry, bone, prop_entry, (a, b) in attached:
                    want = sockets_module.body_socket_world(rig, bone, body_entry)
                    got = sockets_module.prop_socket_world(prop, prop_entry)
                    dist, deg = sockets_module.frame_error(want, got)
                    d = res["drift_mm_deg"][prop.name]
                    d[0], d[1] = max(d[0], dist * 1000), max(d[1], deg)
                    length = span(prop, a, b)
                    L = res["length_m"][prop.name]
                    L["min"], L["max"] = min(L["min"], length), max(L["max"], length)
                for x, y in pairs:
                    n = trees.overlap(x, y)
                    slot = res["pairs"][f"{x.name}|{y.name}"]
                    if n > slot.get(action.name, [-1, None])[0]:
                        slot[action.name] = [n, f]
    finally:
        rig.animation_data_clear()
        for pb in rig.pose.bones:
            pb.matrix_basis = standing.get(pb.name, Matrix.Identity(4))
        bpy.context.view_layer.update()
    for L in res["length_m"].values():
        L["min"], L["max"] = round(L["min"], 4), round(L["max"], 4)
    return res


# --------------------------------------------------------------------------- review renders


def ensure_camera(name):
    cam = bpy.data.objects.get(name)
    if cam is None:
        cam = bpy.data.objects.new(name, bpy.data.cameras.new(name))
        bpy.context.scene.collection.objects.link(cam)
    cam.data.type = "ORTHO"
    cam.data.clip_end = 200.0
    return cam


def aim_camera(cam, target, direction, ortho, distance=30.0):
    d = Vector(direction).normalized()
    cam.location = Vector(target) - d * distance
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    cam.data.ortho_scale = ortho
    return cam


def game_camera(target=(0.0, 0.0, 1.35), ortho=2.6, elevation_deg=30.0, name="Gear_Game_Camera"):
    """Orthographic game view from -Y, looking +Y and down `elevation_deg`."""
    e = math.radians(elevation_deg)
    return aim_camera(ensure_camera(name), target, (0.0, math.cos(e), -math.sin(e)), ortho)


def three_quarter_camera(target=(0.0, 0.0, 1.35), ortho=3.3, name="Gear_3Q_Camera"):
    return aim_camera(ensure_camera(name), target, (2.7, 5.0, -0.85), ortho)


def render_png(cam, path, resolution):
    scene = bpy.context.scene
    scene.camera = cam
    scene.render.resolution_x, scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    return str(path)


def _pixels(path):
    img = bpy.data.images.load(str(path), check_existing=False)
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    return px.reshape(h, w, 4)


def contact_sheet(rows, out_path, pad=6, background=(0.18, 0.18, 0.18, 1.0)):
    """Tile PNGs: rows = [[(path, integer upscale), ...], ...]; nearest-neighbour upscaling keeps
    sprite pixels crisp. Pillow is not bundled with Blender, so this uses bpy + numpy."""
    grid = [[np.repeat(np.repeat(_pixels(p), s, axis=0), s, axis=1) for p, s in row] for row in rows]
    cell_w = max(img.shape[1] for row in grid for img in row)
    row_h = [max(img.shape[0] for img in row) for row in grid]
    cols = max(len(row) for row in grid)
    width = cols * cell_w + (cols + 1) * pad
    height = sum(row_h) + (len(grid) + 1) * pad
    sheet = np.empty((height, width, 4), dtype=np.float32)
    sheet[:] = background
    bg = np.array(background[:3], dtype=np.float32)
    y = pad
    for r, row in enumerate(grid):
        for c, img in enumerate(row):
            h, w = img.shape[:2]
            x = pad + c * (cell_w + pad) + (cell_w - w) // 2
            top = y + (row_h[r] - h)
            a = img[..., 3:4]
            sheet[height - top - h:height - top, x:x + w, :3] = img[..., :3] * a + bg * (1 - a)
            sheet[height - top - h:height - top, x:x + w, 3] = 1.0
        y += row_h[r] + pad
    out = bpy.data.images.new("gear_sheet", width, height, alpha=True)
    out.pixels.foreach_set(sheet.ravel())
    out.filepath_raw, out.file_format = str(out_path), "PNG"
    out.save()
    bpy.data.images.remove(out)
    return str(out_path)
