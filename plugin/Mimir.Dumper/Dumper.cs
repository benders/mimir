using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;

using SoftReferenceableAssets;

using UnityEngine;

using Object = UnityEngine.Object;

namespace Mimir.Dumper
{
    /// <summary>
    /// Writes the dump. Layout (all JSON):
    ///   prefabs/&lt;name&gt;.json        every networked prefab + every ObjectDB item, game components only
    ///   recipes.json                   ObjectDB.m_recipes
    ///   status_effects.json            ObjectDB.m_StatusEffects
    ///   status_effect_defaults.json    a fresh instance of each status effect type (to tell set fields from defaults)
    ///   piece_tables.json              build menus of tools (hammer, hoe, ...), not networked prefabs
    ///   world/&lt;Type&gt;.json            world-level systems (zones, environments, spawns, events)
    ///   subprefabs/&lt;name&gt;.json     non-networked prefabs referenced (transitively) by anything dumped, so every {"$ref"} resolves
    ///                                  (not in ZNetScene; effect-only vfx_/sfx_/fx_ objects and objects with no game components are skipped)
    ///   world/seasons.json             SeasonalItemGroup assets (event dates, pieces, recipes)
    ///   locations/&lt;name&gt;.json      every enabled ZoneSystem location (soft-referenced asset), components as for prefabs,
    ///                                  plus "instances": network prefabs placed in its hierarchy
    ///   rooms/&lt;name&gt;.json          every dungeon room in DungeonDB, plus its theme (Room.Theme bitmask) and "instances"
    ///   room_themes.json               Room.Theme name -> bit (DungeonGenerator.m_themes is written by name)
    ///   localization/English.json      $token -> text
    ///   manifest.json                  written last; its presence marks a complete dump
    /// </summary>
    internal static class Dumper
    {
        private static readonly UTF8Encoding Utf8 = new UTF8Encoding(false);

        // World-level MonoBehaviours worth dumping whole. Looked up by name so a type that
        // disappears in a future patch is reported as missing rather than breaking the build.
        private static readonly string[] WorldTypes =
        {
            "ZoneSystem", "EnvMan", "RandEventSystem", "SpawnSystemList", "DungeonDB", "Game",
        };

        public sealed class Result
        {
            public int SubPrefabs, Seasons; public long SubPrefabBytes;
            public int Prefabs, Locations, Rooms, Items, Recipes, StatusEffects, PieceTables, WorldObjects, Translations;
            public List<string> Warnings = new List<string>();
        }

        // Names of everything written so far (prefabs, locations, rooms, sub-prefabs).
        private static readonly HashSet<string> Dumped = new HashSet<string>(StringComparer.Ordinal);
        // Names of networked prefabs (ZNetScene + ObjectDB items): a child with one of these names and a ZNetView is an instance.
        private static readonly HashSet<string> NetPrefabs = new HashSet<string>(StringComparer.Ordinal);
        private static readonly HashSet<int> SeenRoots = new HashSet<int>();
        private static readonly Queue<GameObject> Pending = new Queue<GameObject>();
        private static readonly HashSet<string> SubFiles = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        private static string _subDir;

        public static Result Run(string outDir)
        {
            var r = new Result();
            if (Directory.Exists(outDir)) Directory.Delete(outDir, true);
            Directory.CreateDirectory(outDir);
            _subDir = Path.Combine(outDir, "subprefabs");
            Directory.CreateDirectory(_subDir);
            Serializer.RefSink = OnReference;

            DumpPrefabs(Path.Combine(outDir, "prefabs"), r);
            DrainSubPrefabs(r);
            r.Recipes = DumpObjects(Path.Combine(outDir, "recipes.json"), ObjectDB.instance.m_recipes.Cast<Object>());
            r.StatusEffects = DumpObjects(Path.Combine(outDir, "status_effects.json"), ObjectDB.instance.m_StatusEffects.Cast<Object>());
            DumpObjects(Path.Combine(outDir, "status_effect_defaults.json"), ObjectDB.instance.m_StatusEffects
                .Where(e => e != null).Select(e => e.GetType()).Distinct().Select(NewInstance).Cast<Object>());
            r.PieceTables = DumpObjects(Path.Combine(outDir, "piece_tables.json"), ObjectDB.instance.m_items
                .Select(i => i != null ? i.GetComponent<ItemDrop>() : null)
                .Select(d => d != null ? d.m_itemData.m_shared.m_buildPieces : null)
                .Where(t => t != null).Distinct().Cast<Object>());
            DumpWorld(Path.Combine(outDir, "world"), r);
            DumpSeasons(Path.Combine(outDir, "world", "seasons.json"), r);
            DumpLocations(Path.Combine(outDir, "locations"), r);
            DumpRooms(Path.Combine(outDir, "rooms"), r);
            DrainSubPrefabs(r);
            Serializer.RefSink = null;
            r.Translations = DumpLocalization(Path.Combine(outDir, "localization"), r);
            WriteManifest(outDir, r);
            return r;
        }

        private static void DumpPrefabs(string dir, Result r)
        {
            Directory.CreateDirectory(dir);
            var items = new HashSet<string>(ObjectDB.instance.m_items.Where(i => i != null).Select(i => i.name));
            r.Items = items.Count;

            var all = new SortedDictionary<string, GameObject>(StringComparer.Ordinal);
            foreach (var go in ZNetScene.instance.m_prefabs.Concat(ObjectDB.instance.m_items))
            {
                if (go == null) continue;
                if (all.ContainsKey(go.name)) continue;
                all[go.name] = go;
            }
            foreach (var go in ZNetScene.instance.m_prefabs) if (go != null) NetPrefabs.Add(go.name);
            foreach (var go in ObjectDB.instance.m_items) if (go != null) NetPrefabs.Add(go.name);

            var usedFiles = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var kv in all)
            {
                WriteGameObject(dir, usedFiles, kv.Value, w => { w.Key("isItem"); w.Value(items.Contains(kv.Key)); });
                r.Prefabs++;
            }
        }

        /// <summary>
        /// Locations (dungeon entrances, villages, boss altars, ...) aren't networked prefabs: ZoneSystem holds them
        /// as soft references and loads them on demand. Their children hold the creature spawners, chests and
        /// dungeon generators that place content in the world.
        /// </summary>
        private static void DumpLocations(string dir, Result r)
        {
            Directory.CreateDirectory(dir);
            var usedFiles = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var seen = new HashSet<AssetID>();
            foreach (var loc in ZoneSystem.instance.m_locations)
            {
                if (loc == null || !loc.m_enable || !loc.m_prefab.IsValid || !seen.Add(loc.m_prefab.m_assetID)) continue;
                if (WriteSoftReference(dir, usedFiles, loc.m_prefab, null, r)) r.Locations++;
            }
        }

        /// <summary>Dungeon rooms; a location's DungeonGenerator picks rooms whose theme matches its m_themes.</summary>
        private static void DumpRooms(string dir, Result r)
        {
            Directory.CreateDirectory(dir);
            var rooms = DungeonDB.GetRooms();
            if (rooms == null || rooms.Count == 0) { r.Warnings.Add("no dungeon rooms"); return; }
            var themes = new JsonWriter();
            themes.BeginObject();
            foreach (Room.Theme t in Enum.GetValues(typeof(Room.Theme))) { themes.Key(t.ToString()); themes.Value((long)t); }
            themes.EndObject();
            Write(Path.Combine(Path.GetDirectoryName(dir), "room_themes.json"), themes);

            var usedFiles = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var room in rooms.Where(x => x != null && x.m_prefab.IsValid).OrderBy(x => x.m_prefab.Name, StringComparer.Ordinal))
            {
                var data = room;
                if (WriteSoftReference(dir, usedFiles, room.m_prefab, w =>
                    {
                        w.Key("theme"); w.Value((long)data.m_theme);
                        w.Key("enabled"); w.Value(data.m_enabled);
                    }, r)) r.Rooms++;
            }
        }

        private static bool WriteSoftReference(string dir, HashSet<string> usedFiles, SoftReference<GameObject> sr,
                                               Action<JsonWriter> extra, Result r)
        {
            if (sr.Load() != LoadResult.Succeeded || sr.Asset == null)
            {
                r.Warnings.Add("could not load " + sr.Name);
                return false;
            }
            try { WriteGameObject(dir, usedFiles, sr.Asset, extra, sr.Name, true); DrainSubPrefabs(r); }
            finally { sr.Release(); }
            return true;
        }

        /// <summary>{"name", ...extra, "components": [{type, path?, fields}]} for every game component of the object.</summary>
        private static long WriteGameObject(string dir, HashSet<string> usedFiles, GameObject go, Action<JsonWriter> extra,
                                            string name = null, bool instances = false)
        {
            name ??= go.name;
            Dumped.Add(name);
            var w = new JsonWriter();
            w.BeginObject();
            w.Key("name"); w.Value(name);
            extra?.Invoke(w);
            w.Key("components");
            w.BeginArray();
            foreach (var mb in go.GetComponentsInChildren<MonoBehaviour>(true))
            {
                if (mb == null || !IsGameType(mb.GetType())) continue;
                w.BeginObject();
                w.Key("type"); w.Value(mb.GetType().Name);
                if (mb.transform != go.transform) { w.Key("path"); w.Value(Serializer.PathOf(mb.transform)); }
                w.Key("fields");
                w.BeginObject();
                Serializer.WriteFields(w, mb);
                w.EndObject();
                w.EndObject();
            }
            w.EndArray();
            if (instances) WriteInstances(w, go);
            w.EndObject();

            var file = SafeFileName(name);
            if (!usedFiles.Add(file)) { file += "__" + (name.GetHashCode() & 0x7fffffff); usedFiles.Add(file); }
            return Write(Path.Combine(dir, file + ".json"), w);
        }

        /// <summary>
        /// "instances": [{"prefab", "path", "inactive"?, "randomSpawn"?}] for the descendants that are instances of
        /// networked prefabs (name minus " (N)" / "(Clone)" is a ZNetScene prefab and the object has a ZNetView: this is how
        /// ZNetView and ZoneSystem.SpawnLocation identify them). Doesn't descend into an instance.
        /// "inactive" = the object or an ancestor is disabled in the prefab; "randomSpawn" = the nearest RandomSpawn at or
        /// above it (chance in percent, optional theme/biome requirements, "path" when it sits on an ancestor).
        /// One compact line per instance to keep the files small.
        /// </summary>
        private static void WriteInstances(JsonWriter w, GameObject root)
        {
            w.Key("instances");
            w.BeginArray();
            WalkInstances(w, root.transform, root.transform, false, null);
            w.EndArray();
        }

        private static void WalkInstances(JsonWriter w, Transform root, Transform t, bool inactive, RandomSpawn rs)
        {
            foreach (Transform c in t)
            {
                var own = c.GetComponent<RandomSpawn>();
                var rs2 = own != null ? own : rs;
                bool inactive2 = inactive || !c.gameObject.activeSelf;
                var prefab = GetPrefabName(c.name);
                if (NetPrefabs.Contains(prefab) && c.GetComponent<ZNetView>() != null)
                {
                    var sb = new StringBuilder();
                    sb.Append("{\"prefab\":").Append(JsonWriter.Quote(prefab));
                    sb.Append(",\"path\":").Append(JsonWriter.Quote(Serializer.PathOf(c)));
                    if (inactive2) sb.Append(",\"inactive\":true");
                    if (rs2 != null)
                    {
                        sb.Append(",\"randomSpawn\":{\"chance\":").Append(rs2.m_chanceToSpawn.ToString("R", CultureInfo.InvariantCulture));
                        if (rs2.m_dungeonRequireTheme != Room.Theme.None) sb.Append(",\"theme\":").Append(JsonWriter.Quote(rs2.m_dungeonRequireTheme.ToString()));
                        if (rs2.m_requireBiome != Heightmap.Biome.None) sb.Append(",\"biome\":").Append(JsonWriter.Quote(rs2.m_requireBiome.ToString()));
                        if (rs2.transform != c) sb.Append(",\"path\":").Append(JsonWriter.Quote(Serializer.PathOf(rs2.transform)));
                        sb.Append('}');
                    }
                    sb.Append('}');
                    w.Raw(sb.ToString());
                    continue;
                }
                WalkInstances(w, root, c, inactive2, rs2);
            }
        }

        /// <summary>Utils.GetPrefabName: the name up to the first '(' or ' ' (strips "(Clone)" and " (N)").</summary>
        private static string GetPrefabName(string name)
        {
            int i = name.IndexOfAny(new[] { '(', ' ' });
            return i == -1 ? name : name.Substring(0, i);
        }

        private static void OnReference(GameObject root)
        {
            if (root != null && SeenRoots.Add(root.GetInstanceID())) Pending.Enqueue(root);
        }

        /// <summary>
        /// Writes every queued referenced root that isn't already dumped to subprefabs/ (refs found while writing
        /// these are queued and handled in the same loop; SeenRoots is the cycle guard).
        /// </summary>
        private static void DrainSubPrefabs(Result r)
        {
            while (Pending.Count > 0)
            {
                var go = Pending.Dequeue();
                if (go == null) continue;
                try
                {
                    var name = go.name;
                    if (go.scene.IsValid() || name.EndsWith("(Clone)", StringComparison.Ordinal)) continue;
                    if (Dumped.Contains(name)) continue;
                    if (name.StartsWith("vfx_", StringComparison.OrdinalIgnoreCase) || name.StartsWith("sfx_", StringComparison.OrdinalIgnoreCase)
                        || name.StartsWith("fx_", StringComparison.OrdinalIgnoreCase)) continue;
                    if (go.GetComponent<Location>() != null || go.GetComponent<Room>() != null) continue;
                    if (!go.GetComponentsInChildren<MonoBehaviour>(true).Any(mb => mb != null && IsGameType(mb.GetType()))) continue;
                    r.SubPrefabBytes += WriteGameObject(_subDir, SubFiles, go, null);
                    r.SubPrefabs++;
                }
                catch (Exception e) { r.Warnings.Add("sub-prefab failed: " + e.Message); }
            }
        }

        /// <summary>
        /// SeasonalItemGroup ScriptableObjects (Player.m_seasonalItemGroups; not in ObjectDB): name, _startDate/_endDate
        /// (day, month), Pieces ($ref prefab) and Recipes ($asset recipe name).
        /// </summary>
        private static void DumpSeasons(string path, Result r)
        {
            var groups = new Dictionary<string, Object>(StringComparer.Ordinal);
            foreach (var o in Resources.FindObjectsOfTypeAll(typeof(SeasonalItemGroup)))
                if (o != null) groups[o.name] = o;
            var player = ZNetScene.instance.m_prefabs.FirstOrDefault(p => p != null && p.name == "Player");
            var pl = player != null ? player.GetComponent<Player>() : null;
            var f = typeof(Player).GetField("m_seasonalItemGroups", BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public);
            if (pl != null && f != null && f.GetValue(pl) is IEnumerable<SeasonalItemGroup> list)
                foreach (var g in list) if (g != null) groups[g.name] = g;
            if (groups.Count == 0) r.Warnings.Add("no SeasonalItemGroup assets");
            r.Seasons = DumpObjects(path, groups.Values);
        }

        private static int DumpObjects(string path, IEnumerable<Object> objects)
        {
            var list = objects.Where(o => o != null).OrderBy(o => o.name, StringComparer.Ordinal).ToList();
            var w = new JsonWriter();
            w.BeginArray();
            foreach (var o in list)
            {
                w.BeginObject();
                w.Key("name"); w.Value(o.name);
                w.Key("type"); w.Value(o.GetType().Name);
                w.Key("fields");
                w.BeginObject();
                Serializer.WriteFields(w, o);
                w.EndObject();
                w.EndObject();
            }
            w.EndArray();
            Write(path, w);
            return list.Count;
        }

        private static ScriptableObject NewInstance(Type t)
        {
            var o = ScriptableObject.CreateInstance(t);
            o.name = t.Name;
            return o;
        }

        private static void DumpWorld(string dir, Result r)
        {
            Directory.CreateDirectory(dir);
            var asm = typeof(ZNetScene).Assembly;
            foreach (var typeName in WorldTypes)
            {
                var type = asm.GetType(typeName);
                if (type == null) { r.Warnings.Add("world type missing: " + typeName); continue; }
                // FindObjectsOfTypeAll also returns objects that live in prefabs, not just the scene.
                var objs = Resources.FindObjectsOfTypeAll(type);
                if (objs.Length == 0) { r.Warnings.Add("no instances of " + typeName); continue; }
                r.WorldObjects += DumpObjects(Path.Combine(dir, typeName + ".json"), objs);
            }
        }

        private static int DumpLocalization(string dir, Result r)
        {
            Directory.CreateDirectory(dir);
            var loc = Localization.instance;
            var field = typeof(Localization).GetField("m_translations", BindingFlags.Instance | BindingFlags.NonPublic);
            if (loc == null || field == null) { r.Warnings.Add("localization unavailable"); return 0; }
            var dict = (Dictionary<string, string>)field.GetValue(loc);

            var w = new JsonWriter();
            w.BeginObject();
            foreach (var kv in dict.OrderBy(k => k.Key, StringComparer.Ordinal)) { w.Key(kv.Key); w.Value(kv.Value); }
            w.EndObject();
            Write(Path.Combine(dir, loc.GetSelectedLanguage() + ".json"), w);
            return dict.Count;
        }

        private static void WriteManifest(string outDir, Result r)
        {
            var w = new JsonWriter();
            w.BeginObject();
            w.Key("gameVersion"); w.Value(Version.CurrentVersion.ToString());
            // A const would be inlined at *our* compile time; read the running game's value instead.
            var netVer = typeof(Version).GetField("c_networkVersion")?.GetRawConstantValue();
            w.Key("networkVersion"); if (netVer != null) w.Value(Convert.ToInt64(netVer)); else w.Null();
            w.Key("dumperVersion"); w.Value(Plugin.PluginVersion);
            w.Key("generatedAt"); w.Value(DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"));
            w.Key("counts");
            w.BeginObject();
            w.Key("prefabs"); w.Value(r.Prefabs);
            w.Key("locations"); w.Value(r.Locations);
            w.Key("rooms"); w.Value(r.Rooms);
            w.Key("items"); w.Value(r.Items);
            w.Key("recipes"); w.Value(r.Recipes);
            w.Key("statusEffects"); w.Value(r.StatusEffects);
            w.Key("pieceTables"); w.Value(r.PieceTables);
            w.Key("worldObjects"); w.Value(r.WorldObjects);
            w.Key("translations"); w.Value(r.Translations);
            w.Key("subPrefabs"); w.Value(r.SubPrefabs);
            w.Key("subPrefabBytes"); w.Value(r.SubPrefabBytes);
            w.Key("seasons"); w.Value(r.Seasons);
            w.Key("skippedFields"); w.Value(Serializer.SkippedFields);
            w.EndObject();
            w.Key("warnings");
            w.BeginArray();
            foreach (var s in r.Warnings) w.Value(s);
            w.EndArray();
            w.EndObject();
            Write(Path.Combine(outDir, "manifest.json"), w);
        }

        private static bool IsGameType(Type t) => t.Assembly.GetName().Name.StartsWith("assembly_", StringComparison.Ordinal);

        private static string SafeFileName(string name)
        {
            var sb = new StringBuilder(name.Length);
            foreach (char c in name) sb.Append(char.IsLetterOrDigit(c) || c == '_' || c == '-' || c == '.' ? c : '_');
            return sb.ToString();
        }

        private static long Write(string path, JsonWriter w)
        {
            var text = w.ToString() + "\n";
            File.WriteAllText(path, text, Utf8);
            return Utf8.GetByteCount(text);
        }
    }
}
