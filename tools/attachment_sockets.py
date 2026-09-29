"""Named, bone-local attachment frames for derived character assets.

Every body socket is stored relative to a *pose bone*, never as a guessed
world-space shift from a joint head. Every prop socket is in prop object space.
Aligning the two frames is then independent of character facing or animation.
This module adds no deform bones and never changes mesh or skin weights.
"""

import json
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector


def load_manifest(path):
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["units"] == "meters"
    assert manifest["quaternion_order"] == "wxyz"
    assert manifest["body_sockets"] and manifest["prop_sockets"]
    for entry in (*manifest["body_sockets"].values(), *manifest["prop_sockets"].values()):
        assert len(entry["translation_m"]) == 3
        assert len(entry["rotation_wxyz"]) == 4
        assert abs(sum(x * x for x in entry["rotation_wxyz"]) - 1) < 1e-3
    return manifest


def local_matrix(entry):
    translation = Vector(entry["translation_m"])
    rotation = Quaternion(entry["rotation_wxyz"])
    rotation.normalize()
    return Matrix.Translation(translation) @ rotation.to_matrix().to_4x4()


def body_socket_world(rig, bone_name, entry):
    """World transform of a socket authored in the animated bone's frame."""
    return rig.matrix_world @ rig.pose.bones[bone_name].matrix @ local_matrix(entry)


def prop_socket_world(prop, entry):
    return prop.matrix_world @ local_matrix(entry)


def align_prop(rig, bone_name, body_entry, prop, prop_entry):
    """Move the entire prop so its named grip frame matches the body frame."""
    target = body_socket_world(rig, bone_name, body_entry)
    prop.matrix_world = target @ local_matrix(prop_entry).inverted()
    bpy.context.view_layer.update()
    return target


def align_by_names(rig, prop, attachment_manifest, anatomy_manifest,
                   body_socket_name, prop_socket_name):
    """Bone-parent a new prop and align its named grip to the body socket."""
    body = attachment_manifest["body_sockets"][body_socket_name]
    prop_socket = attachment_manifest["prop_sockets"][prop_socket_name]
    assert prop.name == prop_socket["object"], (prop.name, prop_socket["object"])
    bone_name = anatomy_manifest["roles"][body["bone_role"]]["bone"]
    if prop.parent is None:
        prop.parent = rig
        prop.parent_type = "BONE"
        prop.parent_bone = bone_name
    else:
        assert prop.parent == rig and prop.parent_type == "BONE" and prop.parent_bone == bone_name, (
            prop.name, "Already parented outside the requested body socket's bone")
    return align_prop(rig, bone_name, body, prop, prop_socket)


def add_body_marker(collection, name, rig, bone_name, entry):
    """Visible-in-editor, render-hidden cue for humans and LLM scene probes."""
    marker = bpy.data.objects.new(name, None)
    collection.objects.link(marker)
    marker.empty_display_type = "ARROWS"
    marker.empty_display_size = 0.065
    marker.hide_render = True
    marker.parent = rig
    marker.parent_type = "BONE"
    marker.parent_bone = bone_name
    marker.matrix_world = body_socket_world(rig, bone_name, entry)
    marker["attachment_kind"] = "body_socket"
    marker["semantic_name"] = name
    marker["anatomy_bone"] = bone_name
    marker["description"] = entry["description"]
    bpy.context.view_layer.update()
    return marker


def add_prop_marker(collection, name, prop, entry):
    marker = bpy.data.objects.new(name, None)
    collection.objects.link(marker)
    marker.empty_display_type = "ARROWS"
    marker.empty_display_size = 0.065
    marker.hide_render = True
    marker.parent = prop
    marker.matrix_world = prop_socket_world(prop, entry)
    marker["attachment_kind"] = "prop_socket"
    marker["semantic_name"] = name
    marker["description"] = entry["description"]
    bpy.context.view_layer.update()
    return marker


def frame_error(first, second):
    """Return origin separation (m) and orientation difference (degrees)."""
    distance = (first.translation - second.translation).length
    degrees = first.to_quaternion().rotation_difference(second.to_quaternion()).angle * 180 / 3.141592653589793
    return distance, degrees
