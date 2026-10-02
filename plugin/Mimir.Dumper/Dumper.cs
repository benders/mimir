using System;
using System.Collections.Generic;
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
    ///   locations/&lt;name&gt;.json      every enabled ZoneSystem location (soft-referenced asset), components as for prefabs
    ///   rooms/&lt;name&gt;.json          every dungeon room in DungeonDB, plus its theme (Room.Theme bitmask)
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
            public int Prefabs, Locations, Rooms, Items, Recipes, StatusEffects, PieceTables, WorldObjects, Translations;
            public List<string> Warnings = new List<string>();
        }

        public static Result Run(string outDir)
        {
            var r = new Result();
            if (Directory.Exists(outDir)) Directory.Delete(outDir, true);
            Directory.CreateDirectory(outDir);

            DumpPrefabs(Path.Combine(outDir, "prefabs"), r);
            r.Recipes = DumpObjects(Path.Combine(outDir, "recipes.json"), ObjectDB.instance.m_recipes.Cast<Object>());
            r.StatusEffects = DumpObjects(Path.Combine(outDir, "status_effects.json"), ObjectDB.instance.m_StatusEffects.Cast<Object>());
            DumpObjects(Path.Combine(outDir, "status_effect_defaults.json"), ObjectDB.instance.m_StatusEffects
                .Where(e => e != null).Select(e => e.GetType()).Distinct().Select(NewInstance).Cast<Object>());
            r.PieceTables = DumpObjects(Path.Combine(outDir, "piece_tables.json"), ObjectDB.instance.m_items
                .Select(i => i != null ? i.GetComponent<ItemDrop>() : null)
                .Select(d => d != null ? d.m_itemData.m_shared.m_buildPieces : null)
                .Where(t => t != null).Distinct().Cast<Object>());
            DumpWorld(Path.Combine(outDir, "world"), r);
            DumpLocations(Path.Combine(outDir, "locations"), r);
            DumpRooms(Path.Combine(outDir, "rooms"), r);
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
            try { WriteGameObject(dir, usedFiles, sr.Asset, extra, sr.Name); }
            finally { sr.Release(); }
            return true;
        }

        /// <summary>{"name", ...extra, "components": [{type, path?, fields}]} for every game component of the object.</summary>
        private static void WriteGameObject(string dir, HashSet<string> usedFiles, GameObject go, Action<JsonWriter> extra,
                                            string name = null)
        {
            name ??= go.name;
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
            w.EndObject();

            var file = SafeFileName(name);
            if (!usedFiles.Add(file)) { file += "__" + (name.GetHashCode() & 0x7fffffff); usedFiles.Add(file); }
            Write(Path.Combine(dir, file + ".json"), w);
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

        private static void Write(string path, JsonWriter w) => File.WriteAllText(path, w.ToString() + "\n", Utf8);
    }
}
