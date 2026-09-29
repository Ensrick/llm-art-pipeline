using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Security.Cryptography;
using System.Text;

namespace ByzantineUnits
{
    /// <summary>One atlas page as manifest.json lists it.</summary>
    public sealed class ManifestPage
    {
        public ManifestPage(string name, string mask, int width, int height, string sha256, string maskSha256)
        {
            Name = name; Mask = mask; Width = width; Height = height; Sha256 = sha256; MaskSha256 = maskSha256;
        }

        public string Name { get; }
        public string Mask { get; }
        public int Width { get; }
        public int Height { get; }
        public string Sha256 { get; }
        public string MaskSha256 { get; }
    }

    /// <summary>
    /// manifest.json of one atlas folder, written by tools/pack_atlas.py. No Unity types, so a
    /// separate command-line validator can link this same class and check an atlas without starting
    /// the game - which is exactly what makes "the plugin accepts it" a testable claim.
    /// </summary>
    public sealed class AtlasManifest
    {
        public const string Schema = "sprite_atlas_manifest/1";

        private AtlasManifest(string unit, string file, int normal, int alternate, string framesSha256,
            string teamColour, List<ManifestPage> pages)
        {
            Unit = unit; File = file; Normal = normal; Alternate = alternate; FramesSha256 = framesSha256;
            TeamColour = teamColour; Pages = pages;
        }

        public string Unit { get; }
        public string File { get; }
        public int Normal { get; }
        public int Alternate { get; }
        public string FramesSha256 { get; }
        public string TeamColour { get; }
        public IReadOnlyList<ManifestPage> Pages { get; }

        /// <summary>Parse and check the fields the plugin relies on; throws InvalidDataException.</summary>
        public static AtlasManifest Parse(string json, UnitVariant variant)
        {
            if (!(Json.Parse(json) is Dictionary<string, object> root))
                throw new InvalidDataException("manifest.json is not a JSON object.");
            string schema = Text(root, "schema");
            if (schema != Schema) throw new InvalidDataException($"manifest schema is '{schema}', expected '{Schema}'.");
            string unit = Text(root, "unit"), file = Text(root, "file");
            if (unit != variant.ManifestUnit)
                throw new InvalidDataException($"manifest is for unit '{unit}', expected '{variant.ManifestUnit}'.");
            if (file != variant.File.Name)
                throw new InvalidDataException($"manifest is for file '{file}', expected '{variant.File.Name}'.");
            if (!(root.TryGetValue("pages", out object pagesValue) && pagesValue is List<object> pageList) || pageList.Count == 0)
                throw new InvalidDataException("manifest lists no pages.");
            var pages = new List<ManifestPage>();
            for (int i = 0; i < pageList.Count; i++)
            {
                if (!(pageList[i] is Dictionary<string, object> page)) throw new InvalidDataException($"manifest page {i} is not an object.");
                var entry = new ManifestPage(Text(page, "name"), Text(page, "mask"), Int(page, "width"), Int(page, "height"),
                    Hash(page, "sha256"), Hash(page, "maskSha256"));
                // The loader reads page0.png, page1.png, ... in order, so the manifest must list exactly those.
                if (entry.Name != $"page{i}.png" || entry.Mask != $"page{i}_m.png")
                    throw new InvalidDataException($"manifest page {i} is '{entry.Name}'/'{entry.Mask}', expected page{i}.png/page{i}_m.png.");
                pages.Add(entry);
            }
            string teamColour = root.TryGetValue("teamColour", out object colour) ? colour as string : null;
            return new AtlasManifest(unit, file, Int(root, "normal"), Int(root, "alternate"), Hash(root, "framesSha256"),
                teamColour, pages);
        }

        /// <summary>Upper-case hex SHA-256, as build_preview_assets.py writes it.</summary>
        public static string Sha256(byte[] data)
        {
            using (SHA256 sha = SHA256.Create())
            {
                byte[] hash = sha.ComputeHash(data);
                var text = new StringBuilder(hash.Length * 2);
                foreach (byte b in hash) text.Append(b.ToString("X2", CultureInfo.InvariantCulture));
                return text.ToString();
            }
        }

        /// <summary>Width and height from a PNG's IHDR chunk.</summary>
        public static (int Width, int Height) PngSize(byte[] data, string label)
        {
            if (data == null || data.Length < 24 || data[0] != 0x89 || data[1] != (byte)'P' || data[2] != (byte)'N' ||
                data[3] != (byte)'G' || data[12] != (byte)'I' || data[13] != (byte)'H' || data[14] != (byte)'D' || data[15] != (byte)'R')
                throw new InvalidDataException("Not a PNG file: " + label);
            int width = data[16] << 24 | data[17] << 16 | data[18] << 8 | data[19];
            int height = data[20] << 24 | data[21] << 16 | data[22] << 8 | data[23];
            return (width, height);
        }

        /// <summary>
        /// Read and verify a whole atlas folder: every page, mask and frames.tsv must match the
        /// manifest's SHA-256, sizes must agree, no unlisted page may exist, and frames.tsv must parse
        /// within the variant's slots (the carrier's, plus any idle clips) with the manifest's frame
        /// counts. Returns the verified bytes.
        /// </summary>
        public static VerifiedAtlas ReadVerified(string directory, UnitVariant variant)
        {
            string manifestPath = Path.Combine(directory, "manifest.json");
            if (!System.IO.File.Exists(manifestPath)) throw new FileNotFoundException("No manifest.json.", manifestPath);
            AtlasManifest manifest = Parse(System.IO.File.ReadAllText(manifestPath, Encoding.UTF8), variant);
            if (System.IO.File.Exists(Path.Combine(directory, $"page{manifest.Pages.Count}.png")))
                throw new InvalidDataException($"page{manifest.Pages.Count}.png exists but the manifest lists {manifest.Pages.Count} page(s).");
            var colours = new List<byte[]>();
            var masks = new List<byte[]>();
            var sizes = new List<(int Width, int Height)>();
            foreach (ManifestPage page in manifest.Pages)
            {
                byte[] colour = ReadMatching(directory, page.Name, page.Sha256);
                byte[] mask = ReadMatching(directory, page.Mask, page.MaskSha256);
                (int width, int height) = PngSize(colour, page.Name);
                if (PngSize(mask, page.Mask) != (width, height))
                    throw new InvalidDataException($"{page.Name} and {page.Mask} differ in size.");
                if (width != page.Width || height != page.Height)
                    throw new InvalidDataException($"{page.Name} is {width}x{height}; the manifest says {page.Width}x{page.Height}.");
                if (width > 4096 || height > 4096) throw new InvalidDataException($"{page.Name} is {width}x{height}, over 4096.");
                colours.Add(colour);
                masks.Add(mask);
                sizes.Add((width, height));
            }
            byte[] table = ReadMatching(directory, "frames.tsv", manifest.FramesSha256);
            // The carrier's slots, plus the variant's idle-clip slots above them (IDLE_CLIPS.md).
            List<FrameEntry> frames = FrameTable.Parse(Encoding.UTF8.GetString(table), sizes, variant.MaxArtSlot);
            int normal = 0;
            foreach (FrameEntry frame in frames) if (!frame.Alternate) normal++;
            if (normal != manifest.Normal || frames.Count - normal != manifest.Alternate)
                throw new InvalidDataException($"frames.tsv has {normal} frames + {frames.Count - normal} in-betweens; " +
                    $"the manifest says {manifest.Normal} + {manifest.Alternate}.");
            return new VerifiedAtlas(manifest, colours, masks, frames);
        }

        private static byte[] ReadMatching(string directory, string name, string expected)
        {
            string path = Path.Combine(directory, name);
            if (!System.IO.File.Exists(path)) throw new FileNotFoundException("Missing " + name + ".", path);
            byte[] data = System.IO.File.ReadAllBytes(path);
            string actual = Sha256(data);
            if (!string.Equals(actual, expected, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException($"{name} does not match its manifest hash.");
            return data;
        }

        private static string Text(Dictionary<string, object> obj, string name)
        {
            if (!obj.TryGetValue(name, out object value) || !(value is string text) || text.Length == 0)
                throw new InvalidDataException($"manifest field '{name}' is missing or not text.");
            return text;
        }

        private static int Int(Dictionary<string, object> obj, string name)
        {
            if (!obj.TryGetValue(name, out object value) || !(value is double number) ||
                number < 0 || number > int.MaxValue || Math.Floor(number) != number)
                throw new InvalidDataException($"manifest field '{name}' is missing or not a whole number.");
            return (int)number;
        }

        private static string Hash(Dictionary<string, object> obj, string name)
        {
            string text = Text(obj, name);
            if (text.Length != 64) throw new InvalidDataException($"manifest field '{name}' is not a SHA-256.");
            foreach (char c in text)
                if (!Uri.IsHexDigit(c)) throw new InvalidDataException($"manifest field '{name}' is not a SHA-256.");
            return text;
        }
    }

    /// <summary>An atlas folder whose bytes matched its manifest; the loader decodes these exact bytes.</summary>
    public sealed class VerifiedAtlas
    {
        internal VerifiedAtlas(AtlasManifest manifest, List<byte[]> colours, List<byte[]> masks, List<FrameEntry> frames)
        {
            Manifest = manifest; Colours = colours; Masks = masks; Frames = frames;
        }

        public AtlasManifest Manifest { get; }
        public IReadOnlyList<byte[]> Colours { get; }
        public IReadOnlyList<byte[]> Masks { get; }
        public IReadOnlyList<FrameEntry> Frames { get; }
    }

    /// <summary>
    /// A small strict JSON reader (objects, arrays, strings, numbers, true, false, null), enough for
    /// the manifests. .NET Framework on the game's Mono has no built-in JSON parser we can rely on.
    /// Objects become Dictionary&lt;string, object&gt;, arrays List&lt;object&gt;, numbers double.
    /// </summary>
    public static class Json
    {
        public static object Parse(string text)
        {
            if (text == null) throw new ArgumentNullException(nameof(text));
            int at = 0;
            object value = Value(text, ref at, 0);
            Skip(text, ref at);
            if (at != text.Length) throw Error(at, "trailing text");
            return value;
        }

        private static object Value(string s, ref int at, int depth)
        {
            if (depth > 64) throw Error(at, "nesting too deep");
            Skip(s, ref at);
            if (at >= s.Length) throw Error(at, "unexpected end");
            char c = s[at];
            if (c == '{')
            {
                at++;
                var obj = new Dictionary<string, object>(StringComparer.Ordinal);
                Skip(s, ref at);
                if (at < s.Length && s[at] == '}') { at++; return obj; }
                while (true)
                {
                    Skip(s, ref at);
                    if (at >= s.Length || s[at] != '"') throw Error(at, "expected a property name");
                    string name = String(s, ref at);
                    Skip(s, ref at);
                    if (at >= s.Length || s[at] != ':') throw Error(at, "expected ':'");
                    at++;
                    if (obj.ContainsKey(name)) throw Error(at, "duplicate property '" + name + "'");
                    obj.Add(name, Value(s, ref at, depth + 1));
                    Skip(s, ref at);
                    if (at < s.Length && s[at] == ',') { at++; continue; }
                    if (at < s.Length && s[at] == '}') { at++; return obj; }
                    throw Error(at, "expected ',' or '}'");
                }
            }
            if (c == '[')
            {
                at++;
                var list = new List<object>();
                Skip(s, ref at);
                if (at < s.Length && s[at] == ']') { at++; return list; }
                while (true)
                {
                    list.Add(Value(s, ref at, depth + 1));
                    Skip(s, ref at);
                    if (at < s.Length && s[at] == ',') { at++; continue; }
                    if (at < s.Length && s[at] == ']') { at++; return list; }
                    throw Error(at, "expected ',' or ']'");
                }
            }
            if (c == '"') return String(s, ref at);
            if (Literal(s, ref at, "true")) return true;
            if (Literal(s, ref at, "false")) return false;
            if (Literal(s, ref at, "null")) return null;
            int start = at;
            while (at < s.Length && "+-0123456789.eE".IndexOf(s[at]) >= 0) at++;
            if (at == start ||
                !double.TryParse(s.Substring(start, at - start), NumberStyles.Float, CultureInfo.InvariantCulture, out double number))
                throw Error(start, "invalid value");
            return number;
        }

        private static string String(string s, ref int at)
        {
            at++; // opening quote
            var text = new StringBuilder();
            while (at < s.Length)
            {
                char c = s[at++];
                if (c == '"') return text.ToString();
                if (c < ' ') throw Error(at, "control character in a string");
                if (c != '\\') { text.Append(c); continue; }
                if (at >= s.Length) break;
                char e = s[at++];
                switch (e)
                {
                    case '"': text.Append('"'); break;
                    case '\\': text.Append('\\'); break;
                    case '/': text.Append('/'); break;
                    case 'b': text.Append('\b'); break;
                    case 'f': text.Append('\f'); break;
                    case 'n': text.Append('\n'); break;
                    case 'r': text.Append('\r'); break;
                    case 't': text.Append('\t'); break;
                    case 'u':
                        if (at + 4 > s.Length || !int.TryParse(s.Substring(at, 4), NumberStyles.HexNumber,
                                CultureInfo.InvariantCulture, out int code)) throw Error(at, "invalid \\u escape");
                        text.Append((char)code);
                        at += 4;
                        break;
                    default: throw Error(at, "invalid escape");
                }
            }
            throw Error(at, "unterminated string");
        }

        private static bool Literal(string s, ref int at, string word)
        {
            if (string.CompareOrdinal(s, at, word, 0, word.Length) != 0) return false;
            at += word.Length;
            return true;
        }

        private static void Skip(string s, ref int at)
        {
            while (at < s.Length && (s[at] == ' ' || s[at] == '\t' || s[at] == '\r' || s[at] == '\n' || s[at] == '﻿')) at++;
        }

        private static InvalidDataException Error(int at, string message) =>
            new InvalidDataException($"manifest.json: {message} at character {at}.");
    }
}
