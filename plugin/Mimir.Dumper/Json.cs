using System;
using System.Globalization;
using System.Text;

namespace Mimir.Dumper
{
    /// <summary>
    /// Minimal indented JSON writer. Unity's Mono profile has no System.Text.Json, and pulling in
    /// Newtonsoft would mean shipping a second DLL. Output is stable (no reordering) so that dumps
    /// diff cleanly in git.
    /// </summary>
    internal sealed class JsonWriter
    {
        private readonly StringBuilder _sb = new StringBuilder(1 << 16);
        private int _depth;
        private bool _needComma;
        private bool _afterKey;

        public override string ToString() => _sb.ToString();

        public void BeginObject() { Prefix(); _sb.Append('{'); _depth++; _needComma = false; }
        public void EndObject() { Close('}'); }
        public void BeginArray() { Prefix(); _sb.Append('['); _depth++; _needComma = false; }
        public void EndArray() { Close(']'); }

        public void Key(string name)
        {
            if (_needComma) _sb.Append(',');
            Newline();
            WriteString(name);
            _sb.Append(": ");
            _afterKey = true;
            _needComma = false;
        }

        public void Null() { Prefix(); _sb.Append("null"); _needComma = true; }
        public void Value(bool v) { Prefix(); _sb.Append(v ? "true" : "false"); _needComma = true; }
        public void Value(long v) { Prefix(); _sb.Append(v.ToString(CultureInfo.InvariantCulture)); _needComma = true; }
        public void Value(ulong v) { Prefix(); _sb.Append(v.ToString(CultureInfo.InvariantCulture)); _needComma = true; }

        public void Value(double v, bool single)
        {
            if (double.IsNaN(v) || double.IsInfinity(v)) { Null(); return; }
            Prefix();
            // "R" on float gives the shortest string that round-trips the float (0.1f -> "0.1"),
            // which is what a human reading the dump expects.
            _sb.Append(single ? ((float)v).ToString("R", CultureInfo.InvariantCulture)
                              : v.ToString("R", CultureInfo.InvariantCulture));
            _needComma = true;
        }

        public void Value(string s)
        {
            if (s == null) { Null(); return; }
            Prefix();
            WriteString(s);
            _needComma = true;
        }

        /// <summary>Append an already-serialized (compact) JSON value as one element.</summary>
        public void Raw(string json) { Prefix(); _sb.Append(json); _needComma = true; }

        public static string Quote(string s)
        {
            var sb = new StringBuilder(s.Length + 2);
            AppendString(sb, s);
            return sb.ToString();
        }

        private void Prefix()
        {
            if (_afterKey) { _afterKey = false; return; }
            if (_needComma) _sb.Append(',');
            if (_depth > 0) Newline();
        }

        private void Close(char c)
        {
            _depth--;
            if (_needComma) Newline(); // non-empty container
            _sb.Append(c);
            _needComma = true;
        }

        private void Newline()
        {
            _sb.Append('\n');
            _sb.Append(' ', _depth * 2);
        }

        private void WriteString(string s) => AppendString(_sb, s);

        private static void AppendString(StringBuilder sb, string s)
        {
            sb.Append('"');
            foreach (char c in s)
            {
                switch (c)
                {
                    case '"': sb.Append("\\\""); break;
                    case '\\': sb.Append("\\\\"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    default:
                        if (c < 0x20) sb.Append("\\u").Append(((int)c).ToString("x4"));
                        else sb.Append(c);
                        break;
                }
            }
            sb.Append('"');
        }
    }
}
