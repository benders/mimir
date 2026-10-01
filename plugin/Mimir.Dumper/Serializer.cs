using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;

using UnityEngine;

using Object = UnityEngine.Object;

namespace Mimir.Dumper
{
    /// <summary>
    /// Reflection-based serializer that mirrors Unity's own serialization rules: it writes the
    /// fields Unity would persist (public or [SerializeField], not [NonSerialized], not static or
    /// readonly). That is exactly the data designers set in prefabs, so new fields added by a game
    /// patch appear in the dump without any change here.
    ///
    /// References to other Unity objects are written as named references instead of being
    /// followed, which keeps every prefab self-contained and the output acyclic.
    /// </summary>
    internal static class Serializer
    {
        private const int MaxDepth = 12;

        private static readonly Dictionary<Type, FieldInfo[]> FieldCache = new Dictionary<Type, FieldInfo[]>();

        public static int SkippedFields;

        /// <summary>Write all serialized fields of <paramref name="obj"/> as JSON object members.</summary>
        public static void WriteFields(JsonWriter w, object obj, int depth = 0)
        {
            foreach (var f in SerializedFields(obj.GetType()))
            {
                object v;
                try { v = f.GetValue(obj); }
                catch { SkippedFields++; continue; }
                w.Key(f.Name);
                WriteValue(w, v, f.FieldType, depth + 1);
            }
        }

        public static void WriteValue(JsonWriter w, object v, Type declared, int depth)
        {
            if (depth > MaxDepth) { w.Value("$maxdepth"); return; }

            // Unity's overloaded == makes destroyed/missing references compare equal to null.
            if (v == null || (v is Object uo && uo == null)) { w.Null(); return; }

            var t = v.GetType();

            switch (v)
            {
                case string s: w.Value(s); return;
                case bool b: w.Value(b); return;
                case float fl: w.Value(fl, true); return;
                case double d: w.Value(d, false); return;
                case Enum e: w.Value(e.ToString()); return;
                case int or short or sbyte or byte or long or uint or ushort or char:
                    w.Value(Convert.ToInt64(v)); return;
                case ulong ul: w.Value(ul); return;
                case LayerMask lm: w.Value(lm.value); return;
                case Vector2 v2: Floats(w, v2.x, v2.y); return;
                case Vector3 v3: Floats(w, v3.x, v3.y, v3.z); return;
                case Vector4 v4: Floats(w, v4.x, v4.y, v4.z, v4.w); return;
                case Vector2Int v2i: Ints(w, v2i.x, v2i.y); return;
                case Vector3Int v3i: Ints(w, v3i.x, v3i.y, v3i.z); return;
                case Quaternion q: Floats(w, q.x, q.y, q.z, q.w); return;
                case Color c: Floats(w, c.r, c.g, c.b, c.a); return;
                case Color32 c32: Floats(w, c32.r, c32.g, c32.b, c32.a); return;
                case AnimationCurve curve: WriteCurve(w, curve); return;
                case Gradient: w.Value("$gradient"); return;
                case Object o: WriteReference(w, o); return;
            }

            if (v is IList list)
            {
                w.BeginArray();
                var elem = t.IsArray ? t.GetElementType() : (t.IsGenericType ? t.GetGenericArguments()[0] : typeof(object));
                foreach (var item in list) WriteValue(w, item, elem, depth + 1);
                w.EndArray();
                return;
            }

            if (IsSerializableComposite(t))
            {
                w.BeginObject();
                WriteFields(w, v, depth);
                w.EndObject();
                return;
            }

            w.Value("$unsupported:" + t.Name);
        }

        /// <summary>A reference to another Unity object, by name. Prefab components point at their root.</summary>
        public static void WriteReference(JsonWriter w, Object o)
        {
            w.BeginObject();
            switch (o)
            {
                case GameObject go:
                    w.Key("$ref"); w.Value(go.transform.root.name);
                    if (go.transform.parent != null) { w.Key("path"); w.Value(PathOf(go.transform)); }
                    break;
                case Component comp:
                    w.Key("$ref"); w.Value(comp.transform.root.name);
                    if (comp.transform.parent != null) { w.Key("path"); w.Value(PathOf(comp.transform)); }
                    w.Key("component"); w.Value(comp.GetType().Name);
                    break;
                case Sprite sp:
                    w.Key("$sprite"); w.Value(sp.name);
                    break;
                default:
                    w.Key("$asset"); w.Value(o.name);
                    w.Key("type"); w.Value(o.GetType().Name);
                    break;
            }
            w.EndObject();
        }

        public static string PathOf(Transform t)
        {
            var parts = new List<string>();
            for (var cur = t; cur.parent != null; cur = cur.parent) parts.Add(cur.name);
            parts.Reverse();
            return string.Join("/", parts.ToArray());
        }

        public static IEnumerable<FieldInfo> SerializedFields(Type type)
        {
            if (FieldCache.TryGetValue(type, out var cached)) return cached;

            // Walk base classes so inherited fields (e.g. Humanoid -> Character) are included, but
            // stop at Unity's own base types, whose internals are not interesting here.
            var chain = new List<Type>();
            for (var t = type; t != null && t != typeof(object) && !IsUnityBase(t); t = t.BaseType) chain.Add(t);
            chain.Reverse(); // base-class fields first, like the Unity inspector

            var fields = new List<FieldInfo>();
            var seen = new HashSet<string>();
            foreach (var t in chain)
            {
                foreach (var f in t.GetFields(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
                {
                    if (f.IsInitOnly || f.IsLiteral) continue;
                    if (f.IsDefined(typeof(NonSerializedAttribute), false)) continue;
                    if (!f.IsPublic && !f.IsDefined(typeof(SerializeField), false)) continue;
                    if (!IsSerializableType(f.FieldType)) continue;
                    if (seen.Add(f.Name)) fields.Add(f);
                }
            }
            var arr = fields.ToArray();
            FieldCache[type] = arr;
            return arr;
        }

        private static bool IsUnityBase(Type t) =>
            t == typeof(MonoBehaviour) || t == typeof(Behaviour) || t == typeof(Component)
            || t == typeof(ScriptableObject) || t == typeof(Object);

        private static bool IsSerializableType(Type t)
        {
            if (t.IsPrimitive || t.IsEnum || t == typeof(string)) return true;
            if (typeof(Object).IsAssignableFrom(t)) return true;
            if (t.IsArray) return t.GetArrayRank() == 1 && IsSerializableType(t.GetElementType());
            if (t.IsGenericType && t.GetGenericTypeDefinition() == typeof(List<>))
                return IsSerializableType(t.GetGenericArguments()[0]);
            if (t.IsGenericType) return IsSerializableComposite(t); // e.g. SoftReference<T>
            if (t == typeof(AnimationCurve) || t == typeof(Gradient) || t == typeof(LayerMask)) return true;
            if (t.Namespace == "UnityEngine" && t.IsValueType) return true; // Vector3, Color, ...
            return IsSerializableComposite(t);
        }

        private static bool IsSerializableComposite(Type t)
        {
            if (t.IsAbstract || t.IsInterface || t.IsPointer) return false;
            if (typeof(Delegate).IsAssignableFrom(t)) return false;
            if (t.IsGenericType && t.GetGenericTypeDefinition() == typeof(Dictionary<,>)) return false;
            return t.IsDefined(typeof(SerializableAttribute), false);
        }

        private static void Floats(JsonWriter w, params float[] vals)
        {
            w.BeginArray();
            foreach (var f in vals) w.Value(f, true);
            w.EndArray();
        }

        private static void Ints(JsonWriter w, params int[] vals)
        {
            w.BeginArray();
            foreach (var i in vals) w.Value(i);
            w.EndArray();
        }

        private static void WriteCurve(JsonWriter w, AnimationCurve curve)
        {
            w.BeginArray();
            foreach (var k in curve.keys) Floats(w, k.time, k.value);
            w.EndArray();
        }
    }
}
