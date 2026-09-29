# Stronghold Crusader Definitive Edition: facts for this pipeline

This is the target this repository's tools and runtime code are actually built for: **Stronghold
Crusader Definitive Edition** (a Unity remaster of the 2002 RTS), modded through **BepInEx 5** and
**Rawra's Script Extender** ("SHCDESE"). Numbers here, not adjectives - this is the reference a
human needs to reproduce the look and feel of a custom unit without an AI. See
[RUNTIME.md](RUNTIME.md) for how the code that reads these numbers actually works, and
[SPRITES.md](SPRITES.md) for the render-side reasoning.

**Sources and what isn't here.** These numbers come from two kinds of source: measuring the
installed game's own shipped sprites and UI art directly (their pixel dimensions, their pivot
convention), and this project's own decompiled-behaviour research turned into plain facts about
what each carrier's animation states do (state numbers, slot ranges, phase counts, timing) with no
addresses, disassembly line numbers or file hashes attached. What isn't here, on purpose: no
extracted Firefly art or audio, no decompiled source or byte offsets, and no third-party downloaded
model. If you need to re-derive any of this yourself, measuring your own installed game's sprite
files and observing its on-screen timing is the same method that produced it.

## 1. Dependencies

| Dependency | What it is | Where |
|---|---|---|
| Stronghold Crusader Definitive Edition | The game (Unity). Purchased separately; not redistributed here. | Steam |
| BepInEx 5 | The .NET/Mono plugin loader every mod, including the Script Extender, runs under. | [BepInEx releases](https://github.com/BepInEx/BepInEx/releases) (5.x for this game) |
| Rawra's Script Extender (SHCDESE) | A BepInEx plugin giving mods typed access to the game's native unit/building/player data and a reactive event API (R3), instead of raw memory offsets. **Required** - `ByzantineUnits.csproj` will not build without it installed, and the plugin declares it as a hard BepInEx dependency. | [gitlab.com/rawra-stronghold-crusader/shcde-script-extender](https://gitlab.com/rawra-stronghold-crusader/shcde-script-extender) - see that repository for its current version and licence |
| .NET SDK (net481 target) | To build the plugin. | `dotnet build`, any recent .NET SDK can target net481 |

This repository was built and tested against Script Extender **2.12.0**; check the Script
Extender's own repository for the current version and compatibility notes before building against
a newer one - its `info.json` (installed under `BepInEx\plugins\000shcdese\`) reports the version
actually installed.

## 2. Carriers and units

The game draws every unit from a fixed native "carrier" type's animation table (a bundle of sprite
slots, states and timing). A custom unit doesn't get its own animation system - it **runs on** an
existing carrier's game logic and states, and a mod redraws that carrier's sprite slots with its
own art. This repository's example plugin (`runtime/`) places six units this way:

| Unit | Carrier | Loadouts |
|---|---|---|
| Vanguard | Bedouin Skirmisher | - |
| Sentinel | Archer | - |
| Fire Siphoner | Arabian grenadier (Fire Thrower) | - |
| Cataphract | Knight | - |
| Icon Bearer | Bedouin healer | - |
| Varangian | Swordsman | Danish axe, sword and shield, one-hand axe (three separate buttons/atlases) |

A unit **keeps its carrier's gameplay and combat stats exactly** - health, damage, speed, AI. Only
the sprite is replaced, and only for units placed through this plugin's own editor button (see
[RUNTIME.md](RUNTIME.md) section 2, "the identity route"). A stock tile of the same carrier, placed
next to a custom one, keeps stock art.

Two more carriers exist in the wider source project this pipeline was extracted from (Pikeman and
Horse Archer) but aren't part of this repository's example plugin; their tables are included below
for completeness since the method is identical.

## 3. Carrier animation tables

Every table entry shows for **delay + 1 updates**, at **40 updates per second at default game
speed** (this follows game speed - a faster game speed shortens real time per update, not the
update count). "Facings" is how many of the 8 directions (section 4) that state actually uses - a
state with fewer than 8 typically only ever faces the camera. "Loop" is whether the state repeats
its play order or plays once and holds.

### Bedouin Skirmisher (Vanguard)

| State and trigger | Slots | Phases | Facings | Delay (updates/entry) | Play order | Loop |
|---|---|---|---|---|---|---|
| Walk, javelin in hand | 0-127 + 0x-127x | 16 (+16 `x`) | 8 | none; 1 phase/movement step | 0-15 | loop |
| Walk, no javelin | 128-255 + 128x-255x | 16 (+16 `x`) | 8 | as above | 0-15 | loop |
| Run, javelin in hand (default gait) | 256-383 + 256x-383x | 16 (+16 `x`) | 8 | as above | 0-15 | loop |
| Run, no javelin | 384-511 + 384x-511x | 16 (+16 `x`) | 8 | as above | 0-15 | loop |
| Melee | 512-767 | 32 (two attacks of 16) | 8 | 3 (4) | variant A 1-16, then B 17-32, repeating | loop |
| Attack a building | 512-639 (melee A) | 16 | 8 | 1 (2) | 1-16 | loop |
| Dig moat | 768-887 | 15 | 8 | 3 (4) | 1-15 | loop |
| Fill moat | 768-887 | 15 | 8 | 3 (4) | 15-1 | loop |
| Climb a ladder | 888-983 | 12 | 8 | 8/phase | up 1-12, down 12-1, once per rung | loop |
| Idle, javelin in hand | 984-1239 | 32 (two loops of 16) | 8 | 4 (5) | loop A 1-16 or loop B 17-32 | loop |
| Idle, no javelin | 1240-1495 | 32 | 8 | 4 (5) | as above | loop |
| Celebrate | idle loop A (984-1111/1240-1367) | 16 | 8 | 4 (5) | 1-16 | loop |
| Javelin throw | 1496-1751 | 32 | 8 | 2 (3) | wind-up, draw, throw at **phase 20** | one-shot |
| Death, backward with arrow | 1752-1943 | 24 | 8 | 2 (3) | 1-23 once, 24 held | one-shot |
| Death, backward, no arrow | 1944-2135 | 24 | 8 | 2 (3) | as above | one-shot |
| Death, forward | 2172-2363 | 24 | 8 | 2 (3) | as above | one-shot |
| Fall from a ladder | 2364-2427 | 8 | 8 | 1 (2) | 1-7 once, 8 held | one-shot |
| Corpse fade | keeps the last frame | - | - | per update | fade to 32 | one-shot |

No sit/rest state, no dedicated celebrate art (it reuses idle loop A).

### Archer (Sentinel)

| State and trigger | Slots | Phases | Facings | Delay (updates/entry) | Play order | Loop |
|---|---|---|---|---|---|---|
| Walk | 0-127 + 0x-127x | 16 (+16 `x`) | 8 | ~2/phase, step-driven | 0-15 | loop |
| Run | 128-255 + 128x-255x | 16 (+16 `x`) | 8 | ~3/phase, step-driven | 0-15 | loop |
| Draw | 256-319 | 8 | 8 | 2 (3) | held pattern, see below | one-shot, then aim |
| Aim (level/up/down) | 320-327 / 448-479 / 544-575 | 1 / 4 / 4 | 8 | 2 (3) | - | one-shot, then release |
| Release (level/up/down) | 384-447 / 480-543 / 576-639 | 8 | 8 | 2 (3) | - | **arrow leaves at phase 6**, then idle |
| Celebrate | art 640-687, requested 643-690 | 12 | 4 | 2 (3) | ping-pong | loop while it holds |
| Alert idle | 688-703 | 16 | 1 (front) | 5 (6) | ping-pong | loop |
| Rest idle | 688-703 | 16 | 1 (front) | 4 (5) | per-unit length table | loop |
| Sit, rest, stand | 704-718 | 15 | 1 (front) | 2 (3) | sit 1-11; rest 12-15 loop; stand 11-1 | loop |
| Melee | 792-887 | 12 | 8 | 3 (4) | primary, alternate, primary | loop, hit at counter 4 |
| Attack a building | 792-839 (melee primary) | 6 | 8 | 3 (4) | 1-6-2 | loop |
| Climb a ladder | 888-983 | 12 | 8 | 8/phase | up 1-12, down 12-1 | loop per rung |
| Fall from a ladder | 984-1047 | 8 | 8 (shown turned 180°) | 1 (2) | 1-8, 8 held | one-shot |
| Dig moat | 1048-1175 | 16 | 8 | 3 (4) | 1-16 | loop |
| Fill moat | 1048-1175 | 16 | 8 | 3 (4) | 16-1 | loop |
| Death, arrow | 1176-1367 | 24 | 8 | 2 (3) | 1-23, 24 held | one-shot |
| Death, forward | 1368-1559 | 24 | 8 | 2 (3) | as above | one-shot |
| Death, backward | 1560-1751 | 24 | 8 | 2 (3) | as above | one-shot |
| Corpse fade | keeps phase 24 | - | - | per update | fade to 32 | one-shot |

Has a run, a celebration, a sit-and-rest, ladder climbing, and a fall-from-height death. No hit/flinch, no brace.

### Arabian grenadier / Fire Thrower (Fire Siphoner)

| State and trigger | Slots | Phases | Facings | Delay (updates/entry) | Play order | Loop |
|---|---|---|---|---|---|---|
| Walk | 0-127 + 0x-127x | 16 (+16 `x`) | 8 | none; ~3/movement step | 0-15 | loop |
| Melee | 128-383 | 32 | 8 | 2 (3) | 1-32 | loop, hit at counter 4 |
| Attack a building | 128-383 (melee block) | 32 | 8 | 3 (4) | 1-32 | loop |
| Throw | 384-639 | 32 | 8 | 6(7), 1(2), 2(3) | wind-up, then release, **pot released at phase 19** | one throw/pass |
| Idle, enemies near | 640-655 | 16 | 1 (front) | 3 (4) | by slot parity | loop |
| Idle, no enemy near | 655-679 | 25 (16-40) | 1 (front) | 3 (4) | by slot parity | loop |
| Death, arrow | 680-871 | 24 | 8 | 2 (3) | 1-23, 24 held | one-shot |
| Death | 872-1063 | 24 | 8 | 2 (3) | as above | one-shot |
| Death | 1064-1255 | 24 | 8 | 2 (3) | as above | one-shot |
| Corpse fade | keeps phase 24 | - | - | per update | fade to 32 | one-shot |

No run, no celebrate, no sit, no dig/fill, no working ladder climb, no separate fall-from-height death, no hit/flinch.

### Knight (Cataphract)

| State and trigger | Slots | Phases | Facings | Delay (updates/entry) | Play order | Loop |
|---|---|---|---|---|---|---|
| Walk, mace family | 0-127 | 16 (+16 `x`) | 8 | ~3/movement step | 0-15 | loop |
| Gallop, mace family | 128-255 | 16 (+16 `x`) | 8 | as above | 0-15 | loop |
| Idle, mace family | 384-479 | - | 8 | 5 (6) | - | loop |
| Celebrate, mace family | 480-575 | - | 8 | 4 (5) | - | loop |
| Melee, mace family | 576-719 | - | 8 | 1 (2) | swings A,B,C,B | loop, hit at counter 12 |
| Walk, lance family | 720-847 | 16 (+16 `x`) | 8 | as walk | 0-15 | loop |
| Gallop, lance family | 848-975 | 16 (+16 `x`) | 8 | as gallop | 0-15 | loop |
| Idle, lance family | 1104-1199 | - | 8 | 5 (6) | - | loop |
| Celebrate, lance family | 1200-1295 | - | 8 | 4 (5) | - | loop |
| Melee, lance family | 1296-1439 | - | 8 | 1 (2) | as mace | loop |
| Death A | 1440-1631 | 24 | 8 | 2 (3) | 1-23, 24 held | one-shot |
| Death B | 1632-1823 | 24 | 8 | 2 (3) | as above | one-shot |

Which weapon family (mace/lance) a rider shows follows that unit's array-index parity in the
game's own unit table (even = mace, odd = lance); slots 256-383 and 976-1103 don't exist.

### Bedouin healer (Icon Bearer)

| State and trigger | Slots | Phases | Facings | Delay (updates/entry) | Play order | Loop |
|---|---|---|---|---|---|---|
| Run | 1472-1599 + `x` | 16 (+16 `x`) | 8 | ~3/phase, 2 sub-steps/step | 0-15 | loop |
| Walk | 0-127 + `x` | 16 (+16 `x`) | 8 | ~2/phase | 0-15 | loop |
| Heal | 384-639 | 32 | 8 | 2 (3) | 1-32, **+10 HP/update to the patient** | loop |
| Idle, no enemy near | 640-895 | 32 | 8 | 2 (3) | 1-32 with holds | loop |
| Idle, enemy within 400 | 640-711 | 9 (phases 1-9) | 8 | 2 (3) | 1-9 and back | loop |
| Death, arrow | 896-1087 | 24 | 8 | 2 (3) | 1-23 once, 24 held | one-shot |
| Death | 1088-1279 | 24 | 8 | 1 (2) | 1-23 twice each, 24 held | one-shot |
| Death, doubled over | 1280-1471 | 24 | 8 | 1 (2) | as above | one-shot |
| Corpse fade | keeps phase 24 | - | - | per update | fade to 32 | one-shot |
| (never requested) | 128-383 | 32 | 8 | - | - | - |

No melee, no celebrate, no sit/rest, no dig/fill, no ladder climb, no fall-from-height death.

### Swordsman (Varangian)

| State and trigger | Slots | Phases | Facings | Delay (updates/entry) | Play order | Loop |
|---|---|---|---|---|---|---|
| Walk | 0-127 + 0x-127x | 16 (+16 `x`) | 8 | none; ~5/movement step | 0-15 | loop |
| Idle | 128-223 | 24/pair | 4 (pairs) | 2 (3) | one of 4 tables by unit index, ping-pong with long holds | loop |
| Celebrate | 448-511 | 16 | 4 (pairs) | 4 (5) | 1-16 | loop |
| Melee, overhead chop (variant 0) | 224-319 | 12 | 8 | 2 (3) | see below, hit at counter 7 | alternates with variant 1 |
| Melee, lunge (variant 1) | 320-415 | 12 | 8 | 2 (3) | see below, hit at counter 6 | alternates with variant 0 |
| Attack a building | 224-319 (chop) | 12 | 8 | 3 (4) | as variant 0 | loop |
| Death A | 512-703 | 24 | 8 | 2 (3) | 1-23 once, 24 held | one-shot |
| Death B (arrow) | 896-1087 | 24 | 8 | 2 (3) | as above | one-shot |
| Death C | 704-895 | 24 | 8 | 2 (3) | as above | one-shot |
| Corpse fade | keeps phase 24 | - | - | per update | fade to 32 | one-shot |

No run, no sit/rest, no dig/fill, no ladder climb, no brace, no hit/flinch, no separate
fall-from-height death. Slots 416-447 don't exist in the native file.

### Pikeman (not in this repository's example plugin)

| State and trigger | Slots | Phases | Facings | Delay (updates/entry) | Play order | Loop |
|---|---|---|---|---|---|---|
| Walk | 0-127 + 0x-127x | 16 (+16 `x`) | 8 | none; ~3/movement step | 0-15 | loop |
| Celebrate | 128-191 | 8 (two sets of 4) | 8 | 4 (5) | by unit-index parity bit | loop |
| Idle | 192-221 | 30 | 1 (front) | 0 (1) | ping-pong | loop |
| Sit down and rest | 222-253 | 32 | 1 (front) | 2 (3) | sit 1-15 then 14-12; rest loops 12-32; stand 12-1 | loop |
| Melee (up/level/down pitch) | 290-353 / 354-417 / 418-481 | 8/pitch | 8 | 2 (3) | 4 variants in turn, hit at counter 3 | loop |
| Attack a building | 354-417 (level melee) | 4 | 8 | 3 (4) | 2,3,4,4,3,2,1 | loop |
| Dig moat | 482-601 | 15 | 8 | 3 (4) | 1-15 | loop |
| Fill moat | 482-601 | 15 | 8 | 3 (4) | 15-1 | loop |
| Death, backward, clean | 602-793 | 24 | 8 | 2 (3) | 1-23, 24 held | one-shot |
| Death, backward, arrow | 794-985 | 24 | 8 | 2 (3) | as above | one-shot |
| Death, forward | 986-1177 | 24 | 8 | 2 (3) | as above | one-shot |
| Corpse fade | keeps phase 24 | - | - | per update | fade to 32 | one-shot |

No run, no hit/flinch, no ladder climb, no brace, no four-facing block. Slots 254-289 don't exist.

### Horse Archer (not in this repository's example plugin; a two-layer mount + rider unit)

| State and trigger | Horse slots | Rider slots | Phases | Facings | Delay | Play order | Loop |
|---|---|---|---|---|---|---|---|
| Ride | 0-127 + `x` | same slot | 16 (+16 `x`) | 8 | none; 2 frames/step | 0-15 | loop |
| Idle | 1200-1455 | same slot | 32 exist, 24 used | 8 | 5 (6) | held pattern | loop |
| Shoot standing | 944-1199 (32-phase loop) | 272-527, facing target | draw 1-20, aim 21, release 22-32 | 8 | 1 (2) | draw, aim, release | per shot |
| Shoot while riding | 272-399 + `x` | 272-527, facing target | horse 16(+16x); rider as above | 8 | horse by step; rider 1 (2) | as above | per shot |
| Melee | 128-271 | same slot | 18 | 8 | 3 (4) | 1-18, hits at counters 7 and 16 | loop |
| Attack a building | 128-271 | same slot | 18 | 8 | 3 (4) | 1-18 | loop |
| Death, fall (incl. with arrow) | 560-751 / 752-943 | same slot | 24 | 8 | 2 (3) | 1-23, 24 held | one-shot |
| Corpse fade | keeps phase 24 | same | - | - | per update | fade to 32 | one-shot |

No separate run, hit/flinch, celebrate, sit/rest, ladder climb, dig/fill, brace, or distinct
fall-from-height death. Arrow is released at **shoot-standing phase 22**.

## 4. Facings

Eight facings, evenly spaced 45 degrees apart, in the game's own native order:

| Index | Direction |
|---|---|
| 0 | right-back |
| 1 | right |
| 2 | right-front |
| 3 | front (faces the camera) |
| 4 | left-front |
| 5 | left |
| 6 | left-back |
| 7 | back |

A sprite's slot is `base + phase * 8 + facing` for most states (see each carrier's table above for
exceptions - some states are single-facing, and mounted units track the rider's facing separately
from the horse's gait phase). All six carrier files in this plugin map a requested "image" number
to slot `image - 1`.

## 5. Scale: 57.37 pixels per metre, and how it was measured

Every native sprite is exported at **64 pixels per Unity unit**; a sprite's pivot is stored as a
fraction of its own (cropped) rect from the bottom-left corner, and **always lands on a whole
pixel**. The pivot is the unit's ground point (between the feet in a standing frame) - it stays on
that spot as the body moves off it (a lunge leans over it, a fall lands away from it), even though
the rect crops tighter or looser per frame.

**Concrete calibration point:** in the native Pikeman's walk cycle, the helmet top sits **84-85
pixels above the pivot** (measured with the pike carried low, facing the camera). To make a
custom rig read at the same apparent scale as the native art, render your rig at a trial
pixels-per-metre, measure the same landmark (your model's own helmet top, at the same pose) in the
rendered image, and solve for the `px_per_m` that puts it at 84-85 px too. That is where this
repository's `57.37` came from - it's a derived calibration constant for one specific ~1.75 m tall
rig, not a fact about the game engine. Re-derive it for your own model's proportions rather than
reusing the number directly (see [SPRITES.md](SPRITES.md) section 2 for the general method).

**The full comparison, per Pikeman block** - native rect height (min/median/max) and width
(median/max) in pixels, and how far above/below the pivot the rect reaches, all measured directly
from the installed game's own shipped sprite files (`tools/pikeman_carrier.py`'s
`NATIVE_FRAME_SIZES_PX`, read by `tools/validate_sprites.py`). Native rects carry a loose margin of
transparent pixels (0-52 px, median 4-5 px per side) that a tight custom render won't have, so
treat "matches" as "falls in a plausible range", not an exact target:

| Block | Height min/med/max | Width med/max | Top above pivot med/max | Below pivot max |
|---|---|---|---|---|
| Walk | 88 / 127 / 171 | 108 / 160 | 89.5 / 120 | 49 |
| Walk `x` | 88 / 125.5 / 168 | 110 / 163 | 89.5 / 120 | 54 |
| Celebrate | 111 / 138 / 169 | 55 / 112 | 111 / 135 | 32 |
| Idle | 123 / 134 / 154 | 89 / 116 | 108 / 110 | 13 |
| Sit and rest | 114 / 132.5 / 164 | 63 / 72 | 98 / 102 | 30 |
| Melee up | 87 / 123 / 167 | 96 / 138 | 91.5 / 130 | 42 |
| Melee level | 83 / 117 / 166 | 84 / 160 | 80.5 / 128 | 42 |
| Melee down | 86 / 109 / 177 | 94.5 / 182 | 79 / 128 | 37 |
| Dig and fill | 63 / 91.5 / 137 | 63.5 / 139 | 72 / 95 | 26 |
| Death, back | 39 / 93.5 / 162 | 104 / 175 | 50.5 / 118 | 58 |
| Death, back, arrow | 39 / 93.5 / 167 | 105.5 / 175 | 50.5 / 118 | 55 |
| Death, forward | 44 / 90 / 158 | 97.5 / 192 | 50 / 120 | 54 |

The upright pike tip reaches 105-110 px above the pivot in the idle and 135 px in the celebration
(facing 0) - taller than the walk-phase-0 range above, since a raised weapon extends well past the
body silhouette that range was measured from.

## 6. Canvas, pivot and atlas layout

| Setting | Value |
|---|---|
| Canvas | 384x384 px per frame before cropping (`examples/sprite_scene.example.json`) |
| Pivot | pixel (192, 144) from the canvas's bottom-left, fixed for every frame |
| Canvas margin | 2 px kept clear on every side; a frame that reaches it is refused before rendering the rest of the batch |
| Atlas width | 2048 px, gutter 2 px between packed frames, height rounded up to the next power of two |
| Pixels per unit (atlas import) | 64, matching every native sprite |

**The atlas format the plugin actually loads** (`runtime/src/AtlasManifest.cs`, written by
`tools/pack_atlas.py --slot-map ...`):

- `manifest.json` (schema `sprite_atlas_manifest/1`): `unit`, `file` (the carrier sprite file name,
  e.g. `body_skirmisher`), `normal` and `alternate` frame counts, `framesSha256`, an optional
  `teamColour` string, and a `pages` array - each page an object with `name`, `mask`, `width`,
  `height`, `sha256` and `maskSha256`.
- `pageN.png` / `pageN_m.png`: one page's colour and mask images, straight alpha, dimensions
  matching the manifest exactly.
- `frames.tsv`: tab-separated, header `slot\talt\tpage\tx\ty\tw\th\tpivot_x\tpivot_y\tppu`, one row
  per packed frame. `slot` is the carrier slot number (section 3's tables); `alt` is 1 for an
  in-between ("walk x") frame, else 0; `x`/`y`/`w`/`h` is the frame's rectangle within its page,
  top-left origin; `pivot_x`/`pivot_y` is the pivot in that rectangle's own pixels.
- Every byte is SHA-256-checked against the manifest before the plugin loads it; a mismatch disables
  that unit's art (and its editor button) rather than showing something unverified.

**Slot names.** A carrier sprite file's individual slots have names too, not just the numeric ranges
in section 3 - the Pikeman's slot 482 (the dig block's first frame) is `body_pikeman-482`, i.e. the
native sprite name the game itself uses (see `spriteLoader.addGMFile`'s registration order, exposed
in this form since it's exactly what appears in the installed game's own sprite asset). Never
requested slots aside, that naming is arithmetic (`base + 8 x phase + facing`, or `base + phase` for
a single-facing block) - `tools/pikeman_carrier.py` implements it in code (`slot()`, `slot_name()`,
`all_slot_names()`, `block_frames()`) with a self-check that every block tiles the carrier's slots
exactly, so `tools/validate_sprites.py` can confirm a render's `--slot-map` covers a block's slots
exactly once, with nothing missing or duplicated.

## 7. Team-colour mask

The game's own sprite shader is `Unlit/TeamColour`, reading a `_TeamMask` texture (this pipeline's
mask page) and a `_SpriteCutoff` float (a foot-clipping level, 0 for a fully-drawn sprite, `(level +
4) / 20` for each of 6 clipped levels above it - used when a unit stands partly behind terrain).
The mask has two channels' worth of meaning, both measured from the installed game's own shipped
mask sprites:

- **Red marks the team-coloured region**: painted bright, it's the area the shader tints with the
  owning player's colour. See [SPRITES.md](SPRITES.md) section 7 for the neutral-albedo technique
  that keeps the *un-tinted* beauty render from double-darkening once the shader's own tint
  multiplies it.
- **Green is a row-based cutaway ramp**, read by the same shader for the foot-clipping effect above:
  `green = clamp(round(189.84 + 2.23457 x (image_row - pivot_row_from_top)), 0, 255)`, with rows
  counted top-origin in native pixels (this pipeline's px/unit already matches the native 64, so no
  extra conversion is needed). `examples/sprite_scene.example.json`'s `mask.green_channel` carries
  these two constants, and `tools/finish_sprites.py`'s `green_ramp()` computes it per frame,
  overwriting whatever `render_sprites.py` put on the green channel for measurement purposes
  (section 10) - the shipped mask's green channel is always this ramp, never a tracked-object flag.

## 8. Ground shadow

The same sheared-silhouette technique in [SPRITES.md](SPRITES.md) section 6 is what this project's
sprites use: shear `(0.035, -0.09)`, composited under the beauty render at 149/255 alpha, rasterised
at 3x supersample. No native-specific numbers beyond those already in SPRITES.md and the example
config.

## 9. Editor button and tab picture sizes

| Element | Size |
|---|---|
| Native troop tab button (drawn) | 30x35 px |
| Troop tab button source art | 60x70 px (2x the drawn size) |
| Full-body idle preview picture, per unit | 44x55 px, unframed |
| The grid holding those preview pictures | 496x90 px total |

These are UI element sizes, not the unit's own sprite canvas (section 6) - they're what an editor
troop-tab button and its hover preview actually render at, sized so pixel art stays crisp at the
game's native UI scale.

## 10. Validating a render against the game

`tools/validate_sprites.py` runs three checks built from the facts above, on a `finish_sprites.py`
output folder:

- **Mask contract:** the mask's alpha channel matches the beauty render's alpha exactly.
- **Native frame size** (`--carrier pikeman --block <name>`, or `--native-heights` with your own
  numbers in the same shape): this render's bounds compared against section 5's table for the same
  block. Reported as a comparison, not a hard gate - a real pose can legitimately sit outside a
  range measured from different poses.
- **Slot coverage** (same flags, plus `--file`): every slot a block is supposed to fill
  (`tools/pikeman_carrier.py`'s tables) is filled exactly once in your `--slot-map`, with nothing
  missing or duplicated.
- **Facing-side** (config `checks.tracked_objects` / `checks.facing_side_rule` -
  [SPRITES.md](SPRITES.md) section 9): a tracked object's on-screen position agrees with its 3D
  geometry across facings - `render_sprites.py` measures the 3D side, `finish_sprites.py` measures
  the on-screen side from the mask, and this check compares them. Originally built to confirm a
  shield stayed on the correct arm across all 8 facings; the same check catches a mirrored rig or a
  flipped facing convention on anything you track.

```
py -3 tools/validate_sprites.py --frames out/frames/walk --config my_scene.json --carrier pikeman --block walk
```
