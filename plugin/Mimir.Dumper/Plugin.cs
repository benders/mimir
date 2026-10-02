using System;
using System.IO;

using BepInEx;
using BepInEx.Logging;

using UnityEngine;

namespace Mimir.Dumper
{
    /// <summary>
    /// Waits for a dedicated server to finish loading the world, dumps game data, and (optionally)
    /// quits. Configured by environment variables so it can be driven by scripts:
    ///   MIMIR_OUT   output directory (default: BepInEx/mimir-dump)
    ///   MIMIR_EXIT  "1" to quit the process after dumping
    /// Read-only: no Harmony patches, nothing in the game is changed.
    /// </summary>
    [BepInPlugin(Guid, Name, PluginVersion)]
    public class Plugin : BaseUnityPlugin
    {
        public const string Guid = "dev.mimir.dumper";
        public const string Name = "Mimir.Dumper";
        public const string PluginVersion = "0.3.0";

        // Frames to wait after everything reports ready, so late Start() initialisation settles.
        private const int SettleFrames = 120;

        internal static ManualLogSource Log;

        private string _outDir;
        private bool _exit;
        private int _readyFrames;
        private bool _done;

        private void Awake()
        {
            Log = Logger;
            _outDir = Environment.GetEnvironmentVariable("MIMIR_OUT");
            if (string.IsNullOrEmpty(_outDir)) _outDir = Path.Combine(Paths.BepInExRootPath, "mimir-dump");
            _exit = Environment.GetEnvironmentVariable("MIMIR_EXIT") == "1";
            Log.LogInfo($"{Name} {PluginVersion} loaded; out={_outDir} exit={_exit}");
        }

        private void Update()
        {
            if (_done) return;
            bool ready = ZNet.instance != null && ZNetScene.instance != null && ObjectDB.instance != null
                         && ObjectDB.instance.m_items.Count > 0 && ZoneSystem.instance != null;
            if (!ready) { _readyFrames = 0; return; }
            if (++_readyFrames < SettleFrames) return;

            _done = true;
            int code = 0;
            try
            {
                var r = Dumper.Run(_outDir);
                Log.LogInfo($"MIMIR_DUMP_OK prefabs={r.Prefabs} locations={r.Locations} rooms={r.Rooms} items={r.Items} recipes={r.Recipes} " +
                            $"statusEffects={r.StatusEffects} world={r.WorldObjects} translations={r.Translations} " +
                            $"warnings={r.Warnings.Count}");
                foreach (var wrn in r.Warnings) Log.LogWarning(wrn);
            }
            catch (Exception e)
            {
                code = 1;
                Log.LogError($"MIMIR_DUMP_FAILED {e}");
                try { Directory.CreateDirectory(_outDir); File.WriteAllText(Path.Combine(_outDir, "error.txt"), e.ToString()); }
                catch { /* nothing more we can do */ }
            }

            if (_exit)
            {
                Log.LogInfo("MIMIR_EXIT");
                Application.Quit(code);
            }
        }
    }
}
