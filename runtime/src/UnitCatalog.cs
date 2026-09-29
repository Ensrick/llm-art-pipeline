using System;
using System.Collections.Generic;

namespace ByzantineUnits
{
    /// <summary>A stock sprite file one of our units draws over: its name, GM enum entry and highest slot.</summary>
    public sealed class CarrierFile
    {
        public CarrierFile(string name, string gmName, int gm, int maxSlot, params SlotBlock[] blocks)
        {
            Name = name; GmName = gmName; Gm = gm; MaxSlot = maxSlot; Blocks = blocks;
        }

        /// <summary>The game's sprite name prefix, also the atlas folder name.</summary>
        public string Name { get; }
        /// <summary>The name of the file's entry in the Script Extender's and the game's GM enums.</summary>
        public string GmName { get; }
        /// <summary>The GM number; SpriteMapping.SetBodySprite receives it as "file".</summary>
        public int Gm { get; }
        /// <summary>Highest slot the game registers for the file (spriteLoader.addGMFile).</summary>
        public int MaxSlot { get; }
        /// <summary>Named slot blocks from the carrier docs, used only to report atlas coverage.</summary>
        public SlotBlock[] Blocks { get; }
    }

    /// <summary>One animation block of a carrier file: slots First to Last inclusive.</summary>
    public sealed class SlotBlock
    {
        public SlotBlock(string name, int first, int last)
        {
            Name = name; First = first; Last = last;
        }

        public string Name { get; }
        public int First { get; }
        public int Last { get; }
    }

    /// <summary>
    /// One unit the editor can place: a Byzantine unit, or one Varangian loadout. Each has its own
    /// button, its own saved identity (key plus loadout) and its own atlas.
    /// </summary>
    public sealed class UnitVariant
    {
        internal UnitVariant(int index, string key, string loadout, string unit, string label,
            string manifestUnit, string carrier, string chimpName, int chimp, string mapperName, int mapper,
            CarrierFile file, string folder)
        {
            Index = index; Key = key; Loadout = loadout; Unit = unit; Label = label;
            ManifestUnit = manifestUnit; Carrier = carrier; ChimpName = chimpName; Chimp = chimp;
            MapperName = mapperName; Mapper = mapper; File = file; Folder = folder;
        }

        /// <summary>Position in <see cref="UnitCatalog.Variants"/>; never persisted.</summary>
        public int Index { get; }
        /// <summary>Stable saved key, for example byzantine:varangian.</summary>
        public string Key { get; }
        /// <summary>Varangian loadout (danish_axe, sword_shield, one_hand_axe); null for every other unit.</summary>
        public string Loadout { get; }
        /// <summary>Unit name, as in the art folders (Vanguard, FireSiphoner, ...).</summary>
        public string Unit { get; }
        /// <summary>Editor button text; a newline splits it into two lines.</summary>
        public string Label { get; }
        /// <summary>The "unit" value build_preview_assets.py writes into this atlas's manifest.json.</summary>
        public string ManifestUnit { get; }
        public string Carrier { get; }
        /// <summary>The carrier's name in SHCDESE.Interop.eChimps and the game's Enums.eChimps.</summary>
        public string ChimpName { get; }
        public int Chimp { get; }
        /// <summary>The carrier's Map Editor tool in the game's Enums.eMappers.</summary>
        public string MapperName { get; }
        public int Mapper { get; }
        public CarrierFile File { get; }
        /// <summary>Folder under the installed units\ directory holding button.png and the atlas folder.</summary>
        public string Folder { get; }
        /// <summary>Highest slot this variant's atlas may use.</summary>
        public int MaxArtSlot => File.MaxSlot;

        /// <summary>Human-readable name for logs: "Varangian (danish_axe)".</summary>
        public string DisplayName => Loadout == null ? Unit : Unit + " (" + Loadout + ")";
    }

    /// <summary>
    /// Every unit this plugin can place. Numbers were checked against the installed Script Extender
    /// (SHCDESE.Interop.GM, SHCDESE.Interop.eChimps) and the game's own Assembly-CSharp
    /// (Enums.eMappers, Enums.eChimps, Enums.GM); UnitsPlugin.MatchesGame re-checks each one at
    /// startup, so a Script Extender or game update that renumbers something disables that unit
    /// instead of drawing the wrong art. Slot blocks are docs/SHCDE.md's carrier tables.
    /// </summary>
    public static class UnitCatalog
    {
        /// <summary>ModSaveDataAPI identifier for this plugin's saved identities; pick your own,
        /// distinct from any other plugin's, so two plugins' saves never collide.</summary>
        public const string SaveKey = "ByzantineUnits.Identities";
        public const string DanishAxe = "danish_axe", SwordShield = "sword_shield", OneHandAxe = "one_hand_axe";

        // CARRIER_SKIRMISHER.md, "Slot map".
        internal static readonly CarrierFile Skirmisher = new CarrierFile("body_skirmisher", "GM_BODY_BEDOUIN_SKIRMISHER", 212, 2427,
            new SlotBlock("walk, javelin", 0, 127), new SlotBlock("walk, no javelin", 128, 255),
            new SlotBlock("run, javelin", 256, 383), new SlotBlock("run, no javelin", 384, 511),
            new SlotBlock("melee", 512, 767), new SlotBlock("dig/fill moat", 768, 887),
            new SlotBlock("climb", 888, 983), new SlotBlock("idle, javelin", 984, 1239),
            new SlotBlock("idle, no javelin", 1240, 1495), new SlotBlock("throw", 1496, 1751),
            new SlotBlock("death 111", 1752, 1943), new SlotBlock("death 114-116", 1944, 2135),
            new SlotBlock("death 113", 2172, 2363), new SlotBlock("fall from ladder", 2364, 2427));

        // CARRIER_ARCHER.md, "Slot map".
        internal static readonly CarrierFile Archer = new CarrierFile("body_archer", "GM_BODY_ARCHER", 18, 1751,
            new SlotBlock("walk", 0, 127), new SlotBlock("run", 128, 255), new SlotBlock("draw", 256, 319),
            new SlotBlock("aim, level", 320, 327), new SlotBlock("release, level", 384, 447),
            new SlotBlock("aim, up", 448, 479), new SlotBlock("release, up", 480, 543),
            new SlotBlock("aim, down", 544, 575), new SlotBlock("release, down", 576, 639),
            new SlotBlock("celebrate", 640, 687), new SlotBlock("idle", 688, 703),
            new SlotBlock("sit and rest", 704, 718), new SlotBlock("melee", 792, 887),
            new SlotBlock("climb", 888, 983), new SlotBlock("fall from ladder", 984, 1047),
            new SlotBlock("dig/fill moat", 1048, 1175), new SlotBlock("death, arrow", 1176, 1367),
            new SlotBlock("death, forward", 1368, 1559), new SlotBlock("death, backward", 1560, 1751));

        // CARRIER_FIRE_THROWER.md, "Slot map".
        internal static readonly CarrierFile Grenadier = new CarrierFile("body_arab_grenadier", "GM_BODY_ARAB_GRENADIER", 196, 1255,
            new SlotBlock("walk", 0, 127), new SlotBlock("melee", 128, 383), new SlotBlock("throw", 384, 639),
            new SlotBlock("idle", 640, 679), new SlotBlock("death 111", 680, 871),
            new SlotBlock("death 113", 872, 1063), new SlotBlock("death 112-116", 1064, 1255));

        // CARRIER_SWORDSMAN.md, "Slot map"; 416-447 do not exist in the native file.
        internal static readonly CarrierFile Swordsman = new CarrierFile("body_swordsman", "GM_BODY_SWORDSMAN", 42, 1087,
            new SlotBlock("walk", 0, 127), new SlotBlock("idle", 128, 223), new SlotBlock("melee, chop", 224, 319),
            new SlotBlock("melee, lunge", 320, 415), new SlotBlock("celebrate", 448, 511),
            new SlotBlock("death A", 512, 703), new SlotBlock("death C", 704, 895), new SlotBlock("death B, arrow", 896, 1087));

        // INTEGRATION_CLAUDE_UNITS.md, Cataphract table (CARRIER_KNIGHT.md): family A = even unit
        // index (mace), family B = odd (lance); 256-383 and 976-1103 do not exist.
        internal static readonly CarrierFile Knight = new CarrierFile("body_knight", "GM_BODY_KNIGHT", 44, 1823,
            new SlotBlock("walk, mace", 0, 127), new SlotBlock("gallop, mace", 128, 255),
            new SlotBlock("idle, mace", 384, 479), new SlotBlock("celebrate, mace", 480, 575),
            new SlotBlock("melee, mace", 576, 719), new SlotBlock("walk, lance", 720, 847),
            new SlotBlock("gallop, lance", 848, 975), new SlotBlock("idle, lance", 1104, 1199),
            new SlotBlock("celebrate, lance", 1200, 1295), new SlotBlock("melee, lance", 1296, 1439),
            new SlotBlock("death A (111)", 1440, 1631), new SlotBlock("death B (112-116)", 1632, 1823));

        // INTEGRATION_CLAUDE_UNITS.md, Icon Bearer (CARRIER_BEDOUIN_HEALER.md); 128-383 are never requested.
        internal static readonly CarrierFile BedouinHealer = new CarrierFile("body_bedouin_healer", "GM_BODY_BEDOUIN_HEALER", 209, 1599,
            new SlotBlock("walk", 0, 127), new SlotBlock("heal (blessing)", 384, 639), new SlotBlock("idle", 640, 895),
            new SlotBlock("death, arrow", 896, 1087), new SlotBlock("death, doubled over A", 1088, 1279),
            new SlotBlock("death, doubled over B", 1280, 1471), new SlotBlock("run", 1472, 1599));

        public static readonly UnitVariant[] Variants =
        {
            new UnitVariant(0, "byzantine:vanguard", null, "Vanguard", "Vanguard", "Vanguard",
                "Bedouin Skirmisher", "CHIMP_TYPE_BEDOUIN_SKIRMISHER", 82, "MAPPER_PEOPLE_BEDOUIN_SKIRMISHER", 404,
                Skirmisher, "Vanguard"),
            new UnitVariant(1, "byzantine:sentinel", null, "Sentinel", "Sentinel", "Sentinel",
                "Archer", "CHIMP_TYPE_ARCHER", 22, "MAPPER_PEOPLE_ARCHERS", 270,
                Archer, "Sentinel"),
            new UnitVariant(2, "byzantine:fire_siphoner", null, "FireSiphoner", "Fire\nSiphoner", "FireSiphoner",
                "Arabian grenadier (Fire Thrower)", "CHIMP_TYPE_ARAB_GRENADIER", 76, "MAPPER_PEOPLE_ARAB_GRENADIER", 356,
                Grenadier, "FireSiphoner"),
            new UnitVariant(3, "byzantine:cataphract", null, "Cataphract", "Cataphract", "Cataphract",
                "Knight", "CHIMP_TYPE_KNIGHT", 28, "MAPPER_PEOPLE_KNIGHTS", 276,
                Knight, "Cataphract"),
            new UnitVariant(4, "byzantine:icon_bearer", null, "IconBearer", "Icon\nBearer", "IconBearer",
                "Bedouin healer", "CHIMP_TYPE_BEDOUIN_HEALER", 79, "MAPPER_PEOPLE_BEDOUIN_HEALER", 401,
                BedouinHealer, "IconBearer"),
            new UnitVariant(5, "byzantine:varangian", DanishAxe, "Varangian", "Varangian\nDanish axe", "Varangian/" + DanishAxe,
                "Swordsman", "CHIMP_TYPE_SWORDSMAN", 27, "MAPPER_PEOPLE_SWORDSMEN", 275,
                Swordsman, "Varangian/" + DanishAxe),
            new UnitVariant(6, "byzantine:varangian", SwordShield, "Varangian", "Varangian\nsword+shield", "Varangian/" + SwordShield,
                "Swordsman", "CHIMP_TYPE_SWORDSMAN", 27, "MAPPER_PEOPLE_SWORDSMEN", 275,
                Swordsman, "Varangian/" + SwordShield),
            new UnitVariant(7, "byzantine:varangian", OneHandAxe, "Varangian", "Varangian\n1-hand axe", "Varangian/" + OneHandAxe,
                "Swordsman", "CHIMP_TYPE_SWORDSMAN", 27, "MAPPER_PEOPLE_SWORDSMEN", 275,
                Swordsman, "Varangian/" + OneHandAxe),
        };

        /// <summary>Only the Varangian carries a loadout; every other key must have none.</summary>
        public static bool TryFind(string key, string loadout, out UnitVariant variant)
        {
            foreach (UnitVariant candidate in Variants)
                if (string.Equals(candidate.Key, key, StringComparison.Ordinal) &&
                    string.Equals(candidate.Loadout, loadout, StringComparison.Ordinal))
                {
                    variant = candidate;
                    return true;
                }
            variant = null;
            return false;
        }

        /// <summary>Every GM number any variant draws over, once.</summary>
        public static IEnumerable<int> CoveredGms()
        {
            var seen = new HashSet<int>();
            foreach (UnitVariant variant in Variants)
                if (seen.Add(variant.File.Gm)) yield return variant.File.Gm;
        }
    }
}
