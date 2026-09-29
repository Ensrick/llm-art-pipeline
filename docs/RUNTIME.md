# The runtime route: how custom art reaches the game

Rendering, finishing and packing a sprite atlas (docs/SPRITES.md) only gets you image files. This
covers the other half: a BepInEx plugin that draws those files over a stock unit in **Stronghold
Crusader Definitive Edition**, only for units placed through its own editor button, without
touching that unit's gameplay. The plugin's source lives in `runtime/`; it's ours, MIT-licensed,
the same as everything else in this repository.

## 1. What's here, and what's deliberately left out

The source project this was extracted from also had an aura effect, an automated AI behaviour
(enemy units picking up terrain hazards), paid-recruitment integration, a developer preview mode,
and voice-line routing, all built on top of the same art-loading mechanism. **None of that is
here.** Two different reasons:

- The aura, the AI behaviour and a few animation-timing corrections were built by reading the
  game's disassembled code to find exact native function addresses and byte offsets. That's
  decompiled-derived material, and it doesn't belong in a repository meant to teach the *method*,
  independent of any one reverse-engineering effort. Nothing in `runtime/` needs it: with no
  animation-timing correction table, a slot the atlas has a frame for is simply always drawn there.
- The paid recruitment, developer preview and voice routing are gameplay/UX features on top of the
  art pipeline, not the pipeline itself, and each pulls in its own scope (an economy system, a
  second plugin's audio runtime). Cutting them keeps this example to exactly one thing: how a
  custom sprite reaches the screen.

A second, separate plugin in the source project (a collaborator's own "preview" plugin, handling
two additional units) isn't included either. It isn't needed: the plugin here is completely
self-sufficient for placing a unit and seeing custom art end to end, which is what
[TUTORIAL.md](TUTORIAL.md) demonstrates. If you're integrating with someone else's existing runtime
plugin instead of building your own from scratch, expect to adapt the identity/save-key constants
in `src/UnitCatalog.cs` so the two never collide.

What's left, in `runtime/src/`, is the complete, load-bearing mechanism:

| File | What it does |
|---|---|
| `UnitCatalog.cs` | Every placeable unit: its saved key, its carrier's game/editor identifiers (checked against the Script Extender and the game at startup - docs/SHCDE.md section 2-3), and its slot layout. |
| `AtlasManifest.cs` | Parses and verifies `manifest.json` (docs/SHCDE.md section 6): schema, page list, SHA-256 of every page/mask/frames.tsv. Also a small dependency-free JSON reader, since .NET Framework on the game's Mono runtime has none built in. |
| `FrameTable.cs` | Parses and validates `frames.tsv`. No Unity types, so this and `AtlasManifest.cs` can be linked into a separate command-line validator that checks an atlas without starting the game. |
| `UnitArt.cs` | Loads one unit's verified atlas into Unity textures, sprites and per-page materials (the shader interface in docs/SHCDE.md section 7). |
| `UnitIdentities.cs` | The saved-game format: which global unit IDs are tagged as which catalog variant. A small versioned binary format with fail-closed validation - any corruption or unknown data is rejected as a whole rather than partially trusted. |
| `UnitPlacement.cs` | The identity route itself (section 2 below): arms an editor button, tags the unit a placement creates, and answers "what variant is this exact live unit" for the rest of the plugin. |
| `UnitSprites.cs` | Hooks the game's own sprite-assignment call; draws this plugin's frame for a tagged unit's slot; leaves everything else - including another mod's own change to the same renderer - alone. |
| `UnitsDriver.cs` | A tiny `MonoBehaviour` that survives scene loads, so there's somewhere to run per-frame refresh logic (the game destroys the plugin's own object during startup). |
| `UnitsPlugin.cs` | Wires the above together: config, startup validation, atlas loading per unit, install. |

## 2. How the identity route works

The problem: a modded unit and a stock unit of the same carrier are, to the game, identical - same
type, same AI, same save format. Something has to mark *this specific one* as "draw custom art
here" without touching gameplay, and that mark has to survive a save and reload even though the
game recycles unit-slot numbers.

1. An editor button calls the carrier's own native editor tool (`EngineInterface.StartMapperItem`),
   exactly as the carrier's stock tile would, while a detour on that same call notes that *this*
   arming came from the plugin's button. Any other tool - including a stock tile of the same
   carrier - ends that session immediately.
2. When the armed tool places a unit (`PlaceMapperItem`, a real editor click, not a preview), the
   native spawn happens synchronously inside that call. A detour on unit creation tags the exact
   unit that call produced with the button's catalog key, identified by the game's own **global
   unit ID** (not the reusable unit-slot index). Shift/Ctrl/Alt multi-placement places several
   units in a loop; each call is tagged individually.
3. Tags are saved under this plugin's own `ModSaveDataAPI` key, as a small versioned binary blob
   (`UnitIdentities.cs`). Unreadable or unrecognised data is rejected as a whole, so a corrupted or
   foreign save can't half-apply - every unit falls back to stock art instead. Closing a map clears
   every tag; deleting a unit removes its tag; a recycled unit slot never inherits one, because the
   tag is keyed by the global ID, checked against the live unit's actual type on every read.
4. After the game's own sprite-assignment call runs (so colour, transparency and draw order stay
   completely native), a hook checks whether the renderer being painted belongs to a tagged unit.
   If so, and if this plugin's atlas has a frame for that exact slot, it swaps the sprite; if the
   atlas doesn't cover that slot, or the unit isn't tagged, the native frame stands. If some *other*
   mod's hook already changed the sprite before this one runs, that result is left alone rather than
   overwritten - the guard compares the renderer's current sprite against the expected stock one and
   backs off on a mismatch.

Nothing above touches combat stats, AI state, or pathing. The tag is purely "which art to draw",
checked at draw time.

## 3. Build guide

**Requirements:** the game installed, BepInEx 5 installed into it, Rawra's Script Extender
installed as a BepInEx plugin (docs/SHCDE.md section 1), and a .NET SDK that can target `net481`
(any recent SDK can - .NET Framework 4.8.1 is the game's own Mono runtime's target, not a
requirement on your SDK version).

```powershell
dotnet build runtime\ByzantineUnits.csproj -c Release
```

Every reference in `ByzantineUnits.csproj` is a `HintPath` into your own installed game and mods
(`<Private>false</Private>` - nothing is copied into the build output, and this repository
redistributes none of them). If your game isn't at the default Steam path, pass it explicitly:

```powershell
dotnet build runtime\ByzantineUnits.csproj -c Release -p:GameDir="D:\Games\...\Stronghold Crusader Definitive Edition"
```

A missing Script Extender or missing game assemblies fail the build immediately with a clear error
(`ByzantineUnits.csproj`'s `CheckGameReferences` target) rather than a wall of missing-reference
errors.

## 4. Install and rollback

`runtime/install.ps1` builds the plugin, then copies it and any atlases it finds under `-ArtRoot`
(default `runtime\out\`, `tools/pack_atlas.py`'s usual `--out`) into
`BepInEx\plugins\ByzantineUnits\`. It:

- refuses outright while the game is running, and never starts it;
- verifies every atlas file's SHA-256 against its own manifest before copying, and every copied
  file's SHA-256 again immediately after;
- **moves** an existing install to `runtime\backups\<timestamp>-install\` rather than deleting it,
  and moves it back automatically if anything fails partway through;
- fingerprints every other file under `BepInEx\plugins` and `BepInEx\config` before and after, so
  it can prove (and tell you) whether anything outside its own two paths changed;
- records what it did in `runtime\installed.json`.

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File runtime\install.ps1 -DryRun   # prints the plan, changes nothing
pwsh -NoProfile -ExecutionPolicy Bypass -File runtime\install.ps1           # installs
```

`runtime\rollback.ps1` undoes it the same way - move, don't delete, verify, record:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File runtime\rollback.ps1
```

Both take `-GamePath` if your game isn't at the default Steam path (the same default as the
`.csproj`, in `runtime\common.ps1`).

## 5. Adapting this for your own units

- **A different roster:** edit `UnitCatalog.Variants` in `src/UnitCatalog.cs` - each entry is one
  button, carrying its saved key, its carrier's identifiers (checked against the Script Extender
  and the game at startup, so a mismatch disables that unit rather than drawing wrong art), and its
  art folder name. `install.ps1`'s `$UnitCatalogFolders` list needs the matching folder names.
- **A different carrier:** find its slot table the same way docs/SHCDE.md section 3 did - by
  measuring the installed game's own shipped sprites and their timing, not by decompiling anything
  new. Add a `CarrierFile` entry with its GM/chimp/mapper identifiers (visible through the Script
  Extender's own typed interop, `SHCDESE.Interop`) and slot blocks.
- **Extra atlas variants** (a colour variant, a seasonal skin): call `UnitArtLoader.Load` again for
  an alternate folder and pick between the results at draw time in `UnitSprites.cs` - `UnitsPlugin`
  already shows the pattern of validating one atlas's frame/team-colour counts against another's
  before trusting it as a drop-in alternate.
- **Your own save key:** `UnitCatalog.SaveKey` must be unique across every plugin that touches the
  same save file. Change it before shipping alongside anyone else's runtime plugin.
