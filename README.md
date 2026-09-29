# LLM Art Pipeline

An LLM-agent-driven workflow and toolkit for turning a rigged 3D model into reviewed animation
clips and native-looking 2D game sprites - built around a tight loop: an agent edits motion or gear
in 3D, renders a cheap review clip, a human approves or gives plain-language edits, repeat, then
export the final asset once.

This repository holds the **process and the reusable tools only**. It ships no 3D models,
textures, animation clips, images, audio or video of any kind, and no third-party, game or
downloaded-model assets - see [Assets](#assets) below. Everything here is text: Python, C#,
PowerShell, documentation and a couple of small JSON examples.

## Target

This pipeline is built and documented against one concrete target: **Stronghold Crusader
Definitive Edition** (a Unity remaster), modded through **BepInEx 5** and
[**Rawra's Script Extender**](https://gitlab.com/rawra-stronghold-crusader/shcde-script-extender)
(SHCDESE - see that repository for its current version and licence). [`docs/SHCDE.md`](docs/SHCDE.md)
has the game facts (carrier animation tables, timing, scale, atlas format) and
[`docs/RUNTIME.md`](docs/RUNTIME.md) has the plugin that draws custom art in that game. The four
earlier guides (PROCESS/ANIMATION/GEAR/SPRITES) are written to generalize beyond this one target -
useful on their own for a different engine - but this repository's runtime code, its example scene
config's exact numbers, and the worked tutorial are specifically for this game.

**The end-to-end order**, each stage a separate doc:
1. Start from a free, CC0-licensed base body and rig ([ANIMATION.md](docs/ANIMATION.md) section 4).
2. Fit gear and props onto it ([GEAR.md](docs/GEAR.md)).
3. Animate ([ANIMATION.md](docs/ANIMATION.md)).
4. Review every change in 3D before anything slow runs ([PROCESS.md](docs/PROCESS.md)).
5. Export native-looking sprites ([SPRITES.md](docs/SPRITES.md), `tools/render_sprites.py` +
   `tools/finish_sprites.py`).
6. Pack an atlas ([SHCDE.md](docs/SHCDE.md) section 6, `tools/pack_atlas.py`).
7. Build and install the runtime plugin ([RUNTIME.md](docs/RUNTIME.md)).
8. Check it in the game (docs/PROCESS.md section 2, step 10).

[`docs/TUTORIAL.md`](docs/TUTORIAL.md) walks all eight steps for one real example, with exact
commands.

## Why

Exporting a finished 3D asset to its final form (a game engine import, a baked texture, a packed
sprite atlas) is often slow. If you only review at that final stage, every small correction costs
a full re-export. This workflow instead reviews cheap 3D renders - stills, turntables, short
clips - before anything goes through the slow path, and only exports once a human has actually
approved what they're looking at. [`docs/PROCESS.md`](docs/PROCESS.md) covers the loop in detail;
it's the first thing to read.

## What's here

```
tools/    Reusable Blender + Python helpers (see below)
runtime/  The BepInEx plugin that draws custom sprites in SHCDE (see docs/RUNTIME.md)
docs/     PROCESS.md, ANIMATION.md, GEAR.md, SPRITES.md, SHCDE.md, RUNTIME.md, TUTORIAL.md
examples/ Filled-in example configs for tools/prepare_downloaded_model.py and tools/render_sprites.py
```

**Tools:**

| File | What it does | Runs under |
|---|---|---|
| `anim_cookbook.py` | Retargeting, layering, baking, prop attach/release, pose save/load, spring follow-through | Blender |
| `anim_cookbook_selftest.py` | Self-test for the above | Blender |
| `attachment_sockets.py` | Bone-local socket frames and `align_by_names` attachment | Blender |
| `attachment_nudge.py` | Plain-language position nudges on top of a socket | Blender |
| `gear_kit.py` | Loadouts, true-size props under a scaled rig, weight transfer, hide regions, validation | Blender |
| `gear_kit_selftest.py` | Self-test for `gear_kit`, `attachment_nudge` and `body_charts` | Blender |
| `body_charts.py` | Labelled anatomy/socket charts, rendered and captioned entirely in Blender | Blender |
| `grip_quality.py` | Sampled geometric check that a hand-held prop isn't penetrating the hand | Blender |
| `grip_enclosure.py` | Stricter grip check: palm contact, finger wrap, thumb closure, no crossing | Blender |
| `review_render.py` | Turntables, fitted multi-view stills, game-timed MP4s, and the loop-seam check | Blender |
| `frames_to_gif.py` | Assemble rendered frames into a shared-palette looping review GIF | system Python + Pillow |
| `prepare_downloaded_model.py` | Measure, reorient and uniform-scale a downloaded model; bake its licence onto the result | Blender |
| `render_sprites.py` | Native-look final sprite rendering: fixed camera/lights, ground shadow, team-colour mask (see `docs/SPRITES.md`) | Blender |
| `finish_sprites.py` | Composite the ground shadow, build the finished mask, refuse anything that clips the canvas | system Python + Pillow |
| `pack_atlas.py` | Crop, dedupe and pack finished frames into a pivot-indexed atlas | system Python + Pillow |

`docs/PROCESS.md`, `docs/ANIMATION.md`, `docs/GEAR.md` and `docs/SPRITES.md` explain what these are
for and how they fit together; the tools are deliberately light on their own inline usage docs so
those guides don't drift out of sync with the code.

**Runtime (SHCDE-specific, [docs/RUNTIME.md](docs/RUNTIME.md)):**

| Path | What it does |
|---|---|
| `runtime/ByzantineUnits.csproj` | The BepInEx 5 plugin project (net481); builds against your own installed game, BepInEx and Script Extender |
| `runtime/src/*.cs` | Atlas loading and verification, the editor identity route, the sprite-draw hook - see docs/RUNTIME.md section 1 for what each file does |
| `runtime/install.ps1`, `rollback.ps1`, `common.ps1` | Build, verify, back up (never delete) and install; undo the same way |
| `runtime/info.json` | The plugin's BepInEx manifest |

## Requirements

- **Blender 4.4** (the version this was built and tested against; every Blender-side script is run
  headless with `--background`). The code avoids the legacy `Action.fcurves` API that Blender 5.0
  removes, but only 4.4 has actually been verified.
- **Python 3.13** (system Python, *separate* from Blender's own bundled Python) with
  [Pillow](https://pypi.org/project/Pillow/) installed, for `frames_to_gif.py` only. Everything
  else runs inside Blender's bundled Python, which already includes numpy.
- A rigged humanoid (or other) base model of your own. None is included - see
  [Assets](#assets). [Quaternius](https://quaternius.com/) is a good free (CC0) starting point for
  both a rig and a broad animation library; `docs/ANIMATION.md` section 4 covers other sources and
  their licence terms.
- The example commands below use PowerShell syntax (`&`, quoted paths) since that's this project's
  own shell. Blender itself runs the same way on macOS/Linux; adjust the invocation syntax for your
  shell - nothing here is Windows-specific beyond the example commands.
- For the runtime plugin only ([RUNTIME.md](docs/RUNTIME.md)): Stronghold Crusader Definitive
  Edition, BepInEx 5, Rawra's Script Extender, and a .NET SDK that can target `net481` (see
  [SHCDE.md](docs/SHCDE.md) section 1 for links and versions).

## Install

There's nothing to build. Clone the repository, install Blender 4.4 and Pillow, and point the
tools at your own files:

```powershell
git clone https://github.com/Ensrick/llm-art-pipeline.git
cd llm-art-pipeline
py -3 -m pip install pillow
```

## Testing against your own rig

`anim_cookbook_selftest.py` and `gear_kit_selftest.py` need a sample rigged character to run
against - none is shipped (see [Assets](#assets)). Point them at your own files matching this
shape (the exact names the scripts look for, read straight from the code):

**`anim_cookbook_selftest.py`** - set `ANIM_COOKBOOK_ASSETS` to a folder containing:
- `UAL1_Standard.glb`: an animation-library file with a `Walk_Loop` action, on a rig using bone
  names `hand_l`, `hand_r`, `thigh_l`, `calf_l`, `foot_l`, `foot_r`, `ball_l`, `Head`.
- `Male_Peasant.gltf`: a second rig (the retarget target) with matching bone names, plus mesh
  objects named `Male_Peasant_Arms` and `Male_Peasant_Body`.

**`gear_kit_selftest.py`** - set `GEAR_KIT_ART` to a folder shaped like this repo's original
`art/` layout, containing:
- `hoplite/shared_spearman/shared_spearman.blend`: a rig (named by `anatomy_map.json`'s `"rig"`
  key) with actions `Spear_Guard_Idle`, `Walk_Carry`, `Spear_Underarm_Thrust`, and objects
  `Male_Peasant_Arms`, `Male_Peasant_Legs`, `Male_Peasant_Body`, `Fitted_Helmet`,
  `Left_Forearm_Shield`, `Shield_Leather_Forearm_Band`, `Right_Hand_Spear`, `Quilted_Cuirass`.
  Its own chart render (`body_charts.py`) additionally expects `Male_Peasant_Feet`,
  `CC0_Head_Only`, `Padded_Sleeve_L`, `Padded_Sleeve_R`.
- `hoplite/shared_spearman/anatomy_map.json`: role/bone/joint names for that rig.
- `shared_humanoid/candidates/attachment_socket_pilot/attachment_frames.json`: a sample
  body/prop socket manifest in `attachment_sockets.py`'s schema.

None of this is needed to use the tools themselves on your own rig and your own object names -
only to run their self-tests, which check the helpers against a known-shape fixture.

## Quickstart: a model to a review GIF to a sprite sheet

This assumes you already have a rigged character `.blend` and at least one animation library
`.blend`/`.glb` of your own (see Requirements). Paths below are examples - use your own.

**1. Check the toolchain against your own rig.**

```powershell
$blender = 'C:\Program Files\Blender Foundation\Blender 4.4\blender.exe'
$env:ANIM_COOKBOOK_ASSETS = 'path\to\your\animation_library_folder'
& $blender --background -t 2 --factory-startup --python-exit-code 1 --python tools/anim_cookbook_selftest.py
```

**2. Prepare a downloaded prop** (skip this if you're only animating the bare rig). Copy
`examples/prepare_downloaded_model.example.json`, fill in your own model's path and *verified*
licence, then:

```powershell
& $blender --background --factory-startup --python-exit-code 1 --python tools/prepare_downloaded_model.py -- my_model.json
```

**3. Write a short build script** for your action, following
[`docs/ANIMATION.md`](docs/ANIMATION.md): open your rigged character, retarget a donor clip with
`anim_cookbook.retarget_action`, layer your unit's own posture on top with `layered_rotation`, run
the polish passes, then attach any props via `attachment_sockets.align_by_names` /
`gear_kit.apply_loadout`. This part is necessarily project-specific - it's the one script this
toolkit can't write for you - but every helper it needs is in `tools/`.

**4. Render a review clip and a sprite sheet**, from a script run in the same Blender session:

```python
import sys
from pathlib import Path
sys.path.insert(0, "tools")
import review_render as rr

tt = rr.review_turntable([my_rig])
facings = rr.render_views(
    "out/work", "my_action", count=8,
    pose=lambda i: (rr.facing_pose(tt, i), rr.play(my_rig, my_action), rr.frame_set(key_frame)),
    meshes=lambda: my_meshes,
    labels=[f"facing {i}" for i in range(8)],
    views={"g0": {}, "g1": {}, "g2": {}, "g3": {}},  # "g" + facing index -> a game-facing view
)
```

This writes one PNG per facing under `out/work/my_action/` - that *is* your review sprite sheet's
source frames; `anim_cookbook.contact_sheet` tiles them into one image for the review package.

**5. Turn a sequence of rendered frames into a review GIF:**

```powershell
py -3 tools/frames_to_gif.py out/review/my_action.gif out/work/my_action/*_mp4_00.png out/work/my_action/*_mp4_01.png --fps 12
```

**6. Send the GIF, the sprite sheet, and a five-line changes note** to whoever is reviewing -
that's the review package `docs/PROCESS.md` section 3 describes.

**7. Once it's approved, render the final, native-look game sprites.** This is a separate, slower
pass (`docs/PROCESS.md` step 8: only from a frozen, approved commit) with its own fixed camera,
lighting and ground shadow so the result looks like it was built for your target engine rather than
pasted on top of it - see [`docs/SPRITES.md`](docs/SPRITES.md) for every number and why. Copy
`examples/sprite_scene.example.json`, then:

```powershell
& $blender --background -t 2 --factory-startup --python-exit-code 1 --python tools/render_sprites.py -- `
    --config my_scene.json --rig my_unit.blend --action Walk_Loop --frames 0 2 4 6 8 10 12 14 --out out/raw/walk
py -3 tools/finish_sprites.py --raw out/raw/walk --out out/frames/walk
py -3 tools/pack_atlas.py --frames out/frames/walk --out out/atlas --config my_scene.json
```

`out/atlas/atlas.png` + `atlas_m.png` + `atlas_index.json` (rect, pivot and pixels-per-unit per
frame) are what a game engine actually imports.

## How the review loop works

In short (`docs/PROCESS.md` has the full version): an agent builds a change in 3D, behind a flag so
the currently-shipping version keeps working; automatic checks run and report numbers; a review
package (clips, stills, a before/after, a short changes note) goes to a human; the human approves,
asks for a named edit, or defers; repeat until approved; only then does the slow final export run,
from a frozen, committed state. `docs/ANIMATION.md` and `docs/GEAR.md` cover the animation- and
gear-specific mechanics (retargeting, layering, sockets, loadouts, grips) and the automatic checks
that back this up; `docs/SPRITES.md` covers that final export in detail if your target is 2D game
sprites.

## Assets

**This repository never holds assets - only the process, the tools and the runtime source.**
Nothing 3D, no images, no audio, no video, no archives, and no third-party, game or
downloaded-model file ships here; `.gitignore` blocks every such file type at the extension level
so this stays true by default, not just by convention. Bring your own rig, animation library and
downloaded props; `docs/ANIMATION.md` section 4 and section 7 point at commonly-used free and paid
sources and their licence terms as of when this was written - re-verify current terms yourself
before shipping anything. The game itself, BepInEx and the Script Extender are separate downloads
this repository doesn't redistribute (see [Target](#target)).

## Contributing

Pull requests are welcome for the process docs, the tools and the runtime plugin. Please keep to
the same rules this repository holds itself to:
- **No assets, ever** - no `.blend`/`.fbx`/`.obj`/image/audio/video/archive files, and nothing
  extracted from the game itself.
- **No hard-coded personal paths** - a command-line argument, an environment variable or a config
  file instead, following the existing tools' pattern. If a tool needs a sample asset to
  demonstrate or test against, document what shape it needs rather than committing one.
- **No decompiled game code** in the runtime plugin or its docs - a fact about the game's observable
  behaviour (a slot range, a timing number, a file format) is fine and often necessary; a native
  function address, a disassembly line number or an extracted binary hash is not. See
  [RUNTIME.md](docs/RUNTIME.md) section 1 for where this project already drew that line.

## Licence

MIT - see [LICENSE](LICENSE).
