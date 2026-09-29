# Worked example: a walk cycle, start to finish

This follows the whole pipeline for one small, real piece of a unit - the Vanguard's walk - using
only free, CC0-licensed inputs, with the exact commands at each step. It stops short of a complete,
in-game-ready unit (a full unit needs every state in [SHCDE.md](SHCDE.md) section 3, dozens of
render passes), but every step here is the real step, at full scale just repeated more times. Read
[PROCESS.md](PROCESS.md) first for why the loop is shaped this way.

**What you need**, all free:
- [Blender 4.4](https://www.blender.org/download/releases/4-4/).
- [Quaternius' Universal Animation Library 1](https://quaternius.com/packs/universalanimationlibrary.html)
  ("Standard", CC0, free) - download it and note where `UAL1_Standard.glb` lands. It ships a
  `Walk_Loop` action on a CC0 rig.
- Python 3.13 with Pillow (`py -3 -m pip install pillow`), for the system-Python tools.
- Stronghold Crusader Definitive Edition, BepInEx 5 and the Script Extender, only for the last,
  optional in-game step ([SHCDE.md](SHCDE.md) section 1).

None of these are bundled here - see this repository's own README on why.

## 1. Look at what you have

Open `UAL1_Standard.glb` in Blender and confirm the pieces this tutorial uses: an armature (any
name is fine - this tutorial calls it `SRC`), a `Walk_Loop` action, and bone names including
`hand_l`/`hand_r`/`thigh_l`/`calf_l`/`foot_l`/`foot_r`. Note the action's frame range (33 frames,
0-32, for one full stride cycle, in the Standard file as of this writing).

## 2. Build a minimal per-facing scene

For a first pass, skip retargeting onto a separate character rig (docs/ANIMATION.md section 5.2
covers that) and just review the donor clip directly on its own rig - enough to prove out the
review and export mechanics before investing in a full custom body. Save a `.blend` with:
- the `SRC` armature and its mesh, at the world origin;
- a `Review_Turntable` empty parented as `tools/review_render.py`'s `review_turntable()` expects
  (or just call that function once from the Python console and save the result).

## 3. Review in 3D first

Before spending any time on the SHCDE-specific export, look at the motion the cheap way
(docs/PROCESS.md section 1):

```powershell
$blender = 'C:\Program Files\Blender Foundation\Blender 4.4\blender.exe'
```
```python
# Blender Python console, with your saved .blend open:
import sys; sys.path.insert(0, "tools")
import review_render as rr
rig = D.objects["SRC"]
tt = rr.review_turntable([rig])
manifest = rr.render_views(
    "out/work", "walk_review", count=8,
    pose=lambda i: (rr.facing_pose(tt, i), rr.play(rig, D.actions["Walk_Loop"]), rr.frame_set(i * 4)),
    meshes=lambda: [o for o in D.objects if o.type == "MESH"],
    labels=[f"facing {i}" for i in range(8)], views={"3q": {}},
)
```

This writes 8 stills (one per facing, at frame `i * 4`) under `out/work/walk_review/`. Look at them.
If something's wrong with the pose or the retarget, fix it here - it costs a re-render of 8 stills,
not a full sprite export.

## 4. Render for SHCDE

Copy the example scene config and point `render_sprites.py` at your file. The Vanguard's "walk,
javelin in hand" block ([SHCDE.md](SHCDE.md) section 3, Bedouin Skirmisher table) is slots 0-127:
16 phases times 8 facings. Sampling the 33-frame `Walk_Loop` every 2 frames gives 16 phases (frames
0, 2, 4, ... 30); this tutorial renders only the first 4 of those 16 to keep the example short -
extend `--frames` to all 16 for a real block.

```powershell
copy examples\sprite_scene.example.json my_scene.json
& $blender --background -t 2 --factory-startup --python-exit-code 1 --python tools/render_sprites.py -- `
    --config my_scene.json --rig my_walk.blend --rig-object SRC --action Walk_Loop `
    --frames 0 2 4 6 --facings 0 1 2 3 4 5 6 7 --out out/raw/walk
```

**What "done" looks like here:** `out/raw/walk/` holds `frames.json` plus, for each of the 32
(4 frames x 8 facings) combinations, a `<key>.png`, a `<key>_raw_m.png` and a `<key>.shadow.npz`.
No `## CLIPS` line in the console output - if one appears, enlarge the config's canvas and re-run
(never shrink the model - [SPRITES.md](SPRITES.md) section 3).

## 5. Finish

```powershell
py -3 tools/finish_sprites.py --raw out/raw/walk --out out/frames/walk
```

**What "done" looks like:** `FINISHED walk: 32 frames, 0 touching the canvas edge`. Open a `<key>.png`
in `out/frames/walk/` - you should see the pose with a soft, sheared shadow under it, not a hard
black box and not a missing shadow.

## 6. Build the slot map and pack

`frames.tsv` needs a carrier **slot** per frame, not just a source frame and facing. For this block,
slot = phase x 8 + facing, and this tutorial's phase is `frame / 2`:

```powershell
py -3 -c "
import json
man = json.load(open('out/raw/walk/frames.json'))
slot_map = {f['key']: (f['frame'] // 2) * 8 + f['facing'] for f in man['frames']}
json.dump(slot_map, open('walk_slot_map.json', 'w'), indent=1)
print(len(slot_map), 'frames mapped, slots', min(slot_map.values()), '-', max(slot_map.values()))
"
py -3 tools/pack_atlas.py --frames out/frames/walk --out out/atlas/Vanguard/body_skirmisher `
    --config my_scene.json --slot-map walk_slot_map.json --unit Vanguard --file body_skirmisher
```

**What "done" looks like:** the pack script prints `runtime manifest: Vanguard/body_skirmisher, 32
frames, slots 0-31` (only 32 of the block's 128 slots are filled at this tutorial's reduced scale -
that's expected and fine; the plugin below simply keeps the native frame for every slot you haven't
rendered yet). `out/atlas/Vanguard/body_skirmisher/` now holds `page0.png`, `page0_m.png`,
`frames.tsv`, `manifest.json` and the generic `atlas_index.json`.

## 7. Build and install the plugin (needs the actual game)

```powershell
dotnet build runtime\ByzantineUnits.csproj -c Release
pwsh -NoProfile -ExecutionPolicy Bypass -File runtime\install.ps1 -ArtRoot out\atlas -DryRun
```

Read the dry run's plan. If it looks right (the Vanguard listed as installed, with 32 frames, the
other five units skipped for lack of art), drop `-DryRun`:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File runtime\install.ps1 -ArtRoot out\atlas
```

**What "done" looks like:** `Installed Byzantine units 0.1.0: ... BepInEx\plugins\ByzantineUnits`,
listing `Vanguard: 32 frames`, and `Other plugins and configs: N files compared, none changed.`

## 8. Check it in the game

1. Start the game, open the Map Editor, and find the Byzantine tab next to the native tabs
   ([RUNTIME.md](RUNTIME.md) section 2 - the tab and its button only appear once at least one
   unit's art is installed).
2. Place a Vanguard. Place a stock Bedouin Skirmisher next to it.
3. Walk both units in a few directions. For the four rendered phases (0, 2, 4, 6 of 16) and all 8
   facings, the Vanguard shows this tutorial's custom frames; for the other 12 phases it falls back
   to the native Skirmisher frame at that slot, since nothing was rendered there - so at full speed
   you'll see your 4 poses and 12 native ones cycle together. That partial, honest result **is**
   "done" for this tutorial. Rendering all 16 phases (and every other state in the Skirmisher's
   table) is exactly the same process, repeated.
4. `BepInEx\LogOutput.log` should show `Vanguard: 32 frames loaded for body_skirmisher (manifest and
   SHA-256 verified...)` and, once the Vanguard is placed and walks into view, `Vanguard: first
   frame drawn over the Bedouin Skirmisher (body_skirmisher native slot 0)`.

## Where to go from here

- Render the remaining 12 walk phases the same way (extend `--frames`), and the block's `x`
  in-betweens if you want them (docs/SHCDE.md doesn't require them - a carrier falls back to the
  primary frame where no `x` exists).
- Move to the next block (walk-no-javelin, melee, idle, ...), following the same six steps, using
  the matching slot range from [SHCDE.md](SHCDE.md) section 3.
- Retarget onto your own character rig instead of the raw donor (docs/ANIMATION.md section 5.2),
  and layer your unit's own posture on top (section 5.3) before repeating this tutorial's steps.
