"""Plain-language position adjustment ("nudges") on top of attachment_sockets body sockets.

Blender 4.4, headless-tested by gear_kit_selftest.py. Companion to
tools/attachment_sockets.py; it never edits attachment_frames.json or its schema.

A nudge moves and turns ONE attached item relative to the body socket it uses, in character
terms (character space = the rig's armature space; he faces -Y, HIS right is -X, up is +Z):

    forward_cm        + towards where he faces          - backwards
    right_cm          + towards HIS right               - towards his left
    up_cm             + up                              - down
    tilt_forward_deg  + the item's top tips forward     - tips back
    turn_right_deg    + its front turns to HIS right    - to his left (seen from above: clockwise)
    roll_right_deg    + its top leans to HIS right      - to his left

Rotations turn about the socket point, applied roll, then tilt, then turn. Moves are exact
world centimetres even under the shared rig's Z-only 0.9 height scale; angles are defined in
character space (under that scale a tilt or roll appears up to ~11% larger in world space).
The nudge is interpreted once, at the saved standing pose (no action assigned), and stored as
a bone-local frame, so the adjusted grip follows the animation like the original socket.

Nudge file (next to the frames manifest), e.g. attachment_nudges.json:
{
  "schema": "attachment_nudges/1",
  "frames_manifest": "attachment_frames.json",
  "nudges": {"spear": {"body_socket": "right_palm_shaft_grip", "prop_socket": "spear_main_grip",
                       "forward_cm": 0, "right_cm": 0, "up_cm": 0,
                       "tilt_forward_deg": 0, "turn_right_deg": 0, "roll_right_deg": 0}}
}
"""

import copy
import json
import math
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector

SCHEMA = "attachment_nudges/1"
MOVES = ("forward_cm", "right_cm", "up_cm")
TURNS = ("tilt_forward_deg", "turn_right_deg", "roll_right_deg")
FIELDS = MOVES + TURNS
FORWARD, RIGHT, UP = Vector((0.0, -1.0, 0.0)), Vector((-1.0, 0.0, 0.0)), Vector((0.0, 0.0, 1.0))
AXES = {"forward_cm": FORWARD, "right_cm": RIGHT, "up_cm": UP}


# --------------------------------------------------------------------------- file


def new_nudge_file(frames_manifest_name="attachment_frames.json"):
    return {"schema": SCHEMA, "frames_manifest": frames_manifest_name,
            "axes": "character space: forward = the way he faces, right = HIS right, up; "
                    "cm and degrees; rotations about the socket point, roll then tilt then turn",
            "reference_pose": "saved standing pose (no action assigned)",
            "nudges": {}}


def load_nudges(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    assert data["schema"] == SCHEMA, data.get("schema")
    for item, entry in data["nudges"].items():
        assert entry.get("body_socket"), item
        for key in FIELDS:
            float(entry.get(key, 0.0))
    return data


def save_nudges(data, path):
    Path(path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def zero_nudge(body_socket, prop_socket=None):
    entry = {"body_socket": body_socket}
    if prop_socket:
        entry["prop_socket"] = prop_socket
    entry.update({key: 0.0 for key in FIELDS})
    return entry


WORDS = {"forward_cm": ("forward", "back", "cm"), "right_cm": ("right", "left", "cm"),
         "up_cm": ("up", "down", "cm"), "tilt_forward_deg": ("tilt forward", "tilt back", "deg"),
         "turn_right_deg": ("turn right", "turn left", "deg"), "roll_right_deg": ("roll right", "roll left", "deg")}


def describe(entry, keys=FIELDS):
    """'forward 2.00 cm, tilt forward 5.00 deg' (zero fields omitted)."""
    parts = []
    for key in keys:
        v = float(entry.get(key, 0.0))
        if abs(v) >= 0.005:
            pos, neg, unit = WORDS[key]
            parts.append(f"{pos if v > 0 else neg} {abs(v):.2f} {unit}")
    return ", ".join(parts) or ("no nudge" if keys == FIELDS else "-")


# --------------------------------------------------------------------------- maths


def local_matrix(entry):
    """Same convention as attachment_sockets.local_matrix (translation_m + rotation_wxyz)."""
    q = Quaternion(entry["rotation_wxyz"])
    q.normalize()
    return Matrix.Translation(Vector(entry["translation_m"])) @ q.to_matrix().to_4x4()


def frame_entry(matrix, digits=9):
    q = matrix.to_quaternion().normalized()
    return {"translation_m": [round(float(x), digits) for x in matrix.translation],
            "rotation_wxyz": [round(float(x), digits) for x in q]}


def rotation(entry):
    """Character-space 3x3 rotation of a nudge: turn @ tilt @ roll."""
    roll = Matrix.Rotation(math.radians(float(entry.get("roll_right_deg", 0.0))), 3, FORWARD)
    tilt = Matrix.Rotation(math.radians(float(entry.get("tilt_forward_deg", 0.0))), 3, -RIGHT)
    turn = Matrix.Rotation(math.radians(float(entry.get("turn_right_deg", 0.0))), 3, -UP)
    return turn @ tilt @ roll


def displacement(rig, entry):
    """Armature-space move that is exactly entry's centimetres in WORLD space."""
    scale = rig.matrix_world.to_3x3()
    d = Vector()
    for key, axis in AXES.items():
        d += axis * (float(entry.get(key, 0.0)) / 100.0) / (scale @ axis).length
    return d


def reference_pose_matrix(rig, bone_name):
    """Pose matrix of `bone_name` at the reference (saved standing) pose."""
    ad = rig.animation_data
    if ad is not None and ad.action is not None:
        raise RuntimeError("Nudges are defined at the saved standing pose: clear the rig's action first")
    return rig.pose.bones[bone_name].matrix.copy()


def nudged_local(rig, bone_name, local, entry):
    """Bone-local frame of a socket after applying a nudge (orthonormal, pose-independent)."""
    pose = reference_pose_matrix(rig, bone_name)
    before = pose @ local
    pivot = before.translation.copy()
    after = (Matrix.Translation(pivot + displacement(rig, entry)) @ rotation(entry).to_4x4()
             @ Matrix.Translation(-pivot) @ before)
    return pose.inverted() @ after


def nudge_between(rig, bone_name, local_before, local_after):
    """Inverse of nudged_local: the nudge fields that turn one bone-local frame into another."""
    pose = reference_pose_matrix(rig, bone_name)
    before, after = pose @ local_before, pose @ local_after
    delta = after @ before.inverted()
    rot = delta.to_3x3().to_quaternion().to_matrix()
    pivot = before.translation
    move = delta.translation + rot @ pivot - pivot
    e = rot.to_euler("YXZ")          # rot = Rz(z) @ Rx(x) @ Ry(y)
    scale = rig.matrix_world.to_3x3()
    out = {key: move.dot(axis) * (scale @ axis).length * 100.0 for key, axis in AXES.items()}
    out.update({"tilt_forward_deg": math.degrees(e.x), "roll_right_deg": -math.degrees(e.y),
                "turn_right_deg": -math.degrees(e.z)})
    return out


def bone_local_of(obj, rig):
    """Frame of a BONE-parented object relative to its parent bone's HEAD frame.

    A bone-parented child sits on the bone's TAIL (object.cc ob_parbone), so the head-relative
    frame is Translation(0, length, 0) @ parent_inverse @ matrix_basis. Independent of the frame
    shown when the file was saved. Scale is dropped (only position and orientation count).
    """
    assert obj.parent is rig and obj.parent_type == "BONE", (obj.name, obj.parent, obj.parent_type)
    length = rig.data.bones[obj.parent_bone].length
    m = Matrix.Translation((0.0, length, 0.0)) @ obj.matrix_parent_inverse @ obj.matrix_basis
    return Matrix.LocRotScale(m.translation, m.to_quaternion().normalized(), None)


def prop_grip_local(prop, rig, bone_name, prop_entry):
    """Bone-local frame of a prop's grip socket, from its WORLD grip point and axes at the
    reference pose. Uses the prop's full world matrix, so any scale Blender stored while the
    author rotated it (a child of the Z-scaled rig cannot hold a pure world rotation) still
    places the grip point where the author saw it."""
    grip_world = prop.matrix_world @ local_matrix(prop_entry)
    m = (rig.matrix_world @ reference_pose_matrix(rig, bone_name)).inverted() @ grip_world
    return Matrix.LocRotScale(m.translation, m.to_quaternion().normalized(), None)


def frame_error(a, b):
    """(origin distance m, orientation angle deg) between two frames (scale/shear ignored)."""
    qa = a.to_quaternion().normalized()
    qb = b.to_quaternion().normalized()
    return (a.translation - b.translation).length, math.degrees(qa.rotation_difference(qb).angle)


# --------------------------------------------------------------------------- builder side


def nudged_manifest(manifest, anatomy, rig, nudges, item_id):
    """Copy of `manifest` whose body socket for `item_id` carries the nudge (attachment_sockets' schema).

    The copy is in memory only; attachment_frames.json on disk is untouched.
    Returns (manifest copy, body socket name, prop socket name).
    """
    entry = nudges["nudges"][item_id]
    body_name = entry["body_socket"]
    out = copy.deepcopy(manifest)
    body = out["body_sockets"][body_name]
    bone = anatomy["roles"][body["bone_role"]]["bone"]
    body.update(frame_entry(nudged_local(rig, bone, local_matrix(body), entry)))
    body["nudge"] = {k: entry.get(k, 0.0) for k in FIELDS}
    return out, body_name, entry.get("prop_socket")


def attach_with_nudge(sockets_module, rig, prop, manifest, anatomy, nudges, item_id, marker_collection=None):
    """Attach `prop` with attachment_sockets.align_by_names on the nudged socket; optionally add an
    editor-visible SOCKET marker the author can drag (see writeback_nudge). Returns the marker."""
    frames, body_name, prop_name = nudged_manifest(manifest, anatomy, rig, nudges, item_id)
    sockets_module.align_by_names(rig, prop, frames, anatomy, body_name, prop_name)
    prop["nudge_item"] = item_id
    marker = None
    if marker_collection is not None:
        bone = anatomy["roles"][frames["body_sockets"][body_name]["bone_role"]]["bone"]
        marker = sockets_module.add_body_marker(marker_collection, f"SOCKET.{item_id}@{body_name}", rig, bone,
                                                frames["body_sockets"][body_name])
        marker["nudge_item"] = item_id
        marker["nudge_body_socket"] = body_name
    return marker


def writeback_nudge(rig, manifest, anatomy, nudges, item_id, source):
    """Author moved the SOCKET marker (or the prop) in Blender and saved: compute the nudge that
    reproduces it and store it in `nudges` (in memory; call save_nudges). `source` is the moved
    marker Empty or the prop object. Returns (new entry, new bone-local frame)."""
    entry = nudges["nudges"][item_id]
    body = manifest["body_sockets"][entry["body_socket"]]
    bone = anatomy["roles"][body["bone_role"]]["bone"]
    if source.get("attachment_kind") == "body_socket" or source.type == "EMPTY":
        local_after = bone_local_of(source, rig)
    else:
        local_after = prop_grip_local(source, rig, bone, manifest["prop_sockets"][entry["prop_socket"]])
    fields = nudge_between(rig, bone, local_matrix(body), local_after)
    entry.update({k: round(v, 6) for k, v in fields.items()})
    return entry, local_after
