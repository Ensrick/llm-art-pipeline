using BepInEx.Logging;
using MonoMod.RuntimeDetour;
using R3;
using SHCDESE.API;
using SHCDESE.EventAPI;
using SHCDESE.EventAPI.Units;
using SHCDESE.Interop;
using System;
using System.Collections.Generic;
using System.Reflection;
using System.Threading;

namespace ByzantineUnits
{
    /// <summary>
    /// Gives a unit our identity only when it was placed through one of our editor buttons: the
    /// button arms the carrier's native editor tool, and the synchronous native spawn inside that
    /// PlaceMapperItem call is tagged by its global unit ID. The native tool, the stock tiles and
    /// the unit's gameplay are unchanged.
    ///
    /// Trimmed for this public example: the original also tracked a per-unit Cataphract horse-coat
    /// appearance, a paid-recruitment reservation path and a group-order lookup. Those are cut here
    /// as gameplay features outside an art pipeline's scope; the identity route below - arm, place,
    /// tag, save/load, read back - is the complete, load-bearing mechanism and needs none of them.
    /// </summary>
    internal sealed class UnitPlacement : IDisposable
    {
        private delegate int StartMapper(int item);
        private delegate void PlaceMapper(int item, int x, int y, int size, int player,
            bool inGameNotEditor, bool constructingOnly, int mouseState);

        private readonly ManualLogSource log;
        private readonly UnitIdentities identities = new UnitIdentities();
        private readonly Dictionary<int, int> deleting = new Dictionary<int, int>();
        private readonly List<IDisposable> subscriptions = new List<IDisposable>();
        private readonly object engineLock;
        private Hook startHook, placeHook;
        private StartMapper startOriginal;
        private PlaceMapper placeOriginal;
        private bool saveRegistered;
        private UnitVariant arming, armed, placing;
        private int placementDepth, revision;

        internal UnitPlacement(ManualLogSource log)
        {
            this.log = log ?? throw new ArgumentNullException(nameof(log));
            engineLock = typeof(global::EngineInterface).GetField("threadLock", BindingFlags.Static | BindingFlags.NonPublic)
                ?.GetValue(null) ?? throw new MissingFieldException("EngineInterface.threadLock");
        }

        /// <summary>Changes whenever a tag is added, removed, loaded or cleared.</summary>
        internal int Revision => Volatile.Read(ref revision);

        /// <summary>The variant whose button armed the editor tool, while that exact tool is still active.</summary>
        internal UnitVariant ArmedVariant
        {
            get
            {
                UnitVariant current = armed;
                return current != null && MainControls.instance != null &&
                    MainControls.instance.CurrentAction == 7 && MainControls.instance.CurrentSubAction == current.Mapper
                    ? current : null;
            }
        }

        /// <summary>
        /// Read the live unit, its AI state, its facing (0-7) and its tag as one engine-locked
        /// snapshot. A tag applies only while the live unit still has the tagged global ID and is
        /// still the variant's carrier type.
        /// </summary>
        internal unsafe bool TryReadTag(int unitId, out int global, out UnitVariant variant, out int aiState, out int facing)
        {
            global = 0;
            variant = null;
            aiState = -1;
            facing = 0;
            if (unitId <= 0) return false;
            lock (engineLock)
            {
                if (!GameUnitManagerAPI.Instance.TryGetUnitById(unitId, out GameUnit* unit) ||
                    unit == null || unit->r_GlobalId == 0 || unit->r_GlobalId > int.MaxValue) return false;
                global = (int)unit->r_GlobalId;
                if (!identities.TryGet(global, out UnitVariant tagged) || (int)unit->r_UnitChimp != tagged.Chimp) return false;
                variant = tagged;
                aiState = (int)unit->r_AIState;
                facing = (int)unit->r_Direction & 7;
                return true;
            }
        }

        internal unsafe void Install()
        {
            if (saveRegistered) throw new InvalidOperationException("Unit placement is already installed.");
            // Keep the exact global IDs in the map or save file. The Script Extender calls the unload
            // callback when a map closes, so tags never leak into the next map; a file without our
            // data therefore starts with no tags. A duplicate identifier returns false, and running
            // without persistence would turn tagged units stock after a reload, so that is fatal.
            if (!ModSaveDataAPI.Instance.RegisterModDataHandler(UnitCatalog.SaveKey,
                context => identities.Save(),
                (bytes, context) =>
                {
                    try
                    {
                        identities.Load(bytes);
                        log.LogInfo($"Loaded {identities.Count} unit identities: {identities.Summary()}.");
                    }
                    catch (Exception ex)
                    {
                        // Fail closed: unreadable data must not leave the previous map's tags live.
                        lock (engineLock) identities.Clear();
                        log.LogError("Saved unit identities in this file were rejected; every unit keeps stock art. " + ex.Message);
                    }
                    Interlocked.Increment(ref revision);
                },
                () =>
                {
                    lock (engineLock) { identities.Clear(); deleting.Clear(); placementDepth = 0; placing = null; }
                    Interlocked.Increment(ref revision);
                    // The unload event can come from a native detour off the Unity thread, so only
                    // drop the session here; UnitSprites.Refresh puts the cursor sprite back.
                    armed = null;
                })) throw new InvalidOperationException($"Save handler identifier {UnitCatalog.SaveKey} is already registered.");
            saveRegistered = true;
            try { InstallHooks(); }
            catch { Dispose(); throw; }
        }

        private unsafe void InstallHooks()
        {
            subscriptions.Add(UnitR3EventHooks.OnUnitCreate.Observable.Subscribe(args =>
            {
                if (args.Phase != EventHookPhase.Post || args.ReturnValue <= 0 || args.ReturnValue > int.MaxValue) return;
                int id = (int)args.ReturnValue;
                int global;
                UnitVariant variant;
                lock (engineLock)
                {
                    variant = placing;
                    if (placementDepth <= 0 || variant == null || (int)args.UnitType != variant.Chimp ||
                        !GameUnitManagerAPI.Instance.TryGetUnitById(id, out GameUnit* unit) || unit == null ||
                        (int)unit->r_UnitChimp != variant.Chimp ||
                        unit->r_GlobalId == 0 || unit->r_GlobalId > int.MaxValue) return;
                    global = (int)unit->r_GlobalId;
                    try
                    {
                        if (identities.Add(global, variant)) Interlocked.Increment(ref revision);
                    }
                    catch (InvalidOperationException ex)
                    {
                        log.LogWarning("Placed unit was not tagged: " + ex.Message);
                        return;
                    }
                }
                log.LogInfo($"{variant.DisplayName} placed in the editor: unit {id}, global {global}, tile {args.WorldTileX},{args.WorldTileY}.");
            }));
            subscriptions.Add(UnitR3EventHooks.OnUnitDelete.Observable.Subscribe(args =>
            {
                int id = (int)args.UnitId;
                lock (engineLock)
                {
                    if (args.Phase == EventHookPhase.Pre)
                    {
                        deleting[id] = GameUnitManagerAPI.Instance.TryGetUnitById(id, out GameUnit* before) && before != null &&
                            before->r_GlobalId > 0 && before->r_GlobalId <= int.MaxValue ? (int)before->r_GlobalId : 0;
                        return;
                    }
                    if (!deleting.TryGetValue(id, out int global)) return;
                    deleting.Remove(id);
                    // A completed delete can leave the live slot briefly present: keep the tag only
                    // while that exact unit is still alive in the slot.
                    if (global > 0 &&
                        (!GameUnitManagerAPI.Instance.TryGetUnitById(id, out GameUnit* after) || after == null ||
                         after->r_GlobalId != (uint)global || after->r_AliveState == 0) &&
                        identities.Remove(global))
                        Interlocked.Increment(ref revision);
                }
            }));

            const BindingFlags flags = BindingFlags.Public | BindingFlags.Static;
            MethodInfo start = typeof(global::EngineInterface).GetMethod("StartMapperItem", flags)
                ?? throw new MissingMethodException("EngineInterface.StartMapperItem");
            MethodInfo place = typeof(global::EngineInterface).GetMethod("PlaceMapperItem", flags)
                ?? throw new MissingMethodException("EngineInterface.PlaceMapperItem");
            startHook = new Hook(start, (StartMapper)StartMapperDetour);
            startOriginal = startHook.GenerateTrampoline<StartMapper>();
            placeHook = new Hook(place, (PlaceMapper)PlaceMapperDetour);
            placeOriginal = placeHook.GenerateTrampoline<PlaceMapper>();
            log.LogInfo("Editor identity route ready; units placed with the stock tiles stay stock.");
        }

        public void Dispose()
        {
            Disarm();
            try { placeHook?.Dispose(); placeHook = null; placeOriginal = null; }
            catch (Exception ex) { log.LogWarning("Place hook could not unwind: " + ex.Message); }
            try { startHook?.Dispose(); startHook = null; startOriginal = null; }
            catch (Exception ex) { log.LogWarning("Arm hook could not unwind: " + ex.Message); }
            for (int i = subscriptions.Count - 1; i >= 0; i--)
            {
                try { subscriptions[i].Dispose(); }
                catch (Exception ex) { log.LogWarning("Event subscription could not unwind: " + ex.Message); }
            }
            subscriptions.Clear();
            if (saveRegistered)
            {
                saveRegistered = false;
                try
                {
                    if (!ModSaveDataAPI.Instance.UnregisterModDataHandler(UnitCatalog.SaveKey))
                        log.LogWarning("Save handler was no longer registered during unwind.");
                }
                catch (Exception ex) { log.LogWarning("Save handler could not unwind: " + ex.Message); }
            }
        }

        /// <summary>Called only by our editor buttons, around the native arming action.</summary>
        internal void Arm(UnitVariant variant, Action nativeArm)
        {
            Disarm();
            arming = variant ?? throw new ArgumentNullException(nameof(variant));
            try { nativeArm(); }
            finally { arming = null; }
        }

        /// <summary>Cancel our session when the editor leaves the troop tabs or switches tools.</summary>
        internal void Sync(bool troopTabVisible)
        {
            if (armed != null && (!troopTabVisible || ArmedVariant == null)) Disarm();
        }

        private void Disarm() => armed = null;

        private int StartMapperDetour(int item)
        {
            // Every editor tool, including a stock tile for the same carrier, passes here first.
            // Only our button sets arming, so a stock tile always ends our session.
            Disarm();
            int result = startOriginal(item);
            UnitVariant variant = arming;
            if (variant != null && item == variant.Mapper && result >= 0) armed = variant;
            return result;
        }

        private void PlaceMapperDetour(int item, int x, int y, int size, int player,
            bool inGameNotEditor, bool constructingOnly, int mouseState)
        {
            UnitVariant variant = ArmedVariant;
            // EditorDirector's troop click is action 7 with mouse state 3, in the editor, not a preview.
            if (variant == null || item != variant.Mapper || inGameNotEditor || constructingOnly || mouseState != 3)
            {
                placeOriginal(item, x, y, size, player, inGameNotEditor, constructingOnly, mouseState);
                return;
            }
            // EditorDirector calls PlaceMapperItem once per unit, including the Shift/Ctrl/Alt loops.
            // The native spawn is synchronous, so OnUnitCreate(Post) can tag only this call's unit.
            lock (engineLock) { placementDepth++; placing = variant; }
            try { placeOriginal(item, x, y, size, player, inGameNotEditor, constructingOnly, mouseState); }
            finally
            {
                lock (engineLock)
                {
                    placementDepth--;
                    if (placementDepth <= 0) { placementDepth = 0; placing = null; }
                }
            }
        }
    }
}
