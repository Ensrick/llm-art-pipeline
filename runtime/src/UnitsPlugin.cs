using BepInEx;
using BepInEx.Configuration;
using BepInEx.Logging;
using SHCDESE.API.LowLevel;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using UnityEngine;
using ExtenderChimps = SHCDESE.Interop.eChimps;
using ExtenderGM = SHCDESE.Interop.GM;

namespace ByzantineUnits
{
    /// <summary>
    /// Map Editor placement and art for every unit in UnitCatalog. A unit shows this plugin's art
    /// only when it was placed through one of its editor buttons and its exact global unit ID was
    /// tagged; units placed with the stock tiles keep stock art, even standing next to a tagged one.
    /// Gameplay stays the carrier's - this plugin only ever changes what is drawn.
    ///
    /// Trimmed for this public example from a larger plugin: the original also carried an aura, an
    /// automated pitch-scooping behaviour, paid-recruitment integration, a developer preview "cheer"
    /// mode and voice-line routing. Those are gameplay/audio features, not the art pipeline's runtime
    /// route, and are cut here - see docs/RUNTIME.md for the full scope decision. What is below is
    /// the complete, load-bearing mechanism: check the catalog against the installed game, load each
    /// unit's atlas, install the identity route, and hook the sprite draw.
    /// </summary>
    [BepInPlugin(Guid, Name, Version)]
    [BepInDependency(ScriptExtenderGuid)]
    public sealed class UnitsPlugin : BaseUnityPlugin
    {
        public const string Guid = "ByzantineUnits";
        public const string Name = "Byzantine units";
        public const string Version = "0.1.0";
        private const string ScriptExtenderGuid = "000shcdese";

        // The game destroys the plugin's own object during startup, so the log, the settings and the
        // loaded art are held in static fields for the whole process.
        private static ManualLogSource log;
        private static string unitsDirectory;
        private static readonly HashSet<string> enabledUnits = new HashSet<string>(StringComparer.Ordinal);
        private static UnitPlacement placement;
        private static bool subscribed;

        private void Awake()
        {
            log = Logger;
            unitsDirectory = Path.Combine(Path.GetDirectoryName(Info.Location), "units");
            ConfigEntry<bool> master = Config.Bind("General", "Enabled", true,
                "Master switch. false = no editor buttons and every unit keeps its stock sprites. Takes effect at the next game start.");
            foreach (UnitVariant variant in UnitCatalog.Variants)
            {
                if (enabledUnits.Contains(variant.Unit)) continue;
                ConfigEntry<bool> entry = Config.Bind("Units", variant.Unit, true,
                    $"Editor button and art for the {variant.Unit} (carrier: {variant.Carrier}). Only units placed with this " +
                    "plugin's button are affected; takes effect at the next game start.");
                if (entry.Value) enabledUnits.Add(variant.Unit);
            }
            if (!master.Value)
            {
                log.LogInfo("Switched off in the config; no buttons, every unit keeps its stock sprites.");
                return;
            }
            if (subscribed) return;
            subscribed = true;
            CrusaderLibrary.Instance.LibraryLoaded += context => Start(log, context.ModuleHandle, context.Memory);
            log.LogInfo($"{Name} {Version} waiting for the Script Extender; units switched on: {string.Join(", ", enabledUnits)}.");
        }

        private static void Start(ManualLogSource logSource, IntPtr libraryHandle, ReadOnlySpan<byte> originalImage)
        {
            try
            {
                Shader shader = Shader.Find("Unlit/TeamColour");
                if (shader == null)
                {
                    logSource.LogError("The game's Unlit/TeamColour shader was not found; every unit stays stock.");
                    return;
                }
                var loaded = new List<VariantArt>();
                var timer = Stopwatch.StartNew();
                foreach (UnitVariant variant in UnitCatalog.Variants)
                {
                    if (!enabledUnits.Contains(variant.Unit) || !MatchesGame(variant, logSource)) continue;
                    string directory = Path.Combine(Path.Combine(unitsDirectory, variant.Folder.Replace('/', Path.DirectorySeparatorChar)),
                        variant.File.Name);
                    if (!Directory.Exists(directory))
                    {
                        logSource.LogInfo($"{variant.DisplayName}: no art installed yet; its button stays disabled.");
                        continue;
                    }
                    try
                    {
                        VariantArt art = UnitArtLoader.Load(directory, variant, shader);
                        loaded.Add(art);
                        logSource.LogInfo($"{variant.DisplayName}: {art.NormalCount} frames loaded for {variant.File.Name} " +
                            $"(manifest and SHA-256 verified; team colour: {art.TeamColour ?? "not stated"}). " +
                            "Slots without a frame keep the native art.");
                    }
                    catch (Exception ex)
                    {
                        logSource.LogError($"{variant.DisplayName}: art disabled, its button stays disabled and stock art stays. {ex.Message}");
                    }
                }
                logSource.LogInfo($"Unit art checked and loaded in {timer.ElapsedMilliseconds} ms.");
                if (loaded.Count == 0)
                {
                    logSource.LogInfo("No unit art is installed; no editor buttons, nothing to draw.");
                    return;
                }
                try { placement = new UnitPlacement(logSource); placement.Install(); }
                catch (Exception ex)
                {
                    placement = null; // Fail closed: no art can apply without exact identities.
                    logSource.LogError("Editor identity route unavailable; every unit keeps stock art. " + ex);
                    return;
                }
                UnitSprites.Install(logSource, loaded, placement);
                logSource.LogInfo("Units ready: SetBodySprite hook installed after the stock drawing code; exact tags only.");
            }
            catch (Exception ex)
            {
                // A failed start must not leave the save handler or the editor detours behind.
                placement?.Dispose();
                placement = null;
                logSource.LogError("Start-up failed; every unit keeps its stock sprites. " + ex);
                return;
            }
            try
            {
                UnitsDriver.Run(UnitSprites.Refresh);
            }
            catch (Exception ex)
            {
                logSource.LogError("Editor buttons could not start; tagged units keep their art. " + ex);
            }
        }

        /// <summary>
        /// Re-check the catalog against this install: the carrier file against the Script Extender's GM
        /// enum, the carrier type against its eChimps enum, and the editor tool against the game's
        /// Enums.eMappers. A mismatch leaves that variant off, so a Script Extender or game update that
        /// renumbers something disables the affected unit instead of silently drawing the wrong art.
        /// </summary>
        private static bool MatchesGame(UnitVariant variant, ManualLogSource logSource)
        {
            try
            {
                object gm = Enum.ToObject(typeof(ExtenderGM), variant.File.Gm);
                if (!Enum.IsDefined(typeof(ExtenderGM), gm) || gm.ToString() != variant.File.GmName)
                {
                    logSource.LogError($"{variant.DisplayName}: GM {variant.File.Gm} is not {variant.File.GmName} in this Script Extender; left off.");
                    return false;
                }
                object chimp = Enum.ToObject(typeof(ExtenderChimps), variant.Chimp);
                if (!Enum.IsDefined(typeof(ExtenderChimps), chimp) || chimp.ToString() != variant.ChimpName)
                {
                    logSource.LogError($"{variant.DisplayName}: unit type {variant.Chimp} is not {variant.ChimpName} in this Script Extender; left off.");
                    return false;
                }
                var mapper = (global::Enums.eMappers)Enum.Parse(typeof(global::Enums.eMappers), variant.MapperName);
                if ((int)mapper != variant.Mapper)
                {
                    logSource.LogError($"{variant.DisplayName}: {variant.MapperName} is {(int)mapper} in this game, not {variant.Mapper}; left off.");
                    return false;
                }
                return true;
            }
            catch (Exception ex)
            {
                logSource.LogError($"{variant.DisplayName}: could not check its carrier against the game; left off. {ex.Message}");
                return false;
            }
        }
    }
}
