using BepInEx.Logging;
using MonoMod.RuntimeDetour;
using R3;
using SHCDESE.EventAPI;
using SHCDESE.EventAPI.Units;
using System;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.CompilerServices;
using UnityEngine;
using GameGM = Enums.GM;

namespace ByzantineUnits
{
    /// <summary>
    /// After the game's own SpriteMapping.SetBodySprite, draw our frame for the same slot, but only
    /// on a renderer bound to a live unit whose exact global ID we tagged. The stock call (and any
    /// other mod's hook in the chain) runs first, so colour, transparency and sort order stay native;
    /// if the sprite on the renderer is then not the stock one, another mod changed it and we leave
    /// it alone. A slot our atlas lacks keeps the native frame.
    ///
    /// Trimmed for this public example: the original also remapped a handful of slots per carrier to
    /// correct specific native celebrate-animation requests, played occasional relaxed-idle clips
    /// packed above a carrier's own slots, and showed a preview sprite on the editor cursor. Cut here
    /// because the remap table's every entry existed to compensate for one native engine quirk found
    /// by reading disassembly - which is exactly the kind of decompiled-derived fact this repository
    /// doesn't carry - and because the other two are cosmetic extras, not the load-bearing mechanism.
    /// What remains below (slot = image - 1, tag lookup, draw-or-leave-native) is that mechanism in
    /// full: with no remap table, an atlas that has a frame for slot N is simply always drawn there.
    /// </summary>
    internal static class UnitSprites
    {
        private delegate void SetBodySpriteDelegate(SpriteRenderer renderer, int file, int image, int colour,
            bool alternateFrame, int chopFeet, int transparency);

        private const int MissingSlotLogLimit = 40;

        // Static roots: the hook and its art live for the whole process.
        private static readonly VariantArt[] artByVariant = new VariantArt[UnitCatalog.Variants.Length];
        private static readonly bool[] coveredFile = new bool[1024];
        private static readonly HashSet<string> loggedOnce = new HashSet<string>(StringComparer.Ordinal);
        private static readonly Dictionary<SpriteRenderer, Binding> bindings =
            new Dictionary<SpriteRenderer, Binding>(RendererReferenceComparer.Instance);
        private static readonly List<SpriteRenderer> staleBindings = new List<SpriteRenderer>();
        private static readonly List<RefreshRequest> pendingRefresh = new List<RefreshRequest>();
        private static readonly List<IDisposable> subscriptions = new List<IDisposable>();
        private static ManualLogSource log;
        private static UnitPlacement placement;
        private static Hook hook;
        private static SetBodySpriteDelegate original;
        private static int missingSlotLogs, lastRefreshRevision = -1;

        /// <summary>True when this variant's art is installed in the hook.</summary>
        internal static bool Covers(UnitVariant variant) => artByVariant[variant.Index] != null;

        internal static void Install(ManualLogSource logSource, IEnumerable<VariantArt> art, UnitPlacement route)
        {
            if (hook != null) throw new InvalidOperationException("The sprite hook is already installed.");
            log = logSource;
            placement = route ?? throw new ArgumentNullException(nameof(route));
            try
            {
                foreach (VariantArt entry in art)
                {
                    int gm = entry.Variant.File.Gm;
                    if (gm < 0 || gm >= coveredFile.Length)
                        throw new ArgumentOutOfRangeException(nameof(art), $"GM {gm} is outside the hook's table.");
                    artByVariant[entry.Variant.Index] = entry;
                    coveredFile[gm] = true;
                }
                MethodInfo method = typeof(SpriteMapping).GetMethod(nameof(SpriteMapping.SetBodySprite),
                    BindingFlags.Public | BindingFlags.Static, null,
                    new[] { typeof(SpriteRenderer), typeof(int), typeof(int), typeof(int), typeof(bool), typeof(int), typeof(int) }, null)
                    ?? throw new MissingMethodException(nameof(SpriteMapping), nameof(SpriteMapping.SetBodySprite));
                hook = new Hook(method, (SetBodySpriteDelegate)SetBodySpriteHook);
                original = hook.GenerateTrampoline<SetBodySpriteDelegate>();
                subscriptions.Add(UnitR3EventHooks.OnUnitUnityVisualSpawn.Observable.Subscribe(args =>
                {
                    if (args != null && args.UnitId > 0 && args.SpriteRenderer != null)
                        bindings[args.SpriteRenderer] = new Binding { UnitId = args.UnitId };
                }));
                subscriptions.Add(UnitR3EventHooks.OnUnitUnityVisualInterpolate.Observable.Subscribe(args =>
                {
                    try
                    {
                        Chimp chimp = args?.Chimp;
                        if (chimp == null || chimp.objectID <= 0 || chimp.sprRenderer == null) return;
                        if (!bindings.TryGetValue(chimp.sprRenderer, out Binding binding) || binding.UnitId != chimp.objectID)
                            bindings[chimp.sprRenderer] = binding = new Binding { UnitId = chimp.objectID };
                        binding.Chimp = chimp;
                        if (binding.HasFrame) return;
                        // A renderer bound after its first native paint: paint it once through the hook.
                        if ((uint)chimp.file1 >= (uint)coveredFile.Length || !coveredFile[chimp.file1]) return;
                        SpriteMapping.SetBodySprite(chimp.sprRenderer, chimp.file1, chimp.image1, chimp.colour1,
                            chimp.altFrame1Set, chimp.chopFeet, chimp.transparency);
                    }
                    catch (Exception ex) { LogFailure("visual interpolation", ex); }
                }));
                subscriptions.Add(UnitR3EventHooks.OnUnitUnityVisualRemove.Observable.Subscribe(args =>
                {
                    SpriteRenderer renderer = args?.Chimp?.sprRenderer;
                    if (ReferenceEquals(renderer, null)) return;
                    if (bindings.TryGetValue(renderer, out Binding binding) && binding.Drawn && renderer != null && original != null)
                    {
                        // The renderer may be pooled for an ordinary unit: put its native frame back first.
                        try
                        {
                            original(renderer, binding.File, binding.Image, binding.Colour, binding.Alternate,
                                binding.ChopFeet, binding.Transparency);
                        }
                        catch (Exception ex) { LogFailure("visual removal", ex); }
                    }
                    bindings.Remove(renderer);
                }));
            }
            catch
            {
                for (int i = subscriptions.Count - 1; i >= 0; i--)
                {
                    try { subscriptions[i].Dispose(); }
                    catch (Exception ex) { log?.LogWarning("Visual subscription could not unwind: " + ex.Message); }
                }
                subscriptions.Clear();
                bool hookDisposed = hook == null;
                try { hook?.Dispose(); hookDisposed = true; }
                catch (Exception ex) { log?.LogWarning("Sprite hook could not unwind: " + ex.Message); }
                // If Dispose itself fails, keep its trampoline: with the tables cleared below, a
                // still-active detour passes every stock sprite through untouched.
                if (hookDisposed) { hook = null; original = null; }
                Array.Clear(artByVariant, 0, artByVariant.Length);
                Array.Clear(coveredFile, 0, coveredFile.Length);
                bindings.Clear();
                placement = null;
                throw;
            }
        }

        /// <summary>
        /// Each frame, on the Unity thread: repaint every bound renderer whose tag no longer matches
        /// what it shows (a placement, a load, a delete or a map close changed the tags since the
        /// last check), from its last native request.
        /// </summary>
        internal static void Refresh()
        {
            UnitPlacement route = placement;
            if (route == null) return;
            int revision = route.Revision;
            if (revision == lastRefreshRevision) return;
            staleBindings.Clear();
            pendingRefresh.Clear();
            foreach (KeyValuePair<SpriteRenderer, Binding> pair in bindings)
            {
                try
                {
                    SpriteRenderer renderer = pair.Key;
                    Binding binding = pair.Value;
                    if (renderer == null) { staleBindings.Add(renderer); continue; }
                    if (!binding.HasFrame || (uint)binding.File >= (uint)coveredFile.Length || !coveredFile[binding.File]) continue;
                    route.TryReadTag(binding.UnitId, out _, out UnitVariant variant, out _, out _);
                    bool shouldDraw = variant != null && variant.File.Gm == binding.File && artByVariant[variant.Index] != null;
                    if (binding.Drawn == shouldDraw && ReferenceEquals(binding.DrawnVariant, shouldDraw ? variant : null)) continue;
                    pendingRefresh.Add(new RefreshRequest(renderer, binding));
                }
                catch (Exception ex) { LogFailure("visual refresh", ex); }
            }
            foreach (SpriteRenderer stale in staleBindings) bindings.Remove(stale);
            foreach (RefreshRequest request in pendingRefresh)
            {
                try
                {
                    SpriteMapping.SetBodySprite(request.Renderer, request.File, request.Image, request.Colour,
                        request.Alternate, request.ChopFeet, request.Transparency);
                }
                catch (Exception ex) { LogFailure("visual refresh", ex); }
            }
            staleBindings.Clear();
            pendingRefresh.Clear();
            lastRefreshRevision = revision;
        }

        private static void LogFailure(string operation, Exception ex)
        {
            if (loggedOnce.Add("failure:" + operation))
                log?.LogError("Unit art " + operation + " failed; stock art is kept: " + ex);
        }

        private static void SetBodySpriteHook(SpriteRenderer renderer, int file, int image, int colour,
            bool alternateFrame, int chopFeet, int transparency)
        {
            original(renderer, file, image, colour, alternateFrame, chopFeet, transparency);
            Binding binding = null;
            if (!ReferenceEquals(renderer, null) && bindings.TryGetValue(renderer, out binding))
            {
                // Record every native paint, covered or not, so a later refresh can never replay a
                // stale request onto a renderer the game has reused for another sprite file.
                binding.File = file; binding.Image = image; binding.Colour = colour;
                binding.Alternate = alternateFrame; binding.ChopFeet = chopFeet;
                binding.Transparency = transparency; binding.HasFrame = true;
                binding.Drawn = false; binding.DrawnVariant = null;
            }
            if ((uint)file >= (uint)coveredFile.Length || renderer == null || !coveredFile[file] || binding == null) return;
            UnitVariant variant = null;
            try
            {
                UnitPlacement route = placement;
                if (route == null) return;
                if (!route.TryReadTag(binding.UnitId, out _, out variant, out _, out _) || variant.File.Gm != file) return;
                VariantArt art = artByVariant[variant.Index];
                if (art == null) return;
                // All six carrier files map image to slot image - 1 (SpriteMapping.getBodyImage).
                int slot = image - 1;
                if (slot < 0 || slot >= art.Normal.Length) return;
                FrameArt frame = (!alternateFrame ? null : art.Alternate[slot]) ?? art.Normal[slot];
                if (frame == null)
                {
                    if (missingSlotLogs < MissingSlotLogLimit && loggedOnce.Add($"missing:{variant.Index}:{slot}"))
                    {
                        missingSlotLogs++;
                        log.LogInfo($"{variant.DisplayName}: no frame for {variant.File.Name} slot {slot}; the stock frame is shown.");
                    }
                    return;
                }
                if (spriteLoader.instance != null)
                {
                    Sprite stock = spriteLoader.instance.GetGMSprite((GameGM)file, slot, alternateFrame);
                    if (!ReferenceEquals(renderer.sprite, stock))
                    {
                        if (loggedOnce.Add($"conflict:{file}"))
                            log.LogWarning($"{variant.DisplayName}: another mod already changed a {variant.File.Name} sprite; that result is left alone.");
                        return;
                    }
                }
                renderer.sprite = frame.Sprite;
                renderer.sharedMaterial = frame.ChopMaterials[chopFeet > 0 ? Math.Min(6, chopFeet / 4) : 0];
                binding.Drawn = true;
                binding.DrawnVariant = variant;
                if (loggedOnce.Add($"applied:{variant.Index}"))
                    log.LogInfo($"{variant.DisplayName}: first frame drawn over the {variant.Carrier} " +
                        $"({variant.File.Name} native slot {slot}).");
            }
            catch (Exception ex)
            {
                if (loggedOnce.Add($"error:{file}:{ex.GetType().Name}"))
                    log.LogError($"{variant?.DisplayName ?? "unit"}: frame failed, stock frame kept: {ex}");
            }
        }

        private sealed class Binding
        {
            internal int UnitId, File, Image, Colour, ChopFeet, Transparency;
            internal bool Alternate, HasFrame, Drawn;
            internal UnitVariant DrawnVariant;
            internal Chimp Chimp;
        }

        private readonly struct RefreshRequest
        {
            internal readonly SpriteRenderer Renderer;
            internal readonly int File, Image, Colour, ChopFeet, Transparency;
            internal readonly bool Alternate;

            internal RefreshRequest(SpriteRenderer renderer, Binding binding)
            {
                Renderer = renderer;
                File = binding.File; Image = binding.Image; Colour = binding.Colour;
                ChopFeet = binding.ChopFeet; Transparency = binding.Transparency;
                Alternate = binding.Alternate;
            }
        }

        private sealed class RendererReferenceComparer : IEqualityComparer<SpriteRenderer>
        {
            internal static readonly RendererReferenceComparer Instance = new RendererReferenceComparer();
            public bool Equals(SpriteRenderer x, SpriteRenderer y) => ReferenceEquals(x, y);
            public int GetHashCode(SpriteRenderer value) => RuntimeHelpers.GetHashCode(value);
        }
    }
}
