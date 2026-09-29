"""Verified Blender 4.4 animation helpers for the shared humanoid (see art/ANIMATION_PLAYBOOK.md).

Every function here was run headless in Blender 4.4.0 (--background --factory-startup) on
2026-09-25 by anim_cookbook_selftest.py, which prints one "## ... ok" line per helper. Re-run the
self-test after a Blender upgrade; Blender 5.0 removes the legacy Action.fcurves API, which none of
these helpers use.

Nothing here is imported by the unit builders yet. Import it, or copy what you need:

    import sys; sys.path.insert(0, str(Path(__file__).resolve().parents[N] / "tools"))
    import anim_cookbook as ac
"""

import json
import math

import bpy
import numpy as np
from bpy_extras import anim_utils
from bpy_extras.anim_utils import BakeOptions, bake_action
from mathutils import Matrix, Quaternion, Vector
from mathutils.bvhtree import BVHTree

IDENTITY = Quaternion()  # (1, 0, 0, 0)


# --------------------------------------------------------------------------- actions and keys

def channelbag(action, slot=None):
    """The F-curve container of one slot (Blender 4.4 slotted actions)."""
    return anim_utils.action_get_channelbag_for_slot(action, slot or action.slots[0])


def play(rig, action):
    """Show `action` on `rig`: mute NLA tracks and always set the slot explicitly.

    Assigning an action without its slot leaves action_slot=None and the rig silently stays in its
    rest pose (seen with UAL actions assigned to the Peasant rig).
    """
    ad = rig.animation_data_create()
    for track in ad.nla_tracks:
        track.mute = True
    ad.action = action
    ad.action_slot = action.slots[0]


def write_keys(name, owner, keys, interpolation="LINEAR"):
    """Create a new slotted action from keys[(data_path, index)] = [f0, v0, f1, v1, ...].

    About 16x faster than keyframe_insert. fc.update() sorts the keys and recomputes handles;
    handles stay at (0, 0) without it. The action is assigned to `owner` and returned.
    """
    action = bpy.data.actions.new(name)
    slot = action.slots.new(id_type=owner.id_type, name=owner.name)
    bag = action.layers.new("Layer").strips.new(type="KEYFRAME").channelbag(slot, ensure=True)
    ipo = bpy.types.Keyframe.bl_rna.properties["interpolation"].enum_items[interpolation].value
    for (path, index), co in keys.items():
        fc = bag.fcurves.new(path, index=index)
        count = len(co) // 2
        fc.keyframe_points.add(count)
        fc.keyframe_points.foreach_set("co", co)
        fc.keyframe_points.foreach_set("interpolation", [ipo] * count)
        fc.update()
    ad = owner.animation_data_create()
    ad.action, ad.action_slot = action, slot
    return action


def replace_keys(action, keys, slot=None):
    """Overwrite F-curves inside an existing action (for polish passes such as springs)."""
    bag = channelbag(action, slot)
    for (path, index), co in keys.items():
        old = bag.fcurves.find(path, index=index)
        if old is not None:
            bag.fcurves.remove(old)
        fc = bag.fcurves.new(path, index=index)
        fc.keyframe_points.add(len(co) // 2)
        fc.keyframe_points.foreach_set("co", co)
        fc.update()


def bake_options(**overrides):
    """BakeOptions has no defaults in 4.4; all 12 fields must be given."""
    fields = dict(only_selected=False, do_pose=True, do_object=False, do_visual_keying=True,
                  do_constraint_clear=True, do_parents_clear=False, do_clean=False,
                  do_location=True, do_rotation=True, do_scale=True, do_bbone=False,
                  do_custom_props=False)
    fields.update(overrides)
    return BakeOptions(**fields)


def bake_to_action(obj, frames, name, **overrides):
    """Bake constraints, IK and NLA layers on `obj` into one plain action named `name`.

    The new action has LINEAR keys. Mute or remove NLA tracks afterwards, or they still evaluate.
    """
    action = bake_action(obj, action=None, frames=frames, bake_options=bake_options(**overrides))
    action.name = name
    return action


# --------------------------------------------------------------------------- retargeting

def retarget_action(src, tgt, frames, name, move=("root", "pelvis"), align_rest=True):
    """Copy `src`'s current action onto `tgt` (same bone names, different rest pose).

    World-space delta with rest alignment, computed in armature space (both rigs at identity
    object transforms). Each target bone's rest joint direction (towards the centroid of its
    children) is turned onto the source's, so the posed limbs point where the donor's point.
    Translation is copied only for `move`, scaled by the leg-length ratio.
    Measured on UAL1 Walk_Loop -> Peasant rig: single-child joint directions exact (0.000 deg),
    worst joint 6.2 deg (thumbs, spine_03); 0.04 s for 33 frames x 65 bones.
    Target bones must use QUATERNION rotation mode (the glTF default).
    """
    scene = bpy.context.scene
    sb, tb = src.data.bones, tgt.data.bones
    names = sorted((b.name for b in tb if b.name in sb), key=lambda n: len(tb[n].parent_recursive))
    leg = lambda bones: (bones["thigh_l"].head_local - bones["foot_l"].head_local).length
    scale = leg(tb) / leg(sb)
    correction = {}
    for n in names:
        align = Quaternion()
        kids = [c.name for c in tb[n].children if c.name in sb]
        if align_rest and kids and n not in move:
            target_dir = sum((tb[c].head_local for c in kids), Vector()) / len(kids) - tb[n].head_local
            source_dir = sum((sb[c].head_local for c in kids), Vector()) / len(kids) - sb[n].head_local
            align = target_dir.rotation_difference(source_dir)
        correction[n] = (sb[n].matrix_local.to_quaternion().inverted() @ align
                         @ tb[n].matrix_local.to_quaternion())
    rest_in_parent = {n: tb[n].parent.matrix_local.inverted() @ tb[n].matrix_local if tb[n].parent
                      else tb[n].matrix_local for n in names}
    keys, previous = {}, {}
    for f in frames:
        scene.frame_set(f)
        posed = {}
        for n in names:
            source = src.pose.bones[n].matrix
            base = posed[tb[n].parent.name] @ rest_in_parent[n] if tb[n].parent else rest_in_parent[n]
            head = (tb[n].head_local + (source.translation - sb[n].head_local) * scale
                    if n in move else base.translation)
            posed[n] = Matrix.LocRotScale(head, source.to_quaternion() @ correction[n], None)
            basis = base.inverted() @ posed[n]
            q = basis.to_quaternion()
            if n in previous:
                q.make_compatible(previous[n])
            previous[n] = q
            path = f'pose.bones["{n}"]'
            for i in range(4):
                keys.setdefault((path + ".rotation_quaternion", i), []).extend((f, q[i]))
            if n in move:
                for i in range(3):
                    keys.setdefault((path + ".location", i), []).extend((f, basis.translation[i]))
    for pb in tgt.pose.bones:
        pb.rotation_mode = "QUATERNION"
    return write_keys(name, tgt, keys)


def joint_direction_error(src, tgt, frames, skip=("root", "pelvis")):
    """Worst parent->child direction difference (deg) between two playing rigs: (single-child, all)."""
    scene = bpy.context.scene
    single = worst = 0.0
    for f in frames:
        scene.frame_set(f)
        for bone in tgt.data.bones:
            if bone.name in skip or bone.name not in src.pose.bones:
                continue
            for child in bone.children:
                if child.name not in src.pose.bones:
                    continue
                a = src.pose.bones[child.name].head - src.pose.bones[bone.name].head
                b = tgt.pose.bones[child.name].head - tgt.pose.bones[bone.name].head
                error = math.degrees(a.angle(b))
                worst = max(worst, error)
                if len(bone.children) == 1:
                    single = max(single, error)
    return single, worst


# --------------------------------------------------------------------------- layering

def layered_rotation(q_posture, q_ref, q_donor, keep):
    """Our posture plus `keep` (0..1) of the donor's motion around its reference pose.

    All three are local pose-bone quaternions. keep=0 holds the posture; keep=1 adds the donor's
    full motion relative to q_ref. Same composition as an NLA COMBINE strip (base @ offset).
    """
    delta = q_ref.inverted() @ q_donor
    if delta.w < 0.0:
        delta.negate()
    return q_posture @ IDENTITY.slerp(delta, keep)


def layered_location(p_posture, p_ref, p_donor, keep):
    return Vector(p_posture) + keep * (Vector(p_donor) - Vector(p_ref))


# --------------------------------------------------------------------------- constraints and props

def pole_angle(base, tip, pole):
    """IK pole_angle for a 2-bone chain; `base`/`tip` are rest Bones, `pole` in armature space."""
    normal = (tip.tail_local - base.head_local).cross(pole - base.head_local)
    projected = normal.cross(base.tail_local - base.head_local)
    angle = base.x_axis.angle(projected)
    return -angle if base.x_axis.cross(projected).angle(base.tail_local - base.head_local) < 1 else angle


def attach_child_of(prop, rig, bone_name):
    """Child Of to a bone, with the inverse set by hand (the operator needs context headless)."""
    constraint = prop.constraints.new("CHILD_OF")
    constraint.target, constraint.subtarget = rig, bone_name
    constraint.inverse_matrix = (rig.matrix_world @ rig.pose.bones[bone_name].matrix).inverted()
    return constraint


def release_prop(prop, constraint, frame):
    """Let go of `prop` at `frame`: it keeps its world transform and stops following the bone."""
    scene = bpy.context.scene
    basis = prop.matrix_basis.copy()
    scene.frame_set(frame)
    released = prop.matrix_world.copy()
    constraint.influence = 1.0
    constraint.keyframe_insert("influence", frame=frame - 1)
    constraint.influence = 0.0
    constraint.keyframe_insert("influence", frame=frame)
    prop.matrix_basis = basis
    for prop_path in ("location", "rotation_euler", "scale"):
        prop.keyframe_insert(prop_path, frame=frame - 1)
    prop.matrix_world = released
    for prop_path in ("location", "rotation_euler", "scale"):
        prop.keyframe_insert(prop_path, frame=frame)
    bag = channelbag(prop.animation_data.action, prop.animation_data.action_slot)
    for fc in bag.fcurves:
        for key in fc.keyframe_points:
            key.interpolation = "CONSTANT"


# --------------------------------------------------------------------------- poses

def save_pose_json(rig, path):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({pb.name: {"q": list(pb.rotation_quaternion), "loc": list(pb.location),
                             "scl": list(pb.scale)} for pb in rig.pose.bones}, fh, indent=1)


def load_pose_json(rig, path, frame=None):
    """Apply a saved pose; key it at `frame` when given. Poses only suit rigs with the same rest."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    for name, values in data.items():
        pb = rig.pose.bones.get(name)
        if pb is None:
            continue
        pb.rotation_mode = "QUATERNION"
        pb.rotation_quaternion, pb.location, pb.scale = values["q"], values["loc"], values["scl"]
        if frame is not None:
            for prop_path in ("rotation_quaternion", "location", "scale"):
                pb.keyframe_insert(prop_path, frame=frame, group=name)


# --------------------------------------------------------------------------- checks

def world_mesh(obj):
    """Evaluated (skinned) vertices in world space and triangle indices, as numpy arrays."""
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    co = np.empty(len(mesh.vertices) * 3)
    mesh.vertices.foreach_get("co", co)
    world = np.array(evaluated.matrix_world)
    co = co.reshape(-1, 3) @ world[:3, :3].T + world[:3, 3]
    mesh.calc_loop_triangles()
    tris = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("vertices", tris)
    evaluated.to_mesh_clear()
    return co, tris.reshape(-1, 3)


def overlap_pairs(obj_a, obj_b):
    """Intersecting triangle pairs between two objects in world space.

    BVHTree.FromObject works in object-local space, so build world-space trees like this.
    Objects that share a seam (arms and body) overlap even at rest: compare against a rest baseline.
    """
    (ca, ta), (cb, tb) = world_mesh(obj_a), world_mesh(obj_b)
    tree_a = BVHTree.FromPolygons(ca.tolist(), ta.tolist(), all_triangles=True)
    tree_b = BVHTree.FromPolygons(cb.tolist(), tb.tolist(), all_triangles=True)
    return len(tree_a.overlap(tree_b))


def stance_drift(rig, bone, frames, tol=0.01):
    """Per stance (bone within `tol` m of its lowest height): (first, last, drift m, speed m/s)."""
    scene = bpy.context.scene
    fps = scene.render.fps / scene.render.fps_base
    points = []
    for f in frames:
        scene.frame_set(f)
        points.append(rig.matrix_world @ rig.pose.bones[bone].head)
    floor = min(p.z for p in points)
    stances, run = [], []
    for i, p in enumerate(points + [None]):
        if p is not None and p.z <= floor + tol:
            run.append(i)
        elif run:
            drift = (points[run[-1]].xy - points[run[0]].xy).length
            stances.append((frames[run[0]], frames[run[-1]], drift, drift / max(1, len(run) - 1) * fps))
            run = []
    return stances


def joint_angle(rig, a, b, c):
    """Bend at bone `b` between a->b and b->c, in degrees; 0 means straight."""
    bones = rig.pose.bones
    return math.degrees((bones[b].head - bones[a].head).angle(bones[c].head - bones[b].head))


# --------------------------------------------------------------------------- review images

def contact_sheet(paths, cols, out_path):
    """Tile rendered PNGs into one sheet with bpy + numpy (Pillow is not bundled with Blender)."""
    images = [bpy.data.images.load(p, check_existing=False) for p in paths]
    w, h = images[0].size
    rows = -(-len(images) // cols)
    sheet = np.zeros((rows * h, cols * w, 4), dtype=np.float32)
    for i, image in enumerate(images):
        pixels = np.empty(w * h * 4, dtype=np.float32)
        image.pixels.foreach_get(pixels)
        r, c = divmod(i, cols)
        sheet[(rows - 1 - r) * h:(rows - r) * h, c * w:(c + 1) * w] = pixels.reshape(h, w, 4)
        bpy.data.images.remove(image)
    out = bpy.data.images.new("contact_sheet", cols * w, rows * h, alpha=True)
    out.pixels.foreach_set(sheet.ravel())
    out.filepath_raw, out.file_format = out_path, "PNG"
    out.save()
    bpy.data.images.remove(out)


# --------------------------------------------------------------------------- secondary motion

def spring_chain_keys(rig, chain, frames, stiffness=200.0, damping=20.0, substeps=4):
    """Damped-spring lag for a parent-first bone chain; returns keys for replace_keys().

    The first bone's parent must not be in the chain. Each bone's tail chases its animated
    position, so the chain lags, overshoots and settles.
    """
    scene = bpy.context.scene
    h = scene.render.fps_base / scene.render.fps / substeps
    bones = rig.data.bones
    rest_in_parent = {n: bones[n].parent.matrix_local.inverted() @ bones[n].matrix_local for n in chain}
    state, keys = {}, {}
    for f in frames:
        scene.frame_set(f)
        simulated = {}
        for n in chain:
            parent = simulated.get(bones[n].parent.name, rig.pose.bones[bones[n].parent.name].matrix)
            animated = parent @ rest_in_parent[n] @ rig.pose.bones[n].matrix_basis
            head, target = animated.translation, animated @ Vector((0, bones[n].length, 0))
            p, v = state.get(n, (target.copy(), Vector()))
            for _ in range(substeps):
                v += (stiffness * (target - p) - damping * v) * h
                p += v * h
            p = head + (p - head).normalized() * bones[n].length
            state[n] = (p, v)
            swing = (target - head).rotation_difference(p - head)
            simulated[n] = Matrix.Translation(head) @ swing.to_matrix().to_4x4() @ animated.to_3x3().to_4x4()
            q = ((parent @ rest_in_parent[n]).inverted() @ simulated[n]).to_quaternion()
            for i in range(4):
                keys.setdefault((f'pose.bones["{n}"].rotation_quaternion', i), []).extend((f, q[i]))
    return keys
