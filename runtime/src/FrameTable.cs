using System;
using System.Collections.Generic;
using System.Globalization;

namespace ByzantineUnits
{
    /// <summary>One packed preview frame: a carrier slot, its page and rectangle (bottom-left origin).</summary>
    public readonly struct FrameEntry
    {
        public FrameEntry(int slot, bool alternate, int page, int x, int y, int width, int height,
            float pivotX, float pivotY, float pixelsPerUnit)
        {
            Slot = slot; Alternate = alternate; Page = page; X = x; Y = y; Width = width; Height = height;
            PivotX = pivotX; PivotY = pivotY; PixelsPerUnit = pixelsPerUnit;
        }

        public int Slot { get; }
        public bool Alternate { get; }
        public int Page { get; }
        public int X { get; }
        public int Y { get; }
        public int Width { get; }
        public int Height { get; }
        public float PivotX { get; }
        public float PivotY { get; }
        public float PixelsPerUnit { get; }
    }

    /// <summary>
    /// Parses and validates a frames.tsv file, written by whatever tool packs your atlas
    /// (`tools/pack_atlas.py` in this repository writes a JSON index instead; adapt either side to
    /// match, or emit this exact TSV shape from your packer). No Unity types, so a separate
    /// command-line checker can link this same file and validate an atlas without starting the game.
    /// </summary>
    public static class FrameTable
    {
        private const string Header = "slot\talt\tpage\tx\ty\tw\th\tpivot_x\tpivot_y\tppu";

        /// <param name="pageSizes">Width and height of every page, in page order.</param>
        /// <param name="maxSlot">Highest slot the carrier's sprite file registers.</param>
        public static List<FrameEntry> Parse(string text, IReadOnlyList<(int Width, int Height)> pageSizes, int maxSlot)
        {
            if (text == null) throw new ArgumentNullException(nameof(text));
            string[] lines = text.Replace("\r\n", "\n").Split('\n');
            if (lines.Length == 0 || lines[0] != Header)
                throw new FormatException("frames.tsv must start with the header: " + Header);
            var frames = new List<FrameEntry>();
            var seen = new HashSet<(int, bool)>();
            for (int n = 1; n < lines.Length; n++)
            {
                string line = lines[n];
                if (line.Length == 0) continue;
                string[] f = line.Split('\t');
                if (f.Length != 10) throw new FormatException($"frames.tsv line {n + 1}: expected 10 columns.");
                int slot = Int(f[0], n), alt = Int(f[1], n), page = Int(f[2], n);
                int x = Int(f[3], n), y = Int(f[4], n), w = Int(f[5], n), h = Int(f[6], n);
                float px = Float(f[7], n), py = Float(f[8], n), ppu = Float(f[9], n);
                if (slot < 0 || slot > maxSlot)
                    throw new FormatException($"frames.tsv line {n + 1}: slot {slot} is outside 0-{maxSlot}.");
                if (alt != 0 && alt != 1) throw new FormatException($"frames.tsv line {n + 1}: alt must be 0 or 1.");
                if (page < 0 || page >= pageSizes.Count)
                    throw new FormatException($"frames.tsv line {n + 1}: page {page} does not exist.");
                if (w <= 0 || h <= 0 || x < 0 || y < 0 || x + w > pageSizes[page].Width || y + h > pageSizes[page].Height)
                    throw new FormatException($"frames.tsv line {n + 1}: rectangle lies outside page {page}.");
                if (ppu <= 0) throw new FormatException($"frames.tsv line {n + 1}: pixels per unit must be positive.");
                if (!seen.Add((slot, alt == 1)))
                    throw new FormatException($"frames.tsv line {n + 1}: slot {slot}{(alt == 1 ? "x" : "")} appears twice.");
                frames.Add(new FrameEntry(slot, alt == 1, page, x, y, w, h, px, py, ppu));
            }
            if (frames.Count == 0) throw new FormatException("frames.tsv has no frames.");
            return frames;
        }

        private static int Int(string value, int line)
        {
            if (!int.TryParse(value, NumberStyles.Integer, CultureInfo.InvariantCulture, out int result))
                throw new FormatException($"frames.tsv line {line + 1}: '{value}' is not an integer.");
            return result;
        }

        private static float Float(string value, int line)
        {
            if (!float.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out float result) ||
                float.IsNaN(result) || float.IsInfinity(result))
                throw new FormatException($"frames.tsv line {line + 1}: '{value}' is not a finite number.");
            return result;
        }
    }
}
