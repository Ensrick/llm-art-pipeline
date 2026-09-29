# Making sprites look native

This is the concrete scene setup behind "the sprites look like they were built for the game, not
pasted on top of it": one fixed camera, one fixed pair of lights, one colour-management setup for
the beauty render and a different one for the mask, a sheared ground shadow, and a pivot that never
moves. Every number below is a real, working value from a shipped project - see
`examples/sprite_scene.example.json` for the config they live in, and `tools/render_sprites.py` /
`tools/finish_sprites.py` / `tools/pack_atlas.py` for the code that reads them. Re-derive them
against your own reference material rather than copying them blind; what should transfer is the
*method*, and which knobs matter.

This assumes you've read [ANIMATION.md section 5.9](ANIMATION.md#59-exporting-to-2d-sprites) for
the general shape of a 3D-to-2D-sprite pipeline (facings, canvas sizing, why you never shrink the
model). This doc goes one level more concrete: the actual camera, light and colour-management
numbers, and why each one is set the way it is.

## 1. The camera angle, and why

A fixed orthographic camera, at a fixed elevation, that never moves between frames:

- **Elevation:** 30 degrees above the ground, looking from `-Y` (`camera.elevation_deg` /
  `camera.looks_from` in the config). View direction `d = (0, cos(30deg), -sin(30deg))`.
- **Projection:** orthographic, not perspective - a perspective camera would make a tall pose (a
  raised arm, a long weapon) grow or shrink relative to the body depending on how far it reaches
  toward the camera, which reads as the model changing size between poses. Orthographic keeps
  scale constant regardless of depth.
- **Distance:** far enough that near/far clipping never becomes an issue at your rig's scale
  (`camera.distance_m`, 30 m against a roughly 1.75 m figure); orthographic scale doesn't depend on
  distance, so this number isn't otherwise load-bearing.
- **Why 30 degrees specifically:** it's a compromise readable from directly above (a pure top-down
  view loses silhouette and facial/frontal readability) and readable from the side (a 0-degree
  side-on view loses the ground plane and foreshortens overhead motion). Match this angle by eye
  against whatever your project's existing art (or reference game, if you're aiming for visual
  compatibility with one) actually uses - there is nothing universal about 30 degrees beyond that
  it worked for one RTS-style project.

## 2. Scale: pixels per metre

One `px_per_m` for the whole unit, fixed for every action and every frame - never rescaled per
pose. This project's value: **57.37 px/m**, chosen so the rendered figure's height in pixels
matched a specific reference height in an existing, already-scaled sprite set. The method, not the
number:

1. Pick one clear, comparable landmark on your reference material (a helmet top, a head height, a
   standing figure's total height).
2. Render your own rig at a trial `px_per_m` and measure the same landmark in pixels.
3. Solve for the `px_per_m` that makes the two match, and use that value for every sprite the same
   rig produces from then on.

Getting this from a fixed real-world unit (say, "64 px per metre") instead will also work, but
won't visually match an existing sprite set unless that set happens to share your assumption about
how tall a "standard" character is.

## 3. Canvas and pivot

- **Canvas:** fixed per unit (this project: 384x384 px), with a `margin_px` (2 px here) kept clear
  on every side. `render_sprites.py` refuses to render (before spending any render time on the
  beauty/mask passes) if any frame's bounds reach the margin - **enlarge the canvas, never shrink
  the model** (see ANIMATION.md 5.9).
- **Pivot:** the projected position of world point `(0, 0, ground_z)`, identical on every single
  frame. It must land on a *whole* pixel - `Camera` in `render_sprites.py` asserts this at startup
  and raises immediately if the canvas/pivot combination doesn't produce one, since a fractional
  pivot means every frame will jitter by a sub-pixel amount relative to its neighbours once placed
  in-engine.
- **Never recentre per pose.** A pivot that moves to keep the model centred is the single most
  common cause of a sprite set that "jitters" once installed - the model can move freely on the
  fixed canvas from pose to pose; only the pivot's *position on the canvas* must never change.

## 4. Colour management: two different settings for two different passes

- **Beauty pass:** View Transform **Standard**, Look **None**. Blender's default (AgX, in 4.x) is a
  filmic-style transform that compresses highlights and shifts colour relative to how materials are
  authored - fine for a photoreal render, wrong for flat game art where you want the material's
  actual authored colour to reach the final pixel with only the renderer's light transport applied,
  not an extra tone-mapping curve on top.
- **Mask pass:** View Transform **Raw**. The mask isn't a picture for a human to look at; it's data
  (which pixels are team-colour, and whichever other channels you wire up) smuggled through the
  renderer as colour. Raw skips all colour management, so a flat-emission value of exactly `1.0`
  comes out as exactly `255`, not softened by a display transform.
- **Render settings this project used:** Cycles, CPU device, 64 samples, no denoising, 0.75 px
  filter width. Denoising was tried and rejected: at low sample counts it read soft and
  colour-shifted rather than clean. A narrower-than-default filter width (Blender's factory default
  is 1.5 px) keeps small, thin details (a spear shaft, a bowstring) from smearing across more
  pixels than they need to.

## 5. Lighting

Two area lights (disk shape) plus a flat world colour, all fixed for the whole unit:

- **Key light:** offset `(-4.60, -2.60, 4.80)` m from a target point near the figure's chest height
  (`lighting.target_m`), aimed at that target, size 1.60 m, energy 380 W in this project's chosen
  preset.
- **Fill light:** offset `(-0.40, -5.00, 1.40)` m, aimed at the same target, size 4.00 m (bigger and
  softer than the key), energy 220 W.
- **World:** flat colour `(0.3, 0.3, 0.3)`, strength 0.40 - a soft, non-directional ambient term
  that keeps shadow-side faces from going pure black.
- **Why aimed area lights, not a sun:** a sun light has no falloff and no size, so it can't be
  softened by moving it closer/further or made larger; an aimed area light gives you both a
  direction and a softness knob, and "aimed at a fixed target" means you can reposition it in
  offset-from-target terms without recomputing a rotation by hand.
- **Tuning by eye, concretely:** this preset was reached by rendering several candidates (moving
  the key up/down/left/right, trading key energy against fill energy and ambient strength) and
  comparing them side by side at final sprite scale against reference material, the same review
  process as any other visual decision in [PROCESS.md](PROCESS.md). There's no formula for "the
  right" key/fill ratio - only comparison at true scale.
- **Units matter more than you'd expect.** If your rig or a donor asset is authored in different
  units than your scene scale assumes (centimetres vs. metres is the classic case), every position
  and every light's energy needs the matching conversion factor, or the same "identical-looking"
  light rig will produce a completely different result. Sanity-check by comparing a render against
  a known-good reference before trusting a new rig's numbers.

## 6. The ground shadow

A shadow that's actually cast by the posed mesh, not a fixed blob under the feet:

1. Take every rendered mesh except anything in `shadow.exclude_objects` (a held weapon is a common
   exclusion - a real shadow of a thin shaft at this scale is mostly noise).
2. For each vertex at height `z` above the ground, shear its ground-projected position by
   `(shear_x * z, shear_y * z)` - this project's shear is `(0.035, -0.09)`, which reads as a low
   sun coming from one side. This is a cheap approximation of a directional-light shadow: it needs
   no separate shadow-mapped render pass, just arithmetic on the same vertices you already have.
3. Rasterise the union of the sheared, projected triangles at `supersample`x resolution (3x here)
   and downsample with a Lanczos filter, which anti-aliases the shadow's edge without a separate
   blur pass.
4. Composite the result **under** the straight-alpha beauty render, as flat black at
   `alpha`/255 (149/255 here - not fully opaque, so some ground detail could show through if your
   ground texture isn't flat black already).

`render_sprites.py` computes and saves the sheared, projected geometry (a `.shadow.npz` +
`.topology.npy` per distinct mesh topology, to avoid saving the same triangle list once per frame);
`finish_sprites.py` does the actual rasterising and compositing, in plain Pillow, no Blender needed
for that step.

## 7. The team-colour mask

- **In the beauty render**, a team-colour face's base colour is replaced with a flat, neutral grey:
  `grey = neutral_albedo * (face's own texture mean luminance) / (that texture's own mean
  luminance)` - which, since those two terms are almost the same thing, mostly simplifies to "grey
  = neutral_albedo, modulated by whatever light/dark pattern the texture already had". This matters
  because a multiply-based team-colour shader darkens whatever base colour you give it - render the
  "real" intended colour and the engine's tint multiplies it again, going too dark. `neutral_albedo`
  0.70 was chosen so the tinted result reads close to the source game's own player colours at full
  strength.
- **In the mask render**, that same region gets flat red (`(1, 0, 0)` emission) via a per-face
  attribute (`sprite_team`) read by an override material, under the Raw view transform (section 4).
- **In the finished mask** (`finish_sprites.py`), the red channel is weighted by `body alpha / final
  alpha` before being written out - this keeps team colour from bleeding onto shadow-only or
  soft-edge pixels, which would otherwise show a faint colour fringe around the shadow.
- **Extending the mask:** `render_sprites.py`'s `mask_material()` takes a list of
  `(channel, attribute_name, attribute_type)` triples, so you can wire up more than the team
  channel - a second per-object flag on the green or blue channel, for instance, for any other
  per-pixel data your engine's shader wants.
- **A worked, measured-from-the-game example:** SHCDE's own sprite shader reads a *second* value
  out of the same mask, on the green channel, for a lower-sprite cutaway effect - `docs/SHCDE.md`
  section 7 has the exact formula (an intercept and a per-pixel-row slope), measured the same way
  the scale in section 2 was: by observing the installed game's own behaviour, not by reading its
  code. `examples/sprite_scene.example.json`'s `mask.green_channel` and `finish_sprites.py`'s
  `green_ramp()` implement it. This is engine-specific - if your own target reads mask channels
  differently, derive its convention from its own documentation or shader source instead.

## 8. Frame index convention

Eight facings, evenly spaced, numbered so index 3 is the front (this project's convention - see
ANIMATION.md 5.9's facing table for all eight directions):

- **Turning the subject, not the camera:** a turntable object is rotated by
  `(front_facing - facing) * (360 / facing_count)` degrees rather than moving the camera, so the
  camera/light setup in sections 1 and 5 never has to change. `render_sprites.py`'s `--front-facing`
  and `--facing-count` default to 3 and 8; both are configurable if your convention differs.
- **A frame's identity is `(action, source frame, facing)`**, not a single flat index - your own
  engine's slot numbering is a separate mapping you build from that triple (see
  `pack_atlas.py`'s output, which carries all three per entry) plus how many discrete poses your
  target's animation system holds per state.
- **Space poses by how much the pose changes, not by even time intervals** (ANIMATION.md 5.9) -
  this applies just as much to which frames you choose to render in the first place as to how long
  each one is held once in-engine.

## 9. Checklist

- [ ] One camera, one canvas, one pivot position for the whole unit - verified, not assumed
      (`Camera.info()`'s `pivot_projected_check` in the manifest should equal the configured pivot).
- [ ] `px_per_m` matches a landmark measurement against your actual reference, not a guess.
- [ ] Beauty renders with Standard/None; the mask renders with Raw.
- [ ] No frame's bounds (body or shadow) reach the canvas margin - checked before spending render
      time on the beauty/mask passes, not after.
- [ ] Team-colour faces are neutral grey in the beauty render, flat red in the mask, and the
      finished mask shows zero team colour on shadow-only pixels.
- [ ] The atlas packer's two self-checks both pass: every pivot on a whole pixel, every packed
      rect byte-identical to its source crop.
- [ ] `tools/validate_sprites.py` passes: the mask contract, any configured tracked object's
      on-screen side agrees with its 3D geometry across facings, and (if you're comparing against
      the game's own carrier tables) the render's frame sizes fall in a plausible range of the
      installed game's own shipped sprites for the same kind of pose.
