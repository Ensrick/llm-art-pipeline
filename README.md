# LLM Art Pipeline

An LLM-agent-driven workflow and toolkit for turning a rigged 3D model into reviewed animation
clips, and (optionally) into 2D game sprites - built around a tight loop: an agent edits motion or
gear in 3D, renders a cheap review clip, a human approves or gives plain-language edits, repeat,
then export the final asset once.

This repository holds the **process and the reusable tools only**. It ships no 3D models,
textures, animation clips, images, audio or video of any kind, and no third-party or game assets -
see [Assets](#assets) below. Everything here is text: Python, documentation and a couple of small
JSON examples.

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
docs/     PROCESS.md, ANIMATION.md, GEAR.md - the method, written for a newcomer
examples/ A filled-in example config for tools/prepare_downloaded_model.py
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

`docs/PROCESS.md`, `docs/ANIMATION.md` and `docs/GEAR.md` explain what these are for and how they
fit together; the tools are deliberately light on their own inline usage docs so those guides
don't drift out of sync with the code.

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

## Install

There's nothing to build. Clone the repository, install Blender 4.4 and Pillow, and point the
tools at your own files:

```powershell
git clone https://github.com/Ensrick/llm-art-pipeline.git
cd llm-art-pipeline
py -3 -m pip install pillow
```

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

This writes one PNG per facing under `out/work/my_action/` - that *is* your sprite sheet's source
frames; `anim_cookbook.contact_sheet` tiles them into one image, and
`docs/ANIMATION.md` section 5.9 covers atlas-packing conventions if you need a packed atlas for a
specific engine.

**5. Turn a sequence of rendered frames into a review GIF:**

```powershell
py -3 tools/frames_to_gif.py out/review/my_action.gif out/work/my_action/*_mp4_00.png out/work/my_action/*_mp4_01.png --fps 12
```

**6. Send the GIF, the sprite sheet, and a five-line changes note** to whoever is reviewing -
that's the review package `docs/PROCESS.md` section 3 describes.

## How the review loop works

In short (`docs/PROCESS.md` has the full version): an agent builds a change in 3D, behind a flag so
the currently-shipping version keeps working; automatic checks run and report numbers; a review
package (clips, stills, a before/after, a short changes note) goes to a human; the human approves,
asks for a named edit, or defers; repeat until approved; only then does the slow final export run,
from a frozen, committed state. `docs/ANIMATION.md` and `docs/GEAR.md` cover the animation- and
gear-specific mechanics (retargeting, layering, sockets, loadouts, grips) and the automatic checks
that back this up.

## Assets

**This repository never holds assets - only the process and the tools.** Nothing 3D, no images, no
audio, no video, no archives, and nothing from any third party or any game ships here; `.gitignore`
blocks every such file type at the extension level so this stays true by default, not just by
convention. Bring your own rig, animation library and downloaded props; `docs/ANIMATION.md` section
4 and section 7 point at commonly-used free and paid sources and their licence terms as of when
this was written - re-verify current terms yourself before shipping anything.

## Contributing

Pull requests are welcome for the process docs and the tools themselves. Please keep to the same
rule this repository holds itself to: **no assets, ever** - no `.blend`/`.fbx`/`.obj`/image/
audio/video/archive files, no third-party or game-derived content, and no hard-coded personal
paths (use a command-line argument, an environment variable, or a config file instead, following
the existing tools' pattern). If a tool needs a sample asset to demonstrate or test against,
document what shape it needs rather than committing one.

## Licence

MIT - see [LICENSE](LICENSE).
