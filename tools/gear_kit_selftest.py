"""Self-test for gear_kit.py, attachment_nudge.py and body_charts.py. Writes only to a temp dir.

Placed in art/tools/ next to attachment_sockets.py and anim_cookbook.py, run from the repo root:
  & 'C:\\Program Files\\Blender Foundation\\Blender 4.4\\blender.exe' --background -t 2 --factory-startup
    --python-exit-code 1 --python art/tools/gear_kit_selftest.py
Elsewhere, point GEAR_KIT_ART at the repository's art/ folder. The approved spearman .blend is
opened as input and never saved.
"""

import json
import math
import os
import random
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True
import bpy  # noqa: E402
import numpy as np  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402

HERE = Path(__file__).resolve().parent
ART = Path(os.environ.get("GEAR_KIT_ART", HERE.parent))
for p in (HERE, ART / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
import attachment_nudge as an  # noqa: E402
import attachment_sockets as sockets  # noqa: E402
import body_charts as bc  # noqa: E402
import gear_kit as gk  # noqa: E402

BLEND = ART / "hoplite" / "shared_spearman" / "shared_spearman.blend"
ANATOMY = ART / "hoplite" / "shared_spearman" / "anatomy_map.json"
SAMPLE_SOCKETS = ART / "shared_humanoid" / "candidates" / "attachment_socket_pilot" / "attachment_frames.json"
OUT = Path(tempfile.mkdtemp(prefix="gear_kit_"))
failures = []
T0 = time.time()


def check(label, ok, detail=""):
    print(f"## {label}: {'ok' if ok else 'FAIL'} {detail}".rstrip(), flush=True)
    if not ok:
        failures.append(label)


bpy.ops.wm.open_mainfile(filepath=str(BLEND))
scene = bpy.context.scene
anatomy = json.loads(ANATOMY.read_text(encoding="utf-8"))
rig = bpy.data.objects[anatomy["rig"]]
O = bpy.data.objects
standing = {pb.name: pb.matrix_basis.copy() for pb in rig.pose.bones}
ACTIONS = [(bpy.data.actions[n], last) for n, last in (
    ("Byzantine_Spear_Guard_Idle", 60), ("Byzantine_Walk_Carry", 32), ("Byzantine_Spear_Underarm_Thrust", 36))]
SHORT = [(a, 4) for a, _ in ACTIONS]                                   # first 5 frames of each action
check("rig inherits a non-uniform world scale (the case the kit handles)",
      abs(rig.matrix_world.to_scale().z - 0.9) < 1e-4, f"scale {tuple(round(v, 4) for v in rig.matrix_world.to_scale())}")

# 1. frames under the sheared rig
err = 0.0
random.seed(3)
for _ in range(20):
    world = gk.frame(Vector([random.uniform(-0.3, 0.3) for _ in range(3)]) + Vector((0, 0, 1.2)),
                     Vector([random.uniform(-1, 1) for _ in range(3)]), Vector([random.uniform(-1, 1) for _ in range(3)]))
    local = gk.body_local_from_world(rig, "Head", world)
    back = gk.orthonormal(rig.matrix_world @ rig.pose.bones["Head"].matrix @ local)
    err = max(err, gk.matrix_error(back, world))
check("frame / orthonormal / body_local_from_world", err < 1e-5, f"max matrix error {err:.1e}")

# 2. manifests: the sample socket file plus a generated one, merged
axe, mace = gk.build_axe("Gear_Axe"), gk.build_mace("Gear_Mace")
helmet = O["Byzantine_Fitted_Helmet"]
head = rig.pose.bones["Head"]
seat_world = gk.frame(rig.matrix_world @ (head.matrix @ Vector((0, 0.10, 0))), (0, 0, 1), (0, -1, 0))
shield = O["Byzantine_Left_Forearm_Shield"]
band_co, _ = gk.world_mesh(O["Shield_Leather_Forearm_Band"])
fa, fb = (rig.matrix_world @ rig.pose.bones["lowerarm_l"].head, rig.matrix_world @ rig.pose.bones["lowerarm_l"].tail)
c = Vector(band_co.mean(0))
strap = fa + (fb - fa) * max(0.0, min(1.0, (c - fa).dot(fb - fa) / (fb - fa).length_squared))
shield_rigid = gk.orthonormal(shield.matrix_world)
L_shield = gk.frame(shield_rigid.inverted() @ strap, (0, 0, 1), (0, -1, 0))
back_world = gk.frame(Vector((0.0, 0.33, 1.02)), Matrix.Rotation(math.radians(12), 3, "X") @ Vector((0, 0, 1)),
                      Matrix.Rotation(math.radians(12), 3, "X") @ Vector((0, 1, 0)))
manifest = {"schema_version": 1, "units": "meters", "quaternion_order": "wxyz", "status": "selftest",
            "body_sockets": {
                "head_helmet_seat": {"bone_role": "head", "description": "t",
                                     **gk.frame_entry(gk.body_local_from_world(rig, "Head", seat_world))},
                "left_forearm_shield_strap": {"bone_role": "left_forearm", "description": "t", **gk.frame_entry(
                    gk.body_local_from_world(rig, "lowerarm_l", shield_rigid @ L_shield))},
                "upper_back_shield_sling": {"bone_role": "upper_spine", "description": "t",
                                            **gk.frame_entry(gk.body_local_from_world(rig, "spine_03", back_world))}},
            "prop_sockets": {
                "helmet_seat": {"object": helmet.name, "description": "t",
                                **gk.frame_entry(gk.orthonormal(helmet.matrix_world).inverted() @ seat_world)},
                "shield_strap_center": {"object": shield.name, "description": "t", **gk.frame_entry(L_shield)},
                "axe_haft_grip": {"object": "Gear_Axe", "description": "t", **gk.frame_entry(Matrix.Translation((0, 0, 0.12)))},
                "mace_haft_grip": {"object": "Gear_Mace", "description": "t", **gk.frame_entry(Matrix.Translation((0, 0, 0.10)))}}}
(OUT / "gear_frames.json").write_text(json.dumps(manifest, indent=1))
frames = gk.load_frames([SAMPLE_SOCKETS, OUT / "gear_frames.json"], sockets)
check("load_frames (attachment_sockets' schema, validated by attachment_sockets.load_manifest)",
      "right_palm_shaft_grip" in frames["body_sockets"] and "helmet_seat" in frames["prop_sockets"],
      f"{len(frames['body_sockets'])} body / {len(frames['prop_sockets'])} prop sockets")
zmax = lambda o: max(v.co.z for v in o.data.vertices)  # noqa: E731
check("build_axe / build_mace", abs(zmax(axe) - 0.78) < 1e-4 and abs(zmax(mace) - 0.66) < 1e-4 and
      len(axe.data.materials) == 2, f"axe top {zmax(axe):.3f} m, mace top {zmax(mace):.3f} m")

# 3. items, garment with transferred weights and a Mask hide region
body, legs, arms = O["Male_Peasant_Body"], O["Male_Peasant_Legs"], O["Male_Peasant_Arms"]
t = time.time()
gk.rest_pose(rig, True)
hauberk = gk.shell_garment("Gear_Mail_Hauberk", [body, legs], rig, (0.80, 1.34))
most, worst = gk.transfer_weights(hauberk, [body, legs, arms], "POLYINTERP_NEAREST", 4)
gk.ensure_skinned(hauberk, rig)
trees = gk.FrameTrees()
rest_hits = trees.overlap(hauberk, body) + trees.overlap(hauberk, legs)
covered = gk.covered_vertices(body, hauberk)
gk.create_hide_region(body, "torso_under_hauberk", covered)
gk.rest_pose(rig, False)
check("shell_garment + transfer_weights (limit 4, normalized)", most <= 4 and worst < 1e-5 and rest_hits == 0,
      f"max influences {most}, max |sum-1| {worst:.1e}, rest intersections {rest_hits}, {time.time() - t:.2f} s")
ITEMS = {"schema": gk.ITEMS_SCHEMA, "items": {
    "spear": {"object": "Byzantine_Right_Hand_Spear", "kind": "prop", "prop_socket": "spear_main_grip"},
    "axe": {"object": "Gear_Axe", "kind": "prop", "prop_socket": "axe_haft_grip"},
    "mace": {"object": "Gear_Mace", "kind": "prop", "prop_socket": "mace_haft_grip"},
    "shield": {"object": shield.name, "kind": "prop", "prop_socket": "shield_strap_center",
               "parts": ["Shield_Leather_Forearm_Band", "Shield_Band_lower_Rivet", "Shield_Band_upper_Rivet"],
               "parts_on": ["left_forearm_shield_strap"]},
    "helmet": {"object": helmet.name, "kind": "prop", "prop_socket": "helmet_seat"},
    "quilted_cuirass": {"object": "Byzantine_Quilted_Cuirass", "kind": "skinned"},
    "mail_hauberk": {"object": "Gear_Mail_Hauberk", "kind": "skinned", "hides": ["torso_under_hauberk"]}}}
BASE = {"schema": gk.LOADOUT_SCHEMA, "unit": "selftest", "name": "spearman", "slots": {
    "main_hand": {"item": "spear", "attach": "socket", "socket": "right_palm_shaft_grip"},
    "off_hand": {"item": "shield", "attach": "socket", "socket": "left_forearm_shield_strap"},
    "head": {"item": "helmet", "attach": "socket", "socket": "head_helmet_seat"},
    "torso": {"item": "quilted_cuirass", "attach": "skinned"}, "back": None}}


def variant(**slots):
    lo = json.loads(json.dumps(BASE))
    lo["slots"].update(slots)
    return lo


def verts_world(obj):
    return np.array([tuple(obj.matrix_world @ v.co) for v in obj.data.vertices])


# 4. one-call swaps
spear = O["Byzantine_Right_Hand_Spear"]
t = time.time()
eq = gk.apply_loadout(rig, BASE, ITEMS, frames, anatomy, sockets)
t_apply = time.time() - t
zs = [v.co.z for v in spear.data.vertices]
length = (verts_world(spear)[zs.index(max(zs))] - verts_world(spear)[zs.index(min(zs))])
d, a = sockets.frame_error(sockets.body_socket_world(rig, "hand_r", frames["body_sockets"]["right_palm_shaft_grip"]),
                           sockets.prop_socket_world(spear, frames["prop_sockets"]["spear_main_grip"]))
check("apply_loadout (align_by_names + true size at the standing pose)",
      d < 1e-6 and a < 1e-3 and abs(np.linalg.norm(length) - 2.86) < 2e-4 and spear.parent_bone == "hand_r",
      f"grip {d * 1000:.4f} mm / {a:.4f} deg, spear {np.linalg.norm(length):.4f} m (mesh 2.86), {t_apply * 1000:.0f} ms")
spear_before = verts_world(spear)
band = O["Shield_Leather_Forearm_Band"]
band_before = verts_world(band)
gk.apply_loadout(rig, variant(main_hand={"item": "axe", "attach": "socket", "socket": "right_palm_shaft_grip"},
                              off_hand=None, back={"item": "shield", "attach": "socket",
                                                   "socket": "upper_back_shield_sling"}, head=None), ITEMS, frames,
                 anatomy, sockets)
state_ok = (spear.hide_render and not O["Gear_Axe"].hide_render and helmet.hide_render and band.hide_render
            and shield.parent_bone == "spine_03" and O["Gear_Axe"].parent_bone == "hand_r")
gk.apply_loadout(rig, BASE, ITEMS, frames, anatomy, sockets)
round_trip = max(float(np.abs(verts_world(spear) - spear_before).max()), float(np.abs(verts_world(band) - band_before).max()))
check("swap spear->axe, shield forearm->back, helmet off, and back again",
      state_ok and round_trip < 1e-6, f"visibility/parents ok {state_ok}, round-trip vertex error {round_trip:.1e} m")
full_faces = len(body.data.polygons)
gk.apply_loadout(rig, variant(torso={"item": "mail_hauberk", "attach": "skinned"}), ITEMS, frames, anatomy, sockets)
dg = bpy.context.evaluated_depsgraph_get()
masked = len(body.evaluated_get(dg).to_mesh().polygons)
body.evaluated_get(dg).to_mesh_clear()
cuirass_hidden = O["Byzantine_Quilted_Cuirass"].hide_render and not hauberk.hide_render
gk.apply_loadout(rig, BASE, ITEMS, frames, anatomy, sockets)
dg = bpy.context.evaluated_depsgraph_get()
unmasked = len(body.evaluated_get(dg).to_mesh().polygons)
body.evaluated_get(dg).to_mesh_clear()
check("create_hide_region + armour swap (Mask on with the hauberk, off without)",
      cuirass_hidden and masked < full_faces and unmasked == full_faces,
      f"body faces {full_faces} -> {masked} with hauberk -> {unmasked}")

# 5. validation through (shortened) actions
attached = []
for slot, spec in BASE["slots"].items():
    if spec and ITEMS["items"][spec["item"]]["kind"] == "prop":
        obj = O[ITEMS["items"][spec["item"]]["object"]]
        tm = bpy.data.meshes[obj["gear_true_mesh"]]
        z = [v.co.z for v in tm.vertices]
        entry = frames["body_sockets"][spec["socket"]]
        attached.append((obj, entry, anatomy["roles"][entry["bone_role"]]["bone"],
                         frames["prop_sockets"][ITEMS["items"][spec["item"]]["prop_socket"]], (z.index(min(z)), z.index(max(z)))))
res = gk.validate_loadout(rig, attached, [(spear, arms), (shield, body)], SHORT, frames, anatomy, sockets, standing)
drift = max(v[0] for v in res["drift_mm_deg"].values())
check("validate_loadout", drift < 1e-3 and "Byzantine_Spear_Guard_Idle" in res["pairs"][f"{spear.name}|{arms.name}"],
      f"max drift {drift:.5f} mm over 15 frames, spear length {res['length_m'][spear.name]}")

# 6. nudges: maths round trip, and writeback from a moved marker
worst_m = worst_d = 0.0
local0 = gk.local_matrix(frames["body_sockets"]["right_palm_shaft_grip"])
for _ in range(25):
    n = {k: random.uniform(-4, 4) for k in an.MOVES}
    n.update({k: random.uniform(-15, 15) for k in an.TURNS})
    local1 = an.nudged_local(rig, "hand_r", local0, n)
    back = an.nudge_between(rig, "hand_r", local0, local1)
    worst_m = max(worst_m, max(abs(back[k] - n[k]) for k in an.MOVES))
    worst_d = max(worst_d, max(abs(back[k] - n[k]) for k in an.TURNS))
check("attachment_nudge nudged_local / nudge_between", worst_m < 1e-4 and worst_d < 1e-4,
      f"max recovery error {worst_m:.1e} cm, {worst_d:.1e} deg")
nudges = an.new_nudge_file()
nudges["nudges"]["spear"] = an.zero_nudge("right_palm_shaft_grip", "spear_main_grip")
coll = bpy.data.collections.new("selftest markers")
scene.collection.children.link(coll)
marker = an.attach_with_nudge(sockets, rig, spear, frames, anatomy, nudges, "spear", coll)
pivot = marker.matrix_world.translation.copy()
marker.matrix_world = (Matrix.Translation(pivot + Vector((0.02, -0.015, 0.01))) @ Matrix.Rotation(math.radians(7), 4, "X")
                       @ Matrix.Translation(-pivot) @ marker.matrix_world)
bpy.context.view_layer.update()
dragged = an.bone_local_of(marker, rig)
entry, _ = an.writeback_nudge(rig, frames, anatomy, nudges, "spear", marker)
an.save_nudges(nudges, OUT / "attachment_nudges.json")
reloaded = an.load_nudges(OUT / "attachment_nudges.json")
m2 = an.attach_with_nudge(sockets, rig, spear, frames, anatomy, reloaded, "spear", coll)
e = an.frame_error(an.bone_local_of(m2, rig), dragged)
grip = an.frame_error(sockets.prop_socket_world(spear, frames["prop_sockets"]["spear_main_grip"]),
                      rig.matrix_world @ rig.pose.bones["hand_r"].matrix @ dragged)
check("attachment_nudge writeback -> JSON -> rebuild", e[0] < 1e-6 and e[1] < 1e-3 and grip[0] < 1e-6,
      f"{an.describe(entry)}; rebuilt marker {e[0] * 1000:.4f} mm / {e[1]:.4f} deg, prop grip {grip[0] * 1000:.4f} mm")
gk.apply_loadout(rig, BASE, ITEMS, frames, anatomy, sockets)

# 7. review renders: game camera + contact sheet, and one labelled chart
scene.render.engine = "BLENDER_WORKBENCH"
cam = gk.game_camera()
paths = [gk.render_png(cam, OUT / f"game_{f}.png", (60, 80)) for f in range(2)]
sheet = gk.contact_sheet([[(p, 3) for p in paths]], OUT / "sheet.png", pad=4)
img = bpy.data.images.load(sheet)
check("render_png + contact_sheet (3x nearest neighbour)", tuple(img.size) == (2 * 180 + 3 * 4, 240 + 2 * 4),
      f"sheet {tuple(img.size)}")
labels = bc.collect_labels(rig, anatomy, {"attachment_frames.json": json.loads(SAMPLE_SOCKETS.read_text(encoding="utf-8"))})
anchors, size = bc.render_chart(OUT / "chart_front.png", "front", (0, 1, 0), labels, bc.fit_points_body(step=25), 400,
                                title="selftest", notes=(bc.view_notes(rig, (0, 1, 0)),))
wanted = {r for r, it in anatomy["roles"].items() if it["group"] != "Fingers (protected)"} | set(anatomy["joints"])
got = {k.split("  (")[0] for k in anchors}
check("body_charts.render_chart (roles, joints, sockets labelled)", wanted <= got and (OUT / "chart_front.png").is_file()
      and any(k.startswith("SOCKET right_palm_shaft_grip") for k in anchors), f"{len(anchors)} labels, {size[0]}x{size[1]} px")

print(f"## Blender {bpy.app.version_string}; {time.time() - T0:.1f} s; outputs in {OUT}")
if failures:
    print("## SELFTEST FAILED:", ", ".join(failures))
    sys.exit(1)
print("## SELFTEST PASSED")
