using System;
using UnityEngine;

namespace ByzantineUnits
{
    /// <summary>
    /// Calls the per-frame work from a hidden GameObject that survives scene loads. The game destroys
    /// the plugin's own object during startup, so the per-frame work needs its own. Unity thread.
    /// </summary>
    public sealed class UnitsDriver : MonoBehaviour
    {
        private static Action tick, lateTick;
        private static GameObject host;

        internal static void Run(Action perFrame, Action perLateFrame = null)
        {
            tick = perFrame;
            lateTick = perLateFrame;
            if (host != null) return;
            host = new GameObject("ByzantineUnits.Driver") { hideFlags = HideFlags.HideAndDontSave };
            DontDestroyOnLoad(host);
            host.AddComponent<UnitsDriver>();
        }

        private void Update() => tick?.Invoke();

        // After every Update, so the game has moved its units for this frame (the aura circle).
        private void LateUpdate() => lateTick?.Invoke();
    }
}
