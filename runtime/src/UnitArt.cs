using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace ByzantineUnits
{
    /// <summary>One frame ready to draw: its sprite and the seven foot-clipping materials of its page.</summary>
    internal sealed class FrameArt
    {
        internal FrameArt(Sprite sprite, Material[] chopMaterials)
        {
            Sprite = sprite; ChopMaterials = chopMaterials;
        }

        internal Sprite Sprite { get; }
        internal Material[] ChopMaterials { get; }
    }

    /// <summary>The art of one variant, indexed by carrier slot. A null entry keeps the native frame.</summary>
    internal sealed class VariantArt
    {
        internal VariantArt(UnitVariant variant, FrameArt[] normal, FrameArt[] alternate, string teamColour)
        {
            Variant = variant; Normal = normal; Alternate = alternate; TeamColour = teamColour;
            HasFrameAt = slot => (uint)slot < (uint)Normal.Length && Normal[slot] != null;
        }

        internal UnitVariant Variant { get; }
        internal FrameArt[] Normal { get; }
        internal FrameArt[] Alternate { get; }
        internal string TeamColour { get; }
        /// <summary>Whether our atlas has a frame at a slot; built once so the sprite hook allocates nothing.</summary>
        internal Func<int, bool> HasFrameAt { get; }

        internal int NormalCount => Count(Normal);
        internal int AlternateCount => Count(Alternate);

        private static int Count(FrameArt[] frames)
        {
            int n = 0;
            foreach (FrameArt frame in frames) if (frame != null) n++;
            return n;
        }
    }

    /// <summary>
    /// Loads one variant's atlas (pageN.png, pageN_m.png, frames.tsv, manifest.json) after
    /// AtlasManifest has verified every byte against the manifest. Materials follow the game's own
    /// shader interface (Unlit/TeamColour, _TeamMask, _SpriteCutoff - see docs/SPRITES.md section 7
    /// for what these mean). Unity thread only.
    /// </summary>
    internal static class UnitArtLoader
    {
        internal static VariantArt Load(string directory, UnitVariant variant, Shader shader)
        {
            VerifiedAtlas atlas = AtlasManifest.ReadVerified(directory, variant);
            var pages = new List<(Texture2D Colour, Texture2D Mask, Material[] Chop)>();
            try
            {
                for (int page = 0; page < atlas.Colours.Count; page++)
                {
                    ManifestPage info = atlas.Manifest.Pages[page];
                    if (info.Width > SystemInfo.maxTextureSize || info.Height > SystemInfo.maxTextureSize)
                        throw new InvalidDataException($"page{page} is {info.Width}x{info.Height}; this graphics card allows {SystemInfo.maxTextureSize}.");
                    string label = $"ByzantineUnits_{variant.Unit}_{variant.Loadout ?? variant.File.Name}_page{page}";
                    Texture2D colour = LoadTexture(atlas.Colours[page], label, info);
                    Texture2D mask;
                    try { mask = LoadTexture(atlas.Masks[page], label + "_m", info); }
                    catch { UnityEngine.Object.Destroy(colour); throw; }
                    pages.Add((colour, mask, null));
                    pages[page] = (colour, mask, ChopMaterials(shader, mask, label));
                }
                var normal = new FrameArt[variant.MaxArtSlot + 1];
                var alternate = new FrameArt[variant.MaxArtSlot + 1];
                foreach (FrameEntry entry in atlas.Frames)
                {
                    (Texture2D colour, Texture2D _, Material[] chop) = pages[entry.Page];
                    Sprite sprite = Sprite.Create(colour, new Rect(entry.X, entry.Y, entry.Width, entry.Height),
                        new Vector2(entry.PivotX, entry.PivotY), entry.PixelsPerUnit, 0, SpriteMeshType.FullRect);
                    sprite.name = $"ByzantineUnits_{variant.File.Name}-{entry.Slot}{(entry.Alternate ? "x" : "")}";
                    Keep(sprite);
                    (entry.Alternate ? alternate : normal)[entry.Slot] = new FrameArt(sprite, chop);
                }
                return new VariantArt(variant, normal, alternate, atlas.Manifest.TeamColour);
            }
            catch
            {
                foreach ((Texture2D colour, Texture2D mask, Material[] chop) in pages)
                {
                    UnityEngine.Object.Destroy(colour);
                    UnityEngine.Object.Destroy(mask);
                    if (chop != null) foreach (Material material in chop) UnityEngine.Object.Destroy(material);
                }
                throw;
            }
        }

        /// <summary>
        /// Seven materials per page, as the game builds its unit materials: Unlit/TeamColour, the
        /// page's mask as _TeamMask, and _SpriteCutoff 0 for level 0, (level + 4) / 20 above it.
        /// </summary>
        private static Material[] ChopMaterials(Shader shader, Texture2D mask, string label)
        {
            var materials = new Material[7];
            for (int level = 0; level < materials.Length; level++)
            {
                var material = new Material(shader) { name = $"{label}_chop{level}" };
                material.SetTexture("_TeamMask", mask);
                material.SetFloat("_SpriteCutoff", level == 0 ? 0f : (level + 4f) / 20f);
                materials[level] = Keep(material);
            }
            return materials;
        }

        private static Texture2D LoadTexture(byte[] png, string name, ManifestPage info)
        {
            var texture = new Texture2D(2, 2, TextureFormat.RGBA32, false)
            {
                name = name,
                filterMode = FilterMode.Point,
                wrapMode = TextureWrapMode.Clamp,
            };
            // markNonReadable frees the CPU copy once the page is on the graphics card.
            if (!texture.LoadImage(png, true))
            {
                UnityEngine.Object.Destroy(texture);
                throw new InvalidDataException("Unity could not decode " + name);
            }
            if (texture.width != info.Width || texture.height != info.Height)
            {
                UnityEngine.Object.Destroy(texture);
                throw new InvalidDataException($"{name} decoded as {texture.width}x{texture.height}, not {info.Width}x{info.Height}.");
            }
            return Keep(texture);
        }

        private static T Keep<T>(T asset) where T : UnityEngine.Object
        {
            asset.hideFlags = HideFlags.HideAndDontSave;
            UnityEngine.Object.DontDestroyOnLoad(asset);
            return asset;
        }
    }
}
