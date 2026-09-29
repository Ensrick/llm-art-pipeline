# Gear and outfit guide for a shared rig

This covers **how** gear is attached, adjusted and swapped on a shared humanoid rig. What a given
unit or character actually wears and carries is design work for your own project. See
[PROCESS.md](PROCESS.md) for the review loop, and [ANIMATION.md](ANIMATION.md) for motion.

This guide covers labelled charts, plain-language position nudges, loadout files for swaps, armour
layering, and authoring conventions for new items.

## 1. Goals and rules

Five rules make gear work go smoothly, keep body parts easy to identify, and make repositioning
and swapping easy:

1. **Attach by named frames, never by offsets.** Every item attaches through a body socket on a
   bone and a matching socket on the item, using `attachment_sockets.align_by_names`. Never use a
   world-space shift measured from a joint - it doesn't survive a pose change.
2. **Adjust by nudges, never by editing coordinates.** A position change is either a nudge in plain
   terms ("up 2 cm, tilt forward 5 degrees") stored in a small JSON file, or a drag of a socket
   marker in Blender that a script writes back. Nobody hand-edits numbers inside a builder script.
3. **A unit is a loadout file.** Slot to item: swapping a weapon or an outfit piece is a one-line
   change, not a script edit.
4. **One vocabulary for the body.** Everyone uses the same anatomy role names (from your project's
   anatomy map), shown on labelled charts (section 2).
5. **Nothing is accepted without its checks** (section 8), judged at both close-up and at the
   scale it will actually be seen at.

## 2. Finding body parts: labelled charts

`tools/body_charts.py` renders your rig with every body part named, from several fixed views (for
example front, back, both sides, three-quarter, your in-engine camera angle, and hand close-ups).

How to read a chart like this:
- Labels read `role (bone)`, for example `right_forearm (lowerarm_r)`.
- Use two colours for the character's right and left (consistently - pick one and keep it), a
  third for the centre line, and say on each chart which side faces the viewer.
- Use distinct marks for different kinds of point: a bone, a joint, a body socket (with axis
  ticks), a prop socket, and a landmark that is deliberately never a grip point (a wrist, for
  example).

Use the role names when asking for changes: *"move the shield 2 cm toward the right_forearm
elbow"*, not *"move it left"* - left/right is ambiguous depending on whose left is meant, but a
named role never is. Regenerate the charts whenever your sockets change.

## 3. How attachment works

### 3.1 Sockets

- **Body socket:** a frame stored relative to an **animated pose bone** - a translation plus a
  rotation, in metres. It follows every action exactly, because it's defined relative to the bone,
  not to the world.
- **Prop socket:** a frame in the prop's own object space, such as a shaft's grip centre measured
  from its butt.
- **Attaching:** `align_by_names` bone-parents the prop and snaps its prop socket onto the body
  socket.

Several attachment mechanisms were compared against these criteria in one such project, tracked
across many frames of idle, walk and a thrust action:

| Mechanism | Follows the animation | Notes |
|---|---|---|
| Plain bone parenting, identity inverse | **No** | Blender puts the child at the bone's **tail**, not its head - this can be tens to hundreds of millimetres off depending on the bone, and worse, a glTF importer's guessed bone tails make the offset arbitrary and inconsistent between rigs |
| Bone parenting with a computed inverse (what `align_by_names` does) | Yes, sub-millimetre | Survives export exactly |
| Socket bones added to the rig | Yes, sub-millimetre | An unkeyed socket bone keeps its last pose when the action changes, which leaks a large error unless every action keys it |
| Child Of constraint | Yes, sub-millimetre | Export commonly freezes a constraint unless it's baked first |
| Armature constraint | Yes, sub-millimetre | Only correct when the owner is also parented to the rig |
| Skinned to the rig | Yes, sub-millimetre | Right for garments, not for rigid props |

**Bone-local sockets plus a computed parenting inverse are the right default.** They follow
exactly, survive export, can be nudged, and add no bones to the rig.

### 3.2 Naming a socket set

Body sockets are named `<side>_<body part>_<function>`; prop sockets are named
`<item>_<function>`. A representative set for a spear-and-shield infantry archetype:

| Body socket | On (role, bone) | Carries |
|---|---|---|
| `right_palm_shaft_grip` | right hand | A spear, mace, axe or similar one-handed shafted item |
| `left_forearm_shield_strap` | left forearm | A strapped shield |
| `head_helmet_seat` | head | A helmet or cap |
| `upper_back_shield_sling` | upper spine | A shield or two-handed weapon slung for travel |
| `left_palm_grip` | left hand | A shield handle, bow, or the off hand on a two-handed weapon |
| `left_hip_scabbard` | pelvis | A sword on a belt or baldric |
| `right_hip_case` | pelvis | An axe case, spare weapon, or quiver |
| `right_shoulder_carry` | right shoulder/upper arm | A weapon resting on the shoulder |
| `saddle_seat` | mount's spine bone | The rider, for a mounted unit ([ANIMATION.md section 6](ANIMATION.md#6-mounted-and-multi-layer-units)) |

The same general pattern shows up in several existing games and engines - see [section
10](#10-how-other-games-do-it).

**Two-handed items** (a braced polearm, a bow at full draw, a raised standard): the main hand
holds the item's main socket. The off hand reaches an `<item>_off_grip` socket on the item itself
by IK (a 2-bone chain with a pole target for the elbow). The item leads and the arms follow
([ANIMATION.md 5.4](ANIMATION.md#54-weapons-shields-and-other-props)).

**Drawn and stowed.** An item can list a stow socket (a sword at the hip, a shield on the back).
Between units or loadouts, stowing is just a loadout change. Inside a single action (sheathing,
dropping a weapon), it's a Child Of switch (`anim_cookbook.attach_child_of` / `release_prop`).

## 4. Adjusting positions: nudges

`tools/attachment_nudge.py` adds a **nudge** per attached item, in plain terms, on top of its body
socket, without touching the socket frame files or schema themselves.

| Field | Plus means | Minus means |
|---|---|---|
| `forward_cm` | toward where the character faces | backward |
| `right_cm` | toward **their** right | toward their left |
| `up_cm` | up | down |
| `tilt_forward_deg` | the item's top tips forward | tips back |
| `turn_right_deg` | its front turns to their right (clockwise from above) | to their left |
| `roll_right_deg` | its top leans to their right | to their left |

Nudges live in a small JSON file next to the frames manifest:

```json
{
  "schema": "attachment_nudges/1",
  "frames_manifest": "attachment_frames.json",
  "nudges": {
    "spear": {"body_socket": "right_palm_shaft_grip", "prop_socket": "spear_main_grip",
              "forward_cm": 0, "right_cm": 0, "up_cm": 2,
              "tilt_forward_deg": 5, "turn_right_deg": 0, "roll_right_deg": 0}
  }
}
```

A nudge is read once, at the standing pose, and stored as a bone-local frame, so the adjusted item
still follows every animation afterward.

**Three ways to adjust:**
1. **Say it:** *"spear up 2 cm, tilt forward 5 degrees"*. Edit the nudge file, rebuild, and send a
   before/after sheet.
2. **Drag it in Blender:**
   - Open the candidate file yourself (an agent should not launch a desktop GUI application on
     your behalf).
   - Select the **socket marker** for the item, move or rotate it, and save.
   - A write-back script converts your drag into the equivalent nudge exactly.
   - Drag the marker, not the item itself - under a non-uniformly scaled rig, rotating the item
     directly loses precision when Blender saves it; the marker doesn't.
3. **Ask for a comparison:** render any candidate nudge both ways, side by side, before keeping it.

## 5. Swapping outfits and weapons: loadouts

`tools/gear_kit.py` builds a unit from two small files:
- **An items registry** (`items.json`): what each item is.
- **A loadout** per unit (`loadout_<name>.json`): which item goes in which slot.

```json
{"schema": "gear_items/1",
 "items": {
   "spear":  {"object": "Right_Hand_Spear", "kind": "prop", "prop_socket": "spear_main_grip"},
   "mace":   {"object": "Gear_Mace", "kind": "prop", "prop_socket": "mace_haft_grip"},
   "shield": {"object": "Left_Forearm_Shield", "kind": "prop", "prop_socket": "shield_strap_center",
              "parts": ["Shield_Leather_Forearm_Band"], "parts_on": ["left_forearm_shield_strap"]},
   "mail_hauberk": {"object": "Gear_Mail_Hauberk", "kind": "skinned", "hides": ["torso_under_hauberk"]}}}
```

```json
{"schema": "gear_loadout/1", "unit": "spearman", "name": "maceman_shield_on_back",
 "frames": ["attachment_frames.json", "gear_frames.json"],
 "slots": {
   "main_hand": {"item": "mace", "attach": "socket", "socket": "right_palm_shaft_grip"},
   "off_hand": null,
   "head": {"item": "helmet", "attach": "socket", "socket": "head_helmet_seat"},
   "torso": {"item": "quilted_cuirass", "attach": "skinned"},
   "back": {"item": "shield", "attach": "socket", "socket": "upper_back_shield_sling"}}}
```

Kinds: `prop` for rigid items on a socket, `skinned` for garments and armour layers. `parts` are
pieces that belong to another socket (for example a shield's own forearm strap); `parts_on` lists
those sockets. `hides` names body regions masked while the item is worn.

**One call builds the unit:** `gk.apply_loadout(rig, loadout, items, frames, anatomy, sockets)`.

**What to check after any loadout change** (measured on a six-loadout pilot in one such project):
- **Speed:** a swap should be fast - each one measured in single-digit milliseconds.
- **Drift:** every prop should stay on its socket within a fraction of a millimetre through every
  frame of every action it's used in.
- **Round trips:** swapping an item out and back, or a socket from one place to another and back,
  should return identical geometry.
- **Intersections:** no worse than an approved baseline for the same pair of meshes.
- **Review sheets:** one per loadout, showing your real camera's frames at true on-screen size
  above a closer view, for at least an idle, a walk and one action.

**A representative slot list** for a small roster:

| Slot | Examples |
|---|---|
| `head` | Helmet, cap |
| `torso` layers, in order | Padded layer, mail, plate/lamellar, over-layer |
| `main_hand` | Spear, mace, axe, sword |
| `off_hand` | Strapped shield, bow, a carried object |
| `back` | Slung shield, case, two-handed weapon |
| `hip_left` / `hip_right` | Sword, axe case, quiver |
| `shoulder` | A resting weapon |
| `mount` | A creature and its tack |

## 6. Building a new item

### 6.1 Rigid items (weapons, shields, helmets, cases)

- **Origin and axes.** Model the item at the world origin with its **origin at the main grip
  centre**. A common convention: +Z along the long axis toward the head/tip, +Y toward the
  striking face, edge, or front. For a helmet: origin at the seat, +Z up, and the face toward the
  direction the character faces.
- **Units:** metres, scale applied, one object per item.
- **Name the grip, not the offset.** Add a prop socket per contact point to the frames manifest,
  rather than encoding an offset from some other reference point.
- **Pick one shaft diameter for your whole roster**, if you can, so one solved grip pose fits
  every shafted item instead of needing a separate grip solve per weapon. This is a modelling
  convenience, not something to derive from real-world reference measurements.
- **Budget for the smallest scale you'll render at.** At very small on-screen sizes a shaft can be
  only 1-2 px wide and a hand only a few pixels across. Keep props simple - a few hundred to about
  1,500 triangles is a reasonable ceiling for something this small on screen. Widen thin parts on
  a **render copy**, never in the approved model ([ANIMATION.md 5.9](ANIMATION.md#59-exporting-to-2d-sprites)).
- **Textures and team colour.** Give each item its own UV layout and texture set at a consistent
  texel density. If part of the item should carry team/variant colour, that's a mask region on the
  item, decided per project.

### 6.2 Skinned items (padded coats, mail, plate, skirts)

1. **Model in the rig's rest pose**, not some other reference pose.
2. **Leave a small gap to the layer below** (roughly a centimetre or two) rather than modelling it
   flush - a real garment worn over another layer isn't perfectly form-fitting either.
3. **Transfer weights from the body**, then limit each vertex to a small number of bones (4 is a
   common cap) and renormalize. In one such project's pilot, nearest-face-interpolated weight
   transfer gave noticeably better results (less stretch, fewer intersections during a walk) than
   nearest-vertex, and comparable results to projected-face; a fully automatic heat-based solve
   gave the least stretch on paper but the most walk intersections by far, and ignored the bone-
   count limit entirely. Test more than one method rather than assuming the "automatic" one wins.
4. **Hide the body underneath with a Mask modifier**, switched on only while the item is worn,
   rather than deleting the covered geometry outright - masking is reversible and keeps the shared
   body mesh untouched; deleting requires re-adding geometry if a future item covers less.
5. **Check it against every action** with the tests in section 8.

**A period-appropriate layer order is a design decision, not a technical one** - but once decided,
document it explicitly (innermost to outermost) so every unit that shares layers agrees on the
order.

## 7. Grips and hands

Fitting a hand around a held shaft is commonly the hardest single fitting problem on a shared
rig, because a library hand mesh is rarely posed with enough free space in its closed fist to
accept a shaft of your chosen diameter without re-posing.

A useful sequence, from a project that hit this problem directly:

| Attempt | Result |
|---|---|
| Placing the grip from the wrist bone's own head, with a fixed offset | The shaft visibly passes through the wrist |
| Aligning the grip to the palm socket alone | The knuckle row ends up rotated well off the shaft's axis, with fingers well inside the shaft on one or more digits |
| Aligning to the knuckles as well | The angle error shrinks a lot, but the shaft ends up sitting outside the actual palm, in front of the fingertips |

**Why this happens:** a borrowed fist mesh is often curled nearly shut, with only a few millimetres
of free radius against a shaft several times that in diameter - it physically cannot hold a shaft
that size without being re-posed first.

**A more reliable approach:**
- Add an **enclosure gate** (`tools/grip_enclosure.py`): the shaft should touch the palm, every
  finger should touch the shaft, the wrap should cover a wide arc with the thumb closing over the
  top, and nothing should sink through anything else. Verify the gate actually rejects the
  attempts above before trusting it to accept anything.
- Solve the grip **by closing each finger until it touches** the shaft, joint by joint, using bone
  rotations only - not by moving the whole hand as a rigid unit.
- If a borrowed hand genuinely can't wrap around your target shaft diameter without visibly
  warping, build a purpose-made grip hand around that exact shaft as a fallback.

**A useful set of grip classes** to define once and reuse: one-handed shaft, two-handed shaft
(braced or swung), a pole held more loosely (a standard/icon), a bow (draw and hold are different
poses), a strapped shield (forearm plus a handle), a centre-grip shield (hand only), and anything
else your roster needs a genuinely distinct hand shape for. Solve each class's hand pose once, and
reuse it for every item in that class.

## 8. Checks for every item and loadout

| Check | Pass condition | Tool |
|---|---|---|
| Grip drift (prop socket vs. body socket) | under a fraction of a millimetre at every keyed and half frame | `gear_kit.validate_loadout`, `attachment_nudge.frame_error` |
| Grip overlap | at most ~2 mm per finger into the shaft; knuckle row within ~10° of the shaft axis | `tools/grip_quality.py` |
| Grip enclosure | palm contact, finger wrap and thumb closure (section 7) | `tools/grip_enclosure.py` |
| Intersections | no worse than an approved baseline for the same pair | `gear_kit.validate_loadout` |
| Ground | props and feet stay above the ground plane | see [ANIMATION.md 5.7](ANIMATION.md#57-automatic-checks) |
| Prop size | a rigid item keeps its authored length in every frame (catches non-uniform-scale stretch - see section 11) | measure the evaluated mesh |
| Skinned layers | worst stretch in line with the body's own garments; bone-count limit respected, weights summing to 1 | `gear_kit.edge_strain`, `gear_kit.influence_stats` |
| Readable at target scale | reads correctly in every facing at true render size | loadout review sheets |

## 9. Researching where gear actually sits, for your own setting

If your project is grounded in a real historical period, region or culture, treat gear placement,
construction and layering as a research question, the same way you'd research a real weapon's
proportions - primary and secondary sources, with the date of each source noted, since practice
changes over time even within one culture. Keep a running list of places where your design
deviates from what the sources say, and treat each one as a decision for the project owner, not a
default the agent resolves on its own. This guide intentionally doesn't include any specific
setting's research results - that's project content, not process.

## 10. How other games do it

Looking at how established engines and games name and structure the same idea is a fast way to
sanity-check your own socket and layering scheme:

- **Unreal:**
  - [Sockets](https://dev.epicgames.com/documentation/en-us/unreal-engine/skeletal-mesh-sockets-in-unreal-engine)
    are named attach points relative to a bone.
  - Epic's Lyra sample's equipment definitions name the actor, its socket (e.g. `weapon_r`) and a
    transform.
  - Modular characters commonly share one skeleton across all variants
    ([docs](https://dev.epicgames.com/documentation/en-us/unreal-engine/working-with-modular-characters-in-unreal-engine)).
- **Skyrim:** a weapon's own file names where it's sheathed (`WeaponBack`, `WeaponSword`,
  `WeaponAxe`, `WeaponMace`, `WeaponBow`, `QUIVER`, `SHIELD`); a drawn weapon goes to a single
  `WEAPON` node in the hand
  ([reference](https://wiki.beyondskyrim.org/wiki/Arcane_University:Nifskope_Weapons_Setup)).
- **Bannerlord:**
  - Named holster points (e.g. `sword_left_hip`, `sword_back`) plus grip-family flags such as
    "hand only" vs. "arm and hand"
    ([docs](https://moddocs.bannerlordmodding.com/asset-management/weapon_smithing/)).
  - Armour pieces carry coverage flags (body/legs/head/hands).
- **0 A.D.** (open source - a good one to read the actual source of): prop points are objects
  named `prop-...` attached to bones; a spearman actor is a body mesh plus props at named points
  like `weapon_R`, `shield_arm` and `helmet`
  ([example actor file](https://github.com/0ad/0ad/blob/master/binaries/data/mods/public/art/actors/units/athenians/infantry_spearman_b.xml)).
- **Roblox:**
  - A fixed attachment list, including `RightGrip` and `LeftGrip`.
  - Grip points are oriented "perpendicular to the lower arm bone ... pointing forward" by
    convention.
  - Layered clothing uses inner and outer fitting shells with an explicit order number per layer
    ([spec](https://create.roblox.com/docs/avatar/character-bodies/specifications)).
- **Quaternius-style CC0 body packs** (a common free rig source): one shared skin across the whole
  pack, outfits split into arms/body/legs/feet pieces with overlapping seam bands, so parts from
  different outfits in the same pack can be freely mixed as long as those bands are respected.

## 11. Known issues and Blender pitfalls

1. **A non-uniform scale anywhere in a rig's parent chain stretches rigid props that follow it.**
   If a rig's visual height is adjusted with a Z-only scale on a parent empty, every rigid prop
   that bone-parents to a rotating bone inherits that squash - a prop can measure correctly at rest
   and still come out visibly too long or short mid-animation. In one measured case a prop's
   resting length was correct but stretched about 10% in a extended pose purely from this cause.
   **Root fix:** bake the non-uniform scale into the rig and meshes directly, so every object ends
   up with a uniform scale. A cheaper stopgap: use a Child Of constraint without inheriting scale.
   This is worth fixing before doing any serious prop-fitting work, since it otherwise silently
   affects every rigid item on the rig.
2. **A borrowed hand mesh may not be able to close around your target grip diameter at all**
   without re-posing (section 7).
3. **Weight-transferred skinned layers can still intersect the body underneath more than the
   original, hand-weighted reference garment does** - budget review time for this rather than
   assuming an automated transfer is a final answer.
4. **A prop that reuses another prop's solved grip orientation** (rather than getting its own) will
   often only face the right way in the one pose that grip was solved for. Give each meaningfully
   different prop shape its own solved grip.

**Blender 4.4 pitfalls hit while building a kit like this:**
- A bone's `matrix_local`, read before an edit-mode round trip, returns garbage afterwards -
  always `.copy()` it first.
- `Object.matrix_local` is stale for an object hidden with `hide_viewport` - use
  `matrix_parent_inverse @ matrix_basis` instead.
- `vertex_group_limit_total` ignores `temp_override` and acts on the real active object regardless.
- Datablock names are cut at 63 characters, and a name longer than that then looks up as `None`.
- `parent_set(ARMATURE_AUTO)` on an object already parented to a scaled rig shifts it - unparent
  first.

## Appendix: files and an example command sequence

| Path | What |
|---|---|
| `tools/attachment_sockets.py` | The socket API (`align_by_names`) |
| `tools/attachment_nudge.py` | Nudges and the drag write-back |
| `tools/gear_kit.py` | Loadouts, true-size props, weight transfer, hide regions, validation, review renders |
| `tools/body_charts.py` | Labelled charts |
| `tools/gear_kit_selftest.py` | Self-test for the three modules above (needs your own sample rig - see the [README](../README.md)) |

Example command sequence (adjust paths to your own project's layout):

```powershell
$blender = 'C:\Program Files\Blender Foundation\Blender 4.4\blender.exe'
$rig = 'path/to/your_rigged_character.blend'
& $blender --background -t 2 --factory-startup --python-exit-code 1 --python tools/gear_kit_selftest.py
& $blender --background -t 2 --factory-startup --python-exit-code 1 $rig --python "your_charts_script.py"
```

Write builders that output to a git-ignored `out/` folder next to themselves, and keep reviewed
copies in a separate `review/` folder - see [.gitignore](../.gitignore) and
[PROCESS.md](PROCESS.md) for why neither of those should reach version control as loose files.
