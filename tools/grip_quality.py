"""Sampled geometric preflight for a cylindrical hand-held prop.

Only the actual grip-height interval is checked. Finger surface contact is
reported separately from excessive penetration. The numeric result is a
rejection aid, never a watertight collision or secure-wrap proof: vertices,
skin-weight anatomy labels and finite shaft samples can miss intersections.
Review front, palm, back and both side close-ups through each action.
"""

from math import ceil, degrees

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree


def _shaft_frame(prop, grip_center_local_m, shaft_axis_local):
    """World-space center and unit axis of the shaft at the hand."""
    if grip_center_local_m is None:
        # Existing spears carry this property. Other props must name their
        # actual grip point rather than silently using the object origin.
        height = prop.get("grip_height_from_butt_m")
        if height is None:
            raise ValueError("Supply grip_center_local_m for this prop")
        grip_center_local_m = (0, 0, float(height))
    center = prop.matrix_world @ Vector(grip_center_local_m)
    axis = prop.matrix_world.to_3x3() @ Vector(shaft_axis_local)
    if axis.length < 1e-9:
        raise ValueError("shaft_axis_local must be nonzero")
    return center, axis.normalized()


def _sample_region(points, center, axis, radius, half_span,
                   allowed_overlap, contact_band):
    """Classify near-surface contact and deep intrusion in the grip span."""
    radial = []
    count = 0
    for point in points:
        count += 1
        offset = point - center
        along = offset.dot(axis)
        if abs(along) <= half_span:
            radial.append((offset - axis * along).length)
    depths = [radius - distance for distance in radial if distance < radius]
    return {
        "sampled_vertices": count,
        "sampled_vertices_in_grip_span": len(radial),
        "inside_shaft_vertices": len(depths),
        "surface_contact_vertices": sum(abs(distance - radius) <= contact_band
                                        for distance in radial),
        "deep_penetration_vertices": sum(depth > allowed_overlap for depth in depths),
        "deepest_sampled_overlap_m": max(depths, default=0.0),
    }


def knuckle_axis_error_deg(rig, prop, first_bone, last_bone, shaft_axis_local=(0, 0, 1)):
    first = rig.matrix_world @ rig.pose.bones[first_bone].head
    last = rig.matrix_world @ rig.pose.bones[last_bone].head
    row = last - first
    if row.length < 1e-9:
        raise ValueError("Knuckle landmarks coincide")
    _, shaft = _shaft_frame(prop, (0, 0, 0), shaft_axis_local)
    return min(degrees(row.angle(shaft)), degrees(row.angle(-shaft)))


def finger_intrusion(arm_mesh, prop, shaft_radius_m, *, side="r", digits=None,
                     minimum_skin_weight=0.35, grip_center_local_m=None,
                     grip_half_span_m=0.07, shaft_axis_local=(0, 0, 1),
                     allowed_overlap_m=0.002, contact_band_m=0.002):
    """Classify evaluated finger vertices only inside the actual grip span.

    Near-surface vertices may be part of a legitimate wrap. Vertices deeper
    than ``allowed_overlap_m`` are reported as unacceptable penetration, but
    this metric alone cannot prove a secure grasp or absence of face crossing.
    """
    if digits is None:
        digits = ("index", "middle", "ring", "pinky", "thumb")
    if shaft_radius_m <= 0 or grip_half_span_m <= 0:
        raise ValueError("Shaft radius and grip half-span must be positive")
    center, axis = _shaft_frame(prop, grip_center_local_m, shaft_axis_local)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = arm_mesh.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        if len(mesh.vertices) != len(arm_mesh.data.vertices):
            raise ValueError("Topology changed before grip audit")
        world = [evaluated.matrix_world @ v.co for v in mesh.vertices]
        group_names = {g.index: g.name for g in arm_mesh.vertex_groups}
        result = {}
        for digit in digits:
            prefix, suffix = digit + "_", "_" + side
            matching = []
            for vertex in arm_mesh.data.vertices:
                weight = sum(g.weight for g in vertex.groups
                             if group_names[g.group].startswith(prefix)
                             and group_names[g.group].endswith(suffix))
                if weight > minimum_skin_weight:
                    matching.append(vertex.index)
            if not matching:
                raise ValueError(f"No weighted vertices for {digit}_{side}")
            result[digit] = _sample_region(
                (world[index] for index in matching), center, axis,
                shaft_radius_m, grip_half_span_m, allowed_overlap_m,
                contact_band_m,
            )
        return result
    finally:
        evaluated.to_mesh_clear()


def palm_forearm_intrusion(arm_mesh, prop, shaft_radius_m, *, side="r",
                           minimum_skin_weight=0.35, grip_center_local_m=None,
                           grip_half_span_m=0.07, shaft_axis_local=(0, 0, 1),
                           allowed_overlap_m=0.002, contact_band_m=0.002,
                           sample_step_m=0.0025):
    """Check palm and forearm vertices plus nearby evaluated polygon surfaces.

    Faces are selected when at least two corners carry a region's skin weight.
    This avoids counting most wrapped fingertips as palm, but can omit blended
    boundary faces. A finite centerline sampling interval can miss a narrow
    crossing, so a positive gap is still only a preflight result.
    """
    if shaft_radius_m <= 0 or grip_half_span_m <= 0 or sample_step_m <= 0:
        raise ValueError("Shaft radius, grip half-span and step must be positive")
    center, axis = _shaft_frame(prop, grip_center_local_m, shaft_axis_local)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = arm_mesh.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        if len(mesh.vertices) != len(arm_mesh.data.vertices):
            raise ValueError("Topology changed before grip audit")
        world = [evaluated.matrix_world @ v.co for v in mesh.vertices]
        group_names = {g.index: g.name for g in arm_mesh.vertex_groups}
        result = {}
        for label, group_name in (("palm", f"hand_{side}"),
                                  ("forearm", f"lowerarm_{side}")):
            matching = {vertex.index for vertex in arm_mesh.data.vertices
                        if any(group_names[g.group] == group_name and
                               g.weight > minimum_skin_weight
                               for g in vertex.groups)}
            if not matching:
                raise ValueError(f"No weighted vertices for {group_name}")
            entry = _sample_region(
                (world[index] for index in matching), center, axis,
                shaft_radius_m, grip_half_span_m, allowed_overlap_m,
                contact_band_m,
            )
            faces = [tuple(face.vertices) for face in mesh.polygons
                     if sum(index in matching for index in face.vertices) >= 2]
            if not faces:
                raise ValueError(f"No evaluated faces for {group_name}")
            tree = BVHTree.FromPolygons(world, faces)
            steps = ceil(2 * grip_half_span_m / sample_step_m)
            gaps = []
            for step in range(steps + 1):
                along = -grip_half_span_m + 2 * grip_half_span_m * step / steps
                nearest = tree.find_nearest(center + axis * along)
                if nearest is None:
                    raise ValueError(f"No nearest polygon for {group_name}")
                gaps.append(nearest[3] - shaft_radius_m)
            entry["min_sampled_surface_clearance_m"] = min(gaps)
            result[label] = entry
        return result
    finally:
        evaluated.to_mesh_clear()


def check_grip(rig, arm_mesh, prop, shaft_radius_m, *, side="r",
               grip_center_local_m=None, grip_half_span_m=0.07,
               shaft_axis_local=(0, 0, 1), max_knuckle_error_deg=10.0,
               max_finger_overlap_m=0.002, max_palm_overlap_m=0.002,
               min_forearm_clearance_m=0.0):
    """Reject conspicuous failures; numeric pass still requires visual review."""
    first, last = f"index_01_{side}", f"pinky_01_{side}"
    angle = knuckle_axis_error_deg(rig, prop, first, last, shaft_axis_local)
    fingers = finger_intrusion(
        arm_mesh, prop, shaft_radius_m, side=side,
        grip_center_local_m=grip_center_local_m,
        grip_half_span_m=grip_half_span_m,
        shaft_axis_local=shaft_axis_local,
        allowed_overlap_m=max_finger_overlap_m,
    )
    body = palm_forearm_intrusion(
        arm_mesh, prop, shaft_radius_m, side=side,
        grip_center_local_m=grip_center_local_m,
        grip_half_span_m=grip_half_span_m,
        shaft_axis_local=shaft_axis_local,
        allowed_overlap_m=max_palm_overlap_m,
    )
    return {
        "knuckle_axis_error_deg": angle,
        "max_knuckle_error_deg": max_knuckle_error_deg,
        "grip_half_span_m": grip_half_span_m,
        "finger_intrusion": fingers,
        "palm_forearm_intrusion": body,
        "max_allowed_sampled_finger_overlap_m": max_finger_overlap_m,
        "max_allowed_sampled_palm_overlap_m": max_palm_overlap_m,
        "min_required_forearm_clearance_m": min_forearm_clearance_m,
        "passes_numeric_grip_gate": (
            angle <= max_knuckle_error_deg
            and all(info["deep_penetration_vertices"] == 0
                    for info in fingers.values())
            and body["palm"]["deep_penetration_vertices"] == 0
            and body["palm"]["min_sampled_surface_clearance_m"] >= -max_palm_overlap_m
            and body["forearm"]["min_sampled_surface_clearance_m"] >= min_forearm_clearance_m
        ),
        "numeric_limitations": (
            "Vertex and finite centerline samples are not continuous collision proof; "
            "surface contact is not proof of a secure wrap; skin weights and "
            "face selection only approximate anatomy. Review close-ups."
        ),
    }
