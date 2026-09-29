using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;

namespace ByzantineUnits
{
    /// <summary>
    /// Saved identities for units placed through our editor buttons: global unit ID to catalog
    /// variant (key plus Varangian loadout). Native unit slots are recycled, so only the game's
    /// global unit ID can tell our unit from an ordinary carrier after save and load.
    /// </summary>
    public sealed class UnitIdentities
    {
        // Version 1: "BZUN", version, count, then sorted entries of (global ID, key length, ASCII
        // key, loadout length, ASCII loadout). Keys are stored as text so the catalog order can change.
        private const int Magic = 0x4E555A42; // BZUN
        private const int Version = 1;
        private const int MaxUnits = 100000;
        private const int MaxTextBytes = 64;
        private readonly object gate = new object();
        private Dictionary<int, UnitVariant> units = new Dictionary<int, UnitVariant>();

        public int Count { get { lock (gate) return units.Count; } }

        /// <summary>The variant saved for an exact global ID; false for every other unit.</summary>
        public bool TryGet(int global, out UnitVariant variant)
        {
            variant = null;
            if (global <= 0) return false;
            lock (gate) return units.TryGetValue(global, out variant);
        }

        /// <summary>Tag a global ID. A global ID never changes variant; false when already tagged.</summary>
        public bool Add(int global, UnitVariant variant)
        {
            if (global <= 0) throw new ArgumentOutOfRangeException(nameof(global));
            if (variant == null || !UnitCatalog.TryFind(variant.Key, variant.Loadout, out UnitVariant known) ||
                !ReferenceEquals(known, variant)) throw new ArgumentException("Not a catalog variant.", nameof(variant));
            lock (gate)
            {
                if (units.TryGetValue(global, out UnitVariant existing))
                {
                    if (!ReferenceEquals(existing, variant))
                        throw new InvalidOperationException($"Global unit {global} is already a {existing.DisplayName}.");
                    return false;
                }
                units.Add(global, variant);
                return true;
            }
        }

        public bool Remove(int global) { lock (gate) return units.Remove(global); }
        public void Clear() { lock (gate) units.Clear(); }

        /// <summary>Counts per variant, for log lines.</summary>
        public string Summary()
        {
            lock (gate)
            {
                if (units.Count == 0) return "none";
                return string.Join(", ", units.Values.GroupBy(v => v.DisplayName).OrderBy(g => g.Key, StringComparer.Ordinal)
                    .Select(g => g.Count() + " " + g.Key));
            }
        }

        /// <summary>Always returns a full payload, even with no units, so a save overwrites stale data.</summary>
        public byte[] Save()
        {
            lock (gate)
            using (var stream = new MemoryStream())
            using (var writer = new BinaryWriter(stream))
            {
                writer.Write(Magic);
                writer.Write(Version);
                writer.Write(units.Count);
                foreach (KeyValuePair<int, UnitVariant> pair in units.OrderBy(p => p.Key))
                {
                    writer.Write(pair.Key);
                    WriteText(writer, pair.Value.Key);
                    WriteText(writer, pair.Value.Loadout ?? "");
                }
                writer.Flush();
                return stream.ToArray();
            }
        }

        /// <summary>
        /// Validate the whole payload before replacing the live tags. Throws InvalidDataException for
        /// any unknown version, key, loadout, duplicate, truncation or trailing byte; the live tags are
        /// then unchanged and the caller decides how to fail closed.
        /// </summary>
        public void Load(byte[] bytes)
        {
            if (bytes == null) throw new ArgumentNullException(nameof(bytes));
            var loaded = new Dictionary<int, UnitVariant>();
            using (var stream = new MemoryStream(bytes, false))
            using (var reader = new BinaryReader(stream))
            {
                try
                {
                    if (reader.ReadInt32() != Magic) throw new InvalidDataException("Not Byzantine unit identity data.");
                    int version = reader.ReadInt32();
                    if (version != Version) throw new InvalidDataException($"Unsupported identity data version {version}.");
                    int count = reader.ReadInt32();
                    if (count < 0 || count > MaxUnits) throw new InvalidDataException($"Invalid identity count {count}.");
                    for (int i = 0; i < count; i++)
                    {
                        int global = reader.ReadInt32();
                        string key = ReadText(reader, allowEmpty: false);
                        string loadout = ReadText(reader, allowEmpty: true);
                        if (global <= 0) throw new InvalidDataException($"Invalid global unit ID {global}.");
                        if (!UnitCatalog.TryFind(key, loadout.Length == 0 ? null : loadout, out UnitVariant variant))
                            throw new InvalidDataException($"Unknown unit '{key}' with loadout '{loadout}'.");
                        if (loaded.ContainsKey(global)) throw new InvalidDataException($"Global unit ID {global} appears twice.");
                        loaded.Add(global, variant);
                    }
                    if (stream.Position != stream.Length) throw new InvalidDataException("Trailing identity data.");
                }
                catch (EndOfStreamException ex)
                {
                    throw new InvalidDataException("Truncated identity data.", ex);
                }
            }
            lock (gate) units = loaded;
        }

        private static void WriteText(BinaryWriter writer, string text)
        {
            byte[] data = Encoding.ASCII.GetBytes(text);
            if (data.Length > MaxTextBytes) throw new InvalidOperationException("Identity text is too long: " + text);
            writer.Write((byte)data.Length);
            writer.Write(data);
        }

        private static string ReadText(BinaryReader reader, bool allowEmpty)
        {
            int length = reader.ReadByte();
            if (length > MaxTextBytes || (length == 0 && !allowEmpty))
                throw new InvalidDataException($"Invalid identity text length {length}.");
            byte[] data = reader.ReadBytes(length);
            if (data.Length != length) throw new EndOfStreamException();
            foreach (byte b in data)
                if (!(b >= (byte)'a' && b <= (byte)'z') && !(b >= (byte)'0' && b <= (byte)'9') && b != (byte)'_' && b != (byte)':')
                    throw new InvalidDataException("Identity text has an invalid character.");
            return Encoding.ASCII.GetString(data);
        }
    }
}
