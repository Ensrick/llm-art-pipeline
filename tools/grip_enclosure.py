"""Enclosure gate: is a cylindrical shaft actually held IN the hand?

`grip_quality.check_grip` only penalises penetration, so a shaft moved clear of
the hand passes it. This gate adds the positive conditions of a power grip. It
is measured on the evaluated (skinned, world-space) arm mesh against the prop's
evaluated world mesh, so the rig's non-uniform height scale is included:

    palm contact   palmar palm skin within 3 mm of the shaft surface, no deeper than 2 mm
    finger wrap    index/middle/ring/pinky: proximal or middle phalanx pad within 3 mm
    wrap coverage  angle around the shaft axis where palm or finger skin is within 3 mm
    thumb          wraps the opposite way round the shaft to the fingers, and touches
                   the shaft or the index/middle finger without sinking more than
                   2 mm into that finger
    knuckle row    index-to-pinky knuckle line within 10 degrees of the shaft axis
    overlap        no digit or palm vertex more than 2 mm inside the shaft
    no crossing    the shaft does not pass through palm or wrist, and no finger or
                   thumb triangle passes through a palm triangle

Distances are signed: negative means inside the shaft. The Byzantine spear is an
octagonal prism, so its flats sit 1.3 mm inside its 16.5 mm vertex radius; the
real faces are used, not a cylinder. A pass is necessary, never sufficient:
review the close-ups.
"""

from math import atan2, cos, degrees, pi, radians, sin

import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from anim_cookbook import world_mesh

FINGERS = ("index", "middle", "ring", "pinky")
DIGITS = FINGERS + ("thumb",)
PHALANGES = ("proximal", "middle", "distal")

DEFAULT_LIMITS = {
    "palm_contact_max_gap_m": 0.003,
    "finger_contact_max_gap_m": 0.003,
    "min_wrap_coverage_deg": 200.0,
    "thumb_contact_max_gap_m": 0.003,
    "min_thumb_counter_sweep_deg": 45.0,
    "max_knuckle_error_deg": 10.0,
    "max_digit_overlap_m": 0.002,
    "max_palm_overlap_m": 0.002,
    "min_wrist_clearance_m": 0.0,
    "wrist_region_radius_m": 0.035,
}


# --------------------------------------------------------------------------- joint axes from rest geometry

def _hand_frame(wrist, knuckles, side):
    row = (knuckles["pinky"] - knuckles["index"]).normalized()
    centre = sum(knuckles.values(), Vector()) / len(knuckles)
    forward = (centre - wrist).normalized()
    # Right hand: palm normal = forward x (index -> pinky). Mirrored for the left.
    palm = forward.cross(row) if side == "r" else row.cross(forward)
    palm = (palm - row * palm.dot(row)).normalized()
    return {"wrist": wrist, "knuckles": knuckles, "centre": centre,
            "row": row, "forward": forward, "palm": palm}


def hand_rest_frame(rig, side="r"):
    """Armature-space rest wrist, knuckles, knuckle row, forward and palm normal."""
    bones = rig.data.bones
    return _hand_frame(bones[f"hand_{side}"].head_local.copy(),
                       {d: bones[f"{d}_01_{side}"].head_local.copy() for d in FINGERS}, side)


def hand_world_frame(rig, side="r"):
    """The same frame for the current pose, in world space."""
    world = rig.matrix_world
    bones = rig.pose.bones
    return _hand_frame(world @ bones[f"hand_{side}"].head,
                       {d: world @ bones[f"{d}_01_{side}"].head for d in FINGERS}, side)


def _signed_angle(first, second, axis):
    """Angle from `first` to `second` about `axis`, both projected perpendicular to it."""
    a = first - axis * first.dot(axis)
    b = second - axis * second.dot(axis)
    return atan2(a.cross(b).dot(axis), a.dot(b))


def _parent_direction(bones, digit, segment, side):
    """Rest direction a joint's bone would have if the joint were straight."""
    if segment == 1:  # the metacarpal line: wrist joint to this finger's knuckle
        return (bones[f"{digit}_01_{side}"].head_local - bones[f"hand_{side}"].head_local).normalized()
    parent = bones[f"{digit}_{segment - 1:02d}_{side}"]
    return (parent.tail_local - parent.head_local).normalized()


def flexion_axes(rig, arm_mesh, side="r"):
    """Bone-local unit axis per digit joint; a positive rotation about it curls the digit.

    Uses rest geometry only (edit bones and the unposed mesh), and works for a
    straight T-pose rest and for a curled rest such as a standing fist:
    - fingers: the index-to-pinky knuckle row made perpendicular to the bone,
      pointing pinky-to-index for a right hand (the reverse for a left), so a
      positive angle turns the bone toward the palm;
    - thumb: it is pronated relative to the fingers, so the knuckle row does not
      give its plane. Its axis is the width of the distal phalanx (largest
      principal axis of its rest vertices across the bone, i.e. across the
      nail), made perpendicular to each thumb bone. The sign makes a curled rest
      thumb (interphalangeal joint bent more than 15 degrees) read as flexion;
      a straight rest thumb flexes toward the palm centroid.
    A rest pose whose finger middle joints are bent against the palm normal
    raises ValueError: the side is probably wrong.
    """
    bones = rig.data.bones
    frame = hand_rest_frame(rig, side)
    to_armature = rig.matrix_world.inverted() @ arm_mesh.matrix_world
    rest = np.array([tuple(to_armature @ v.co) for v in arm_mesh.data.vertices])
    dominant = dominant_groups(arm_mesh)
    palm_centroid = Vector(rest[dominant == f"hand_{side}"].mean(axis=0))
    distal = bones[f"thumb_03_{side}"]
    d3 = np.array((distal.tail_local - distal.head_local).normalized())
    ids = np.flatnonzero(np.isin(dominant, [f"thumb_03_{side}", f"thumb_04_leaf_{side}"]))
    across = rest[ids] - np.array(distal.head_local)
    across -= np.outer(across @ d3, d3)
    nail_width = Vector(np.linalg.eigh(np.cov(across.T))[1][:, -1])
    handed = -1.0 if side == "r" else 1.0
    axes_armature = {}
    for digit in DIGITS:
        for segment in (1, 2, 3):
            bone = bones[f"{digit}_{segment:02d}_{side}"]
            d = (bone.tail_local - bone.head_local).normalized()
            reference = nail_width if digit == "thumb" else frame["row"] * handed
            axes_armature[bone.name] = (reference - d * reference.dot(d)).normalized()
    thumb_ip = f"thumb_03_{side}"
    ip_curl = degrees(_signed_angle(_parent_direction(bones, "thumb", 3, side),
                                    (distal.tail_local - distal.head_local).normalized(),
                                    axes_armature[thumb_ip]))
    if abs(ip_curl) > 15.0:
        flip = ip_curl < 0
    else:
        thumb_mcp = bones[f"thumb_02_{side}"]
        d2 = (thumb_mcp.tail_local - thumb_mcp.head_local).normalized()
        flip = axes_armature[thumb_mcp.name].cross(d2).dot(palm_centroid - thumb_mcp.head_local) < 0
    for segment in (1, 2, 3):
        if flip:
            axes_armature[f"thumb_{segment:02d}_{side}"].negate()
    for digit in FINGERS:
        name = f"{digit}_02_{side}"
        curl = degrees(_signed_angle(_parent_direction(bones, digit, 2, side),
                                     (bones[name].tail_local - bones[name].head_local).normalized(),
                                     axes_armature[name]))
        if curl < -15.0:
            raise ValueError(f"{name} rests bent {curl:.1f} deg against the palm: wrong side?")
    return {name: (bones[name].matrix_local.to_3x3().inverted() @ axis).normalized()
            for name, axis in axes_armature.items()}


def rest_curl_deg(rig, axes, side="r"):
    """Signed rest bend of each digit joint about its flexion axis, from straight.

    Straight means in line with the parent phalanx, or for a finger's knuckle
    with the wrist-to-knuckle line. thumb_01 has no straight reference and
    reports 0. Setting a joint's flexion to -curl straightens it.
    """
    bones = rig.data.bones
    out = {}
    for digit in DIGITS:
        for segment in (1, 2, 3):
            name = f"{digit}_{segment:02d}_{side}"
            if digit == "thumb" and segment == 1:
                out[name] = 0.0
                continue
            bone = bones[name]
            axis = (bone.matrix_local.to_3x3() @ axes[name]).normalized()
            out[name] = degrees(_signed_angle(_parent_direction(bones, digit, segment, side),
                                              (bone.tail_local - bone.head_local).normalized(), axis))
    return out


def pad_direction_local(axis_local):
    """Bone-local direction of the digit's pad side: where +flexion moves the bone's +Y."""
    return axis_local.cross(Vector((0.0, 1.0, 0.0))).normalized()


# --------------------------------------------------------------------------- mesh and shaft sampling

def dominant_groups(arm_mesh):
    """Name of the strongest deform group of every vertex ('' when unweighted)."""
    names = {g.index: g.name for g in arm_mesh.vertex_groups}
    dominant = []
    for vertex in arm_mesh.data.vertices:
        best = max(vertex.groups, key=lambda g: g.weight, default=None)
        dominant.append(names[best.group] if best is not None and best.weight > 0 else "")
    return np.array(dominant, dtype=object)


def region_indices(dominant, side="r"):
    """Vertex indices per phalanx ((digit, 1..3), leaf helpers count as distal), palm and forearm."""
    regions = {}
    for digit in DIGITS:
        for segment in (1, 2, 3):
            names = [f"{digit}_{segment:02d}_{side}"]
            if segment == 3:
                names.append(f"{digit}_04_leaf_{side}")
            regions[(digit, segment)] = np.flatnonzero(np.isin(dominant, names))
            if not len(regions[(digit, segment)]):
                raise ValueError(f"No vertices dominated by {names[0]}")
    regions["palm"] = np.flatnonzero(dominant == f"hand_{side}")
    regions["forearm"] = np.flatnonzero(dominant == f"lowerarm_{side}")
    return regions


class Shaft:
    """World-space shaft of an evaluated prop around its grip point."""

    def __init__(self, prop, grip_center_local_m=None, axis_local=(0.0, 0.0, 1.0),
                 half_span_m=0.07, angle_step_deg=2.0, height_step_m=0.0025):
        if grip_center_local_m is None:
            height = prop.get("grip_height_from_butt_m")
            if height is None:
                raise ValueError("Supply grip_center_local_m for this prop")
            grip_center_local_m = (0.0, 0.0, float(height))
        world = prop.matrix_world
        local_center = Vector(grip_center_local_m)
        self.center = world @ local_center
        self.axis = (world @ (local_center + Vector(axis_local).normalized()) - self.center).normalized()
        self.half_span = half_span_m
        co, tris = world_mesh(prop)
        self.tree = BVHTree.FromPolygons(co.tolist(), tris.tolist(), all_triangles=True)
        along = (co - np.array(self.center)) @ np.array(self.axis)
        self.evaluated_length_m = float(along.max() - along.min())
        self.e1 = self.axis.orthogonal().normalized()
        self.e2 = self.axis.cross(self.e1)
        radii, outward = [], 0
        for k in range(32):
            angle = 2 * pi * k / 32
            direction = self.e1 * cos(angle) + self.e2 * sin(angle)
            hit = self.tree.ray_cast(self.center, direction, 0.25)
            if hit[0] is None:
                raise ValueError("Grip centre is not inside the prop's shaft")
            radii.append(hit[3])
            outward += 1 if hit[1].dot(direction) > 0 else -1
        self.flat_radius_m = min(radii)
        self.vertex_radius_m = max(radii)
        self.normal_sign = 1.0 if outward > 0 else -1.0
        self.angle_step_deg = angle_step_deg
        self.height_step_m = height_step_m
        self._surface = None

    def set_reference(self, direction):
        """Angle zero points along `direction` (projected perpendicular to the axis)."""
        flat = direction - self.axis * direction.dot(self.axis)
        if flat.length > 1e-9:
            self.e1 = flat.normalized()
            self.e2 = self.axis.cross(self.e1)
            self._surface = None

    def axial(self, points):
        return (np.asarray(points) - np.array(self.center)) @ np.array(self.axis)

    def in_span(self, points):
        return np.abs(self.axial(points)) <= self.half_span

    def signed_distance(self, points):
        out = np.empty(len(points))
        for i, point in enumerate(points):
            p = Vector(point)
            location, normal, _, distance = self.tree.find_nearest(p)
            inside = (p - location).dot(normal) * self.normal_sign < 0
            out[i] = -distance if inside else distance
        return out

    def angle_deg(self, point):
        v = Vector(point) - self.center
        v -= self.axis * v.dot(self.axis)
        return degrees(atan2(v.dot(self.e2), v.dot(self.e1)))

    def surface_samples(self):
        """(angle bin, world point) on the real shaft faces through the whole grip span."""
        if self._surface is None:
            bins = int(round(360 / self.angle_step_deg))
            steps = int(round(2 * self.half_span / self.height_step_m))
            samples = []
            for k in range(bins):
                angle = radians((k + 0.5) * self.angle_step_deg)
                direction = self.e1 * cos(angle) + self.e2 * sin(angle)
                for step in range(steps + 1):
                    origin = self.center + self.axis * (-self.half_span + step * self.height_step_m)
                    hit = self.tree.ray_cast(origin, direction, 0.25)
                    if hit[0] is not None:
                        samples.append((k, hit[0]))
            self._surface = (bins, samples)
        return self._surface


def sweep_deg(shaft, points):
    """Signed angle a joint chain travels around the shaft axis (right-hand rule)."""
    angles = [radians(shaft.angle_deg(p)) for p in points]
    total = 0.0
    for a, b in zip(angles, angles[1:]):
        total += (b - a + pi) % (2 * pi) - pi
    return degrees(total)


def _tree(co, tris, members):
    keep = tris[np.isin(tris, members).all(axis=1)]
    if not len(keep):
        return None, keep
    return BVHTree.FromPolygons(co.tolist(), keep.tolist(), all_triangles=True), keep


def coverage(shaft, skin_tree, band_m, max_depth_m):
    """Covered degrees around the shaft, and the largest uncovered window.

    A surface sample is covered when skin lies within band_m of it and that skin
    point is no deeper than max_depth_m inside the shaft: skin passing through
    the shaft is an overlap failure, not wrap.
    """
    bins, samples = shaft.surface_samples()
    covered = np.zeros(bins, dtype=bool)
    if skin_tree is not None:
        for k, point in samples:
            if covered[k]:
                continue
            location = skin_tree.find_nearest(point, band_m)[0]
            if location is not None and shaft.signed_distance([location])[0] >= -max_depth_m:
                covered[k] = True
    step = 360.0 / bins
    if covered.all():
        return 360.0, 0.0, covered
    run = best = 0
    for value in np.concatenate([covered, covered]):
        run = 0 if value else run + 1
        best = max(best, run)
    return float(covered.sum() * step), float(min(best, bins) * step), covered


def _signed_to_skin(tree, points, normal_sign=1.0):
    out = np.full(len(points), np.inf)
    for i, point in enumerate(points):
        p = Vector(point)
        location, normal, _, distance = tree.find_nearest(p)
        if location is not None:
            out[i] = distance if (p - location).dot(normal) * normal_sign >= 0 else -distance
    return out


def _edge_crossings(co, edges, shaft, depth_m):
    """Edges whose interior runs deeper than depth_m inside the shaft within the span."""
    if not len(edges):
        return 0
    t = np.linspace(0.0, 1.0, 9)
    a, b = co[edges[:, 0]], co[edges[:, 1]]
    points = a[:, None, :] * (1 - t)[None, :, None] + b[:, None, :] * t[None, :, None]
    rel = points - np.array(shaft.center)
    along = rel @ np.array(shaft.axis)
    radial = np.linalg.norm(rel - along[..., None] * np.array(shaft.axis), axis=2)
    hits = (np.abs(along) <= shaft.half_span) & (radial < shaft.flat_radius_m - depth_m)
    return int(hits.any(axis=1).sum())


def _through_palm(co, tris, digit_ids, palm_ids):
    """Digit triangles intersecting palm triangles (pairs sharing a vertex are ignored)."""
    tree_d, keep_d = _tree(co, tris, digit_ids)
    tree_p, keep_p = _tree(co, tris, palm_ids)
    if tree_d is None or tree_p is None:
        return 0
    return sum(1 for i, j in tree_d.overlap(tree_p) if not set(keep_d[i]) & set(keep_p[j]))


def digit_intersections(co, tris, regions):
    """Intersecting triangle pairs between neighbouring digits (reported, not gated)."""
    pairs = (("index", "middle"), ("middle", "ring"), ("ring", "pinky"),
             ("thumb", "index"), ("thumb", "middle"))
    out = {}
    for first, second in pairs:
        ids_a = np.concatenate([regions[(first, s)] for s in (1, 2, 3)])
        ids_b = np.concatenate([regions[(second, s)] for s in (1, 2, 3)])
        out[f"{first}-{second}"] = _through_palm(co, tris, ids_a, ids_b)
    return out


# --------------------------------------------------------------------------- skin strain

STRAIN_REGIONS = {"fingers_and_thumb": ("thumb", "index", "middle", "ring", "pinky"), "palm": ("hand",)}


def strain_edges(arm_mesh, prefixes, side="r", minimum=0.7):
    """Edges whose two vertices both carry more than `minimum` summed weight in the
    named groups: the same selection as hand_grip._maximum_edge_strain."""
    names = {g.index: g.name for g in arm_mesh.vertex_groups}
    selected = {v.index for v in arm_mesh.data.vertices
                if sum(g.weight for g in v.groups if names[g.group].endswith(f"_{side}")
                       and names[g.group].startswith(prefixes)) > minimum}
    return np.array([tuple(e.vertices) for e in arm_mesh.data.edges
                     if e.vertices[0] in selected and e.vertices[1] in selected], dtype=np.int32)


def edge_strain(arm_mesh, before, after, side="r"):
    """|length change| / length between two (N, 3) vertex arrays, per STRAIN_REGIONS.

    Pass mesh-space (armature-space) coordinates to measure skinning alone; world
    coordinates also include the rig's non-uniform object scale.
    """
    dominant = dominant_groups(arm_mesh)
    out = {}
    for label, prefixes in STRAIN_REGIONS.items():
        edges = strain_edges(arm_mesh, prefixes, side)
        length0 = np.linalg.norm(before[edges[:, 0]] - before[edges[:, 1]], axis=1)
        length1 = np.linalg.norm(after[edges[:, 0]] - after[edges[:, 1]], axis=1)
        keep = length0 > 1e-6
        edges, strain = edges[keep], np.abs(length1[keep] / length0[keep] - 1.0)
        worst = np.argsort(strain)[::-1][:5]
        out[label] = {
            "edges": int(len(edges)),
            "max": float(strain.max()),
            "p99": float(np.percentile(strain, 99)),
            "p95": float(np.percentile(strain, 95)),
            "median": float(np.median(strain)),
            "fraction_over_2pct": float((strain > 0.02).mean()),
            "worst_edges": [{"vertices": [int(v) for v in edges[i]], "strain": float(strain[i]),
                             "groups": [str(dominant[v]) for v in edges[i]]} for i in worst],
        }
    return out


# --------------------------------------------------------------------------- the gate

def check_enclosure(rig, arm_mesh, prop, *, side="r", grip_center_local_m=None,
                    shaft_axis_local=(0.0, 0.0, 1.0), grip_half_span_m=0.07, limits=None):
    """Measure a static grip and return every number plus per-criterion verdicts."""
    lim = dict(DEFAULT_LIMITS, **(limits or {}))
    band = lim["finger_contact_max_gap_m"]
    shaft = Shaft(prop, grip_center_local_m, shaft_axis_local, grip_half_span_m)
    co, tris = world_mesh(arm_mesh)
    if len(co) != len(arm_mesh.data.vertices):
        raise ValueError("Topology changed before grip audit")
    regions = region_indices(dominant_groups(arm_mesh), side)
    hand = hand_world_frame(rig, side)
    axes = flexion_axes(rig, arm_mesh, side)
    world3 = rig.matrix_world.to_3x3()
    in_span = shaft.in_span(co)
    sd = np.full(len(co), np.inf)
    near = np.flatnonzero(np.linalg.norm(
        (co - np.array(shaft.center)) - np.outer(shaft.axial(co), np.array(shaft.axis)), axis=1) < 0.12)
    sd[near] = shaft.signed_distance(co[near])

    def min_sd(ids, span_only=True):
        ids = np.asarray(ids)
        if span_only:
            ids = ids[in_span[ids]]
        return float(sd[ids].min()) if len(ids) else float("inf"), ids

    # Palm: hand-dominant vertices on the palmar side of the wrist-knuckle plane.
    palm_ids = regions["palm"]
    palmar = palm_ids[(co[palm_ids] - np.array(hand["centre"])) @ np.array(hand["palm"]) > 0]
    palm_gap, palm_span = min_sd(palmar)
    palm_contact_vertex = int(palm_span[np.argmin(sd[palm_span])]) if len(palm_span) else None
    if palm_contact_vertex is not None:
        shaft.set_reference(Vector(co[palm_contact_vertex]) - shaft.center)
    else:
        shaft.set_reference(-hand["palm"])

    fingers = {}
    for digit in DIGITS:
        entry = {}
        for segment, label in zip((1, 2, 3), PHALANGES):
            bone = rig.pose.bones[f"{digit}_{segment:02d}_{side}"]
            pad = (world3 @ bone.matrix.to_3x3() @ pad_direction_local(axes[bone.name])).normalized()
            ids = regions[(digit, segment)]
            pad_ids = ids[(co[ids] - np.array(rig.matrix_world @ bone.head)) @ np.array(pad) > 0]
            entry[f"{label}_gap_m"] = min_sd(ids)[0]
            entry[f"{label}_pad_gap_m"] = min_sd(pad_ids)[0]
        all_ids = np.concatenate([regions[(digit, s)] for s in (1, 2, 3)])
        entry["overlap_m"] = max(0.0, -min_sd(all_ids)[0])
        bones = rig.pose.bones
        chain = [rig.matrix_world @ bones[f"{digit}_{s:02d}_{side}"].head for s in (1, 2, 3)]
        chain.append(rig.matrix_world @ bones[f"{digit}_03_{side}"].tail)
        entry["sweep_deg"] = sweep_deg(shaft, chain if digit != "thumb" else chain[1:])
        entry["joint_angles_around_shaft_deg"] = [shaft.angle_deg(p) for p in chain]
        fingers[digit] = entry

    finger_ids = np.concatenate([regions[(d, s)] for d in FINGERS for s in (1, 2, 3)])
    grip_skin = np.concatenate([palmar, finger_ids])
    depth = lim["max_digit_overlap_m"]
    skin_tree, _ = _tree(co, tris, grip_skin)
    covered_deg, open_window_deg, covered = coverage(shaft, skin_tree, band, depth)
    thumb_ids = np.concatenate([regions[("thumb", s)] for s in (1, 2, 3)])
    with_thumb_tree, _ = _tree(co, tris, np.concatenate([grip_skin, thumb_ids]))
    with_thumb_deg, with_thumb_window, _ = coverage(shaft, with_thumb_tree, band, depth)
    per_finger = {}
    for digit in FINGERS:
        tree, _ = _tree(co, tris, np.concatenate([regions[(digit, s)] for s in (1, 2, 3)]))
        per_finger[digit] = coverage(shaft, tree, band, depth)[0]

    # Thumb: closes on the shaft or over the index/middle finger, wrapping the other way round.
    thumb_tip_ids = np.concatenate([regions[("thumb", 2)], regions[("thumb", 3)]])
    thumb_shaft_gap = float(sd[thumb_tip_ids].min()) if np.isfinite(sd[thumb_tip_ids]).any() else float("inf")
    over_ids = np.concatenate([regions[(d, s)] for d in ("index", "middle") for s in (2, 3)])
    over_tree, _ = _tree(co, tris, over_ids)
    thumb_finger = _signed_to_skin(over_tree, co[thumb_tip_ids]) if over_tree else np.array([np.inf])
    finger_sweep = sum(fingers[d]["sweep_deg"] for d in FINGERS)
    finger_sign = 1.0 if finger_sweep >= 0 else -1.0
    thumb_counter_sweep = -fingers["thumb"]["sweep_deg"] * finger_sign
    thumb = {
        "shaft_gap_m": thumb_shaft_gap,
        "index_middle_gap_m": float(thumb_finger.min()),
        "counter_sweep_deg": thumb_counter_sweep,
        "finger_sweep_sum_deg": finger_sweep,
    }

    row_error = min(degrees(hand["row"].angle(shaft.axis)), degrees(hand["row"].angle(-shaft.axis)))

    wrist = hand["wrist"]
    near_wrist = palm_ids[np.linalg.norm(co[palm_ids] - np.array(wrist), axis=1) < lim["wrist_region_radius_m"]]
    wrist_ids = np.concatenate([regions["forearm"], near_wrist])
    wrist_gap = min_sd(wrist_ids)[0]
    palm_overlap = max(0.0, -min_sd(palm_ids)[0])
    body_ids = np.concatenate([palm_ids, regions["forearm"]])
    edges = np.array([tuple(e.vertices) for e in arm_mesh.data.edges], dtype=np.int32)
    body_edges = edges[np.isin(edges, body_ids).all(axis=1)]
    crossing_edges = _edge_crossings(co, body_edges, shaft, lim["max_palm_overlap_m"])
    wrist_edges = edges[np.isin(edges, wrist_ids).all(axis=1)]
    wrist_crossing_edges = _edge_crossings(co, wrist_edges, shaft, 0.0)
    digit_outer = np.concatenate([regions[(d, s)] for d in DIGITS for s in (2, 3)])
    digits_through_palm = _through_palm(co, tris, digit_outer, palm_ids)

    criteria = {
        "palm_contact": -lim["max_palm_overlap_m"] <= palm_gap <= lim["palm_contact_max_gap_m"],
        "finger_wrap": all(min(fingers[d]["proximal_pad_gap_m"], fingers[d]["middle_pad_gap_m"])
                           <= lim["finger_contact_max_gap_m"] for d in FINGERS),
        "wrap_coverage": covered_deg >= lim["min_wrap_coverage_deg"],
        "thumb": (min(thumb_shaft_gap, thumb["index_middle_gap_m"]) <= lim["thumb_contact_max_gap_m"]
                  and thumb_counter_sweep >= lim["min_thumb_counter_sweep_deg"]
                  and thumb["index_middle_gap_m"] >= -lim["max_digit_overlap_m"]),
        "knuckle_row": row_error <= lim["max_knuckle_error_deg"],
        "overlap": (all(fingers[d]["overlap_m"] <= lim["max_digit_overlap_m"] for d in DIGITS)
                    and palm_overlap <= lim["max_palm_overlap_m"]),
        "no_crossing": (crossing_edges == 0 and wrist_crossing_edges == 0
                        and wrist_gap >= lim["min_wrist_clearance_m"] and digits_through_palm == 0),
    }
    return {
        "shaft": {
            "grip_center_world": list(shaft.center),
            "axis_world": list(shaft.axis),
            "flat_radius_m": shaft.flat_radius_m,
            "vertex_radius_m": shaft.vertex_radius_m,
            "evaluated_prop_length_m": shaft.evaluated_length_m,
            "axis_from_world_vertical_deg": min(degrees(shaft.axis.angle(Vector((0, 0, 1)))),
                                                degrees(shaft.axis.angle(Vector((0, 0, -1))))),
            "grip_half_span_m": grip_half_span_m,
        },
        "palm": {"palmar_gap_m": palm_gap, "overlap_m": palm_overlap,
                 "contact_vertex": palm_contact_vertex,
                 "palmar_vertices_in_span": int(len(palm_span))},
        "digits": fingers,
        "coverage": {
            "palm_and_fingers_deg": covered_deg,
            "largest_open_window_deg": open_window_deg,
            "with_thumb_deg": with_thumb_deg,
            "with_thumb_largest_open_window_deg": with_thumb_window,
            "per_finger_deg": per_finger,
            "angle_zero": "direction from the shaft axis to the palm contact vertex",
        },
        "thumb": thumb,
        "knuckle_axis_error_deg": row_error,
        "crossing": {
            "wrist_region_min_gap_m": wrist_gap,
            "palm_forearm_edges_deeper_than_overlap_limit": crossing_edges,
            "wrist_region_edges_inside_shaft": wrist_crossing_edges,
            "outer_phalanx_triangles_through_palm": digits_through_palm,
            "digit_digit_triangle_intersections_info": digit_intersections(co, tris, regions),
        },
        "limits": lim,
        "criteria": criteria,
        "passes_enclosure_gate": all(criteria.values()),
        "numeric_limitations": (
            "Vertex, edge and surface-sample measurements on the evaluated mesh; the skin "
            "classification uses dominant skin weights. A pass does not prove a natural grasp."
        ),
    }


def summary_lines(report):
    """Short human-readable digest of check_enclosure's result."""
    mm = lambda v: f"{v * 1000:.2f} mm" if np.isfinite(v) else "none"  # noqa: E731
    lines = [f"ENCLOSURE {'PASS' if report['passes_enclosure_gate'] else 'FAIL'} "
             + " ".join(f"{k}={'ok' if v else 'FAIL'}" for k, v in report["criteria"].items())]
    lines.append(f"palm gap {mm(report['palm']['palmar_gap_m'])}, palm overlap {mm(report['palm']['overlap_m'])}")
    for digit, entry in report["digits"].items():
        lines.append(f"{digit}: pad gaps P {mm(entry['proximal_pad_gap_m'])} M {mm(entry['middle_pad_gap_m'])} "
                     f"D {mm(entry['distal_pad_gap_m'])}; overlap {mm(entry['overlap_m'])}; "
                     f"sweep {entry['sweep_deg']:.1f} deg")
    c = report["coverage"]
    lines.append(f"coverage {c['palm_and_fingers_deg']:.0f} deg (open window {c['largest_open_window_deg']:.0f}), "
                 f"with thumb {c['with_thumb_deg']:.0f} deg; per finger "
                 + ", ".join(f"{d} {v:.0f}" for d, v in c["per_finger_deg"].items()))
    t = report["thumb"]
    lines.append(f"thumb: shaft gap {mm(t['shaft_gap_m'])}, index/middle gap {mm(t['index_middle_gap_m'])}, "
                 f"counter-sweep {t['counter_sweep_deg']:.1f} deg")
    x = report["crossing"]
    lines.append(f"knuckle row {report['knuckle_axis_error_deg']:.2f} deg; wrist gap {mm(x['wrist_region_min_gap_m'])}; "
                 f"crossing edges {x['palm_forearm_edges_deeper_than_overlap_limit']}/"
                 f"{x['wrist_region_edges_inside_shaft']}; digit-through-palm tris "
                 f"{x['outer_phalanx_triangles_through_palm']}; digit-digit tris (info) "
                 + ", ".join(f"{k} {v}" for k, v in x["digit_digit_triangle_intersections_info"].items()))
    s = report["shaft"]
    lines.append(f"shaft radius flat {mm(s['flat_radius_m'])} vertex {mm(s['vertex_radius_m'])}; "
                 f"prop length {s['evaluated_prop_length_m']:.4f} m; tilt {s['axis_from_world_vertical_deg']:.2f} deg")
    return lines
