"""Self-test for anim_cookbook.py. Writes nothing into the repository.

Run from the repository root:
  & 'C:\\Program Files\\Blender Foundation\\Blender 4.4\\blender.exe' --background -t 2 --factory-startup --python-exit-code 1 --python art/tools/anim_cookbook_selftest.py
"""

import math
import os
import random
import sys
import tempfile
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import anim_cookbook as ac  # noqa: E402

ASSETS = Path(os.environ.get("ANIM_COOKBOOK_ASSETS", HERE.parent / "shared_humanoid" / "assets"))
OUT = Path(tempfile.mkdtemp(prefix="anim_cookbook_"))
FRAMES = range(0, 33)
failures = []


def check(label, ok, detail=""):
    print(f"## {label}: {'ok' if ok else 'FAIL'} {detail}".rstrip())
    if not ok:
        failures.append(label)


def import_rig(path, name):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    new = [o for o in bpy.data.objects if o not in before]
    for o in new:
        if o.type == "MESH" and o.name.startswith("Icosphere"):
            bpy.data.objects.remove(o, do_unlink=True)
    rig = next(o for o in new if o.type == "ARMATURE")
    rig.name = name
    return rig


bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
src = import_rig(ASSETS / "UAL1_Standard.glb", "SRC")
for o in bpy.data.objects:
    if o.type == "MESH" and o.parent == src:
        o.hide_render = True
walk = bpy.data.actions["Walk_Loop"]
ac.play(src, walk)
tgt = import_rig(ASSETS / "Male_Peasant.gltf", "Shared_Humanoid_CC0_Rig")

# 1. Retarget: world-space delta with rest alignment vs. copying local rotations.
aligned = ac.retarget_action(src, tgt, FRAMES, "Walk_Aligned")
single, worst = ac.joint_direction_error(src, tgt, FRAMES)
check("retarget_action (aligned)", single < 0.01 and worst < 8.0,
      f"single-child {single:.3f} deg, worst {worst:.3f} deg")

local = bpy.data.actions.new("Walk_LocalCopy")
tgt.animation_data.action = local
tgt.animation_data.action_slot = local.slots.new(id_type="OBJECT", name=tgt.name)
for f in FRAMES:
    scene.frame_set(f)
    for name, pb in src.pose.bones.items():
        if name not in tgt.pose.bones:
            continue
        t = tgt.pose.bones[name]
        t.rotation_mode = "QUATERNION"
        t.rotation_quaternion = pb.rotation_quaternion.copy()
        t.keyframe_insert("rotation_quaternion", frame=f)
local_single, local_worst = ac.joint_direction_error(src, tgt, FRAMES)
print(f"## local-rotation copy for comparison: single-child {local_single:.3f} deg, worst {local_worst:.3f} deg")
ac.play(tgt, aligned)

# 2. Layering maths.
random.seed(4)


def rand_q():
    q = Quaternion([random.uniform(-1, 1) for _ in range(4)])
    q.normalize()
    return q


def angle_between(a, b):
    d = math.degrees(a.rotation_difference(b).angle)
    return min(d, 360.0 - d)


worst_layer = 0.0
for _ in range(200):
    posture, ref, donor = rand_q(), rand_q(), rand_q()
    worst_layer = max(worst_layer,
                      angle_between(ac.layered_rotation(ref, ref, donor, 1.0), donor),
                      angle_between(ac.layered_rotation(posture, ref, donor, 0.0), posture))
half = ac.layered_rotation(Quaternion(), Quaternion(), Quaternion((1, 0, 0), math.radians(40)), 0.5)
worst_layer = max(worst_layer, abs(angle_between(half, Quaternion()) - 20.0))
check("layered_rotation", worst_layer < 1e-3, f"worst error {worst_layer:.2e} deg")

# 3. Bake through a constraint control layer.
deform = tgt.copy()
deform.data = tgt.data.copy()
deform.name = "DEF"
scene.collection.objects.link(deform)
deform.animation_data_clear()
for pb in deform.pose.bones:
    c = pb.constraints.new("COPY_TRANSFORMS")
    c.target, c.subtarget = tgt, pb.name
baked = ac.bake_to_action(deform, FRAMES, "Walk_Baked")
error = 0.0
for f in (3, 17, 29):
    scene.frame_set(f)
    for n in ("hand_l", "foot_r", "Head"):
        error = max(error, ((deform.matrix_world @ deform.pose.bones[n].matrix).translation
                            - (tgt.matrix_world @ tgt.pose.bones[n].matrix).translation).length)
left = sum(len(pb.constraints) for pb in deform.pose.bones)
check("bake_to_action", error < 1e-4 and left == 0, f"position error {error:.2e} m, constraints left {left}")

# 4. NLA COMBINE offset on top of a base clip.
ad = src.animation_data
reference = {}
for f in FRAMES:
    scene.frame_set(f)
    reference[f] = src.pose.bones["spine_02"].rotation_quaternion.copy()
ad.action = None
base = ad.nla_tracks.new()
base.name = "Base"
base.strips.new("walk", 0, walk)
q10 = Quaternion((1, 0, 0), math.radians(10))
lean = ac.write_keys("Lean10", src, {('pose.bones["spine_02"].rotation_quaternion', i): [0, q10[i], 32, q10[i]]
                                     for i in range(4)})
ad.action = None
top = ad.nla_tracks.new(prev=base)
strip = top.strips.new("lean", 0, lean)
strip.blend_type = "COMBINE"
strip.influence = 1.0
strip.use_animated_influence = True
for f, v in ((0, 0.0), (9, 0.0), (10, 1.0), (20, 1.0), (21, 0.0)):
    strip.influence = v
    strip.keyframe_insert("influence", frame=f)
offsets = []
for f in (5, 15, 25):
    scene.frame_set(f)
    offsets.append(math.degrees(reference[f].rotation_difference(src.pose.bones["spine_02"].rotation_quaternion).angle))
check("NLA COMBINE layer", abs(offsets[0]) < 1e-3 and abs(offsets[1] - 10) < 1e-3 and abs(offsets[2]) < 1e-3,
      "offsets at frames 5/15/25: " + ", ".join(f"{o:.3f}" for o in offsets))
for track in list(ad.nla_tracks):
    ad.nla_tracks.remove(track)
ac.play(src, walk)

# 5. Pole angle, Child Of attach and release.
bones = tgt.data.bones
pole = math.degrees(ac.pole_angle(bones["thigh_l"], bones["calf_l"], bones["calf_l"].head_local + Vector((0, -0.4, 0))))
check("pole_angle", abs(abs(pole) - 90.0) < 1.0, f"{pole:.2f} deg")
bpy.ops.mesh.primitive_cube_add(size=0.1)
prop = bpy.context.active_object
prop.name = "Prop"
scene.frame_set(0)
prop.matrix_world = tgt.matrix_world @ tgt.pose.bones["hand_r"].matrix @ Matrix.Translation((0, 0.1, 0))
constraint = ac.attach_child_of(prop, tgt, "hand_r")
bpy.context.view_layer.update()
jump = (prop.matrix_world.translation
        - (tgt.matrix_world @ tgt.pose.bones["hand_r"].matrix @ Matrix.Translation((0, 0.1, 0))).translation).length
ac.release_prop(prop, constraint, 20)
scene.frame_set(20)
released = prop.matrix_world.translation.copy()
follow = drift = 0.0
for f in FRAMES:
    scene.frame_set(f)
    hand = tgt.matrix_world @ tgt.pose.bones["hand_r"].matrix @ Matrix.Translation((0, 0.1, 0))
    if f < 20:
        follow = max(follow, (prop.matrix_world.translation - hand.translation).length)
    else:
        drift = max(drift, (prop.matrix_world.translation - released).length)
check("attach_child_of + release_prop", jump < 1e-5 and follow < 1e-5 and drift < 1e-5,
      f"attach jump {jump:.1e} m, follow {follow:.1e} m, drift after release {drift:.1e} m")

# 6. Pose JSON round trip.
scene.frame_set(8)
saved = {pb.name: pb.rotation_quaternion.copy() for pb in tgt.pose.bones}
pose_path = str(OUT / "pose.json")
ac.save_pose_json(tgt, pose_path)
tgt.animation_data.action = None
for pb in tgt.pose.bones:
    pb.rotation_quaternion = (1, 0, 0, 0)
ac.load_pose_json(tgt, pose_path)
pose_error = max(math.degrees(saved[n].rotation_difference(pb.rotation_quaternion).angle) for n, pb in tgt.pose.bones.items())
check("save/load_pose_json", pose_error < 1e-4, f"max error {pose_error:.1e} deg")
ac.play(tgt, aligned)

# 7. Checks: overlap, stance drift, joint angle.
scene.frame_set(5)
pairs = ac.overlap_pairs(bpy.data.objects["Male_Peasant_Arms"], bpy.data.objects["Male_Peasant_Body"])
stances = ac.stance_drift(tgt, "ball_l", FRAMES)
knee = ac.joint_angle(tgt, "thigh_l", "calf_l", "foot_l")
check("overlap_pairs / stance_drift / joint_angle", pairs > 0 and len(stances) >= 1 and 0 < knee < 150,
      f"arm/body pairs {pairs} (seams overlap at rest too), stances {[(a, b, round(d, 3)) for a, b, d, _ in stances]}, knee {knee:.1f} deg")

# 8. Render four frames and tile them.
cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
scene.collection.objects.link(cam)
cam.data.type, cam.data.ortho_scale = "ORTHO", 2.2
cam.location = (3.0, -3.0, 2.6)
cam.rotation_euler = (Vector((0, 0, 0.85)) - cam.location).to_track_quat("-Z", "Y").to_euler()
scene.camera = cam
deform.hide_render = True
prop.hide_render = True
render = scene.render
render.engine = "BLENDER_WORKBENCH"
render.resolution_x = render.resolution_y = 64
render.film_transparent = True
render.image_settings.file_format, render.image_settings.color_mode = "PNG", "RGBA"
scene.view_settings.view_transform = "Standard"
scene.frame_start, scene.frame_end = 0, 3
render.filepath = str(OUT / "frame_")
bpy.ops.render.render(animation=True)
paths = [render.frame_path(frame=f) for f in range(0, 4)]
sheet_path = str(OUT / "sheet.png")
ac.contact_sheet(paths, 2, sheet_path)
sheet = bpy.data.images.load(sheet_path)
check("contact_sheet", tuple(sheet.size) == (128, 128), f"sheet {tuple(sheet.size)}")

# 9. Spring chain written back with replace_keys.
arm = bpy.data.armatures.new("ChainData")
chain_rig = bpy.data.objects.new("Chain", arm)
scene.collection.objects.link(chain_rig)
bpy.context.view_layer.objects.active = chain_rig
bpy.ops.object.mode_set(mode="EDIT")
previous = arm.edit_bones.new("base")
previous.head, previous.tail = (0, 0, 0), (0, 0, 0.2)
for i in range(5):
    eb = arm.edit_bones.new(f"c{i}")
    eb.head, eb.tail = (0, 0, 0.2 + 0.2 * i), (0, 0, 0.4 + 0.2 * i)
    eb.parent, eb.use_connect = previous, True
    previous = eb
bpy.ops.object.mode_set(mode="OBJECT")
base_bone = chain_rig.pose.bones["base"]
for f, x in ((1, 0.0), (10, 0.6), (20, 0.0)):
    base_bone.location.x = x
    base_bone.keyframe_insert("location", frame=f)
chain_rig.pose.bones["c2"].keyframe_insert("rotation_quaternion", frame=1)  # replace_keys must overwrite this
keys = ac.spring_chain_keys(chain_rig, [f"c{i}" for i in range(5)], range(1, 49))
ac.replace_keys(chain_rig.animation_data.action, keys, chain_rig.animation_data.action_slot)
lag = []
for f in (10, 20, 48):
    scene.frame_set(f)
    lag.append(round(chain_rig.pose.bones["c4"].tail.x - chain_rig.pose.bones["base"].head.x, 4))
check("spring_chain_keys + replace_keys", lag[0] < -0.1 and lag[1] > 0.1 and abs(lag[2]) < 0.01,
      f"tip lag at frames 10/20/48: {lag}")

print(f"## Blender {bpy.app.version_string}; outputs in {OUT}")
if failures:
    print("## SELFTEST FAILED:", ", ".join(failures))
    sys.exit(1)
print("## SELFTEST PASSED")
